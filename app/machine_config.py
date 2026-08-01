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
from pathlib import Path

MACHINE_FILE = "machine.json"

# Test seam. Without it, every test in tests/test_machine_config.py would
# read and WRITE the developer's real per-machine pointer and silently
# redirect their own dev corpus.
_DIR_ENV_VAR = "JLBC_MACHINE_CONFIG_DIR"

MSG_NO_CORPUS = (
    "That folder doesn't contain a JLBC Insight corpus (no lancedb folder inside)."
)


def machine_config_dir() -> Path:
    """Per-machine, per-user config location.

    `%LOCALAPPDATA%` on Windows — deliberately NOT the shared drive, which
    is the whole point: this file says where the share IS, so it cannot
    live on it. `~/.config/jlbc-insight` elsewhere, because the dev
    machines are Linux.
    """
    override = os.environ.get(_DIR_ENV_VAR)
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "JLBC-Insight"
    return Path.home() / ".config" / "jlbc-insight"


def machine_config_path() -> Path:
    return machine_config_dir() / MACHINE_FILE


def read_data_dir() -> Path | None:
    """The configured share, or None if there isn't one or it is unreadable.

    Every failure mode — absent, corrupt, wrong shape, blank value, no
    permission — answers None, which the caller reads as "nothing
    configured here" and falls through to the repo default. A missing file
    is silent (the overwhelmingly common case: nobody has run the repair
    screen). Anything else prints, because a file that exists and cannot
    be used is a real problem someone has to be able to find.
    """
    path = machine_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None  # nothing configured on this machine — normal
    except (OSError, ValueError) as err:
        print(
            f"app.machine_config: {path} is unreadable ({err}) — falling back "
            "to the default data folder. Use the repair screen, or delete "
            "this file, to fix it.",
            file=sys.stderr,
        )
        return None
    if not isinstance(raw, dict):
        print(
            f"app.machine_config: {path} is not a JSON object — ignoring it.",
            file=sys.stderr,
        )
        return None
    value = raw.get("data_dir")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip())


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
    if not str(path).strip():
        return "Type the full path to the shared JLBC Insight folder."
    candidate = Path(str(path).strip())
    if not candidate.exists():
        return (
            "Couldn't find that folder. Check the spelling, and that the "
            "shared drive is connected."
        )
    if not candidate.is_dir():
        return "That's a file, not a folder. Pick the folder that holds the corpus."
    if not (candidate / "lancedb").is_dir():
        return MSG_NO_CORPUS
    return None


def set_data_dir(path: Path | str) -> Path:
    """Point this machine at `path`. Returns the resolved path.

    Written tmp-file-then-`os.replace`, the same discipline as
    `save_settings` and for a sharper reason: a half-written pointer is
    indistinguishable from a corrupt one, so an interrupted write would
    send the app straight back to the repair screen it had just been used
    to escape.

    Does NOT validate — the caller does, so it can report which of the
    three failures happened. Writing an unvalidated path deliberately
    remains possible: an admin fixing a pointer while the share is
    temporarily down should not be blocked by the share being down.
    """
    resolved = Path(str(path).strip())
    target = machine_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".machine-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"data_dir": str(resolved)}, f, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return resolved
