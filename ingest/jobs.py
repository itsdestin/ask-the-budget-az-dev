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

import hashlib
import json
import os
import threading
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingest.archive import (
    ARCHIVE_DIRNAME,
    ARCHIVED_STATES,
    dir_for_state,
    unlink_with_retry,
)
from ingest.archive import sweep as _sweep
from store.config import data_dir
from users.whoami import current_user

JOBS_DIRNAME = "jobs"

# The pipeline, in order. Each stage is a resume point.
PIPELINE_STATES = ("queued", "extracting", "chunking", "embedding", "writing", "live")

# A fiscal-note refresh runs through the same queue — same lock, same backup,
# same visible progress — but it has no document to chunk or embed. It scrapes
# (extracting), then writes the directory and enqueues the new notes (writing).
# Giving it its own pipeline beats padding it with two no-op stages that would
# show a user "building the search index" while nothing is being embedded.
REFRESH_STATES = ("queued", "extracting", "writing", "live")

PIPELINES = {"document": PIPELINE_STATES, "refresh": REFRESH_STATES}

# `live` and `cancelled` are truly final -- nothing in `advance()` ever
# leaves either one. `failed` is the one exception in this set: a human can
# route it back into the pipeline (`failed` -> `queued`, the retry button)
# or forward into `cancelled` (`failed` -> `cancelled`, the Needs-attention
# panel's Dismiss button -- see the WHY comment on that branch below). Both
# of those are named exceptions carved out below the blanket check this
# constant drives; nothing else ever leaves `failed` either.
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
    # Which rung of a doc_type's ladder this upload is (e.g. "introduced" /
    # "engrossed" for budget-bill-summary). Optional with a None default:
    # thousands of job files already on disk predate this field, and
    # `from_json` must not raise reading them.
    stage: str | None = None
    # The agency an uploader DECLARED this document belongs to
    # (agency-submission only). Same optional-with-default reasoning as
    # `stage` above: job files already on disk predate this field and
    # `from_json` must not raise reading them.
    agency_canonical_id: str | None = None
    source_url: str | None = None
    # "document" (the normal ingest) or "refresh" (scrape azjlbc.gov for new
    # fiscal notes). Decides which state pipeline applies.
    kind: str = "document"
    # Which bulk run this job belongs to — one book edition, or one
    # fiscal-note session. The S17 snapshot is taken ONCE per batch instead
    # of once per document (see ingest/worker.py::_should_snapshot); a
    # snapshot zips the whole corpus, so per-document is quadratic on a
    # 7,000-document backfill.
    #
    # None means "not part of a batch" — a hand upload — and still
    # snapshots per document, which is right: that is exactly when an
    # analyst wants a restore point, and one upload is one zip.
    batch_id: str | None = None
    # Page ranges MinerU has already finished, as [[start, end], ...]. The
    # resume granularity is the range because that's one CLI invocation.
    completed_ranges: list[list[int]] = field(default_factory=list)
    # Non-fatal post-ingest validation findings (Task 14), surfaced in the UI.
    warnings: list[str] = field(default_factory=list)
    # One entry per extraction method tried, in order:
    #   {"extractor": "opendataloader", "coverage": 0.02, "chunks": 20}
    # A rung that crashed carries `error` instead of a ratio; a rung whose
    # SOURCE could not be measured carries `coverage_error` alongside a null
    # coverage, so "this document is a scan" stays distinguishable from "we
    # could not read the denominator".
    #
    # Empty on every job written before spec T5 shipped, and `from_json`
    # must keep reading those -- thousands are on the share. Empty is
    # therefore "nothing to say", never "unknown" or "not checked".
    #
    # It is also the ladder's resume marker: ingest/worker.py does not re-run
    # a rung already listed here, which is what stops a reboot during
    # embedding paying for an overnight extraction twice.
    extraction_attempts: list[dict] = field(default_factory=list)
    # True ONLY when `ingest/worker.py::run_job` decided every rung of the
    # ladder scored below `COVERAGE_FLOOR` and held the document out of
    # search -- set in exactly that one branch, never by the generic crash
    # handler (`_fail`). This is what the Needs-attention panel filters on
    # (app/routes/admin.py::get_attention), and NOT `extraction_attempts`:
    # that list is journalled after every rung including a WINNING one, so a
    # job that passed extraction and then failed at embed/write/lock also
    # carries a non-empty `extraction_attempts` -- reproduced live as a
    # 94%-coverage document appearing under "Held out of search" with a raw
    # traceback for its sentence (Plan B final review, Blocking 1). Default
    # False so every job file written before this field existed reads as
    # "not held out", which is correct -- none of them could have been,
    # since the field didn't exist yet to say so.
    held_out: bool = False
    # Which rung's output was actually written, set once in
    # `ingest/worker.py::run_job` after the ladder returns. Recorded
    # because a document whose extractor CHANGED has had its chunk_ids
    # re-minted and its text replaced, and a change that size leaving no
    # trace is how a corpus becomes unexplainable a year later (spec X7).
    # None for every job file written before this field existed, and for a
    # job that never got past extraction.
    kept_extractor: str | None = None

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
            "stage": self.stage,
        }


# --- paths ------------------------------------------------------------------


def jobs_dir() -> Path:
    path = data_dir() / JOBS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_dir() -> Path:
    """Where finished jobs live. Inside `jobs/`, so one folder holds the whole
    audit trail and a person looking for "the queue" finds both halves.

    Nested rather than a sibling because `jobs_dir().glob("*.json")` does not
    descend -- the main-folder listing is naturally unaffected by however many
    files pile up in here, with no exclusion rule to remember.
    """
    path = jobs_dir() / ARCHIVE_DIRNAME
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
    stage: str | None = None,
    agency_canonical_id: str | None = None,
    user: str | None = None,
    source_url: str | None = None,
    kind: str = "document",
    batch_id: str | None = None,
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
        # `or "unknown"`: the private resolver this replaced returned the
        # word "unknown", and job files are read in Notepad — a blank owner
        # would read as a torn file. users.whoami returns "" so the harness
        # can resolve it to the office default; the word is added here.
        user=user or current_user() or "unknown",
        created_at=now,
        updated_at=now,
        source_path=source_path,
        source_sha256=source_sha256,
        publisher=publisher,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        user_title=user_title,
        stage=stage,
        agency_canonical_id=agency_canonical_id,
        source_url=source_url,
        kind=kind,
        batch_id=batch_id,
    )


# --- persistence ------------------------------------------------------------


def save(job: JobRecord) -> Path:
    """Write the job file atomically (tmp + os.replace).

    The queue page polls this directory from other machines; without the
    rename a reader can catch a half-written file, and on a share that's not
    a rare race but a routine one.
    """
    # WHERE, per spec T13: a job in a terminal SUCCESS state belongs in
    # `jobs/done/`, everything else -- including every `failed` job, forever --
    # belongs in the main folder, so that folder IS what the queue shows.
    main = jobs_dir()
    target = dir_for_state(main, job.state)
    if target != main:
        target.mkdir(parents=True, exist_ok=True)
    path = target / f"{job.job_id}.json"
    # WHY the thread id as well as the pid: with parallel ingest several worker
    # THREADS share one process, so a pid-only temp name is the SAME path for
    # all of them. Two threads writing the same job then race — one renames
    # first and the other's os.replace fails with FileNotFoundError, failing a
    # document that was otherwise fine. Observed exactly that at 14 workers
    # (0 occurrences at 8, 1 in ~100 documents at 14). pid+tid is unique per
    # writer on every platform we run on.
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.json.tmp")
    tmp.write_text(json.dumps(job.to_json(), indent=2), encoding="utf-8")
    _replace_with_retry(tmp, path)
    # A job only ever moves ONE way -- into `done/` -- because every
    # transition into an archived state comes from the main folder and
    # nothing ever leaves `live` or `cancelled` (see `advance`). So this is
    # the only twin that can exist, and it is removed only AFTER the new copy
    # landed: a crash here costs a duplicate that `load_all` dedupes, where
    # the other order would cost the file itself.
    if target != main:
        unlink_with_retry(main / f"{job.job_id}.json")
    return path


def _replace_with_retry(tmp: Path, path: Path, *, attempts: int = 20) -> None:
    """os.replace, retried — on Windows it fails while a reader has the file.

    POSIX rename is unconditional, but Windows (and SMB) refuse to replace a
    destination another handle has open. The queue page polls every job file
    every couple of seconds from this and other machines while the worker
    writes progress several times a stage, so this collision is routine, not
    exotic. Retrying briefly is correct: the reader's handle is open for the
    microseconds of a small read.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.02)


def load_job(job_id: str) -> JobRecord | None:
    """Outstanding work first, then the archive.

    A job id arriving from an HTTP route (`/api/jobs/{id}/retry`) may name
    either -- a page open since before a job finished still holds its id.
    """
    name = f"{_validated_job_id(job_id)}.json"
    return _read(jobs_dir() / name) or _read(archive_dir() / name)


def load_active() -> list[JobRecord]:
    """Outstanding work and every failure, newest first -- what the queue shows.

    The main folder holds exactly {non-terminal} union {failed}, by
    construction (see ingest/archive.py), so this needs no state filter of its
    own and cannot drift out of step with one. That is the whole reason spec
    T13 was implemented as a location rather than as a filter.
    """
    return _sorted(_read_dir(jobs_dir()))


def load_all() -> list[JobRecord]:
    """Every job ever, newest first -- outstanding work plus the archive.

    Deliberately unchanged in MEANING. Callers that want only outstanding work
    ask for `load_active()`; this stays the honest "everything", which is what
    the audit trail and the queue's "view all" need.

    Unreadable files are skipped rather than raised: one corrupt job must
    not blank the queue page for everyone.
    """
    by_id = {j.job_id: j for j in _read_dir(jobs_dir())}
    # The archive wins a tie: a job present in both folders crashed between
    # the write and the unlink in `save`, so the archived copy is the later
    # write and the more accurate one.
    by_id.update({j.job_id: j for j in _read_dir(archive_dir())})
    return _sorted(by_id.values())


def archived_count() -> int:
    """How many jobs have finished. A directory listing -- opens no files.

    Rendering this number by reading 7,100 job files is precisely what spec
    T13 exists to stop, so it must stay a listing. `tests/test_job_archive.py`
    asserts the mechanism, not just the number.
    """
    try:
        return sum(1 for _ in archive_dir().glob("*.json"))
    except OSError:
        return 0


# How many archived files to open looking for the newest successful ingest.
# The archive's newest entry by mtime is almost always a `live` job, so the
# common case opens exactly one file; the cap is what stops a pathological
# archive (a long run of dismissed failures) turning one admin panel into a
# full scan of 7,000 files.
_NEWEST_LIVE_SCAN_CAP = 50


def newest_live_job() -> JobRecord | None:
    """The most recently finished successful ingest, wherever its file sits.

    Feeds `last_ingest_at` on the admin health panel -- "when did this corpus
    last actually grow", which is not the same question as "is anything
    running".

    The archive is searched by file MTIME rather than by `updated_at` because
    mtime comes from the directory entry, so the common case opens exactly one
    file where sorting on `updated_at` would open all 7,104. `cancelled` jobs
    are skipped: a dismissed failure is not an ingest, and reporting one as
    the last successful ingest is a quietly false reassurance on the one
    screen an admin checks to find out otherwise.

    WHY the main-folder fallback, which is not merely defensive: until
    `sweep_archive()` has run, every finished job is still in the main folder,
    and the archive is EMPTY. Without this branch the admin panel would report
    "nothing has ever been ingested" against a corpus of 7,434 documents for
    the whole window between server start and the background sweep finishing
    -- and permanently on any machine where the sweep cannot run. Caught by
    tests/test_admin_corpus_route.py::test_corpus_reports_the_queue, which
    writes a `live` job in the pre-sweep layout.

    The fallback is never more expensive than the code this replaced: it only
    runs when the archive holds no successful ingest at all, and it is the
    same single scan the old `load_all()` did unconditionally.

    Accepted edge: during a PARTIAL sweep the archive can hold an older `live`
    job while a newer unswept one is still in the main folder, so the reported
    date can lag by minutes. It self-corrects the moment the sweep completes,
    and every job finishing after this ships is written straight to the
    archive, so the window is one-time and only on upgrade.
    """
    newest = _newest_live_in(archive_dir())
    if newest is not None:
        return newest
    return _newest_live_in(jobs_dir())


def _newest_live_in(directory: Path) -> JobRecord | None:
    try:
        entries = sorted(
            directory.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for path in entries[:_NEWEST_LIVE_SCAN_CAP]:
        job = _read(path)
        if job is not None and job.state == "live":
            return job
    return None


def sweep_archive(*, limit: int | None = None) -> int:
    """Move already-finished job files into `done/`. Returns how many moved.

    Called once per process from the app's lifespan handler. The first run
    against the office share has ~7,100 files to move; afterwards the main
    folder holds only outstanding work and failures, so it is a listing of
    tens of files.
    """
    return _sweep(jobs_dir(), read=_read, limit=limit)


def _read_dir(path: Path) -> list[JobRecord]:
    try:
        return [j for j in (_read(p) for p in path.glob("*.json")) if j is not None]
    except OSError:
        return []


def _sorted(jobs) -> list[JobRecord]:
    return sorted(jobs, key=lambda j: (j.created_at, j.job_id), reverse=True)


def resumable() -> list[JobRecord]:
    """Mid-flight jobs this machine owns, oldest first — startup resume.

    `queued` is excluded on purpose: queued work belongs to the office, not
    to the PC that uploaded it, and the normal poll loop claims it. Only a
    job that was already running here has state (an extractor output dir,
    completed page ranges) that only this machine can pick back up.
    """
    me = socket.gethostname()
    # load_active(), not load_all(): every archived job is terminal, so the
    # `state not in TERMINAL_STATES` filter below already excluded all of them
    # -- the same set, without reading the 7,100-file archive at every startup.
    live = [
        j for j in load_active()
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
      * `failed` → `cancelled` (the Needs-attention panel's Dismiss button —
        see the WHY comment at that branch below)

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
        # Retry means "run the whole extraction ladder again", so the field
        # that makes a job SKIP a rung it already tried is reset along with
        # the error message.
        #
        # `extraction_attempts` is the ladder's resume marker: a retried job
        # that kept it would skip every rung it had already tried and fail
        # again instantly, having done nothing — a retry button that appears
        # not to work. `held_out` resets alongside it for the same class of
        # reason: it must not survive into a retry that goes on to fail for
        # an UNRELATED cause (an embed/write/lock crash on the next attempt)
        # — see the WHY comment on the field itself, and Blocking 1 of this
        # plan's final review, which is what a stale `True` here would have
        # reproduced.
        #
        # `completed_ranges` is DELIBERATELY **KEPT**, not cleared. It used
        # to be cleared here on the theory that carrying it into a fresh
        # ladder run would make rung 1 skip pages it had never extracted —
        # reviewed on this plan's final pass and found FALSE:
        # `_needs_extraction` checks whether THAT RUNG'S OWN output
        # directory (`_extract_dir(job, method)`) already holds every page
        # before ever trusting a range, and each rung writes to its own
        # directory, so a range recorded under one rung can never be
        # mistaken for another rung's progress — the hazard this used to
        # guard against does not exist. Because `_extract_with_mineru`
        # always extracts the WHOLE requested range in one call,
        # `completed_ranges` is only ever empty or fully covers whichever
        # rung wrote it, so the case this matters for is a document whose
        # EXTRACTION SUCCEEDED and which then failed at embed/write/lock —
        # write-phase contention on a shared drive is a documented,
        # recurring failure here. Clearing it forced a 210-page book back to
        # page 1 on retry for a failure that had nothing to do with
        # extraction; kept, Retry resumes exactly where it always did before
        # this field existed. The RESUME path (a job still mid-flight, not
        # failed) was never affected either way.
        job.extraction_attempts = []
        job.held_out = False
        job.kept_extractor = None
        return _commit(job, "queued")

    # T8's held-back documents (every extraction rung scored below the
    # coverage floor) land here in `failed`, and Plan B Task 7's "Dismiss"
    # button on the Needs-attention panel is deliberately the EXISTING
    # cancel action, not a new job state (see that panel's brief: "No new
    # job states"). Without this branch a held-back document could never be
    # dismissed — the blanket TERMINAL_STATES check just below would 409 on
    # every attempt, forever, which is exactly wrong for the one document
    # this project has actually hit where re-extraction cannot help (a
    # fiscal note where azleg.gov published a literal "THIS IS A TEST" file
    # — see docs/superpowers/investigations/2026-08-12-coverage-floor-
    # calibration.md). Scoped to `failed` only, NOT to every terminal state:
    # `live → cancelled` stays illegal, which is what the class comment
    # above is protecting — a stray cancel must never hide a document that
    # already finished successfully.
    #
    # Dismissal is ONE-WAY. Once here the job is `cancelled`, and
    # `app/routes/jobs.py::retry_job` refuses anything whose state isn't
    # `failed` (409) — there is no `cancelled` → anything edge, on purpose,
    # same as every other exit from `cancelled`. The only route back for a
    # dismissed document is re-uploading the source file as a new job.
    # Defensible behind the panel's two-click confirm, but worth naming
    # here since nothing else in the code says it.
    if job.state == "failed" and new_state == "cancelled":
        return _commit(job, "cancelled")

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

    pipeline = PIPELINES.get(job.kind, PIPELINE_STATES)
    expected = pipeline[pipeline.index(job.state) + 1]
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


