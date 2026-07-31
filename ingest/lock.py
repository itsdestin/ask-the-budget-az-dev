"""Single-writer ingest lock (spec S6).

The corpus lives on an office SMB share that several machines mount at once.
Readers are unlimited; writers must be serialized, because `upsert_chunks` is
delete-then-add across two commits and two concurrent writers can interleave
into a corpus that is missing rows.

WHY a lockfile created with `open(path, "x")` rather than `msvcrt.locking`,
`fcntl.flock`, or a LanceDB row: exclusive-create is the one atomicity
primitive Windows SMB honors reliably across machines. Byte-range locks are
advisory-at-best over SMB and leak when a client dies mid-session; a DB-row
lock needs a writer to release it, which is exactly what a crashed writer
can't do.

Crashes are the normal failure here, not the exotic one — someone closes the
laptop mid-ingest. So the lock carries a heartbeat the holder refreshes
between stages, and any lock whose heartbeat has gone quiet for longer than
`stale_after_s` is stolen by the next writer. That trades a small window of
double-writing (only if a machine freezes for minutes and then thaws
mid-write) against the certainty of a permanently wedged corpus.
"""
from __future__ import annotations

import getpass
import json
import os
import socket
import time
from pathlib import Path
from types import TracebackType

from store.config import data_dir

LOCK_FILENAME = "ingest.lock"

# Two minutes of silence means the holder is gone. Long enough that a slow SMB
# round-trip or a paused VM won't trip it; short enough that a colleague who
# reboots mid-upload isn't blocked for the rest of the afternoon.
DEFAULT_STALE_AFTER_S = 120


class LockHeldError(RuntimeError):
    """Another live writer holds the ingest lock."""


class IngestLock:
    """Cross-process, cross-machine single-writer lock on the shared data dir.

    Usable as a context manager (`with IngestLock():`) or explicitly via
    `acquire()` / `release()`. `heartbeat()` must be called periodically
    during long work or another machine will consider the lock abandoned.
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        stale_after_s: int = DEFAULT_STALE_AFTER_S,
    ) -> None:
        self._root = Path(root) if root is not None else data_dir()
        self._stale_after_s = stale_after_s
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    @property
    def path(self) -> Path:
        return self._root / LOCK_FILENAME

    # --- acquire / release --------------------------------------------------

    def acquire(self) -> "IngestLock":
        """Take the lock, or raise LockHeldError naming the current holder."""
        self._root.mkdir(parents=True, exist_ok=True)
        if self._try_create():
            self._held = True
            return self

        owner = self._read_owner()
        if not self._is_stale(owner):
            raise LockHeldError(
                f"ingest lock held by {owner.get('machine', '?')}/"
                f"{owner.get('user', '?')}"
            )

        # Steal exactly once. If the create still fails afterwards, a third
        # machine won the race in between — report that as normal contention
        # rather than looping, so a genuinely busy share can't spin here.
        self._unlink_quietly()
        if not self._try_create():
            owner = self._read_owner()
            raise LockHeldError(
                f"ingest lock held by {owner.get('machine', '?')}/"
                f"{owner.get('user', '?')}"
            )
        self._held = True
        return self

    def release(self) -> None:
        """Drop the lock. Safe to call when we never held it or lost it."""
        if self._held:
            self._unlink_quietly()
        self._held = False

    def heartbeat(self) -> None:
        """Refresh the timestamp so other machines don't judge us dead."""
        if not self._held:
            return
        self._write_payload()

    # --- context manager ----------------------------------------------------

    def __enter__(self) -> "IngestLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    # --- internals ----------------------------------------------------------

    def _try_create(self) -> bool:
        """Exclusive-create the lockfile. False when it already exists."""
        try:
            # "x" is the atomic test-and-set: two machines racing here, exactly
            # one gets the file and the other gets FileExistsError.
            with open(self.path, "x", encoding="utf-8") as fh:
                json.dump(self._payload(), fh)
        except FileExistsError:
            return False
        return True

    def _write_payload(self) -> None:
        # Rewritten in place, not tmp+replace: the lockfile's identity IS the
        # lock, and os.replace would briefly hand it to a racing acquirer.
        try:
            self.path.write_text(json.dumps(self._payload()), encoding="utf-8")
        except OSError:
            # A dropped share connection shouldn't kill a running ingest; the
            # next heartbeat retries, and if the share stays down the lock goes
            # stale on its own.
            pass

    def _payload(self) -> dict:
        return {
            "machine": socket.gethostname(),
            "pid": os.getpid(),
            "user": _current_user(),
            "heartbeat_at": time.time(),
        }

    def _read_owner(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Missing or half-written (SMB can expose a partial write). Either
            # way we can't name an owner, and an unreadable lock must not be
            # permanent — report no heartbeat so it reads as stale.
            return {}
        return data if isinstance(data, dict) else {}

    def _is_stale(self, owner: dict) -> bool:
        beat = owner.get("heartbeat_at")
        if not isinstance(beat, (int, float)):
            return True
        return (time.time() - beat) > self._stale_after_s

    def _unlink_quietly(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        # getuser() raises when no USERNAME/LOGNAME is set (service contexts).
        # The owner string is diagnostic only — never worth failing an ingest.
        return "unknown"
