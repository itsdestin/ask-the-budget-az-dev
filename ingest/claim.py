"""Atomic per-job claiming — the thing that makes parallel ingest safe.

`ingest/lock.py` serializes WRITERS: one machine at a time may mutate the
corpus. That is the wrong tool for deciding who runs which job, because the
expensive stage (MinerU extraction, ~40 s to many minutes per document)
needs no lock at all. Holding the corpus lock through extraction would make
`JLBC_INGEST_WORKERS=8` exactly as slow as one worker.

So ownership of a JOB gets its own primitive: one small file per claim,
created with `open(path, "x")`. That is the same exclusive-create
test-and-set `lock.py` relies on, for the same reason — it is the one
atomicity guarantee Windows SMB honours reliably across machines — but at
per-job granularity, so eight workers can each hold a different document
while nobody holds the corpus.

WHY not just stamp the job's JSON file: writing a field into a file is a
read-then-write, and two workers that read "queued" a microsecond apart both
write "mine" and both start the same document. Only an atomic create can say
"exactly one of you".

Two keys are taken per claim, all-or-nothing:

  * the **job id** — nobody else runs this job record; and
  * the **doc id** — nobody else runs any OTHER job record for the same
    document. Two jobs sharing a doc_id extract into the same
    `extractor-output/<doc_id>/<method>/` directory (rung-scoped since the
    extraction ladder shipped — see `ingest/worker.py::_extract_dir` — but
    still one shared `<doc_id>` tree, so two jobs for the same document
    still collide rung-for-rung) and then write the same LanceDB rows.
    Serial ingest made that safe by accident. It is not hypothetical:
    `make_doc_id()` is known to collide across report families (STATUS.md,
    2026-07-31), so a bulk backfill really does queue two jobs for one id.

Crashes are the normal failure, not the exotic one — the machine reboots
overnight mid-book. So a claim heartbeats itself from a background thread,
and any claim whose heartbeat has gone quiet is stolen by the next worker.
A same-machine claim whose PID is gone is reclaimed immediately, without
waiting out the timeout, because after a restart the app can prove that
holder is dead.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from types import TracebackType

from store.config import data_dir

# Sibling of `jobs/`, not inside it. The jobs directory is meant to be
# readable in Notepad by whoever inherits this system; machine bookkeeping
# does not belong in it, and a swept-clean claims directory is a one-command
# recovery if this ever goes wrong.
CLAIMS_DIRNAME = "job-claims"

CLAIM_SUFFIX = ".claim"

# Ninety seconds of silence means the holder is gone. Shorter than the corpus
# lock's 120 s because losing a claim costs one document's re-extraction,
# while losing the corpus lock costs corpus integrity — the asymmetry should
# be reflected in how eagerly each is stolen.
DEFAULT_CLAIM_STALE_AFTER_S = 90

# Beat well inside the stale window so an SMB round-trip that takes a few
# seconds, or a machine that pauses briefly, never looks dead.
DEFAULT_HEARTBEAT_INTERVAL_S = 15.0


def claims_dir() -> Path:
    path = data_dir() / CLAIMS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


class JobClaim:
    """Exclusive ownership of one job (and of its document) across machines.

    Use `try_acquire()` — it returns False rather than raising, because
    losing a race is the ordinary case in a poll loop, not an error. Always
    `release()` in a `finally`; a leaked claim is only recovered after the
    stale timeout, which parks that document for 90 seconds.
    """

    def __init__(
        self,
        job_id: str,
        *,
        doc_id: str | None = None,
        root: Path | str | None = None,
        stale_after_s: int = DEFAULT_CLAIM_STALE_AFTER_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._job_id = job_id
        self._doc_id = doc_id
        self._root = Path(root) if root is not None else None
        self._stale_after_s = stale_after_s
        self._heartbeat_interval_s = heartbeat_interval_s
        # A per-claim random token. Ownership is checked against it before
        # deleting a file, so a worker whose claim was stolen (because it
        # froze past the timeout) cannot delete the new owner's file and hand
        # the same job to a third worker.
        self._token = uuid.uuid4().hex
        self._held: list[Path] = []
        self._stop = threading.Event()
        self._beat: threading.Thread | None = None

    # --- introspection ------------------------------------------------------

    @property
    def held(self) -> bool:
        return bool(self._held)

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def paths(self) -> list[Path]:
        base = self._root if self._root is not None else claims_dir()
        keys = [f"job-{_safe_key(self._job_id)}"]
        if self._doc_id:
            keys.append(f"doc-{_safe_key(self._doc_id)}")
        return [base / f"{k}{CLAIM_SUFFIX}" for k in keys]

    # --- acquire / release --------------------------------------------------

    def try_acquire(self) -> bool:
        """Take every key, or none of them. False means someone else has it."""
        base = self._root if self._root is not None else claims_dir()
        base.mkdir(parents=True, exist_ok=True)

        for path in self.paths:
            if not self._take(path):
                # All-or-nothing. A claim that kept the job key after losing
                # the doc key would make that job permanently unclaimable —
                # the file would sit there with a live heartbeat and no owner.
                self.release()
                return False
            self._held.append(path)

        self._start_heartbeat()
        return True

    def release(self) -> None:
        """Drop every key we still own. Safe to call twice, or after a steal."""
        self._stop.set()
        beat, self._beat = self._beat, None
        if beat is not None and beat is not threading.current_thread():
            beat.join(timeout=2.0)
        held, self._held = self._held, []
        for path in held:
            self._unlink_if_ours(path)

    def heartbeat(self) -> None:
        """Refresh every held key so other workers don't judge us dead."""
        for path in list(self._held):
            try:
                path.write_text(json.dumps(self._payload()), encoding="utf-8")
            except OSError:
                # A dropped share connection must not kill a running ingest.
                # The next beat retries; if the share stays down the claim
                # goes stale on its own, which is the correct outcome.
                pass

    # --- context manager ----------------------------------------------------

    def __enter__(self) -> "JobClaim":
        if not self.try_acquire():
            raise ClaimHeldError(f"job {self._job_id} is claimed by another worker")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    # --- internals ----------------------------------------------------------

    def _take(self, path: Path) -> bool:
        if self._create(path):
            return True

        owner = _read_settled(path)
        if not self._is_stale(owner):
            return False

        # Steal exactly once. If the create still fails afterwards a third
        # worker won the race in between; report that as ordinary contention
        # rather than looping, so a busy share can never spin here.
        _unlink_quietly(path)
        return self._create(path)

    def _create(self, path: Path) -> bool:
        """Exclusive-create the key file and fill it in one write.

        WHY one `os.write` rather than a buffered `json.dump`: the create and
        the payload are two separate steps, and a worker that loses the race
        reads the file in between. A partially-visible file reads as corrupt,
        corrupt reads as stale, and stale means "steal it" — which is exactly
        how 24 racing threads all ended up believing they had won. Keeping
        the gap to a single syscall shrinks the window; `_read_settled` below
        closes it.
        """
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(fd, json.dumps(self._payload()).encode("utf-8"))
        finally:
            os.close(fd)
        return True

    def _payload(self) -> dict:
        return {
            "machine": socket.gethostname(),
            "pid": os.getpid(),
            "user": _current_user(),
            "token": self._token,
            "job_id": self._job_id,
            "doc_id": self._doc_id,
            "heartbeat_at": time.time(),
        }

    def _is_stale(self, owner: dict) -> bool:
        if not owner:
            # Missing or half-written (SMB can expose a partial write). An
            # unreadable claim must not be permanent.
            return True
        if owner.get("token") == self._token:
            # Our own file from a previous partial acquire. Reclaiming it is
            # correct and avoids deadlocking against ourselves.
            return True
        # A holder on THIS machine whose process is gone is provably dead —
        # no reason to make the queue wait out the timeout after a restart.
        if owner.get("machine") == socket.gethostname():
            pid = owner.get("pid")
            if isinstance(pid, int) and not _pid_alive(pid):
                return True
        beat = owner.get("heartbeat_at")
        if not isinstance(beat, (int, float)):
            return True
        # `>=` rather than `>`: a stale_after_s of 0 means "steal it", which is
        # what the tests (and a future "force reclaim" button) want to express.
        return (time.time() - beat) >= self._stale_after_s

    def _unlink_if_ours(self, path: Path) -> None:
        owner = _read(path)
        if owner and owner.get("token") not in (None, self._token):
            return  # stolen from us — leave the new owner's file alone
        _unlink_quietly(path)

    def _start_heartbeat(self) -> None:
        self._stop.clear()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"claim-heartbeat-{self._job_id}",
            daemon=True,
        )
        self._beat = thread
        thread.start()

    def _heartbeat_loop(self) -> None:
        # WHY a thread rather than beating from the progress callbacks: MinerU
        # can spend three minutes on a single page and emits no callback in
        # between, so a progress-driven heartbeat would let a perfectly
        # healthy extraction be declared dead and started again elsewhere.
        while not self._stop.wait(self._heartbeat_interval_s):
            self.heartbeat()


class ClaimHeldError(RuntimeError):
    """Another worker holds this job's claim."""


def _safe_key(raw: str) -> str:
    """A filename-safe key that never merges two distinct ids.

    doc_ids are derived from filenames and URLs, so they can carry slashes,
    colons and dots. Sanitising alone would map `doc/one` and `doc:one` onto
    one file and silently serialize two unrelated documents (or worse, let a
    `../` escape the claims directory), so the readable part is truncated for
    human eyes and a hash of the ORIGINAL string carries the identity.
    """
    readable = "".join(c if (c.isalnum() or c in "-_") else "_" for c in raw)[:48]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


# How long an unreadable claim file gets to become readable before we call it
# corrupt. A local write lands in microseconds and an SMB one in milliseconds,
# so a second of patience is generous; a file that is still unparseable after
# it is genuinely damaged and must not wedge the queue forever.
_SETTLE_PATIENCE_S = 1.0
_SETTLE_POLL_S = 0.02


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_settled(path: Path) -> dict:
    """Read a claim file, giving a concurrent creator time to finish writing.

    Only reached when we LOST the exclusive-create, i.e. someone else is
    mid-claim right now. Returning `{}` here means "stale, steal it", so an
    impatient read is not a slow path — it is a double-claim.
    """
    deadline = time.monotonic() + _SETTLE_PATIENCE_S
    while True:
        owner = _read(path)
        if owner:
            return owner
        if not path.exists():
            # Released or stolen while we looked. Empty is the right answer:
            # the caller's next create attempt will simply succeed.
            return {}
        if time.monotonic() >= deadline:
            return {}
        time.sleep(_SETTLE_POLL_S)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """Is a process with this id running on THIS machine?

    Only consulted when the claim says it was made here. PID reuse can make a
    dead holder look alive, which merely falls back to the heartbeat timeout —
    the conservative direction.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Someone else's process, but it exists.
        return True
    except OSError:
        return True
    return True


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"
