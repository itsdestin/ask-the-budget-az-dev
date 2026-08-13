"""Which folder a job file belongs in, and the one-time sweep that gets the
already-finished ones there.

Spec T13, as amended 2026-08-13. The queue must show outstanding work and
every failure regardless of age. Doing that as a FILTER means reading every
job file on every poll -- measured at 7,118 files / 3.02 MB per refresh, over
an SMB share, on a page that polls. Doing it as a LOCATION means the main
folder already IS the answer, and every other reader gets cheaper for free.

The spec originally said to filter on each file's mtime from the directory
scan, before parsing it. That was measured and cannot work: an mtime does not
carry the job's STATE, and on the live data dir 13 of the 14 `failed` jobs
had files 12.6 days old, so a 24-hour window drops 13 of 14 failures -- the
exact inversion of the rule the decision calls non-negotiable.

Why a subdirectory rather than encoding the state in the filename: this queue
is a directory of small JSON files specifically so that "a colleague (or a
future maintainer with no code access) can read the queue in Notepad" (see
ingest/jobs.py's module docstring). A folder named `done` says what it holds.
A filename suffix does not. Destin chose this shape on 2026-08-13.

Nothing here deletes anything, ever.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

# States whose files move out of the main folder.
#
# `failed` is deliberately NOT here and must never be added: spec T13 requires
# every failure to stay visible regardless of age, and that guarantee is
# provided by this frozenset and nothing else. Adding it would silently delete
# the Needs-attention panel's entire input as well as the queue's.
ARCHIVED_STATES = frozenset({"live", "cancelled"})

ARCHIVE_DIRNAME = "done"


def dir_for_state(main: Path, state: str) -> Path:
    """The folder a job in `state` belongs in."""
    return (main / ARCHIVE_DIRNAME) if state in ARCHIVED_STATES else main


def unlink_with_retry(path: Path, *, attempts: int = 20) -> bool:
    """Remove a file another machine may have open. Never raises.

    Same hazard as ingest/jobs.py::_replace_with_retry: Windows and SMB refuse
    to touch a file while another handle is open, and the queue page polls
    these files from other PCs every couple of seconds while the worker writes
    progress several times a stage. Retrying briefly is correct -- the
    reader's handle is open for the microseconds of a small read.

    A failure here is benign BY DESIGN, which is why this returns a bool
    instead of raising. The new copy is already written, so the worst case is
    one job appearing in both folders -- which `load_all` dedupes -- rather
    than a job file lost. That is why the caller writes first and removes
    second, and never the other way round.
    """
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if attempt == attempts - 1:
                return False
            time.sleep(0.02)
        except OSError:
            return False
    return False


def sweep(main: Path, *, read: Callable[[Path], object], limit: int | None = None) -> int:
    """Move already-finished job files into `done/`. Idempotent.

    Runs once at startup. The first run on the office share has ~7,100 files
    to move; every later run reads only what is left in the main folder, which
    by then is outstanding work plus failures -- tens of files.

    `read` is injected (`ingest.jobs._read`) rather than imported so this
    module has no import back into jobs.py, which imports it.

    Two machines sweeping at once is safe and expected: `os.replace` to the
    same destination is last-writer-wins over identical bytes, and a file
    another machine already moved simply is not there any more. Both of those
    outcomes are `continue`, not errors.
    """
    archive = main / ARCHIVE_DIRNAME
    archive.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(main.glob("*.json")):
        if limit is not None and moved >= limit:
            break
        job = read(path)
        # An unreadable file stays put: one corrupt job must not stop the
        # sweep, and moving a file we could not parse would hide it in the
        # archive where nobody looks for a problem.
        if job is None or getattr(job, "state", None) not in ARCHIVED_STATES:
            continue
        try:
            os.replace(path, archive / path.name)
            moved += 1
        except FileNotFoundError:
            continue          # another machine got there first
        except OSError:
            continue          # locked right now; the next sweep gets it
    return moved
