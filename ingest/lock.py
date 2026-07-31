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

## Two gates, not one (added for parallel ingest)

The stale-steal above is safe between MACHINES and unsafe between THREADS of
one process. `JLBC_INGEST_WORKERS>1` runs several ingest threads in the app
process, and a write phase that takes longer than `stale_after_s` without a
heartbeat would let thread B declare thread A dead and start writing on top
of it — the exact corpus corruption the lock exists to prevent, produced by
the recovery mechanism.

So every acquisition passes through an in-process mutex FIRST, and only the
winner races for the file. Inside one process the mutex is authoritative and
cannot be stolen at any timeout; across machines the file lock behaves
exactly as it always has.
"""
from __future__ import annotations

import getpass
import json
import os
import socket
import threading
import time
from pathlib import Path
from types import TracebackType

from store.config import data_dir

LOCK_FILENAME = "ingest.lock"

# Two minutes of silence means the holder is gone. Long enough that a slow SMB
# round-trip or a paused VM won't trip it; short enough that a colleague who
# reboots mid-upload isn't blocked for the rest of the afternoon.
DEFAULT_STALE_AFTER_S = 120

# How long an unreadable lockfile gets to become readable before it is judged
# corrupt (and therefore stealable). See `_read_owner`.
_SETTLE_PATIENCE_S = 1.0
_SETTLE_POLL_S = 0.02

# One mutex per data root. Keyed by root rather than global because tests (and
# a future multi-corpus install) open locks on several roots in one process,
# and a single global would serialize unrelated corpora.
_PROCESS_MUTEXES: dict[Path, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()


def _process_mutex(root: Path) -> threading.Lock:
    try:
        key = root.resolve()
    except OSError:
        key = root
    with _REGISTRY_LOCK:
        mutex = _PROCESS_MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _PROCESS_MUTEXES[key] = mutex
        return mutex


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
        wait_s: float = 0.0,
    ) -> None:
        # How long `with IngestLock(...)` will wait for a busy writer. Zero
        # (the default) preserves the original fail-fast behaviour for every
        # caller that doesn't opt in.
        self._wait_s = wait_s
        self._root = Path(root) if root is not None else data_dir()
        self._stale_after_s = stale_after_s
        self._held = False
        # Set only while we hold the in-process gate, so release() knows
        # whether it has anything to give back.
        self._mutex: threading.Lock | None = None

    @property
    def held(self) -> bool:
        return self._held

    @property
    def path(self) -> Path:
        return self._root / LOCK_FILENAME

    # --- acquire / release --------------------------------------------------

    def acquire(self, *, wait_s: float = 0.0, poll_s: float = 0.5) -> "IngestLock":
        """Take the lock, or raise LockHeldError naming the current holder.

        `wait_s=0` (the DEFAULT, and what every pre-parallel caller gets) is
        the original behaviour byte for byte: one create attempt, one
        stale-steal attempt, then raise. Parallel ingest passes a real budget
        because with several workers in one process contention on the write
        phase is the normal case, not an error — a worker that failed its
        document because a sibling was mid-write would turn concurrency into
        a failure generator.

        NOT reentrant: a thread that already holds this lock must not acquire
        it again. Nothing in the ingest path does, and making it reentrant
        would hide exactly the nesting bug worth failing on.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, wait_s)

        mutex = _process_mutex(self._root)
        if wait_s > 0:
            got = mutex.acquire(timeout=wait_s)
        else:
            got = mutex.acquire(blocking=False)
        if not got:
            # Another THREAD here holds it. Name the file's owner anyway —
            # from the caller's point of view the answer is the same shape.
            raise LockHeldError(self._owner_message())
        self._mutex = mutex

        try:
            while True:
                if self._try_create():
                    self._held = True
                    return self

                owner = self._read_owner()
                if self._is_stale(owner):
                    # Steal exactly once per pass. If the create still fails a
                    # third machine won the race in between; fall through to
                    # the deadline check rather than spinning on a busy share.
                    self._unlink_quietly()
                    if self._try_create():
                        self._held = True
                        return self

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockHeldError(self._owner_message())
                time.sleep(min(poll_s, remaining))
        except BaseException:
            self._release_mutex()
            raise

    def release(self) -> None:
        """Drop the lock. Safe to call when we never held it or lost it."""
        if self._held:
            self._unlink_quietly()
        self._held = False
        self._release_mutex()

    def heartbeat(self) -> None:
        """Refresh the timestamp so other machines don't judge us dead."""
        if not self._held:
            return
        self._write_payload()

    # --- context manager ----------------------------------------------------

    def __enter__(self) -> "IngestLock":
        return self.acquire(wait_s=self._wait_s)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    # --- internals ----------------------------------------------------------

    def _release_mutex(self) -> None:
        mutex, self._mutex = self._mutex, None
        if mutex is not None:
            mutex.release()

    def _owner_message(self) -> str:
        owner = self._read_owner()
        return (
            f"ingest lock held by {owner.get('machine', '?')}/"
            f"{owner.get('user', '?')}"
        )

    def _try_create(self) -> bool:
        """Exclusive-create the lockfile. False when it already exists.

        WHY the raw fd and the single `os.write`: creating the file and
        filling it are two steps, and the machine that loses the race reads it
        in between. An empty read looks corrupt, corrupt is treated as stale,
        and stale means "steal" — so a buffered write leaves a window in which
        both machines believe they hold the single-writer lock. One syscall
        shrinks that window to nothing observable; `_read_owner`'s patience
        (below) covers the rest.
        """
        try:
            # O_EXCL is the atomic test-and-set: two machines racing here,
            # exactly one gets the file and the other gets FileExistsError.
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(fd, json.dumps(self._payload()).encode("utf-8"))
        finally:
            os.close(fd)
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
        """Who holds the lock — waiting briefly for a mid-create write to land.

        Missing or half-written (SMB can expose a partial write) means we
        can't name an owner, and an unreadable lock must not be permanent, so
        `{}` reads as stale. But "unreadable" must mean genuinely damaged, not
        "written a millisecond ago by the machine that just beat us" — that
        misreading is how two writers both conclude the lock is abandoned.
        """
        deadline = time.monotonic() + _SETTLE_PATIENCE_S
        while True:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict) and data:
                return data
            if not self.path.exists() or time.monotonic() >= deadline:
                return {}
            time.sleep(_SETTLE_POLL_S)

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
