"""Where THIS machine thinks the shared corpus lives (Plan 5 Task 10, S18).

The failure this exists for: the shared drive moves, or a colleague's PC
maps it to a different letter, and the app on that machine stops finding
the corpus. Before this, the only fix was an environment variable, which
requires knowing what an environment variable is. Now the repair screen
writes a small JSON file here and the app finds the corpus next launch.

RESOLUTION ORDER (`store.config.data_dir` implements it):

    JLBC_DATA_DIR  >  machine.json  >  the repo default

The env var staying on top is load-bearing, not incidental. The Z13
backfill runs with `JLBC_DATA_DIR` set, and a `machine.json` written on
that box by a repair screen must never silently redirect a running
multi-hour ingest to a different folder.

NOTHING IN THIS MODULE RAISES ON A BROKEN FILE. This file being
unreadable is exactly the moment the app has to still boot far enough to
show the repair screen that fixes it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path, PosixPath, WindowsPath

MACHINE_FILE = "machine.json"

# The REAL local filesystem class, captured once at import — before any
# test can monkeypatch os.name to exercise normalize_data_dir's Windows
# string-formatting branch. `pathlib.Path(...)` re-reads `os.name` on
# EVERY call (`PurePath.__new__`), so this module's own file I/O would
# otherwise start building WindowsPath objects mid-test on a Linux box —
# and CPython 3.12 refuses to instantiate WindowsPath a second time on a
# non-Windows system (`.parent`, `/`, `.mkdir()` all raise
# NotImplementedError, since pathlib's internals reconstruct paths via
# `type(self)(...)`, not the dispatcher). Binding the concrete class here,
# once, keeps this module's actual reads/writes tied to the machine it is
# really running on, regardless of what a test mocks afterward.
_LocalPath = WindowsPath if os.name == "nt" else PosixPath

# Test seam. Without it, every test in tests/test_machine_config.py would
# read and WRITE the developer's real per-machine pointer and silently
# redirect their own dev corpus.
_DIR_ENV_VAR = "JLBC_MACHINE_CONFIG_DIR"

# Whether THIS machine processes the upload queue. Same resolution order as
# the data dir — env > machine.json > default — for the same reason: a dev
# clone and the backfill box have no machine.json and must not have to click
# a button in a browser to make their own queue run.
_INGEST_ENV_VAR = "JLBC_INGEST_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off", ""})

MSG_NO_CORPUS = (
    "That folder doesn't contain a JLBC Search corpus (no budget documents "
    "in its search index)."
)
MSG_CANT_OPEN = (
    "That folder is there, but the search index inside it can't be opened. "
    "Copy the folder's address from File Explorer's address bar and try again."
)
MSG_DIFFERENT_INDEX = (
    "That folder holds a search index made by a different version of the app. "
    "Ask whoever maintains the shared drive to re-copy the corpus for this build."
)


def machine_config_dir() -> Path:
    """Per-machine, per-user config location.

    `%LOCALAPPDATA%` on Windows — deliberately NOT the shared drive, which
    is the whole point: this file says where the share IS, so it cannot
    live on it. `~/.config/jlbc-search` elsewhere, because the dev
    machines are Linux.
    """
    override = os.environ.get(_DIR_ENV_VAR)
    if override:
        return _LocalPath(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return _LocalPath(local_appdata) / "JLBC-Search"
    return _LocalPath.home() / ".config" / "jlbc-search"


def machine_config_path() -> Path:
    return machine_config_dir() / MACHINE_FILE


def _read_all(*, quiet: bool = False) -> dict:
    """The whole machine.json as a dict, or `{}` on any problem.

    Every failure mode — absent, corrupt, wrong shape, no permission —
    answers `{}`, which every caller reads as "nothing configured here".
    A missing file is silent (the overwhelmingly common case: nobody has
    run the repair screen). Anything else prints, because a file that
    exists and cannot be used is a real problem someone has to find.
    """
    path = machine_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}  # nothing configured on this machine — normal
    except (OSError, ValueError) as err:
        if not quiet:
            print(
                f"app.machine_config: {path} is unreadable ({err}) — falling back "
                "to the default data folder. Use the repair screen, or delete "
                "this file, to fix it.",
                file=sys.stderr,
            )
        return {}
    if not isinstance(raw, dict):
        if not quiet:
            print(
                f"app.machine_config: {path} is not a JSON object — ignoring it.",
                file=sys.stderr,
            )
        return {}
    return raw


def read_data_dir() -> Path | None:
    """The configured share, or None if there isn't one or it is unreadable."""
    value = _read_all().get("data_dir")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip())


def ingest_enabled() -> bool:
    """Does THIS machine process the upload queue?

    **Defaults to False, and that default is the whole point.** The
    packaging decision was one bundle on all ~20 office PCs, and
    `launcher.pyw` calls `create_app()` with no arguments — so without
    this, twenty machines start a worker against one shared queue.
    `IngestLock` keeps that SAFE, but the winner is arbitrary and may be
    an analyst's laptop that then spends six hours at 100% CPU on a
    Baseline book while they are trying to work.

    Resolution order mirrors `store.config.data_dir`: `JLBC_INGEST_ENABLED`
    > `machine.json` > False. The env var is what a dev clone and the
    backfill machine use — neither has a machine.json, and neither should
    have to click a button in a browser to make its own queue run.

    A machine.json with no `ingest_enabled` key reads as False: that is
    the file `Install-JLBC-Search.cmd` writes (via `python -m
    app.machine_config`), and silence must not read as consent.

    An unrecognised env value falls through to the file rather than
    reading as False. A typo on the ONE machine configured to do the work
    would otherwise stop the office's uploads with no error anywhere —
    the exact silent pile-up the admin warning exists to catch.
    """
    raw = os.environ.get(_INGEST_ENV_VAR)
    if raw is not None:
        value = raw.strip().lower()
        if value in _TRUTHY:
            return True
        if value in _FALSY:
            return False
    return _read_all(quiet=True).get("ingest_enabled") is True


def set_ingest_enabled(enabled: bool) -> None:
    """Record whether this machine processes the queue."""
    _update({"ingest_enabled": bool(enabled)})


# The analyst's name as it should appear on a generated memo. Keyed by
# username, so a machine with two Windows accounts keeps two names.
#
# HERE RATHER THAN THE SHARED settings.json ON PURPOSE (spec M6).
# `save_settings` is a read-modify-write on a file ~20 machines share, and
# it holds the OpenRouter API key, the tier->model map, the admin username
# and every spend limit. Routing a routine per-analyst write through it
# would add a corruption path to all of that in exchange for a name
# following an analyst between PCs — and the app is installed per machine
# (S7) and launched by the person sitting at it (S8), so it rarely moves.
_DISPLAY_NAMES_KEY = "display_names"

# Long enough for a real name with a suffix, short enough that the memo's
# FROM row cannot wrap.
MAX_DISPLAY_NAME = 120


def read_display_name(user: str) -> str:
    """This machine's stored name for `user`, or "" if there isn't one."""
    names = _read_all(quiet=True).get(_DISPLAY_NAMES_KEY)
    if not isinstance(names, dict):
        return ""
    value = names.get(user)
    return value.strip() if isinstance(value, str) else ""


def set_display_name(user: str, name: str) -> None:
    """Record (or, with a blank name, forget) this machine's name for `user`."""
    names = _read_all(quiet=True).get(_DISPLAY_NAMES_KEY)
    if not isinstance(names, dict):
        names = {}
    cleaned = name.strip()[:MAX_DISPLAY_NAME]
    if cleaned:
        names[user] = cleaned
    else:
        # Removed rather than stored blank, so "never set" and "cleared"
        # are the same state and neither shadows the Windows name.
        names.pop(user, None)
    _update({_DISPLAY_NAMES_KEY: names})


def normalize_data_dir(path: Path | str) -> str:
    """The stored form of a data-dir path: the spelling the storage engine
    can open.

    WHY this exists (work laptop, 2026-08-18 — see
    docs/superpowers/investigations/2026-08-25-windows-launch-failure.md):
    `//bcpool/JLBCSearch` passes every pathlib check (`exists`, `is_dir`,
    `iterdir`), so the repair screen accepted it and said "saved"; LanceDB's
    Rust object store then built a `file://` URL from it and refused it
    (InvalidUrl) — and the app kept serving stub fixtures. Every writer
    funnels through here first, so what lands in machine.json is the form
    LanceDB opens, not what was typed.

    Rules: trim, strip surrounding quotes, drop trailing separators (but not
    from a bare drive root — `E:` alone means "current directory on E:").
    On Windows every `/` becomes `\\`; a path starting with ONE separator
    (`/host/share`) is read as a UNC root and gains its second one. That
    last rule is a guess — `\\JLBCSearch` can also mean `C:\\JLBCSearch` —
    and is harmless only because validate_data_dir refuses anything that
    does not open.
    """
    cleaned = str(path).strip().strip('"').strip("'").strip()
    stripped = cleaned.rstrip("\\/")
    # A drive root keeps ONE separator: `E:\` stays, and a bare `E:` becomes
    # `E:\` — `E:` alone means "current directory on E:" to Windows and
    # Path("E:").exists() is True, so it would validate and then open LanceDB
    # relative to wherever the process happens to be.
    cleaned = stripped + "\\" if stripped.endswith(":") else stripped
    if os.name == "nt":
        cleaned = cleaned.replace("/", "\\")
        if len(cleaned) >= 2 and cleaned[0] == "\\" and cleaned[1] != "\\":
            cleaned = "\\" + cleaned
    return cleaned


def validate_data_dir(path: Path | str) -> str | None:
    """None if `path` is a usable corpus folder, else ONE plain sentence.

    Returns the message rather than raising because the caller is an HTTP
    route rendering it to a person who just typed a path into a repair
    screen — and that person needs to know which of the three things went
    wrong: typo, right folder but empty, or right idea but a file.

    The `lancedb/` check is what distinguishes "the share" from "a folder
    on the share". Pointing the app at the parent of the real data
    directory is the single most likely mistake here, and it would
    otherwise look like a successful repair followed by an empty corpus.
    """
    candidate_str = normalize_data_dir(path)
    if not candidate_str:
        return "Type the full path to the shared JLBC Search folder."
    candidate = Path(candidate_str)
    if not candidate.exists():
        return (
            "Couldn't find that folder. Check the spelling, and that the "
            "shared drive is connected."
        )
    if not candidate.is_dir():
        return "That's a file, not a folder. Pick the folder that holds the corpus."
    if not (candidate / "lancedb").is_dir():
        return MSG_NO_CORPUS
    # Open it the way the app does. The laptop incident (2026-08-18):
    # `//bcpool/JLBCSearch` passed every pathlib check above and the storage
    # engine refused it, so the repair screen reported success over an app
    # still serving fixtures. This is the only check that cannot false-pass.
    # create=False: validation must never manufacture a folder (principle 3).
    # Repair path only — never a hot path — so an open is affordable.
    try:
        from store.chunk_store import ChunkStore

        rows = ChunkStore(root=candidate, create=False).count("budget_chunks")
    except Exception as err:  # noqa: BLE001 — every engine failure is one sentence
        # `_check_dim` raises ValueError naming the dimension: an index
        # embedded by another model. Retyping the address cannot fix that —
        # same discrimination app/health.py::_check_corpus already makes.
        if "dim" in (str(err) + type(err).__name__).lower():
            return MSG_DIFFERENT_INDEX
        return MSG_CANT_OPEN
    if rows <= 0:
        return MSG_NO_CORPUS
    return None


def _update(changes: dict) -> None:
    """Merge `changes` into machine.json, preserving every other key.

    READ-MODIFY-WRITE, not write. `set_data_dir` used to write
    `{"data_dir": ...}` wholesale, which was harmless while that was the
    only key — with `ingest_enabled` alongside it, using the repair screen
    would silently switch off the one machine configured to process
    uploads, and the symptom would surface days later as a queue nothing
    drains.

    Written tmp-file-then-`os.replace`, the same discipline as
    `save_settings` and for a sharper reason: a half-written pointer is
    indistinguishable from a corrupt one, so an interrupted write would
    send the app straight back to the repair screen it had just been used
    to escape.

    A corrupt existing file is REPLACED rather than merged into — `_read_all`
    already reported it, and refusing to write would leave the machine with
    no way to fix itself.
    """
    merged = _read_all(quiet=True)
    merged.update(changes)
    target = machine_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".machine-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def set_data_dir(path: Path | str) -> Path:
    """Point this machine at `path`. Returns the stored path.

    Does NOT validate — the caller does, so it can report which of the
    failures happened. Writing an unvalidated path deliberately remains
    possible: an admin fixing a pointer while the share is temporarily
    down should not be blocked by the share being down.

    STORED NORMALISED (`normalize_data_dir`): the laptop incident proved a
    pointer can pass every Python check and still be a form the storage
    engine refuses.
    """
    stored = normalize_data_dir(path)
    _update({"data_dir": stored})
    return Path(stored)


# ---------------------------------------------------------------------------
# CLI — for packaging/Install-JLBC-Search.cmd
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """`python -m app.machine_config --set-data-dir "\\\\server\\share"`.

    `packaging/Install-JLBC-Search.cmd` — the one-click installer on the
    USB — runs this before the app has ever started, so it used to write
    machine.json with a hand-rolled JSON literal — the schema duplicated
    in a batch file, guaranteed to rot the first time this module changed
    shape (which it just did, gaining `ingest_enabled`).

    Contract, as `packaging/` depends on it:

    * Exit 0 on success, silently. The installer prints its own progress
      and a chatty subprocess in the middle reads as an error to whoever
      is watching.
    * Validation failure is a WARNING on stderr and still exit 0. A
      network drive that is not connected during setup is normal, and
      refusing to record the path would strand the user with an installed
      app pointing nowhere.
    * Non-zero only when there is genuinely nothing to record.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.machine_config",
        description="Configure JLBC Search for THIS computer.",
    )
    parser.add_argument("--set-data-dir", metavar="PATH")
    parser.add_argument(
        "--set-ingest-enabled", metavar="BOOL", choices=("true", "false"),
    )
    parser.add_argument(
        "--default-ingest-enabled", metavar="BOOL", choices=("true", "false"),
        help="record the value only if machine.json has no ingest_enabled key",
    )
    args = parser.parse_args(argv)

    if (
        args.set_data_dir is None
        and args.set_ingest_enabled is None
        and args.default_ingest_enabled is None
    ):
        parser.error(
            "nothing to do — pass --set-data-dir, --set-ingest-enabled or "
            "--default-ingest-enabled"
        )

    if args.set_data_dir is not None:
        if not args.set_data_dir.strip():
            print(
                "Nothing to record: --set-data-dir was empty.", file=sys.stderr
            )
            return 2
        problem = validate_data_dir(args.set_data_dir)
        if problem:
            print(f"Warning: {problem} Recording it anyway.", file=sys.stderr)
        set_data_dir(args.set_data_dir)

    if args.set_ingest_enabled is not None:
        set_ingest_enabled(args.set_ingest_enabled == "true")

    if args.default_ingest_enabled is not None:
        # WHY a separate flag: the installer runs on every upgrade, and
        # `--set-ingest-enabled false` there switched the one ingest machine
        # off each time (2026-08-25). A default must not override a choice.
        if "ingest_enabled" not in _read_all(quiet=True):
            set_ingest_enabled(args.default_ingest_enabled == "true")

    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
