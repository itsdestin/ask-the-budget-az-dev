"""The roster: one small JSON file per person under <data_dir>/users/.

    users/dmoss.json
    {
      "version": 1,
      "username": "dmoss",          <- most recently OBSERVED spelling
      "display_name": "Danielle Moss",
      "name_source": "windows",     <- "typed" | "windows" | ""
      "first_seen": "2026-08-25T09:14:03-07:00",
      "last_seen":  "2026-08-25T09:14:03-07:00"
    }

WHY one file per person and not one list (spec U1): ~20 machines rewriting
one list is exactly the corruption risk that kept names off the share
(spec M6). One file per person makes collision structurally impossible
BECAUSE a file is only ever written by the machine its own user is sitting
at — so nothing an ADMIN decides about a person lives here. `hidden` is
`settings.hidden_users` (spec U7); the first draft put it in this file and
had the admin's machine racing the person's own daily touch.

Precedents with the same shape and the same Notepad-readable reason:
ingest/jobs.py (one file per job), app/issue_reports.py (one per report).

Degrades on READ (a torn file costs one row), raises on WRITE (a caller
that could not record something must know — except the /api/me touch,
which catches and drops because a stale last_seen date is not worth a
slow page).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from store.config import data_dir
from users.whoami import fold, roster_key

USERS_DIR = "users"
VERSION = 1

# Fixed UTC-7, no DST — the same rule harness/ledger.py shards on, pinned
# equal by test. The daily touch buckets on THIS clock so a person opening
# the app at 1 a.m. does not write once for UTC's day and once for Arizona's.
ARIZONA_TZ = timezone(timedelta(hours=-7), name="MST")


class RosterUnavailable(Exception):
    """The users folder itself could not be read — distinct from "nobody
    has opened the app", which is an empty list (spec U12)."""


@dataclass(frozen=True)
class Person:
    key: str
    username: str
    display_name: str
    name_source: str  # "typed" | "windows" | ""
    first_seen: str
    last_seen: str


def users_dir() -> Path:
    return data_dir() / USERS_DIR


def _now() -> datetime:
    return datetime.now(ARIZONA_TZ)


def _path_for(username: str) -> Path | None:
    key = roster_key(username)
    return users_dir() / f"{key}.json" if key else None


# ---------------------------------------------------------------------------
# Reading — one file, cached on its stamp; never raises
# ---------------------------------------------------------------------------

_lock = threading.Lock()
# path -> ((mtime_ns, size), Person | None). display_name() calls this on
# every page load (spec U6), so a page load after a page load costs one stat.
_cache: dict[str, tuple[tuple[int, int], Person | None]] = {}


def reset_roster_cache() -> None:
    with _lock:
        _cache.clear()


def _parse(path: Path, raw: object) -> Person | None:
    if not isinstance(raw, dict):
        return None
    username = raw.get("username")
    if not isinstance(username, str) or not username.strip():
        return None

    def s(key: str) -> str:
        v = raw.get(key)
        return v.strip() if isinstance(v, str) else ""

    return Person(
        key=path.stem,
        username=username,
        display_name=s("display_name"),
        name_source=s("name_source") if s("name_source") in ("typed", "windows") else "",
        first_seen=s("first_seen"),
        last_seen=s("last_seen"),
    )


def _read_path(path: Path) -> Person | None:
    """NEVER raises. Any failure — missing, unreadable, torn, wrong shape —
    is None, because the callers are `display_name()` on the request path
    of every page load and `list_people()`, which counts torn files."""
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError — the
        # trap harness/ledger.py documents.
        return None
    person = _parse(path, raw)
    with _lock:
        _cache[str(path)] = (stamp, person)
    return person


def read_person(username: str) -> Person | None:
    path = _path_for(username)
    return _read_path(path) if path else None


def typed_name(username: str) -> str:
    """The name this person TYPED, or "". A Windows-sourced name is not
    returned here: `display_name()` already reads Windows itself, and this
    is only the roster's claim on the top of that ladder (spec U6)."""
    p = read_person(username)
    return p.display_name if p and p.name_source == "typed" else ""


def list_people() -> tuple[list[Person], int]:
    """Every readable row, plus a COUNT of unreadable ones (spec U12).

    Raises RosterUnavailable when the folder cannot be read. Same
    discrimination app/issue_reports.py makes: `os.listdir`, not
    `Path.glob` (pathlib swallows the error and yields nothing — verified
    on this project), and a FileNotFoundError is "nobody yet" only when
    the ROOT data dir exists, because `data_dir()` creates the root as a
    side effect and a vanished share raises the same exception.
    """
    directory = users_dir()
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        if not directory.parent.is_dir():
            raise RosterUnavailable(f"shared data folder is unreachable: {directory.parent}")
        return [], 0
    except OSError as err:
        print(f"users.registry: cannot read {directory} ({err})", file=sys.stderr)
        raise RosterUnavailable(str(err)) from err
    people: list[Person] = []
    unreadable = 0
    for name in sorted(names):
        if not name.endswith(".json"):
            continue  # a ".tmp-…" half-write never shows up
        person = _read_path(directory / name)
        if person is None:
            unreadable += 1
            print(f"users.registry: unreadable row {directory / name}", file=sys.stderr)
        else:
            people.append(person)
    return people, unreadable


# ---------------------------------------------------------------------------
# Writing — only ever the CALLER'S OWN user; raises
# ---------------------------------------------------------------------------

def _write(path: Path, row: dict) -> None:
    """tmp + os.replace, like every other JSON writer on the share."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json.part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(row, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _row(p: Person) -> dict:
    return {
        "version": VERSION,
        "username": p.username,
        "display_name": p.display_name,
        "name_source": p.name_source,
        "first_seen": p.first_seen,
        "last_seen": p.last_seen,
    }


def touch(username: str, *, windows_name: str = "", local_typed_name: str = "") -> bool:
    """Record that `username` opened the app today. Returns True iff it wrote.

    Writes only when something changed (spec U3): the person is new, the
    Arizona calendar day rolled over, the observed spelling changed, or the
    name changed — and a name changes only per spec U5: a typed name is
    never overwritten; a Windows name is refreshed only from a NON-EMPTY
    read (`_windows_display_name()` returns "" on any failure, and a blank
    must not erase a good name); a name typed on this machine before the
    roster existed migrates up once (spec U6).
    """
    path = _path_for(username)
    if path is None:
        return False
    now = _now()
    stamp = now.isoformat(timespec="seconds")
    existing = _read_path(path)

    windows_name = windows_name.strip()
    local_typed_name = local_typed_name.strip()

    if existing is None:
        if local_typed_name:
            name, source = local_typed_name, "typed"
        elif windows_name:
            name, source = windows_name, "windows"
        else:
            name, source = "", ""
        _write(path, _row(Person(path.stem, username, name, source, stamp, stamp)))
        return True

    name, source = existing.display_name, existing.name_source
    if source != "typed":
        if local_typed_name:
            name, source = local_typed_name, "typed"
        elif windows_name and windows_name != name:
            name, source = windows_name, "windows"

    changed = (
        existing.last_seen[:10] != stamp[:10]
        or existing.username != username
        or (name, source) != (existing.display_name, existing.name_source)
    )
    if not changed:
        return False
    _write(path, _row(Person(
        path.stem, username, name, source, existing.first_seen or stamp, stamp,
    )))
    return True


def set_typed_name(username: str, name: str) -> None:
    """The person's own name, typed on Settings. Blank clears it (spec U5) —
    "never set" and "cleared" are one state, so the Windows name can come
    back on the next touch. Raises on failure; the route decides what that
    means (the local machine file is written first and still counts)."""
    path = _path_for(username)
    if path is None:
        return
    now = _now().isoformat(timespec="seconds")
    existing = _read_path(path)
    cleaned = name.strip()
    if existing is None:
        person = Person(path.stem, username, cleaned, "typed" if cleaned else "", now, now)
    elif cleaned:
        person = Person(path.stem, existing.username, cleaned, "typed",
                        existing.first_seen or now, existing.last_seen or now)
    else:
        person = Person(path.stem, existing.username, "", "",
                        existing.first_seen or now, existing.last_seen or now)
    _write(path, _row(person))
