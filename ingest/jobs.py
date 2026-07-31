"""Persistent ingest-queue journal.

One JSON file per job under `<data_dir>/jobs/`. Not a LanceDB table and not
a SQLite file, for three reasons that all come back to the share: a
directory of small files is the only thing SMB handles well under concurrent
readers; a partially-written job costs one job rather than the whole queue;
and a colleague (or a future maintainer with no code access) can read the
queue in Notepad when something goes wrong.

Job records outlive the process on purpose. MinerU takes 1–3 minutes per
page on an office i5, so a 210-page Baseline book runs overnight and WILL be
interrupted by a reboot, a sleep, or a closed lid. Every stage transition
and every progress tick is persisted, so a restart resumes at the last
completed stage (and, inside extraction, the last completed page range)
instead of starting the night over.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from store.config import data_dir

JOBS_DIRNAME = "jobs"

# The pipeline, in order. Each stage is a resume point.
PIPELINE_STATES = ("queued", "extracting", "chunking", "embedding", "writing", "live")

# Nothing leaves these. `live` is success; `failed` and `cancelled` are ends a
# human has to act on (retry re-queues; cancel is final).
TERMINAL_STATES = frozenset({"live", "failed", "cancelled"})

STATES = frozenset(PIPELINE_STATES) | {"failed", "cancelled"}


class IllegalTransition(RuntimeError):
    """A state change the queue's state machine does not allow."""


@dataclass
class JobRecord:
    """One document's trip through the ingest pipeline.

    The first block of fields is the `JobView` API contract the webapp
    renders. The second is what the worker needs to actually do the work and
    to resume it — deliberately in the same record, because a job that can't
    be resumed from its own file isn't crash-safe.
    """

    # --- JobView (frozen API contract) ---
    job_id: str
    doc_id: str
    title: str
    corpus: str
    state: str
    pct: int
    stage_detail: str
    error: str | None
    machine: str
    user: str
    created_at: str
    updated_at: str

    # --- worker state ---
    source_path: str
    source_sha256: str
    publisher: str
    doc_type: str
    fiscal_year: int
    user_title: str
    source_url: str | None = None
    # Page ranges MinerU has already finished, as [[start, end], ...]. The
    # resume granularity is the range because that's one CLI invocation.
    completed_ranges: list[list[int]] = field(default_factory=list)
    # Non-fatal post-ingest validation findings (Task 14), surfaced in the UI.
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "JobRecord":
        # Unknown keys are dropped rather than raising: a job file written by
        # a newer version must not brick an older one mid-upgrade.
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})

    def view(self) -> dict[str, Any]:
        """The `JobView` half — what GET /api/jobs returns."""
        return {
            "job_id": self.job_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "corpus": self.corpus,
            "state": self.state,
            "pct": self.pct,
            "stage_detail": self.stage_detail,
            "error": self.error,
            "machine": self.machine,
            "user": self.user,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --- paths ------------------------------------------------------------------


def jobs_dir() -> Path:
    path = data_dir() / JOBS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- creation ---------------------------------------------------------------


def new_job(
    *,
    doc_id: str,
    title: str,
    corpus: str,
    source_path: str,
    source_sha256: str,
    publisher: str,
    doc_type: str,
    fiscal_year: int,
    user_title: str = "",
    user: str | None = None,
    source_url: str | None = None,
) -> JobRecord:
    """Build a queued job. Does not persist — call `save()`."""
    now = _now()
    return JobRecord(
        job_id=_new_job_id(f"{doc_id}|{source_sha256}|{now}"),
        doc_id=doc_id,
        title=title,
        corpus=corpus,
        state="queued",
        pct=0,
        stage_detail="",
        error=None,
        machine=socket.gethostname(),
        user=user or _current_user(),
        created_at=now,
        updated_at=now,
        source_path=source_path,
        source_sha256=source_sha256,
        publisher=publisher,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        user_title=user_title,
        source_url=source_url,
    )


# --- persistence ------------------------------------------------------------


def save(job: JobRecord) -> Path:
    """Write the job file atomically (tmp + os.replace).

    The queue page polls this directory from other machines; without the
    rename a reader can catch a half-written file, and on a share that's not
    a rare race but a routine one.
    """
    path = jobs_dir() / f"{job.job_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_job(job_id: str) -> JobRecord | None:
    path = jobs_dir() / f"{_validated_job_id(job_id)}.json"
    return _read(path)


def load_all() -> list[JobRecord]:
    """Every machine's jobs, newest first.

    Unreadable files are skipped rather than raised: one corrupt job must
    not blank the queue page for everyone.
    """
    jobs = [j for j in (_read(p) for p in jobs_dir().glob("*.json")) if j is not None]
    return sorted(jobs, key=lambda j: (j.created_at, j.job_id), reverse=True)


def resumable() -> list[JobRecord]:
    """Mid-flight jobs this machine owns, oldest first — startup resume.

    `queued` is excluded on purpose: queued work belongs to the office, not
    to the PC that uploaded it, and the normal poll loop claims it. Only a
    job that was already running here has state (an extractor output dir,
    completed page ranges) that only this machine can pick back up.
    """
    me = socket.gethostname()
    live = [
        j for j in load_all()
        if j.machine == me and j.state not in TERMINAL_STATES and j.state != "queued"
    ]
    return list(reversed(live))


# --- state machine ----------------------------------------------------------


def advance(job: JobRecord, new_state: str, *, error: str | None = None) -> JobRecord:
    """Move a job to `new_state`, persist, and return it.

    Allowed moves:
      * one step forward along PIPELINE_STATES
      * anything non-terminal → `failed` (an error message is required) or
        `cancelled`
      * `failed` → `queued` (the retry button)

    Everything else raises. The guard matters because two writers can reach
    the same job — the worker and an HTTP cancel — and a "cancel" that landed
    on an already-`live` job would otherwise hide a finished document.
    """
    if new_state not in STATES:
        raise IllegalTransition(f"Unknown job state {new_state!r}")

    if job.state == "failed" and new_state == "queued":
        job.error = None
        job.pct = 0
        job.stage_detail = ""
        return _commit(job, "queued")

    if job.state in TERMINAL_STATES:
        raise IllegalTransition(
            f"Job {job.job_id} is already {job.state}; it cannot become {new_state}."
        )

    if new_state == "failed":
        if not error:
            raise ValueError(
                "Failing a job requires an error message — a failed upload with "
                "no reason gives the user nothing to act on."
            )
        job.error = error
        return _commit(job, "failed")

    if new_state == "cancelled":
        return _commit(job, "cancelled")

    expected = PIPELINE_STATES[PIPELINE_STATES.index(job.state) + 1]
    if new_state != expected:
        raise IllegalTransition(
            f"Job {job.job_id} is {job.state}; the next stage is {expected!r}, "
            f"not {new_state!r}."
        )
    job.pct = 0
    job.stage_detail = ""
    return _commit(job, new_state)


def mark_stage(job: JobRecord, stage: str, *, pct: int, detail: str) -> JobRecord:
    """Record progress within the stage the job is currently in.

    `stage` is checked against the job's state so a late callback from a
    stage that already ended (a cancelled MinerU run flushing one last
    progress line) can't overwrite the newer stage's progress.
    """
    if job.state != stage:
        raise IllegalTransition(
            f"Job {job.job_id} is {job.state}, not {stage!r} — refusing a stale "
            "progress update."
        )
    job.pct = max(0, min(100, int(pct)))
    job.stage_detail = detail
    job.updated_at = _now()
    save(job)
    return job


# --- internals --------------------------------------------------------------


def _commit(job: JobRecord, state: str) -> JobRecord:
    job.state = state
    job.updated_at = _now()
    save(job)
    return job


def _read(path: Path) -> JobRecord | None:
    try:
        return JobRecord.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job_id(seed: str) -> str:
    """`<UTC compact>-<sha8>`: sorts chronologically, collides never.

    The timestamp does the ordering (so a directory listing is already the
    queue order); the hash disambiguates jobs inside the same second. The
    random component is load-bearing — seeding purely on the document would
    give two re-uploads of the same file in one second the same id, and the
    second would silently overwrite the first's journal file.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        f"{seed}|{uuid.uuid4().hex}".encode("utf-8")
    ).hexdigest()[:8]
    return f"{stamp}-{digest}"


def _validated_job_id(job_id: str) -> str:
    """job_ids arrive from HTTP routes (`/api/jobs/{id}/retry`)."""
    if job_id != Path(job_id).name or not job_id or job_id.startswith("."):
        raise ValueError(f"Not a job id: {job_id!r}")
    return job_id


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"
