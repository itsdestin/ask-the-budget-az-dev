"""Filesystem operations that survive Windows and SMB sharing violations.

POSIX rename/unlink are unconditional. Windows (and SMB shares served to it)
refuse to replace or delete a file another handle has open, and antivirus
holds a freshly written file for a moment. Every writer of a file that other
PCs read live goes through here: job files (polled every couple of seconds by
~20 PCs), documents.json (4.5 MB, read on every search), the fiscal-note
directory, the ingest lock.

Lifted out of ingest/jobs.py and ingest/archive.py on 2026-08-25 because
store/config.py needed the same thing and must not import ingest/.
"""
from __future__ import annotations

import errno
import os
import time
from pathlib import Path

_SLEEP_S = 0.02
# WinError 5 = access denied, 32 = sharing violation. Both are transient here.
_TRANSIENT_WINERRORS = (5, 32)


def _transient(err: OSError) -> bool:
    if isinstance(err, PermissionError):
        return True
    return getattr(err, "winerror", None) in _TRANSIENT_WINERRORS or err.errno == errno.EACCES


def replace_with_retry(tmp: Path, path: Path, *, budget_s: float = 3.0) -> None:
    """os.replace, retried for up to `budget_s` on a transient lock.

    On final failure the tmp file is removed and the error re-raised — a
    stale `.tmp` beside a shared file reads as corruption to the next person.
    3 s by default because documents.json is multi-MB and a reader's handle
    over SMB is open for tens of milliseconds, not microseconds.
    """
    deadline = time.monotonic() + budget_s
    while True:
        try:
            os.replace(tmp, path)
            return
        except OSError as err:
            if not _transient(err) or time.monotonic() >= deadline:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(_SLEEP_S)


def unlink_with_retry(path: Path, *, budget_s: float = 0.4) -> bool:
    """Remove a file another machine may have open. Never raises; False if it
    could not be removed within the budget (the caller decides whether that
    matters — for an archived job it does not, the new copy already exists)."""
    deadline = time.monotonic() + budget_s
    while True:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as err:
            if not _transient(err) or time.monotonic() >= deadline:
                return False
            time.sleep(_SLEEP_S)
