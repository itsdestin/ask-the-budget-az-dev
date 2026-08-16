"""Agencies the office added, for the upload page's agency picker.

`samples/entity-catalog.yaml` is a COMMITTED file the office bundle ships
read-only, and it holds the 157 agencies Phase 0 catalogued. Agencies are
created, merged and renamed by the Legislature, so a picker that can only
ever offer those 157 will eventually be unable to name the document in
front of somebody. This is the escape hatch: a small JSON file on the
shared data dir listing extra agencies, merged after the catalog.

🔴 THIS IS NOT RETRIEVAL VOCABULARY, and the distinction is the whole
reason it is a separate file from `store/office_aliases.py` rather than
another key inside it. An office alias changes what a SEARCH resolves to,
so a bad one silently sends queries to the wrong agency and every entry in
that module is validated on that basis. An entry here only decides what an
uploaded document is CALLED. The worst a bad one can do is put a wrong
name in one document's title, which is visible on the search page the
moment anybody looks — the opposite of silent.

Read posture mirrors `store/office_aliases.py`, which mirrors
`harness/settings.py`: cached on a (path, mtime, size) stamp so a rewrite
by another machine on the share is picked up, degrading to empty on any
bad file. Writes are tmp+os.replace and RAISE — a failed save must reach
the admin's screen, not vanish.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from chunking.agency_catalog import load_agency_catalog
from store.config import data_dir

OFFICE_AGENCIES_FILE = "office-agencies.json"

# Added agencies are namespaced away from the catalog's own ids. Two reasons,
# and the second is the load-bearing one:
#
#   1. A catalog id and an office id can never collide, so an office entry
#      cannot shadow a shipped agency by accident.
#   2. It stays VISIBLE in the data that this name did not come from the
#      Phase 0 catalog. `agency:office-...` on a document is a standing
#      reminder that nothing in the corpus was stamped with it — see the
#      picker's own note in app/routes/agencies.py.
OFFICE_ID_PREFIX = "agency:office-"


@dataclass(frozen=True)
class OfficeAgency:
    canonical_id: str
    name: str
    added_by: str = ""
    added_at: str = ""


@dataclass(frozen=True)
class Agency:
    """One row of the picker, from either source."""

    canonical_id: str
    name: str
    source: str  # "catalog" | "office"


def office_agencies_path() -> Path:
    return data_dir() / OFFICE_AGENCIES_FILE


_lock = threading.Lock()
# (path_str, mtime_ns, size) -> tuple[OfficeAgency, ...]. One entry — one file.
_cache: tuple[tuple[str, int, int], tuple[OfficeAgency, ...]] | None = None


def reset_office_agencies_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _say_unavailable(resolved: Path, err: Exception) -> None:
    """The one sentence both degraded reads print, written once so the two
    paths cannot drift into saying different things about the same
    outcome."""
    print(
        f"store.office_agencies: ignoring {resolved} ({err}) — agencies the "
        "office added are unavailable for this read.",
        file=sys.stderr,
    )


def load_office_agencies(path: Path | None = None) -> tuple[OfficeAgency, ...]:
    """The overlay, or empty. NEVER raises: a bad file must cost the office's
    additions, not the whole picker — the 157 shipped agencies still work."""
    global _cache
    resolved = path if path is not None else office_agencies_path()
    try:
        stat = resolved.stat()
        stamp = (str(resolved), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        # No overlay is the normal, silent case — most offices never need one.
        return ()
    except OSError as err:
        _say_unavailable(resolved, err)
        return ()
    with _lock:
        if _cache is not None and _cache[0] == stamp:
            return _cache[1]
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"expected an object, got {type(raw).__name__}")
        parsed = _from_dict(raw)
    except (OSError, ValueError, TypeError, KeyError) as err:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError —
        # the trap harness/ledger.py documents.
        _say_unavailable(resolved, err)
        return ()
    with _lock:
        _cache = (stamp, parsed)
    return parsed


def _from_dict(raw: dict) -> tuple[OfficeAgency, ...]:
    out: list[OfficeAgency] = []
    seen: set[str] = set()
    for row in raw.get("added", []) or []:
        # A non-dict element (null, a bare string, a number) is torn data and
        # costs itself, not the file. Without this check `row.get` raises
        # AttributeError, which is not in the caught tuple above, and the
        # whole load blows up.
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        canonical_id = str(row.get("canonical_id") or "").strip()
        if not name or not canonical_id or canonical_id in seen:
            continue
        seen.add(canonical_id)
        out.append(
            OfficeAgency(
                canonical_id=canonical_id,
                name=name,
                added_by=str(row.get("added_by") or ""),
                added_at=str(row.get("added_at") or ""),
            )
        )
    return tuple(out)


def save_office_agencies(
    agencies: tuple[OfficeAgency, ...], path: Path | None = None
) -> None:
    """Atomic write. RAISES on failure — the admin route turns that into a
    visible error, never a silent no-op save."""
    resolved = path if path is not None else office_agencies_path()
    payload = {
        "added": [
            {
                "canonical_id": a.canonical_id,
                "name": a.name,
                "added_by": a.added_by,
                "added_at": a.added_at,
            }
            for a in agencies
        ]
    }
    # Per-call uuid suffix, not per-process — the chat-history lesson: two
    # writers on one file must not share a tmp name.
    tmp = resolved.with_name(f"{resolved.name}.tmp-{uuid.uuid4().hex[:8]}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, resolved)
    reset_office_agencies_cache()


def all_agencies() -> tuple[Agency, ...]:
    """Every agency the picker may offer: the shipped catalog, then the
    office's own, sorted by name within each source.

    Catalog first and office second is deliberate rather than one merged
    alphabetical run — an office entry is a name nothing in the corpus is
    stamped with, and keeping the two groups separable lets the picker say
    so instead of hiding it among 157 that are.
    """
    catalog = sorted(
        (
            Agency(canonical_id=entry.canonical_id, name=entry.canonical_name,
                   source="catalog")
            for entry in load_agency_catalog().values()
        ),
        key=lambda a: a.name.lower(),
    )
    office = sorted(
        (
            Agency(canonical_id=a.canonical_id, name=a.name, source="office")
            for a in load_office_agencies()
        ),
        key=lambda a: a.name.lower(),
    )
    return tuple(catalog) + tuple(office)


def agency_name(canonical_id: str) -> str | None:
    """Display name for an id from EITHER source, or None if unknown.

    One function, because the upload route validates against the picker's
    list and the ingest worker later turns the same id into the document's
    title — two lookups that must agree, or a document is accepted under a
    name it is then not given.
    """
    if not canonical_id:
        return None
    for agency in all_agencies():
        if agency.canonical_id == canonical_id:
            return agency.name
    return None
