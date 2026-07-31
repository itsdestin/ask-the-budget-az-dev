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
"""
from __future__ import annotations

import shutil
import socket
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
from ingest.lock import IngestLock, LockHeldError
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
    with IngestLock() as lock:
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


# --- the worker thread ------------------------------------------------------


class IngestWorker:
    """Polls the job journal and runs one document at a time.

    Deliberately serial. Two documents extracting at once on a 16 GB office
    PC means both crawl and the machine becomes unusable — and the write
    phase is single-writer anyway.
    """

    def __init__(
        self,
        *,
        ctx: WorkerContext | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._ctx = ctx
        self._poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def context(self) -> WorkerContext:
        # Built lazily: constructing it loads the embedding model, which must
        # not happen at import time or in a test that never ingests anything.
        if self._ctx is None:
            self._ctx = WorkerContext.default()
        return self._ctx

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ingest-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            self._thread = None

    def run_one(self, job: JobRecord) -> None:
        """Run one job, converting any failure into a `failed` job record.

        Failures are recorded, never raised: the queue must not stall on a
        bad document, and the user needs the reason on the queue page rather
        than in a log file they'll never open.
        """
        try:
            if job.kind == "refresh":
                run_refresh_job(job)
            else:
                run_job(job, self.context)
        except JobCancelled:
            _finish_cancelled(job)
        except Exception as exc:  # noqa: BLE001 — every failure is a job failure
            traceback.print_exc()
            _fail(job, exc)

    # --- internals ----------------------------------------------------------

    def _loop(self) -> None:
        try:
            for job in resumable():
                if self._stop.is_set():
                    return
                self.run_one(job)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

        while not self._stop.wait(self._poll_interval_s):
            try:
                job = self._claim_next()
            except Exception:  # noqa: BLE001 — a share hiccup must not end the loop
                traceback.print_exc()
                continue
            if job is not None:
                self.run_one(job)

    def _claim_next(self) -> JobRecord | None:
        """Take the oldest queued job, stamping this machine on it.

        The claim happens under the ingest lock so two office machines
        running the app can't both start the same document. The lock is
        released immediately — it's the write phase that needs to hold it,
        not the hours of extraction before it.
        """
        queued = [j for j in load_all() if j.state == "queued"]
        if not queued:
            return None
        try:
            with IngestLock():
                for candidate in reversed(queued):  # oldest first
                    fresh = load_job(candidate.job_id)
                    if fresh is None or fresh.state != "queued":
                        continue
                    fresh.machine = socket.gethostname()
                    save(fresh)
                    return fresh
        except LockHeldError:
            # Another machine is mid-write. Try again next poll.
            return None
        return None


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
