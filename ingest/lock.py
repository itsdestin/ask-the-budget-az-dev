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

# How often a held lock refreshes itself. A quarter of the stale window, so a
# holder has to miss FOUR consecutive beats before another machine writes it
# off — one slow SMB round-trip must not be enough to make a live writer look
# dead. Cheap: one small write every 30s while a document is being ingested.
DEFAULT_HEARTBEAT_EVERY_S = DEFAULT_STALE_AFTER_S / 4

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
    `acquire()` / `release()`.

    **Holding it is enough to keep it.** `acquire()` starts a daemon thread
    that refreshes the lockfile every `heartbeat_every_s` until `release()`,
    so no caller has to remember anything.

    That auto-heartbeat is not a convenience. `ingest/worker.py::_write`
    beat the lock before `write_doc` and not during it, and inside
    `write_doc` are `build_fts_index` and `optimize` — both of which grow
    with the corpus and, at 24,841 budget chunks and climbing, will pass
    the 120s stale window. When they do, another machine reads a
    two-minute-old timestamp, correctly concludes the holder is dead,
    steals the lock, and writes to a corpus that is being written. That is
    the S6 single-writer invariant failing on a live, healthy writer.

    `heartbeat()` remains public and still works — `ingest/worker.py` and
    the backfill maintainer script both call it — it is simply no longer
    load-bearing.
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        stale_after_s: int = DEFAULT_STALE_AFTER_S,
        wait_s: float = 0.0,
        heartbeat_every_s: float = DEFAULT_HEARTBEAT_EVERY_S,
    ) -> None:
        # How long `with IngestLock(...)` will wait for a busy writer. Zero
        # (the default) preserves the original fail-fast behaviour for every
        # caller that doesn't opt in.
        self._wait_s = wait_s
        self._root = Path(root) if root is not None else data_dir()
        self._stale_after_s = stale_after_s
        self._heartbeat_every_s = heartbeat_every_s
        self._held = False
        # Set only while we hold the in-process gate, so release() knows
        # whether it has anything to give back.
        self._mutex: threading.Lock | None = None
        # The auto-heartbeat thread and its stop signal. Recreated per
        # acquire: an Event stays set once set, so reusing one across
        # acquisitions would stop the second beat before it began.
        self._beat_thread: threading.Thread | None = None
        self._beat_stop: threading.Event | None = None

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
                    return self._take()

                owner = self._read_owner()
                if self._is_stale(owner):
                    # Steal exactly once per pass. If the create still fails a
                    # third machine won the race in between; fall through to
                    # the deadline check rather than spinning on a busy share.
                    self._unlink_quietly()
                    if self._try_create():
                        return self._take()

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockHeldError(self._owner_message())
                time.sleep(min(poll_s, remaining))
        except BaseException:
            self._release_mutex()
            raise

    def _take(self) -> "IngestLock":
        """The ONE place a successful acquisition is recorded. Do not inline.

        `acquire()` has two ways to win the file — the ordinary create, and
        the create that follows stealing a stale lock — and for a while only
        the ordinary one started the heartbeat. A lock taken by stealing
        therefore never refreshed itself: its `heartbeat_at` stayed frozen at
        the instant of acquisition, so after `stale_after_s` (120s) every
        OTHER machine correctly judged it dead and stole it out from under a
        writer that was still writing. Two writers on one corpus — the exact
        S6 failure the heartbeat was added to prevent, reintroduced through
        the recovery path.

        It is also self-perpetuating: once one steal happens the next holder
        also acquires by stealing, so the heartbeat never runs again for the
        life of the corpus.

        OBSERVED LIVE 2026-08-01, not theorised. A server restart during a
        book backfill left a stale lockfile; the new worker stole it and the
        lockfile's `heartbeat_at` then sat frozen for 866 seconds while the
        holder did genuine work and 147 threads queued behind it.

        Two paths each setting `_held = True` by hand is what let the
        omission happen, so both now funnel through here. Keep it that way:
        adding a third success path without a heartbeat costs one line and
        has NO symptom until a corpus is silently corrupted.
        """
        self._held = True
        # After `_held`, never before: the beat thread returns early when it
        # sees a lock that is not held.
        self._start_heartbeat()
        return self

    def release(self) -> None:
        """Drop the lock. Safe to call when we never held it or lost it.

        ORDER IS LOAD-BEARING: the heartbeat thread is stopped and JOINED
        before the lockfile is unlinked. Unlinking first leaves a window in
        which a beat already in flight writes the file back — producing an
        ownerless lockfile that blocks every other machine until it goes
        stale two minutes later, with no process to explain it.
        """
        self._stop_heartbeat()
        if self._held:
            self._unlink_quietly()
        self._held = False
        self._release_mutex()

    def heartbeat(self) -> None:
        """Refresh the timestamp so other machines don't judge us dead.

        Still public, still works, no longer load-bearing: `acquire()` now
        does this on a timer. `ingest/worker.py` and the backfill
        maintainer both call it and should keep working unchanged.
        """
        if not self._held:
            return
        self._write_payload()

    # --- auto-heartbeat -----------------------------------------------------

    def _start_heartbeat(self) -> None:
        if self._heartbeat_every_s <= 0:
            return  # opt-out, used by tests that drive the timestamp by hand
        stop = threading.Event()

        def beat() -> None:
            # `wait()` rather than `sleep()`: release() returns promptly
            # instead of blocking for up to a full interval.
            while not stop.wait(self._heartbeat_every_s):
                if not self._held:
                    return
                try:
                    self._write_payload()
                except Exception:  # noqa: BLE001
                    # `_write_payload` already swallows OSError, but a
                    # thread that died on anything else would leave a LIVE
                    # writer silently un-heartbeated — which is precisely
                    # the bug this thread exists to fix, now invisible
                    # instead of merely present. Keep beating; if the share
                    # really is gone the lock goes stale on its own.
                    pass

        thread = threading.Thread(
            target=beat,
            name=f"ingest-lock-heartbeat-{self._root.name}",
            daemon=True,  # must never hold up interpreter shutdown
        )
        self._beat_stop = stop
        self._beat_thread = thread
        thread.start()

    def _stop_heartbeat(self) -> None:
        stop, self._beat_stop = self._beat_stop, None
        thread, self._beat_thread = self._beat_thread, None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            # Bounded join: a beat is one small write, so this is
            # effectively instant — but a hung share must not wedge
            # release() forever. The thread is a daemon, so worst case it
            # is abandoned rather than leaked past process exit.
            thread.join(timeout=5.0)

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
        # A PC reading the lockfile at the instant of release used to escape
        # as PermissionError out of __exit__ -- failing a job AFTER a good
        # corpus write and leaving a frozen-heartbeat lock for 120 s.
        from store.fs import unlink_with_retry

        unlink_with_retry(self.path)


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        # getuser() raises when no USERNAME/LOGNAME is set (service contexts).
        # The owner string is diagnostic only — never worth failing an ingest.
        return "unknown"
