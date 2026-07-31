"""Background ingest worker.

One daemon thread inside the app process drives every queued document
through extract → chunk → embed → write. It runs in-process (rather than as
a separate service) because spec S1 is one bundle, one process: a second
executable is a second thing that can fail to start on a locked-down PC
with nobody to debug it.

Three properties this is built around, all consequences of the hardware:

**It takes hours.** MinerU runs 1–3 minutes per page on an i5-1245U, so a
210-page Baseline book is an overnight job. Everything is journalled so a
reboot resumes rather than restarts.

**Extraction is the only expensive stage.** Chunking and embedding are
minutes; extraction is hours. So the resume point is "did extraction
finish?" — anything after it is simply re-derived from the extractor output
on the share. That keeps the journal small and the resume logic honest.

**Exactly one writer.** The write phase takes `IngestLock`, snapshots the
corpus (S17), and only then touches LanceDB. Everything before it is
read-only against shared state, so several machines reading the corpus
during a long extraction is fine.

## Environment variables

`JLBC_INGEST_SNAPSHOT` — when to take the S17 corpus snapshot.

- unset, or `per-doc` (the DEFAULT): snapshot before every document. This is
  the office behaviour and it does not change.
- `off`: skip the per-document snapshot. **Opt-in bulk mode, for a
  supervised backfill only.** Each snapshot zips the WHOLE corpus, so the
  cost grows with the corpus while the number of snapshots grows with the
  documents — 7,000 documents is O(n²) work and terabytes of
  immediately-rotated zip. Turning this off trades the automatic restore
  point for finishing the backfill this decade; take your own archive of
  `<data_dir>/lancedb/` first.

Only the exact word `off` disables it. Any other value (including a typo
like `false`) keeps snapshots on — losing the safety net must take intent.

`JLBC_INGEST_WORKERS` — how many documents to process at once.

- unset, or `1` (the DEFAULT): today's behaviour exactly. One document at a
  time. The office install must never change unless someone deliberately
  changes it.
- `N` > 1: **opt-in parallel mode, for a supervised backfill on a machine
  with cores to spare.** N worker threads each claim their own job and run
  extraction concurrently; the write phase stays strictly serialized behind
  `IngestLock`, so the single-writer invariant is untouched.

WHY this is worth having: measured on the 2026-07-31 backfill machine, a
MinerU extraction averages ~3.2 CPU cores (peaking near 7) and ~2.1 GB RSS
(peaking near 3.0 GB) across its 2–3 processes, and it is ~90% of a
document's wall clock. One worker therefore leaves ~28 of 32 threads idle.
The write phase — the part that CANNOT overlap — is seconds per document.

The value is clamped (see `configured_worker_count`) to both a hard ceiling
and a CPU-derived one, because the same env var typed on a 4-core office PC
would otherwise make that PC unusable and swap-thrash on MinerU's RAM.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from chunking.agency_catalog import id_to_name
from chunking.builder import chunk_doc
from chunking.entity_stamper import EntityStamper
from chunking.types import Chunk, DocMeta
from ingest import dispatcher
from ingest.cache import DownloadCache
from ingest.claim import JobClaim
from ingest.jobs import (
    TERMINAL_STATES,
    JobRecord,
    advance,
    load_all,
    load_job,
    mark_stage,
    resumable,
    save,
)
from ingest.lance_writer import build_title, write_doc
from ingest.lock import IngestLock
from ingest.mineru_runner import MineruCancelled, MineruRunner
from ingest.validate import validate_doc
from store.backup import snapshot
from store.chunk_store import ChunkStore
from store.config import data_dir

# corpus name (API contract) → LanceDB table
CORPUS_TABLES = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}

# Embedding batch size. Small enough that progress moves visibly on a long
# document, large enough that per-call overhead stays negligible.
EMBED_BATCH = 64

DEFAULT_POLL_INTERVAL_S = 5.0

# Bulk-ingest mode. See the module docstring. The default lives here as a
# literal rather than as "anything that isn't off" so that reading this line
# tells you what an unset environment does.
SNAPSHOT_ENV_VAR = "JLBC_INGEST_SNAPSHOT"
SNAPSHOT_PER_DOC = "per-doc"     # default: a restore point before every write
SNAPSHOT_OFF = "off"             # opt-in bulk mode: no per-document snapshot
SNAPSHOT_SUPPRESSED_MESSAGE = (
    f"jlbc-insight: corpus snapshot suppressed by {SNAPSHOT_ENV_VAR}={SNAPSHOT_OFF} "
    "— bulk mode; ensure you have an external archive of <data_dir>/lancedb/."
)

# Parallel ingest. Same shape as the snapshot switch above: the default is a
# literal here, not "whatever the env happens to say", so reading this line
# tells you what an unset environment does.
WORKERS_ENV_VAR = "JLBC_INGEST_WORKERS"
DEFAULT_WORKERS = 1

# Hard ceiling regardless of hardware. Beyond ~16 concurrent extractions the
# LanceDB write phase and the shared embedder stop being free, and the queue
# journal — one small file per job on an SMB share, re-read by every worker
# every poll — starts costing more than it saves.
#
# Raised 8 -> 16 on 2026-07-31 against measurement, not guesswork: on a
# 32-thread box, 8 workers drew only 14.6 cores (1.8 per worker, not the 3.2
# originally assumed) and delivered 7.6x serial throughput while leaving over
# half the CPU idle. The write phase was NOT the limit at that point — an FTS
# rebuild cost 0.25s at 4.7k rows, i.e. a ~14,000 docs/hr ceiling against ~700
# actual. WATCH: that rebuild grows with table size, so on a much larger corpus
# the serialized write, not the CPU, becomes the wall.
MAX_WORKERS = 16

# Threads' worth of headroom reserved per worker. This is what stops a stray
# `JLBC_INGEST_WORKERS=16` from bricking a 4-core office PC: there it clamps to
# 2, and with the office default (unset) that machine still runs exactly one
# document at a time as it does today.
#
# Was 4, from a bench estimate of ~3.2 cores per extraction. Under real 8-way
# load the measured draw was ~1.8 cores per worker (14.6 cores across 8), so
# reserving 4 threads each left the machine less than half used. 2 reflects
# what extraction actually costs when several run at once.
THREADS_PER_WORKER = 2

# Machines this small run one document at a time no matter what the env says.
# The office PCs are 4-core; an explicit floor is safer than trusting a divisor
# to happen to land on 1, and it means the divisor above can be tuned for big
# machines without ever loosening the office guarantee.
SINGLE_WORKER_MAX_CPUS = 8

# How long a worker will wait for the corpus lock before failing its job.
# Generous because the wait is EXPECTED in parallel mode: while one worker
# writes, the others queue behind it. Still bounded, so a wedged writer on
# another machine eventually surfaces as a failed job rather than a queue
# that has silently stopped.
WRITE_LOCK_WAIT_S = 1800.0

# One embedding at a time inside this process. The ONNX embedder is a single
# shared model (loading one per worker would cost hundreds of MB each for a
# stage that is seconds long), and serializing it sidesteps every question
# about whether fastembed's session is thread-safe. At N=1 this lock is
# uncontended and costs nothing measurable, so the default path is unchanged.
_EMBED_MUTEX = threading.Lock()


class JobCancelled(RuntimeError):
    """A user cancelled this job while it was running."""


class Embedder(Protocol):
    dim: int

    def embed_batch(
        self, texts: list[str], *, input_type: str = ...
    ) -> list[list[float]]: ...


@dataclass
class WorkerContext:
    """Everything a job needs to run, injected so tests need no models.

    The store and embedder are built ONCE per worker: `LocalEmbedder` loads
    an ONNX model that costs seconds and hundreds of MB, and rebuilding it
    per document would dominate the runtime of a queue of small files.
    """

    store: ChunkStore
    embedder: Embedder
    stamper: EntityStamper
    # Overrides the registry lookup. Tests inject a fake; production leaves
    # it None so dispatcher.pick_extractor routes by (doc_type, format).
    extractor: Any | None = None
    agency_names: dict[str, str] = field(default_factory=id_to_name)
    # How long the write phase waits for the corpus lock, or None to decide
    # from `JLBC_INGEST_WORKERS`. It lives on the context rather than as a
    # parameter because `run_job()` is called directly — by tests and by the
    # resume path — and threading a plumbing argument through four call sites
    # would just be four places to forget it.
    write_lock_wait_s: float | None = None

    @classmethod
    def default(cls) -> "WorkerContext":
        from retrieval.pipeline import _get_embedder

        embedder = _get_embedder()
        # Three-way dim lockstep: the model, the store, and the table's Arrow
        # schema must agree, or the store refuses to open the table.
        return cls(
            store=ChunkStore(dim=embedder.dim),
            embedder=embedder,
            stamper=EntityStamper.from_default_paths(),
        )


# --- the pipeline -----------------------------------------------------------


def run_job(job: JobRecord, ctx: WorkerContext) -> JobRecord:
    """Drive one job to `live`, resuming from whatever stage it's in.

    Stages run in forward order regardless of the resume point: a job found
    at `embedding` still re-chunks first, because the chunks were never
    persisted and re-deriving them from the extractor output costs seconds.
    Only extraction is skipped, and only because its output IS on disk.
    """
    _check_cancelled(job)

    if job.state == "queued":
        advance(job, "extracting")
    if job.state == "extracting":
        _extract(job, ctx)
        _check_cancelled(job)
        advance(job, "chunking")

    chunks = _chunk(job, ctx)
    _check_cancelled(job)
    if job.state == "chunking":
        advance(job, "embedding")

    vectors = _embed(job, ctx, chunks)
    _check_cancelled(job)
    if job.state == "embedding":
        advance(job, "writing")

    _write(job, ctx, chunks, vectors)
    advance(job, "live")
    # Warnings share the stage_detail line rather than getting their own field:
    # the queue page has one place per job for "what should I know about this",
    # and a second channel would just be a second thing nobody reads.
    detail = f"{len(chunks)} passages indexed"
    if job.warnings:
        detail = f"{detail} — {' '.join(job.warnings)}"
    mark_stage(job, "live", pct=100, detail=detail)
    return job


def run_refresh_job(job: JobRecord, *, fetcher=None) -> JobRecord:
    """Drive a fiscal-note refresh job (spec S10).

    Runs through the same queue as documents so it's visible, serialized, and
    journalled — but its own two-stage pipeline (scrape, then write), because
    there is nothing to chunk or embed. The notes it discovers become ordinary
    document jobs that the worker picks up on a later poll.
    """
    from ingest.fiscal_notes_refresh import run_refresh

    _check_cancelled(job)
    if job.state == "queued":
        advance(job, "extracting")

    kwargs = {"fetcher": fetcher} if fetcher is not None else {}
    result = run_refresh(
        on_progress=lambda detail: _progress(job, "extracting", pct=50, detail=detail),
        **kwargs,
    )

    if job.state == "extracting":
        advance(job, "writing")
    advance(job, "live")
    mark_stage(
        job, "live", pct=100,
        detail=f"{result['queued']} new fiscal notes queued",
    )
    return job


def _extract(job: JobRecord, ctx: WorkerContext) -> None:
    """Run the extractor into `<data_dir>/extractor-output/<doc_id>/`.

    Output goes on the SHARE, not in a temp dir, so a machine that dies
    overnight doesn't cost the office the extraction — any machine can pick
    the job up and continue from the pages already done.
    """
    source = _ensure_source(job)
    out = _extract_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    source_format = source.suffix.lstrip(".").lower()

    extractor = ctx.extractor or dispatcher.pick_extractor(job.doc_type, source_format)

    if ctx.extractor is None and isinstance(extractor, dispatcher.MinerUExtractor):
        _extract_with_mineru(job, source=source, out=out)
        return

    # DOCX and OpenDataLoader run as one blocking call — both are minutes,
    # not hours, so there's nothing to stream progress against.
    _progress(job, "extracting", pct=0, detail=f"reading {source.name}")
    dispatcher.extract(
        source_path=source,
        doc_type=job.doc_type,
        source_format=source_format,
        output_dir=out,
        extractor=extractor,
    )
    _progress(job, "extracting", pct=100, detail="")


def _extract_with_mineru(job: JobRecord, *, source: Path, out: Path) -> None:
    """MinerU path: streamed progress, cancellable, resumable per page range."""
    pages = list(range(1, dispatcher._pdf_page_count(source) + 1))
    runner = MineruRunner()

    stop = threading.Event()

    def watch_for_cancel() -> None:
        # The cancel signal arrives as a state change in the job FILE (an HTTP
        # route on this or another machine wrote it), so it has to be polled.
        # Killing MinerU matters: a single page can take three minutes, and a
        # user who clicked cancel should not wait it out.
        while not stop.wait(2.0):
            current = load_job(job.job_id)
            if current is not None and current.state == "cancelled":
                runner.cancel()
                return

    watcher = threading.Thread(target=watch_for_cancel, daemon=True)
    watcher.start()
    try:
        completed = runner.run(
            pdf=source,
            out=out,
            pages=pages,
            completed_ranges=job.completed_ranges,
            on_progress=lambda done, total: _progress(
                job,
                "extracting",
                pct=int(done * 100 / total) if total else 0,
                detail=f"page {done}/{total}",
                completed_ranges=None,
            ),
        )
    except MineruCancelled as exc:
        raise JobCancelled(str(exc)) from exc
    finally:
        stop.set()

    job.completed_ranges = completed
    save(job)


def _chunk(job: JobRecord, ctx: WorkerContext) -> list[Chunk]:
    _progress(job, "chunking", pct=0, detail="building passages")
    extractor_name = (
        ctx.extractor.name
        if ctx.extractor is not None
        else dispatcher.pick_extractor(job.doc_type, _source_format(job)).name
    )
    chunks = chunk_doc(
        extractor_output_path=_extract_dir(job),
        doc_meta=DocMeta(
            doc_id=job.doc_id,
            publisher=job.publisher,
            doc_type=job.doc_type,
            fiscal_year=job.fiscal_year,
            extractor=extractor_name,
            source_format=_source_format(job),
            source_url=job.source_url,
        ),
        stamper=ctx.stamper,
    )
    _progress(job, "chunking", pct=100, detail=f"{len(chunks)} passages")
    return chunks


def _embed(
    job: JobRecord, ctx: WorkerContext, chunks: Sequence[Chunk]
) -> list[list[float]]:
    vectors: list[list[float]] = []
    total = len(chunks)
    for start in range(0, total, EMBED_BATCH):
        batch = chunks[start:start + EMBED_BATCH]
        # input_type="document" is not a formality: the model is asymmetric,
        # and embedding passages with the query instruction quietly degrades
        # every future search against this document.
        # The mutex serializes the ONE shared ONNX model across workers; see
        # _EMBED_MUTEX. Held per BATCH, not per document, so a long document
        # can't starve a short one.
        with _EMBED_MUTEX:
            vectors.extend(
                ctx.embedder.embed_batch([c.text for c in batch], input_type="document")
            )
        done = min(start + EMBED_BATCH, total)
        _progress(
            job, "embedding",
            pct=int(done * 100 / total) if total else 100,
            detail=f"passage {done}/{total}",
        )
        _check_cancelled(job)
    return vectors


def _write(
    job: JobRecord,
    ctx: WorkerContext,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
) -> None:
    """The only stage that mutates shared state. Lock → snapshot → write."""
    _progress(job, "writing", pct=0, detail="waiting for the corpus lock")
    # WHY the conditional wait: at one worker, a held lock means ANOTHER
    # MACHINE is writing, and failing fast (today's behaviour) is the honest
    # answer. In parallel mode the holder is usually a sibling thread that
    # will be done in seconds, and failing the job would turn every
    # concurrency win into a failed document.
    wait_s = ctx.write_lock_wait_s
    if wait_s is None:
        wait_s = WRITE_LOCK_WAIT_S if configured_worker_count() > 1 else 0.0
    with IngestLock(wait_s=wait_s) as lock:
        # WHY the guard: `snapshot()` zips the ENTIRE corpus, so the cost of a
        # snapshot grows with the corpus while the NUMBER of snapshots grows
        # with the documents — fine for the office's occasional uploads
        # (seconds, once in a while), quadratic for a 7,000-document supervised
        # backfill. `JLBC_INGEST_SNAPSHOT=off` is the operator saying "I have my
        # own archive, skip it". The policy lives here, in the caller, so
        # store/backup.py stays a dumb honest "make a snapshot" primitive that
        # an admin "Back up now" button can still trust.
        if _snapshot_suppressed():
            print(SNAPSHOT_SUPPRESSED_MESSAGE, file=sys.stderr, flush=True)
            _progress(job, "writing", pct=10, detail="snapshot suppressed (bulk mode)")
        else:
            _progress(job, "writing", pct=10, detail="backing up the corpus")
            snapshot()
        lock.heartbeat()

        # D2: a table names many agencies; a narrative chunk names one.
        agency_ids = {
            c.chunk_id: ctx.stamper.resolve_all(c, source_url=job.source_url)
            for c in chunks
            if c.is_table
        }
        blob_path = _copy_source_to_share(job)
        lock.heartbeat()

        _progress(job, "writing", pct=40, detail="indexing")
        write_doc(
            ctx.store,
            CORPUS_TABLES[job.corpus],
            chunks,
            vectors,
            DocMeta(
                doc_id=job.doc_id,
                publisher=job.publisher,
                doc_type=job.doc_type,
                fiscal_year=job.fiscal_year,
            ),
            title=build_title(
                publisher=job.publisher,
                doc_type=job.doc_type,
                fiscal_year=job.fiscal_year,
                user_title=job.user_title,
                agency_name=_primary_agency_name(chunks, ctx),
            ),
            source_sha256=job.source_sha256,
            source_blob_path=blob_path,
            source_url=job.source_url,
            source_format=_source_format(job),
            uploaded_by=job.user,
            agency_ids_by_chunk=agency_ids,
        )
        # Advisory, inside the lock so the scan sees exactly what we wrote.
        # Findings never fail the job — a partly-stamped document is degraded,
        # not wrong, and refusing it would leave the analyst with nothing.
        job.warnings = validate_doc(ctx.store, CORPUS_TABLES[job.corpus], job.doc_id)
        _progress(job, "writing", pct=90, detail="")


def configured_worker_count() -> int:
    """How many documents to process at once, after clamping.

    Fails SAFE in every direction: unset, empty, a typo, zero, or a negative
    number all mean 1 (today's behaviour). A number above what the hardware
    can carry is clamped down and the clamp is announced, because a silent
    clamp would have the operator believe a backfill is running 8-wide when
    it is running 2-wide, and mis-plan the night around it.
    """
    raw = os.environ.get(WORKERS_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_WORKERS
    try:
        requested = int(raw)
    except ValueError:
        return DEFAULT_WORKERS
    if requested <= 1:
        return DEFAULT_WORKERS

    cpus = os.cpu_count() or 1
    # Small machines (office PCs) never run parallel ingest, whatever is asked.
    if cpus <= SINGLE_WORKER_MAX_CPUS:
        return DEFAULT_WORKERS
    cpu_ceiling = max(1, cpus // THREADS_PER_WORKER)
    return min(requested, MAX_WORKERS, cpu_ceiling)


def _parallel_announcement(count: int) -> str:
    requested = os.environ.get(WORKERS_ENV_VAR, "").strip()
    clamped = (
        f" (clamped from {requested}; ceiling is min({MAX_WORKERS}, cpus/"
        f"{THREADS_PER_WORKER}={max(1, (os.cpu_count() or 1) // THREADS_PER_WORKER)}))"
        if requested and requested.isdigit() and int(requested) != count
        else ""
    )
    return (
        f"jlbc-insight: PARALLEL INGEST — {count} workers{clamped}, set by "
        f"{WORKERS_ENV_VAR}={requested}. Extraction runs concurrently; corpus "
        "writes stay serialized behind the single-writer lock. Expect roughly "
        f"{count} × the RAM MinerU uses (~2-3 GB per concurrent document). "
        f"Unset {WORKERS_ENV_VAR} to return to one-at-a-time ingest."
    )


def _snapshot_suppressed() -> bool:
    """True only when the operator explicitly asked for bulk mode.

    WHY the strict comparison: this switch turns off a data-loss safety net,
    so it fails SAFE. Unset, empty, `per-doc`, or a typo like `false` or `0`
    all mean "keep snapshotting". Nothing but the literal word `off` (spacing
    and capitalisation forgiven) can disable it.
    """
    return os.environ.get(SNAPSHOT_ENV_VAR, "").strip().lower() == SNAPSHOT_OFF


# --- the worker thread ------------------------------------------------------


class IngestWorker:
    """Polls the job journal and runs documents through the pipeline.

    One document at a time by default — two extractions on a 16 GB office PC
    means both crawl and the machine becomes unusable. `JLBC_INGEST_WORKERS`
    opts a big machine into N at once; see the module docstring.

    Ownership of a job is decided by `ingest.claim.JobClaim`, an atomic
    exclusive-create per job, NOT by the corpus lock. That distinction is the
    whole design: extraction (hours) needs no lock, the write phase (seconds)
    needs an exclusive one, and conflating them would make N workers exactly
    as slow as one.
    """

    def __init__(
        self,
        *,
        ctx: WorkerContext | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        workers: int | None = None,
    ) -> None:
        self._ctx = ctx
        self._ctx_lock = threading.Lock()
        self._poll_interval_s = poll_interval_s
        # None means "read the environment at start()". An explicit number
        # (tests, and any future admin toggle) wins over the env var.
        self._workers = workers
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def context(self) -> WorkerContext:
        # Built lazily: constructing it loads the embedding model, which must
        # not happen at import time or in a test that never ingests anything.
        # Under the lock because N workers start at once and would otherwise
        # each build (and then discard) their own copy of the model.
        with self._ctx_lock:
            if self._ctx is None:
                self._ctx = WorkerContext.default()
            return self._ctx

    @property
    def worker_count(self) -> int:
        return self._workers if self._workers is not None else configured_worker_count()

    def start(self) -> None:
        if any(t.is_alive() for t in self._threads):
            return
        # Announce bulk/parallel mode BEFORE the first document, not after: an
        # operator who set the variable in the wrong shell needs to find out
        # now, while the run can still be restarted cheaply.
        if _snapshot_suppressed():
            print(SNAPSHOT_SUPPRESSED_MESSAGE, file=sys.stderr, flush=True)
        count = self.worker_count
        if count > 1:
            print(_parallel_announcement(count), file=sys.stderr, flush=True)
        else:
            # A request that got clamped all the way down to one must still be
            # announced. Staying silent here would let an operator who asked for
            # 32 believe the backfill is running 32-wide when it is running
            # one-at-a-time, and mis-plan the night around a throughput that
            # never happens. Silence is reserved for an unset environment.
            requested = os.environ.get(WORKERS_ENV_VAR, "").strip()
            if requested.isdigit() and int(requested) > 1:
                print(
                    f"jlbc-insight: ingest running ONE document at a time "
                    f"(clamped from {requested}; this machine has "
                    f"{os.cpu_count()} CPUs and parallel ingest needs more "
                    f"than {SINGLE_WORKER_MAX_CPUS}). Set "
                    f"{WORKERS_ENV_VAR} on a larger machine to use it.",
                    file=sys.stderr, flush=True,
                )
        self._stop.clear()
        self._threads = [
            threading.Thread(
                target=self._loop, name=f"ingest-worker-{i}", daemon=True
            )
            for i in range(count)
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        threads, self._threads = self._threads, []
        for thread in threads:
            thread.join(timeout=timeout_s)

    def run_one(self, job: JobRecord) -> None:
        """Run one job, converting any failure into a `failed` job record.

        Failures are recorded, never raised: the queue must not stall on a
        bad document, and the user needs the reason on the queue page rather
        than in a log file they'll never open.
        """
        ctx = self.context
        # In parallel mode a busy corpus lock means a SIBLING is writing and
        # will be done in seconds — waiting is correct. At one worker it means
        # another machine is writing, and failing fast stays the honest
        # answer, so this is only ever raised, never lowered.
        if self.worker_count > 1 and ctx.write_lock_wait_s is None:
            ctx.write_lock_wait_s = WRITE_LOCK_WAIT_S
        try:
            if job.kind == "refresh":
                run_refresh_job(job)
            else:
                run_job(job, ctx)
        except JobCancelled:
            _finish_cancelled(job)
        except Exception as exc:  # noqa: BLE001 — every failure is a job failure
            traceback.print_exc()
            _fail(job, exc)

    # --- internals ----------------------------------------------------------

    def _loop(self) -> None:
        """Claim → run → release, forever. One of these per worker thread."""
        while not self._stop.is_set():
            try:
                claimed = self._claim_next()
            except Exception:  # noqa: BLE001 — a share hiccup must not end the loop
                traceback.print_exc()
                claimed = None

            if claimed is None:
                if self._stop.wait(self._poll_interval_s):
                    return
                continue

            job, claim = claimed
            try:
                self.run_one(job)
            finally:
                # Always, even on a crash inside run_one (which shouldn't
                # happen — it swallows everything — but a leaked claim parks
                # that document for the whole stale window).
                claim.release()

    def _claim_next(self) -> tuple[JobRecord, JobClaim] | None:
        """Take exclusive ownership of the next job this worker should run.

        Resumable work first, then the queue, oldest first in both. Resumable
        jobs come first because their extractor output is already on the
        share: finishing one costs minutes, while starting a fresh document
        costs an hour.

        WHY no `IngestLock` here any more: it never actually did this job.
        The write phase holds that lock for the duration of a write, so a
        lock-based claim silently STOPPED claiming whenever any machine was
        mid-write — and with several workers that would collapse the whole
        pool down to one. Worse, the old claim was a read-then-write of the
        job file, which cannot be atomic: two workers reading "queued" a
        microsecond apart both wrote "mine". `JobClaim` is an atomic
        exclusive-create, so exactly one worker can win.
        """
        for candidate in self._candidates():
            if self._stop.is_set():
                return None
            claim = JobClaim(candidate.job_id, doc_id=candidate.doc_id)
            if not claim.try_acquire():
                continue  # a sibling worker, or another machine, has it

            # Re-read under the claim. The listing that produced this
            # candidate may be seconds old: the job could have been cancelled,
            # retried, or finished by whoever held the claim before us.
            fresh = load_job(candidate.job_id)
            if fresh is None or fresh.state in TERMINAL_STATES:
                claim.release()
                continue
            if fresh.state != "queued" and fresh.machine != socket.gethostname():
                # Mid-flight on ANOTHER machine, whose extractor output we
                # can read but whose progress we shouldn't hijack.
                claim.release()
                continue

            if fresh.state == "queued":
                # Same stamp the serial worker wrote — this is what the queue
                # page shows as "who is running this".
                fresh.machine = socket.gethostname()
                save(fresh)
            return fresh, claim
        return None

    def _candidates(self) -> list[JobRecord]:
        """Jobs worth attempting, best first: our resumable work, then queued."""
        queued = [j for j in reversed(load_all()) if j.state == "queued"]
        return resumable() + queued


def ensure_started(app: Any) -> IngestWorker:
    """Attach a worker to a FastAPI app, starting it once.

    Idempotent so route modules can call it without coordinating.
    """
    worker = getattr(app.state, "ingest_worker", None)
    if worker is None:
        worker = IngestWorker()
        app.state.ingest_worker = worker
    worker.start()
    return worker


# --- helpers ----------------------------------------------------------------


def _source_path(job: JobRecord) -> Path:
    path = Path(job.source_path)
    return path if path.is_absolute() else data_dir() / path


def _ensure_source(job: JobRecord) -> Path:
    """Local file for this job, downloading it first if it's URL-only.

    "Add a JLBC book" queues ~130 jobs from a list of URLs. Downloading all
    of them at enqueue time would make the button hang for minutes and would
    fetch documents the user might cancel; each job fetches its own when its
    turn comes.
    """
    if job.source_path:
        return _source_path(job)
    if not job.source_url:
        raise RuntimeError(
            f"Job {job.job_id} has neither a stored file nor a source URL."
        )

    cache = DownloadCache(data_dir() / "pdfs")
    _progress(job, "extracting", pct=0, detail="downloading from azjlbc.gov")
    local = cache.fetch(job.source_url)
    job.source_path = local.relative_to(data_dir()).as_posix()
    job.source_sha256 = cache.sha256_of(job.source_url) or ""
    save(job)
    return local


def _source_format(job: JobRecord) -> str:
    return Path(job.source_path).suffix.lstrip(".").lower()


def _extract_dir(job: JobRecord) -> Path:
    return data_dir() / "extractor-output" / job.doc_id


def _copy_source_to_share(job: JobRecord) -> str | None:
    """Content-address the source under `<data_dir>/pdfs/` for the viewer.

    Returns the data-dir-relative path recorded in documents.json. Already
    content-addressed by sha256, so a re-ingest of the same bytes is a no-op.
    """
    source = _source_path(job)
    if not source.is_file():
        return None
    target = (
        data_dir() / "pdfs" / job.source_sha256[:2]
        / f"{job.source_sha256}{source.suffix.lower()}"
    )
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return target.relative_to(data_dir()).as_posix()


def _primary_agency_name(chunks: Sequence[Chunk], ctx: WorkerContext) -> str | None:
    """Display name of the agency this document is mostly about.

    Most-common wins rather than first-seen: a per-agency Baseline page opens
    with a statewide summary table that can name several agencies before the
    subject agency's own narrative starts.
    """
    counts: dict[str, int] = {}
    for chunk in chunks:
        if chunk.agency_canonical_id:
            counts[chunk.agency_canonical_id] = counts.get(chunk.agency_canonical_id, 0) + 1
    if not counts:
        return None
    best = max(counts, key=lambda k: (counts[k], k))
    return ctx.agency_names.get(best)


def _progress(
    job: JobRecord,
    stage: str,
    *,
    pct: int,
    detail: str,
    completed_ranges: list[list[int]] | None = None,
) -> None:
    """Journal progress, but only while the job is actually in `stage`.

    Resumed jobs re-run cheap stages (chunking, embedding) while the journal
    already says a later stage — recording those would make the queue page
    appear to run backwards.
    """
    if job.state != stage:
        return
    if completed_ranges is not None:
        job.completed_ranges = completed_ranges
    mark_stage(job, stage, pct=pct, detail=detail)


def _check_cancelled(job: JobRecord) -> None:
    """Raise if a cancel landed on this job's file since we last looked."""
    current = load_job(job.job_id)
    if current is not None and current.state == "cancelled":
        raise JobCancelled(f"job {job.job_id} was cancelled")
    if current is not None and current.state in TERMINAL_STATES:
        raise JobCancelled(f"job {job.job_id} is already {current.state}")


def _finish_cancelled(job: JobRecord) -> None:
    fresh = load_job(job.job_id)
    if fresh is not None and fresh.state not in TERMINAL_STATES:
        advance(fresh, "cancelled")


def _fail(job: JobRecord, exc: Exception) -> None:
    fresh = load_job(job.job_id) or job
    if fresh.state in TERMINAL_STATES:
        return
    advance(fresh, "failed", error=f"{type(exc).__name__}: {exc}")
