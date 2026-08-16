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

**Snapshots are per BATCH, not per document** (see `_should_snapshot`). A
snapshot zips the WHOLE corpus, so one per document costs O(corpus) each
while the count grows with the documents — quadratic. A book edition
(~130 documents) or a fiscal-note session now takes ONE restore point,
which is both the unit somebody would actually roll back to and the unit
that fails as a unit. A hand upload has no batch and still snapshots per
document: that is exactly when an analyst wants a restore point, and one
upload is one zip.

`JLBC_INGEST_SNAPSHOT` — the escape hatch, unchanged.

- unset, or `per-doc` (the DEFAULT): snapshot per batch as above.
- `off`: no automatic snapshot at all. **Opt-in bulk mode, for a
  supervised backfill only.** This predates per-batch snapshots and was
  the only way to escape the quadratic cost; with per-batch it should
  rarely be needed. Turning it off trades the automatic restore point for
  speed; take your own archive of `<data_dir>/lancedb/` first.

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

`JLBC_INGEST_BATCH` — how many documents to hand to ONE MinerU run.

- unset, or `1` (the DEFAULT): today's behaviour exactly. One MinerU
  invocation per document. The office install must never change unless
  someone deliberately changes it.
- `N` > 1: **opt-in batch mode, for a supervised backfill.** A worker claims
  up to N eligible documents, stages them into one directory, and extracts
  them in a single `mineru -p <dir>` run.

WHY: a MinerU invocation was measured at ~38 s for a 2-page document, of
which ~33 s is LOADING MODELS. Paid per document across a ~3,500-document
backfill that is roughly 32 core-hours of pure loading. Batch mode pays it
once per batch instead.

This composes with `JLBC_INGEST_WORKERS` — each worker claims and runs its
own batch — and changes NOTHING about the write phase, which stays
serialized behind `IngestLock` one document at a time.

Only whole, small documents are batched (see `BATCH_MAX_PAGES` and
`batch_eligible`). A long book keeps the per-document path because its
resume granularity is the page RANGE, and that is what makes an overnight
extraction survivable.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import sys
import threading
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

from chunking.agency_catalog import id_to_name
from chunking.builder import chunk_doc
from chunking.entity_stamper import EntityStamper
from chunking.types import Chunk, DocMeta
from ingest import dispatcher
from ingest.cache import DownloadCache
from ingest.claim import JobClaim
from ingest.coverage import COVERAGE_FLOOR, coverage_ratio
from ingest.inspection import inspect_source
from ingest.ladder import ladder_for
from ingest.jobs import (
    TERMINAL_STATES,
    JobRecord,
    advance,
    load_active,
    load_job,
    mark_stage,
    resumable,
    save,
)
from ingest.lance_writer import build_title, write_doc
from store.office_agencies import agency_name
from ingest.lock import IngestLock
from ingest.mineru_runner import MineruCancelled, MineruRunner, batch_timeout_s
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

# Batch extraction. Same shape as the two switches above: the default is a
# literal here, not "whatever the env happens to say".
BATCH_ENV_VAR = "JLBC_INGEST_BATCH"
DEFAULT_BATCH = 1

# Hard ceiling on documents per MinerU run. Unlike JLBC_INGEST_WORKERS this
# gets NO cpu-derived clamp, because batch size does not multiply concurrent
# processes — a batch of 40 is still one `mineru` invocation, so it costs one
# machine's worth of RAM and cores whatever N is.
#
# What batch size DOES multiply is the blast radius. MinerU's output is
# demuxed after the run, so a machine that dies mid-batch loses every
# document in it and re-extracts them all next time. 40 small documents is
# roughly one book edition's worth of re-work — bad but bounded — and past
# that a single interruption starts costing more than the model loads saved.
MAX_BATCH = 40

# The page ceiling for a batched document, in pages of the source PDF.
#
# WHY there is a ceiling at all (Plan 7 ground truth 3): extraction resume
# granularity today is the page RANGE inside a document, which exists because
# a 210-page Baseline book runs overnight on an office i5 and WILL be
# interrupted. Batch mode extracts whole documents, so putting a book in a
# batch would trade that resume point away for a model load it barely
# amortizes anyway.
#
# WHY 12: the corpus median is 2 pages and the volume is all per-agency book
# pages (2-6) and fiscal notes (~2) — everything batch mode exists for sits
# far below this. 12 pages is still under an hour of extraction on the
# slowest machine we run on, so losing one to an interrupted batch is an
# annoyance; a book is a night's work, which is not.
BATCH_MAX_PAGES = 12

# The one extractor that has a batch mode. Named rather than compared against
# the class so `batch_eligible` reads as the routing question it is.
MINERU_EXTRACTOR_NAME = "mineru"

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
    # The batch-extraction counterpart of `extractor`: something exposing
    # `run_batch(items, *, timeout_s, on_document)`. Tests inject a fake;
    # production leaves it None so a real `MineruRunner` is built per batch,
    # the same way the per-document path builds one per job.
    batch_runner: Any | None = None
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

    outcome = _extract_and_chunk(job, ctx)
    _check_cancelled(job)

    if not outcome.passed:
        # Spec T8: held out of search, NOT marked live. Nothing is written,
        # so the document simply is not in the corpus — "held out" needs no
        # separate mechanism, only the discipline of not writing it.
        #
        # A REPROCESS of an already-live document that fails every rung
        # leaves the existing chunks in place, still searchable. That is
        # deliberate: destroying a working document because a re-extraction
        # went badly would turn an attempted improvement into data loss. The
        # queue page says the re-processing failed; the old copy stands.
        #
        # The message goes through `error=`, which `advance` REQUIRES for
        # this transition (jobs.py) — passing it via mark_stage's `detail`
        # alone both raises here and leaves `job.error` empty on the one
        # screen that exists to explain a failure.
        #
        # `held_out = True` is set HERE and ONLY here (never by the generic
        # crash handler `_fail`) — it is what tells the Needs-attention
        # panel "the ladder LOST" apart from "the ladder ran and something
        # else crashed afterward". `extraction_attempts` alone cannot make
        # that distinction: it is journalled after every rung, including a
        # WINNING one, so a job that passed extraction and then failed at
        # embed/write/lock also carries a non-empty `extraction_attempts`.
        # See the field's own WHY comment in ingest/jobs.py and Blocking 1
        # of this plan's final review, which reproduced exactly that
        # mislabel through the real admin route.
        job.held_out = True
        advance(job, "failed", error=_held_out_message(outcome))
        return job

    chunks = outcome.chunks
    if job.state == "extracting":
        advance(job, "chunking")
    if job.state == "chunking":
        advance(job, "embedding")

    vectors = _embed(job, ctx, chunks)
    _check_cancelled(job)
    if job.state == "embedding":
        advance(job, "writing")

    _write(job, ctx, chunks, vectors, outcome)
    advance(job, "live")
    # Warnings share the stage_detail line rather than getting their own field:
    # the queue page has one place per job for "what should I know about this",
    # and a second channel would just be a second thing nobody reads.
    detail = f"{len(chunks)} passages indexed"
    if job.warnings:
        detail = f"{detail} — {' '.join(job.warnings)}"
    mark_stage(job, "live", pct=100, detail=detail)
    return job


@dataclass(frozen=True)
class ExtractionOutcome:
    """What the ladder produced, and what it cost to get there."""

    chunks: list[Chunk]
    attempts: list[dict]
    coverage: float | None
    extractor: str
    fell_back: bool

    @property
    def passed(self) -> bool:
        # A document that produced NO passages has failed regardless of what
        # the ratio says, and the ratio is exactly where that slips through:
        # a scan has no text layer, so there is no denominator and coverage
        # is None. Treating None as an unconditional pass would write a
        # scanned document live and empty — the silent-empty failure this
        # whole plan exists to kill, for precisely the document class the OCR
        # rung serves. So chunks first, ratio second.
        if not self.chunks:
            return False
        if self.coverage is None:
            # Unmeasurable but non-empty. Accept: refusing it would reject
            # every scan the OCR rung exists to rescue, and the floor is a
            # rejector — it never approves anything, so it cannot be asked
            # to approve on no evidence either.
            return True
        return self.coverage >= COVERAGE_FLOOR


def _extract_and_chunk(job: JobRecord, ctx: WorkerContext) -> ExtractionOutcome:
    """Extract, chunk, measure; fall back a rung and repeat if it came out empty.

    The check sits AFTER chunking and BEFORE embedding (spec T6). Extraction
    takes hours and embedding takes minutes, so measuring here catches a
    failed document before the expensive write phase is paid for, and it
    measures exactly what would have been written.

    The job stays in `extracting` for the whole loop, including the chunking
    inside it. That is the honest state: a fallback re-enters extraction, and
    a queue page that showed "chunking" and then went back to "extracting"
    would look like a bug.
    """
    source = _ensure_source(job)
    inspection = inspect_source(source)
    rungs = ladder_for(job.doc_type, inspection.source_format, inspection)
    if not rungs:
        # Preserve today's loud failure for a genuinely unsupported pair —
        # (budget-bill, pdf) and friends are caller bugs, not documents to
        # keep trying tools against.
        raise ValueError(
            f"no extractor for (doc_type={job.doc_type!r}, "
            f"format={inspection.source_format!r})"
        )

    # What earlier runs of THIS job already paid for. Keyed by rung name
    # because that is what the loop below asks about.
    prior = {a.get("extractor"): a for a in job.extraction_attempts}
    attempts: list[dict] = []
    best: ExtractionOutcome | None = None

    for index, name in enumerate(rungs):
        recorded = prior.get(name)
        if recorded is not None and recorded.get("error"):
            # This rung CRASHED on an earlier run. Don't pay for it again,
            # and don't try to chunk output it never produced.
            attempts.append(dict(recorded))
            continue

        if index > 0:
            # completed_ranges is scoped to ONE rung's output directory.
            # Carrying it forward makes the next rung skip pages it has never
            # extracted — a partial document failing coverage for a reason
            # unrelated to the extractor.
            #
            # This clear is POSITIONAL (`index > 0`), not rung-aware — it does
            # not check which rung wrote the ranges it is clearing. That is
            # safe only because nothing today ever arrives at index > 0 with
            # ranges still set from something other than a completed rung 0:
            # `_extract_with_mineru` (the per-document path) always passes the
            # WHOLE page range in one call, so `completed_ranges` stays empty
            # for the whole rung and only gets populated at rung 0 by
            # `extract_batch`'s hand-off, which `_batch_rung_matches`
            # guarantees only ever runs at index 0. If per-range incremental
            # journalling is ever added within a single rung, this positional
            # rule would clear a mid-rung journal it should have kept.
            if job.completed_ranges:
                job.completed_ranges = []
                save(job)
            _progress(job, "extracting", pct=0, detail=_fallback_detail(attempts, name))

        try:
            if recorded is None and _needs_extraction(job, source, name):
                # Each rung extracts into ITS OWN directory. Three things
                # fall out of that: no destructive reset between rungs; a
                # resumed job cannot mistake rung 2's half-finished output
                # for rung 1's; and the best attempt's output survives on
                # disk for the human who is about to look at the failure.
                _extract(job, ctx, extractor=dispatcher.pick_named(name), method=name)
            _check_cancelled(job)
            # The rung name is passed EXPLICITLY. `_chunk` used to derive the
            # reader from the doc_type's DEFAULT extractor, which would parse
            # MinerU output with the OpenDataLoader reader on every fallback.
            chunks = _chunk(job, ctx, extractor=name)
            coverage, coverage_error = _measure_coverage(chunks, source)
            attempt: dict = {
                "extractor": name, "coverage": coverage, "chunks": len(chunks),
            }
            if coverage_error is not None:
                attempt["coverage_error"] = coverage_error
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — a rung's failure, not the job's
            # A rung that CRASHES is a rung that failed, not a job that
            # failed. A malformed PDF making one extractor raise is the
            # likeliest real trigger for the whole ladder, and letting the
            # exception out would bypass the entire mechanism.
            attempt = {
                "extractor": name, "coverage": None, "chunks": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
            chunks, coverage = [], None

        attempts.append(attempt)
        # Journalled per rung, not at the end: a machine that dies during
        # rung 2 must not come back believing rung 1 was never tried.
        job.extraction_attempts = list(attempts)
        save(job)

        outcome = ExtractionOutcome(
            chunks=chunks,
            attempts=list(attempts),
            coverage=coverage,
            extractor=name,
            fell_back=index > 0,
        )
        if outcome.passed:
            return outcome
        if best is None or _outcome_rank(outcome) > _outcome_rank(best):
            best = outcome

    # Every rung is below the floor. Keep whichever scored HIGHEST (spec T5),
    # not whichever ran last: OCR is the final rung and is also the rung most
    # likely to score near zero on a document that was never a scan, so
    # "last" would routinely discard the better evidence a human is about to
    # look at. Nothing below the floor is written either way; what is kept is
    # the number the failure message quotes and the output left on disk.
    if best is None:
        # Only reachable when every rung was a crash recorded by an earlier
        # run, so nothing ran here at all.
        best = ExtractionOutcome(
            chunks=[], attempts=[], coverage=None,
            extractor=rungs[-1], fell_back=len(rungs) > 1,
        )
    # The full attempt list, not the slice that existed when `best` was
    # built: the queue page has to show every method that was tried.
    return replace(best, attempts=list(attempts))


def _outcome_rank(outcome: ExtractionOutcome) -> tuple[float, int]:
    """Sort key for "which failed attempt was least bad".

    An unmeasurable attempt ranks below every measured one (-1.0 is below a
    genuine 0.0): a crash or an unreadable source tells us nothing, while a
    measured 0% is at least a real observation about a real extraction.

    NOTE: among FAILING outcomes, `extractor` and `coverage` are the only
    fields this comparison can distinguish on — nothing downstream currently
    reads which one was picked. `_held_out_message` recomputes
    `max(measured)` from `attempts` directly rather than consulting the
    returned outcome, and nothing else consults it either. Keeping the best
    attempt is still correct and required (spec T5 step 4, "keep whichever
    result scored highest") — it is what leaves the best output on disk for
    a human to look at — but do not delete this function as dead code on the
    strength of nothing reading its result TODAY.
    """
    return (
        outcome.coverage if outcome.coverage is not None else -1.0,
        len(outcome.chunks),
    )


def _measure_coverage(
    chunks: Sequence[Chunk], source: Path
) -> tuple[float | None, str | None]:
    """The coverage ratio, or None plus why it could not be measured.

    A measurement that fails is NOT an extraction that failed. The floor
    rejects; it never approves — so when the denominator cannot be read (a
    PDF PyMuPDF refuses, a source format with no text-layer reader) the
    check has learned nothing and must not hold the document out of search
    on the strength of that.

    The reason is recorded rather than swallowed, so a corpus where the
    denominator has silently stopped being readable is visible on the job
    instead of looking like a corpus of scans.
    """
    try:
        return coverage_ratio((c.text for c in chunks), source), None
    except Exception as exc:  # noqa: BLE001 — any unreadable source
        return None, f"{type(exc).__name__}: {exc}"


def _needs_extraction(job: JobRecord, source: Path, method: str) -> bool:
    """Does this rung still have to run, or is its output already complete?

    This is the batch hand-off, and only that. `extract_batch` extracts a
    whole document and journals `completed_ranges` for it, then hands the job
    back to the ordinary pipeline — which would otherwise re-extract every
    batched document one at a time, undoing the entire point of batching.

    Deliberately requires BOTH the journal and the files: `completed_ranges`
    alone would skip extraction for a job whose output directory was cleared,
    and files alone would reuse a previous ingest's output for a REPROCESS of
    the same doc_id with a corrected source file (a fresh job carries no
    ranges, so it always re-extracts).
    """
    if not job.completed_ranges:
        return True
    pages = _pdf_pages(source)
    if not pages:
        return True
    covered = {p for start, end in job.completed_ranges for p in range(start, end + 1)}
    if not set(range(1, pages + 1)) <= covered:
        return True
    return not _extraction_complete(_extract_dir(job, method), pages)


def _fallback_detail(attempts: list[dict], name: str) -> str:
    """One line for the queue page saying why another method is running."""
    if attempts and attempts[-1].get("error"):
        return f"the previous method failed — trying {name}"
    return f"the previous method produced almost nothing — trying {name}"


def _held_out_message(outcome: ExtractionOutcome) -> str:
    """Why this document is not in the corpus, in a sentence.

    States what was MEASURED — how much text came out — and never that
    anything was verified or checked: this test detects catastrophic loss,
    not correctness, and copy that implies otherwise would be a claim the
    measurement cannot support (see ingest/coverage.py).
    """
    tried = len(outcome.attempts)
    methods = f"{tried} extraction method{'s' if tried != 1 else ''}"
    were = "were" if tried != 1 else "was"
    measured = [
        a["coverage"] for a in outcome.attempts if a.get("coverage") is not None
    ]
    if measured:
        return (
            f"Held out of search — only {max(measured):.0%} of this document's "
            f"text produced any content, after {methods} {were} tried."
        )
    errors = [a["error"] for a in outcome.attempts if a.get("error")]
    if errors:
        return (
            f"Held out of search — all {methods} failed. "
            f"Last error: {errors[-1]}"
        )
    return (
        f"Held out of search — {methods} {were} tried and none of them "
        "produced any passages."
    )


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


def _extract(
    job: JobRecord,
    ctx: WorkerContext,
    *,
    extractor: Any | None = None,
    method: str | None = None,
) -> None:
    """Run one extractor into `<data_dir>/extractor-output/<doc_id>/<method>/`.

    Output goes on the SHARE, not in a temp dir, so a machine that dies
    overnight doesn't cost the office the extraction — any machine can pick
    the job up and continue from the pages already done.

    `method` is the LADDER RUNG name and scopes the output directory. It is
    not MinerU's `-m` flag, despite the word: that value comes off the
    extractor itself (`mineru_method`) further down. Two different things
    that happen to share a name.

    Precedence for which tool runs: `ctx.extractor` (the test override, which
    has always won here) → the rung the caller named → the registry.
    """
    source = _ensure_source(job)
    out = _extract_dir(job, method)
    out.mkdir(parents=True, exist_ok=True)
    source_format = source.suffix.lstrip(".").lower()

    chosen = (
        ctx.extractor
        or extractor
        or dispatcher.pick_extractor(job.doc_type, source_format)
    )

    if ctx.extractor is None and isinstance(chosen, dispatcher.MinerUExtractor):
        _extract_with_mineru(
            job, source=source, out=out,
            # The OCR rung differs from the plain one by exactly this flag.
            # Reading it off the extractor keeps the ladder from having to
            # know anything about MinerU's CLI.
            method=getattr(chosen, "mineru_method", "auto"),
        )
        return

    # DOCX and OpenDataLoader run as one blocking call — both are minutes,
    # not hours, so there's nothing to stream progress against.
    _progress(job, "extracting", pct=0, detail=f"reading {source.name}")
    dispatcher.extract(
        source_path=source,
        doc_type=job.doc_type,
        source_format=source_format,
        output_dir=out,
        extractor=chosen,
    )
    _progress(job, "extracting", pct=100, detail="")


def _extract_with_mineru(
    job: JobRecord, *, source: Path, out: Path, method: str = "auto"
) -> None:
    """MinerU path: streamed progress, cancellable, resumable per page range.

    `method` here IS MinerU's `-m` flag — "auto" for the ordinary rung,
    "ocr" for the ladder's last one. It is per-runner, so a runner is built
    per attempt.
    """
    pages = list(range(1, dispatcher._pdf_page_count(source) + 1))
    runner = MineruRunner(method=method)

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


# --- batch extraction -------------------------------------------------------


def batch_eligible(job: JobRecord) -> bool:
    """Can this document share a MinerU run with others?

    Four conditions, each of which costs something real when broken:

    1. **It is a document.** A fiscal-note refresh has no PDF at all.
    2. **It routes to MinerU.** A batch is one `mineru -p <dir>` invocation,
       so an AFR (OpenDataLoader) or a bill (python-docx) shares nothing with
       it. Note this asks the REGISTRY, not `ctx.extractor`: that override is
       the test seam for the per-document path, and the batch path has its
       own (`ctx.batch_runner`).
    3. **It is not part-way through its pages.** A job carrying
       `completed_ranges` is mid-extraction on the per-document path, whose
       resume granularity is the page range. Batch mode extracts whole
       documents, so batching it would re-do the pages it already paid for.
    4. **It is not part-way through its LADDER.** A job with recorded
       `extraction_attempts` is past rung 1, and rung 2 is never the rung a
       batch runs (see `_batch_rung_matches`).
    5. **It is small** (`BATCH_MAX_PAGES`), and **its first ladder rung is
       the one a batch actually runs**. Both are checked separately by the
       caller, because they need the file on disk and this predicate must
       stay cheap enough to run over every queued job.
    """
    if job.kind != "document":
        return False
    if job.completed_ranges:
        return False
    if job.extraction_attempts:
        return False
    try:
        return dispatcher.pick_extractor(job.doc_type, _batch_format(job)).name \
            == MINERU_EXTRACTOR_NAME
    except ValueError:
        # An unregistered (doc_type, format) pair is a caller bug; let the
        # per-document path raise it with its own clear message rather than
        # swallowing it here as "not batchable".
        return False


def _batch_rung_matches(job: JobRecord) -> bool:
    """Is this document's FIRST ladder rung the one a batch actually runs?

    **A MinerU batch is homogeneous by rung whether or not anybody planned
    it.** `MineruRunner` takes MinerU's `-m` flag at CONSTRUCTION, and
    `extract_batch` builds exactly one runner for up to 40 documents — so one
    `-m` value covers the whole batch. A batch mixing rungs either OCRs 39
    documents that did not need it (hours of wasted work) or fails to OCR the
    one that did.

    Grouping is a document whose ladder starts anywhere other than plain
    `mineru` — today only a scan, which `ingest/ladder.py` routes straight to
    `mineru-ocr` — being kept out of the batch and taking the per-document
    path, where it gets its own runner in the mode it needs. THIS FUNCTION IS
    NOT THE WHOLE OF THAT RULE, and a review confirmed it is not an
    equivalent substitute for the other two: rung-homogeneity holds by THREE
    cooperating guards, and deleting any one of them re-opens a real gap.

    1. **This function** — excludes a document whose first ladder rung is
       not `mineru` (a scan) from ever entering a batch.
    2. **`batch_eligible`'s `completed_ranges` check** — excludes a document
       that is part-way through the per-document page range.
    3. **`batch_eligible`'s `extraction_attempts` check** — excludes a
       document that is past rung 1 already, which THIS function alone
       cannot: `ladder_for` is stateless, so a document that already crashed
       on `mineru` and is waiting to resume still reports `rungs[0] ==
       "mineru"` here (correctly — that IS rung 1 of its ladder), and its
       `completed_ranges` was cleared at the rung change, so guard 2 does not
       see it either. Without guard 3, such a document is re-batched under
       `-m auto`, re-runs the identical extraction that just failed, and
       never reaches the `mineru-ocr` rung it actually needs. Pinned by
       `tests/test_ingest_batch.py::test_a_job_that_already_failed_a_rung_is_not_batch_eligible`.

    Needs the file on disk (inspection reads the text layer), so it is one of
    the two LATE eligibility checks, not part of `batch_eligible`.
    """
    try:
        source = _ensure_source(job)
    except Exception:  # noqa: BLE001 — diagnosed on the per-document path
        return False
    inspection = inspect_source(source)
    rungs = ladder_for(job.doc_type, inspection.source_format, inspection)
    return bool(rungs) and rungs[0] == MINERU_EXTRACTOR_NAME


def _batch_format(job: JobRecord) -> str:
    """Source format for a job that may not have been downloaded yet.

    "Add a JLBC book" queues ~130 URL-only jobs, and those are exactly the
    documents batch mode exists for — reading the format off `source_path`
    alone would make every one of them ineligible.
    """
    raw = job.source_path or (job.source_url or "").split("?")[0]
    return Path(raw).suffix.lstrip(".").lower()


def _pdf_pages(source: Path) -> int | None:
    """Page count, or None when the file cannot be read as a PDF.

    None is deliberately NOT an error here: it only ever means "do not batch
    this", and the per-document path will produce the real diagnosis.
    """
    try:
        return dispatcher._pdf_page_count(source)
    except Exception:  # noqa: BLE001 — an unreadable file is simply not batchable
        return None


def _extraction_complete(out: Path, pages: int) -> bool:
    """Is this document's extractor output already on the share, in full?

    `out` is one RUNG's output directory (`_extract_dir(job, method)`,
    rung-scoped since the extraction ladder shipped — this predates that and
    the un-suffixed base it originally described is now only ever reached
    through `_legacy_extract_dir`'s own fallback). That directory IS the
    resume signal — batch mode adds no journal of its own. This is safe
    because a document that FAILS inside a batch leaves no output directory
    behind, so a partial directory can never be mistaken for a finished one.
    """
    return pages > 0 and all(
        (out / f"page-{page}.json").is_file() for page in range(1, pages + 1)
    )


def _batch_timeout_s(count: int) -> int | None:
    """The runner's own budget for a batch of `count` documents.

    Deliberately delegates instead of computing a budget here: the runner is
    what actually enforces the timeout, and two independent formulas would
    drift the moment either side is tuned.
    """
    return batch_timeout_s(count)


def extract_batch(
    jobs: Sequence[JobRecord], ctx: WorkerContext
) -> dict[str, str | None]:
    """Extract several documents in ONE MinerU run.

    Returns `doc_id -> None` on success, or a per-document failure reason.
    Nothing here writes to the corpus: this is the read-only, hours-long half
    of ingest, and every caller still takes `IngestLock` for the seconds-long
    write half afterwards.
    """
    results: dict[str, str | None] = {}
    pages_by_doc: dict[str, int] = {}
    items: list[tuple[str, Path, Path]] = []

    for job in jobs:
        try:
            source = _ensure_source(job)
            # Scoped to the rung a batch runs. Every member is guaranteed to
            # be at that rung — see `_batch_rung_matches` — so this is the
            # same directory the per-document ladder will read afterwards.
            out = _extract_dir(job, MINERU_EXTRACTOR_NAME)
            out.mkdir(parents=True, exist_ok=True)
            pages = _pdf_pages(source) or 0
            pages_by_doc[job.doc_id] = pages
            if _extraction_complete(out, pages):
                # Resume: an interrupted batch must not re-pay for the
                # documents it already finished.
                results[job.doc_id] = None
                continue
            items.append((job.doc_id, source, out))
        except Exception as exc:  # noqa: BLE001 — one document's problem
            results[job.doc_id] = f"{type(exc).__name__}: {exc}"

    if not items:
        return results

    by_doc = {job.doc_id: job for job in jobs}

    def on_document(doc_id: str, state: str) -> None:
        # The callback is terminal-only — one CLI invocation gives MinerU
        # nothing attributable per document while it runs, so these arrive
        # during demux after it exits. Failure and cancellation are handled
        # from run_batch's return value and its exceptions, so the only thing
        # worth journalling here is a finished document.
        job = by_doc.get(doc_id)
        if job is not None and state == "done":
            _progress(job, "extracting", pct=100, detail="extracted")

    count = len(items)
    for doc_id, _source, _out in items:
        job = by_doc.get(doc_id)
        if job is not None:
            # Batch-level progress, honestly labelled. Anything finer would
            # be invented: MinerU reports nothing per document mid-run.
            _progress(
                job, "extracting", pct=0,
                detail=f"extracting with {count - 1} other document(s)",
            )

    runner = ctx.batch_runner or MineruRunner()
    returned = runner.run_batch(
        items,
        timeout_s=_batch_timeout_s(count),
        on_document=on_document,
    )

    for doc_id, _source, _out in items:
        # A doc_id the runner said nothing about is a failure, not a success.
        # Treating silence as success is how a document lands `live` and
        # empty with nothing flagging it.
        reason = returned.get(
            doc_id, "MinerU returned no result for this document in its batch."
        )
        results[doc_id] = reason
        if reason is None:
            job = by_doc.get(doc_id)
            pages = pages_by_doc.get(doc_id, 0)
            if job is not None and pages > 0:
                # Record the whole document as one completed range so that a
                # later resume on the PER-DOCUMENT path also knows extraction
                # is done and does not start MinerU again.
                job.completed_ranges = [[1, pages]]
                save(job)
    return results


def _chunk(job: JobRecord, ctx: WorkerContext, *, extractor: str) -> list[Chunk]:
    """Build passages from ONE rung's extractor output.

    `extractor` is the rung that produced that output, and it decides both
    which directory is read and which reader parses it. It used to be
    derived from the doc_type's DEFAULT extractor, which is right only while
    nothing ever falls back — a job that fell back to MinerU would then parse
    MinerU output with the OpenDataLoader reader.
    """
    _progress(job, "chunking", pct=0, detail="building passages")
    chunks = chunk_doc(
        extractor_output_path=_extract_dir(job, extractor),
        doc_meta=DocMeta(
            doc_id=job.doc_id,
            publisher=job.publisher,
            doc_type=job.doc_type,
            fiscal_year=job.fiscal_year,
            extractor=extractor,
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


def _extraction_record(outcome: ExtractionOutcome) -> dict[str, Any]:
    """The documents.json shape for Plan B Task 5.

    `method` is taken from the OUTCOME, not `DocMeta.extractor` — checked,
    not assumed: chunk rows carry no extractor column at all
    (`store/schema.py`), so this sidecar entry is the only place the method
    is recorded and there is nothing else it could disagree with. Taking it
    from the outcome is still the right call after a fallback, since that is
    the rung that is true of what was actually written.

    `attempts` counts `outcome.attempts` (every rung this run tried, winner
    included). NOTE the obvious justification for preferring it over
    `job.extraction_attempts` is FALSE and was traced: the two cannot
    disagree. `_extract_and_chunk` carries a prior run's crashed rungs
    FORWARD into `attempts` and then assigns `job.extraction_attempts =
    list(attempts)` in the same call, and retry zeroes the job's list — so
    on every path, including resume, they hold the same contents.

    The real reason to read the outcome is consistency of reporting:
    `_held_out_message` counts the same way for a FAILED document, so an
    analyst sees attempts tallied on one basis whether the document made it
    into the corpus or not.

    This is a record of what was measured, never a verdict: see
    `ingest/coverage.py`'s module docstring for why a passing document is
    not a "verified" or "healthy" one, only one that produced enough text.

    DELIBERATE DIVERGENCE FROM SPEC T8: the spec's sidecar shape shows
    `"attempts": [...]` — the full per-rung list, same shape as the
    Needs-attention panel's `job.extraction_attempts`. Plan B's Task 5
    narrowed it to `len(...)`, a bare count, and that narrowing is correct
    (it was a deliberate scope cut, not an oversight — the job file is
    already the durable record of the list and duplicating it into
    documents.json is a second place for the two to drift). The COST: for a
    document that reached `live`, the sidecar alone can say HOW MANY
    methods were tried but not WHICH ones or what each scored — that detail
    lives only in the job record, and job records are not kept forever the
    way documents.json is. An admin auditing a live document's extraction
    history after its job file has aged out sees "2 attempts" and nothing
    more.
    """
    return {
        "method": outcome.extractor,
        "coverage": outcome.coverage,
        "attempts": len(outcome.attempts),
        "fell_back": outcome.fell_back,
    }


def _write(
    job: JobRecord,
    ctx: WorkerContext,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    outcome: ExtractionOutcome,
) -> None:
    """The only stage that mutates shared state. Lock → snapshot → write.

    `outcome` is the SAME `ExtractionOutcome` `run_job` already measured
    coverage from — passed through rather than re-derived so `write_doc`
    records the value that was actually true after any rung fallback.
    """
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
        # See `_should_snapshot` for the policy. Kept in the caller so
        # store/backup.py stays a dumb honest "make a snapshot" primitive
        # that an admin "Back up now" button can still trust.
        if not _should_snapshot(job):
            if _snapshot_suppressed():
                print(SNAPSHOT_SUPPRESSED_MESSAGE, file=sys.stderr, flush=True)
                detail = "snapshot suppressed (bulk mode)"
            else:
                detail = "backed up at the start of this batch"
            _progress(job, "writing", pct=10, detail=detail)
        else:
            _progress(job, "writing", pct=10, detail="backing up the corpus")
            snapshot()
            _record_batch_snapshot(job)
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
                agency_name=_agency_name_for_title(job, chunks, ctx),
                stage=job.stage,
            ),
            source_sha256=job.source_sha256,
            source_blob_path=blob_path,
            source_url=job.source_url,
            source_format=_source_format(job),
            uploaded_by=job.user,
            agency_ids_by_chunk=agency_ids,
            extraction=_extraction_record(outcome),
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


def configured_batch_size() -> int:
    """How many documents to hand to one MinerU run, after clamping.

    Fails SAFE in exactly the same directions as `configured_worker_count`:
    unset, empty, a typo, zero, or a negative number all mean 1 — today's
    behaviour, one invocation per document. This runs on the live ingest path
    of a working office, so a mistyped variable must never change it.
    """
    raw = os.environ.get(BATCH_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_BATCH
    try:
        requested = int(raw)
    except ValueError:
        return DEFAULT_BATCH
    if requested <= 1:
        return DEFAULT_BATCH
    return min(requested, MAX_BATCH)


def _batch_announcement(count: int) -> str:
    requested = os.environ.get(BATCH_ENV_VAR, "").strip()
    clamped = (
        f" (clamped from {requested}; ceiling is {MAX_BATCH})"
        if requested.isdigit() and int(requested) != count
        else ""
    )
    return (
        f"jlbc-insight: BATCH EXTRACTION — up to {count} documents per MinerU "
        f"run{clamped}, set by {BATCH_ENV_VAR}={requested}. Only whole "
        f"documents of {BATCH_MAX_PAGES} pages or fewer are batched; anything "
        "larger keeps the one-document-at-a-time path so a long book still "
        "resumes page by page. A machine that dies mid-batch re-extracts the "
        f"whole batch. Unset {BATCH_ENV_VAR} to return to one document per run."
    )


def _batch_ignored_announcement(raw: str) -> str:
    """Said out loud because the alternative is a silent no-op.

    An operator who sets `JLBC_INGEST_BATCH=twenty` and sees nothing will plan
    a night around a speed-up that never happens — the same reasoning as the
    clamped-to-one message for `JLBC_INGEST_WORKERS`, extended to typos
    because a batch size is far more likely to be typed by hand.
    """
    return (
        f"jlbc-insight: {BATCH_ENV_VAR}={raw!r} is not a batch size above 1 — "
        "ingest is running ONE document per MinerU run (today's behaviour). "
        f"Set {BATCH_ENV_VAR} to a whole number above 1 to batch."
    )


def _snapshot_suppressed() -> bool:
    """True only when the operator explicitly asked for bulk mode.

    WHY the strict comparison: this switch turns off a data-loss safety net,
    so it fails SAFE. Unset, empty, `per-doc`, or a typo like `false` or `0`
    all mean "keep snapshotting". Nothing but the literal word `off` (spacing
    and capitalisation forgiven) can disable it.
    """
    return os.environ.get(SNAPSHOT_ENV_VAR, "").strip().lower() == SNAPSHOT_OFF


# Marker files recording "this batch already has a restore point". They live
# beside the snapshots because that is what they describe, and ON THE SHARE
# rather than in memory: a 210-page book is an overnight job that WILL be
# interrupted, and an in-memory record would re-zip the whole corpus on every
# restart — the quadratic cost coming back through the side door.
_BATCH_MARKER_PREFIX = ".batch-"


def _batch_marker_path(batch_id: str) -> Path:
    from store.backup import backups_dir

    # Hashed, not interpolated: batch ids are built from publisher/family
    # strings and a path separator in one would escape the backups directory.
    digest = hashlib.sha256(batch_id.encode("utf-8")).hexdigest()[:16]
    return backups_dir() / f"{_BATCH_MARKER_PREFIX}{digest}"


def _should_snapshot(job: JobRecord) -> bool:
    """Does THIS document need its own corpus snapshot before writing?

    `snapshot()` zips the ENTIRE corpus, so per-document snapshots cost
    O(corpus) each while the count grows with the documents — quadratic.
    Measured on the Z13: a ~54 MB zip every ~40 s at 68 MB of corpus,
    projected to 60–90 s per document once the books landed.

    Three cases, in precedence order:

    1. **Bulk mode wins outright.** `JLBC_INGEST_SNAPSHOT=off` is an
       operator saying "I have my own archive". Per-batch must not quietly
       switch snapshots back on for somebody who turned them off.
    2. **No batch → snapshot, as before.** A hand upload is exactly when an
       analyst wants a restore point, and one upload is one zip.
    3. **In a batch → snapshot only the first document.** A book edition or
       a fiscal-note session is the unit somebody would actually roll back
       to, and the unit that fails as a unit. One restore point per batch is
       the protection; the other 200 zips were never buying anything.

    Fails SAFE: if the marker cannot be read, the honest answer is "I don't
    know whether this batch has a restore point", and the conservative
    response is to make one. An extra zip costs time; a missing one costs
    the corpus.
    """
    if _snapshot_suppressed():
        return False
    if not job.batch_id:
        return True
    try:
        return not _batch_marker_path(job.batch_id).exists()
    except OSError as err:
        print(
            f"jlbc-insight: couldn't check the batch snapshot marker ({err}) — "
            "taking a snapshot to be safe.",
            file=sys.stderr,
            flush=True,
        )
        return True


def _record_batch_snapshot(job: JobRecord) -> None:
    """Remember that this batch now has a restore point.

    A failure here is deliberately silent-but-harmless: the next document
    in the batch takes another snapshot, which is wasteful and correct.
    """
    if not job.batch_id:
        return
    try:
        _batch_marker_path(job.batch_id).write_text(
            f"{job.batch_id}\n", encoding="utf-8"
        )
    except OSError:
        pass


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
        batch: int | None = None,
    ) -> None:
        self._ctx = ctx
        self._ctx_lock = threading.Lock()
        self._poll_interval_s = poll_interval_s
        # None means "read the environment at start()". An explicit number
        # (tests, and any future admin toggle) wins over the env var.
        self._workers = workers
        self._batch = batch
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

    @property
    def batch_size(self) -> int:
        return self._batch if self._batch is not None else configured_batch_size()

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
        batch = self.batch_size
        if batch > 1:
            print(_batch_announcement(batch), file=sys.stderr, flush=True)
        elif BATCH_ENV_VAR in os.environ:
            # Set-but-unusable. Silence is reserved for an UNSET variable, so
            # an explicit `=1` (a deliberate "today, please") is silent too.
            raw = os.environ[BATCH_ENV_VAR]
            if raw.strip() != str(DEFAULT_BATCH):
                print(
                    _batch_ignored_announcement(raw), file=sys.stderr, flush=True
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
            mates: list[tuple[JobRecord, JobClaim]] = []
            try:
                # Empty whenever batching is off, so the default install never
                # reaches the batch code at all.
                mates = self._claim_batch_mates(job)
                if mates:
                    self.run_batch([(job, claim), *mates])
                else:
                    self.run_one(job)
            finally:
                # Always, even on a crash inside run_one (which shouldn't
                # happen — it swallows everything — but a leaked claim parks
                # that document for the whole stale window). Every claim the
                # batch took is released here, not just the lead's.
                claim.release()
                for _mate, mate_claim in mates:
                    mate_claim.release()

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
            claimed = self._claim(candidate)
            if claimed is not None:
                return claimed
        return None

    def _claim(self, candidate: JobRecord) -> tuple[JobRecord, JobClaim] | None:
        """Take one candidate's claim and re-read it, or None if we can't."""
        claim = JobClaim(candidate.job_id, doc_id=candidate.doc_id)
        if not claim.try_acquire():
            return None  # a sibling worker, or another machine, has it

        # Re-read under the claim. The listing that produced this candidate
        # may be seconds old: the job could have been cancelled, retried, or
        # finished by whoever held the claim before us.
        fresh = load_job(candidate.job_id)
        if fresh is None or fresh.state in TERMINAL_STATES:
            claim.release()
            return None
        if fresh.state != "queued" and fresh.machine != socket.gethostname():
            # Mid-flight on ANOTHER machine, whose extractor output we can
            # read but whose progress we shouldn't hijack.
            claim.release()
            return None

        if fresh.state == "queued":
            # Same stamp the serial worker wrote — this is what the queue page
            # shows as "who is running this".
            fresh.machine = socket.gethostname()
            save(fresh)
        return fresh, claim

    def _claim_batch_mates(
        self, lead: JobRecord
    ) -> list[tuple[JobRecord, JobClaim]]:
        """Claim documents to share `lead`'s MinerU run. Empty = no batch.

        Returns empty — having done nothing at all — whenever batching is off,
        which is what makes `JLBC_INGEST_BATCH` unset byte-identical to
        today's path rather than merely equivalent to it.

        Also returns empty when only the lead is eligible: a "batch" of one is
        exactly the per-document path with extra staging, so it takes the
        per-document path.
        """
        size = self.batch_size
        if size <= 1:
            return []
        if (
            not batch_eligible(lead)
            or not self._small_enough(lead)
            or not _batch_rung_matches(lead)
        ):
            return []

        mates: list[tuple[JobRecord, JobClaim]] = []
        taken = {lead.job_id}
        for candidate in self._candidates():
            if len(mates) + 1 >= size or self._stop.is_set():
                break
            if candidate.job_id in taken or candidate.doc_id == lead.doc_id:
                continue
            taken.add(candidate.job_id)
            # Cheap predicates first: this runs over the whole queue, and the
            # page count below needs the file on disk.
            if not batch_eligible(candidate):
                continue
            claimed = self._claim(candidate)
            if claimed is None:
                continue
            fresh, claim = claimed
            # Re-checked under the claim, because the listing may be stale —
            # and the page count is only knowable once we own the download.
            if (
                not batch_eligible(fresh)
                or not self._small_enough(fresh)
                or not _batch_rung_matches(fresh)
            ):
                claim.release()
                continue
            mates.append((fresh, claim))
        return mates

    def _small_enough(self, job: JobRecord) -> bool:
        """The page half of batch eligibility — needs the file, so it's late.

        A document we cannot download or cannot read is not batchable; the
        per-document path will produce the real error message for it.
        """
        try:
            source = _ensure_source(job)
        except Exception:  # noqa: BLE001 — diagnosed on the per-document path
            return False
        pages = _pdf_pages(source)
        return pages is not None and 0 < pages <= BATCH_MAX_PAGES

    def run_batch(self, members: Sequence[tuple[JobRecord, JobClaim]]) -> None:
        """Extract several claimed documents in one MinerU run, then finish
        each one separately.

        Only EXTRACTION is shared. Chunking, embedding and the write phase
        still run per document, and the write phase still takes `IngestLock`
        one document at a time — batching changes what MinerU is invoked with,
        nothing about the single-writer invariant.
        """
        ctx = self.context
        prepared: list[JobRecord] = []
        for job, _claim in members:
            try:
                _check_cancelled(job)
                if job.state == "queued":
                    advance(job, "extracting")
                prepared.append(job)
            except JobCancelled:
                _finish_cancelled(job)
            except Exception as exc:  # noqa: BLE001 — one document's failure
                traceback.print_exc()
                _fail(job, exc)

        if not prepared:
            return

        try:
            results = extract_batch(prepared, ctx)
        except MineruCancelled:
            # Ordered before RuntimeError on purpose: MineruCancelled and
            # MineruTimeout both subclass it, and recording a cancel as a
            # generic failure would put a "retry" button on something the user
            # deliberately stopped.
            for job in prepared:
                _finish_cancelled(job)
            return
        except Exception as exc:  # noqa: BLE001 — the whole batch died
            traceback.print_exc()
            for job in prepared:
                _fail(job, exc)
            return

        for job in prepared:
            reason = results.get(
                job.doc_id, "MinerU returned no result for this document."
            )
            if reason is not None:
                # Quarantined with its OWN reason. One bad PDF costs one
                # document, not the nineteen it shared a run with.
                _fail(job, RuntimeError(reason))
                continue
            try:
                _check_cancelled(job)
                if job.state == "extracting":
                    advance(job, "chunking")
            except JobCancelled:
                _finish_cancelled(job)
                continue
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                _fail(job, exc)
                continue
            # From here it is the ordinary pipeline: run_job sees a job past
            # `extracting` and re-derives chunks from the output on the share.
            self.run_one(job)

    def _candidates(self) -> list[JobRecord]:
        """Jobs worth attempting, best first: our resumable work, then queued."""
        # load_active(), not load_all(): `queued` is never an archived
        # state, so this is the same set -- but load_all() reads the whole
        # 7,104-file archive on every pass of this poll loop, off a shared
        # drive. Spec T13.
        queued = [j for j in reversed(load_active()) if j.state == "queued"]
        return resumable() + queued


def ensure_started(app: Any) -> IngestWorker:
    """Attach a worker to a FastAPI app, starting it once.

    Idempotent so route modules can call it without coordinating.

    🔴 CALLERS: this does NOT consult `ingest_enabled()`. It is the "start
    the queue" primitive, and the one place entitled to call it
    unconditionally is app/main.py's lifespan, which checks first. A ROUTE
    must call `revive_if_this_machine_ingests` below instead.
    """
    worker = getattr(app.state, "ingest_worker", None)
    if worker is None:
        worker = IngestWorker()
        app.state.ingest_worker = worker
    worker.start()
    return worker


def revive_if_this_machine_ingests(app: Any) -> bool:
    """Restart an already-attached worker, but only where ingest belongs.

    🔴 THE DEFECT THIS FIXES, found 2026-08-16 by watching a real ingest run
    on a machine with `ingest_enabled()` False. The lifespan handler
    correctly declined to start the queue and said so on stderr — and then
    `POST /api/books/ingest` called `worker.start()` with no check at all,
    so pressing "Add" on a book turned that machine into the ingest machine
    anyway. `POST /api/upload` did the same. Both bypassed the switch
    completely.

    That switch is not a preference. `app/machine_config.ingest_enabled`'s
    own docstring names the outcome it exists to prevent: one bundle on ~20
    office PCs, so without it "the winner is arbitrary and may be an
    analyst's laptop that then spends six hours at 100% CPU on a Baseline
    book while they are trying to work." Queuing a book is exactly the
    request that costs six hours, and it was the one request that ignored
    the switch.

    ONE helper both routes call, rather than the same two-line check written
    out twice — the same reasoning as `IngestLock._take()`. Two paths
    independently deciding when to start a worker is the shape that produced
    this defect and the shape that would reproduce it in six months.

    Never BUILDS a worker (unlike `ensure_started`): a machine that opted
    out must not acquire one because somebody used the upload form. Returns
    whether the queue is running here, so a caller can tell the difference
    between "started" and "deliberately not started".
    """
    from app.machine_config import ingest_enabled

    if not ingest_enabled():
        return False
    worker = getattr(app.state, "ingest_worker", None)
    if worker is None:
        return False
    worker.start()
    return True


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


def _extract_dir(job: JobRecord, method: str) -> Path:
    """Where one rung's extractor output lives.

    Rung-scoped (`<doc_id>/<method>/`) so two attempts on one document never
    share a directory: without that, a MinerU fallback would write pages into
    a directory still holding the OpenDataLoader attempt's pages and the
    chunker would read a mixture of the two with nothing recording which is
    which. It also means the best attempt's output survives on disk for
    whoever looks at the failure.

    `method` is required: every production caller already knows which rung
    it means, and there is no caller left (including in tests) that predates
    rungs and wants the bare un-suffixed base — that shape is now reached
    only through `_legacy_extract_dir`'s fallback below, keyed off the SAME
    named method, not a missing one.
    """
    base = data_dir() / "extractor-output" / job.doc_id
    scoped = base / method
    if not scoped.exists():
        legacy = _legacy_extract_dir(job, base, method)
        if legacy is not None:
            return legacy
    return scoped


def _legacy_extract_dir(job: JobRecord, base: Path, method: str) -> Path | None:
    """The pre-rung, un-suffixed output directory, when it belongs to `method`.

    Thousands of jobs on the share were extracted before rung-scoped
    directories existed, and an interrupted overnight book must resume rather
    than re-extract from page 1.

    Only the doc_type's DEFAULT extractor may claim that directory, because
    that is what wrote it. Letting any rung claim it would point a MinerU
    fallback at a directory full of OpenDataLoader pages — exactly the mixing
    the scoped directories exist to prevent.

    ASSUMPTION THIS RELIES ON: a doc_type's default extractor never changes.
    The rule is meant to be "only the extractor that WROTE this directory may
    claim it" but is implemented as "only the CURRENT default may claim it" —
    those are the same thing only as long as `_default_extractor_name(job)`
    today equals what it was when the legacy directory was written. Plan 6
    (`data/document-types.yaml` becoming an admin-editable registry) is
    exactly the case that breaks this: if a type is ever re-pointed to a
    different default extractor, the NEW default would claim a legacy
    directory the OLD default actually wrote, silently mixing readers again.
    No sentinel file records which extractor really produced a legacy
    directory, so nothing here can currently tell the difference — flagged,
    not fixed.
    """
    if method != _default_extractor_name(job):
        return None
    if not any(base.glob("page-*.json")):
        return None
    return base


def _default_extractor_name(job: JobRecord) -> str | None:
    """The extractor `data/document-types.yaml` declares for this document."""
    try:
        return dispatcher.pick_extractor(job.doc_type, _source_format(job)).name
    except ValueError:
        return None


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


def _agency_name_for_title(
    job: JobRecord, chunks: Sequence[Chunk], ctx: WorkerContext
) -> str | None:
    """The agency name that goes in the title — DECLARED beats INFERRED.

    An uploader who picked "Department of Corrections" from the agency
    picker has told us what the document is. `_primary_agency_name` below
    counts stamps in the extracted text, which is a good guess and only a
    guess: `chunking/entity_stamper.py` cannot resolve an agency it has no
    alias for, and 103 of the 157 catalogued agencies carry no alias at all
    (recorded in STATUS.md under "Query understanding"). On exactly the
    documents this picker exists for -- one agency's own budget request --
    the inferred answer is therefore most likely to be None or wrong, and
    the declared one is ground truth.

    Falls through to the inferred name when nothing was declared, which is
    every doc_type except agency-submission and every job queued before the
    picker existed.
    """
    declared = (job.agency_canonical_id or "").strip()
    if declared:
        # Resolved through the same function the upload route validated
        # against, so a document cannot be accepted under one name and then
        # given another. An id that no longer resolves (an office entry an
        # admin deleted between upload and ingest) falls through rather than
        # failing the job -- a worse title is not worth losing the document.
        name = agency_name(declared)
        if name:
            return name
    return _primary_agency_name(chunks, ctx)


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
