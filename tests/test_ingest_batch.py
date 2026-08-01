"""Tests for batch extraction (`JLBC_INGEST_BATCH`).

A MinerU invocation costs ~38 s and ~33 s of that is loading models. Batch
mode pays that once for N documents instead of N times. These tests are the
safety proofs for putting that on the LIVE ingest path of a working office.

In the order they matter:

  1. **Unset means today, exactly.** The batching code is not merely inert —
     it is never reached. This is the property that makes the feature safe to
     merge before it has been proven at scale, so it is asserted by making
     the batch entry point EXPLODE if anything calls it.
  2. **Only the right documents are batched.** Same extractor, small enough
     to lose cheaply, and never a document that is part-way through a page
     range — extraction resume granularity for a 210-page book is the page
     range, and batching would throw that away.
  3. **Claims are all-or-nothing.** A batch holds a claim for every document
     it touches (per job AND per doc_id — see ingest/claim.py) and releases
     every one of them when it dies.
  4. **One bad document is one bad document.** It is quarantined with its own
     reason while its batch-mates reach `live`.
  5. **Resume is free.** A document whose extractor output is already on the
     share is skipped, not re-extracted.

No models and no MinerU: a fake batch runner stands in for
`MineruRunner.run_batch` and a fake 8-dim embedder for arctic-embed-m, same
as tests/test_ingest_worker.py. The PDFs are real (PyMuPDF writes them),
because eligibility depends on a real page count.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ingest.claim import claims_dir
from ingest.jobs import advance, load_job, new_job, save
from ingest.lock import LOCK_FILENAME
from ingest.worker import (
    BATCH_ENV_VAR,
    BATCH_MAX_PAGES,
    DEFAULT_BATCH,
    MAX_BATCH,
    WORKERS_ENV_VAR,
    IngestWorker,
    WorkerContext,
    configured_batch_size,
)
from store.chunk_store import ChunkStore
from tests.test_ingest_worker import PAGE_BLOCKS, FakeEmbedder, FakeExtractor


class FakeBatchRunner:
    """Stands in for `MineruRunner.run_batch` — one 'model load' per call.

    Records the doc_ids of every call it receives, which is what makes
    "these documents shared one MinerU run" observable at all.
    """

    def __init__(self, fail: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail or {}
        self.raises: Exception | None = None
        self.claims_seen: list[int] = []
        self.lock_seen_while_extracting = False

    def run_batch(self, items, *, timeout_s=None, on_document=None):
        from ingest import dispatcher
        from store.config import data_dir

        self.calls.append([doc_id for doc_id, _pdf, _out in items])
        # How many documents were claimed while this batch ran. Counted from
        # the doc-key claim files, the half that stops a second worker taking
        # the same document.
        self.claims_seen.append(len(list(claims_dir().glob("doc-*.claim"))))
        # Extraction must never hold the corpus lock — that is the whole
        # reason the write phase is a separate, serialized stage.
        if (data_dir() / LOCK_FILENAME).exists():
            self.lock_seen_while_extracting = True
        if self.raises is not None:
            raise self.raises

        results: dict[str, str | None] = {}
        for doc_id, pdf, out in items:
            if on_document is not None:
                on_document(doc_id, "started")
            reason = self.fail.get(doc_id)
            if reason is not None:
                results[doc_id] = reason
                continue
            _write_pages(out, dispatcher._pdf_page_count(Path(pdf)), Path(pdf))
            results[doc_id] = None
            if on_document is not None:
                on_document(doc_id, "done")
        return results


class ExplodingBatchRunner:
    """Proves the batch path is not reached at all on the default install."""

    def run_batch(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("batch extraction ran with JLBC_INGEST_BATCH unset")


def _write_pages(out: Path, pages: int, pdf: Path) -> None:
    """The per-page extractor-output contract, without running MinerU."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for page in range(1, pages + 1):
        (out / f"page-{page}.json").write_text(
            json.dumps({
                "extractor": "mineru-fake",
                "source_pdf": str(pdf),
                "page": page,
                "blocks": PAGE_BLOCKS,
            }),
            encoding="utf-8",
        )


def _make_pdf(path: Path, pages: int) -> None:
    """A REAL pdf — batch eligibility turns on a real page count."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for n in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"page {n + 1}")
        doc.save(str(path))
    finally:
        doc.close()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # Snapshots zip the whole corpus per batch; irrelevant here and slow.
    monkeypatch.setenv("JLBC_INGEST_SNAPSHOT", "off")
    # Never inherit the developer's own backfill settings.
    monkeypatch.delenv(BATCH_ENV_VAR, raising=False)
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    return tmp_path


@pytest.fixture()
def runner():
    return FakeBatchRunner()


@pytest.fixture()
def extractor():
    return FakeExtractor()


@pytest.fixture()
def ctx(data_dir, runner, extractor):
    from chunking.entity_stamper import EntityStamper

    return WorkerContext(
        store=ChunkStore(root=data_dir, dim=8),
        embedder=FakeEmbedder(),
        stamper=EntityStamper.from_default_paths(fund_catalog_path=None),
        extractor=extractor,
        batch_runner=runner,
    )


_counter = {"n": 0}


def _queue_doc(
    data_dir,
    *,
    pages: int = 2,
    completed_ranges: list[list[int]] | None = None,
    state: str | None = None,
):
    """One queued job with its own real PDF of `pages` pages."""
    _counter["n"] += 1
    n = _counter["n"]
    sha = f"{n:02d}" * 32
    source = data_dir / "uploads" / sha[:2] / f"{sha}.pdf"
    _make_pdf(source, pages)
    job = new_job(
        doc_id=f"jlbc-baseline-fy2027-doc{n:03d}",
        title=f"doc {n}",
        corpus="budget",
        source_path=str(source.relative_to(data_dir)),
        source_sha256=sha,
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2027,
    )
    if completed_ranges:
        job.completed_ranges = completed_ranges
    save(job)
    if state is not None:
        advance(job, state)
    # job_ids embed a UTC second; a distinct created_at keeps "oldest first"
    # meaningful rather than an accident of hash ordering.
    time.sleep(0.002)
    return job


def _queue(data_dir, n: int, *, pages: int = 2) -> list:
    return [_queue_doc(data_dir, pages=pages) for _ in range(n)]


def _wait_for(predicate, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def _drain(worker, jobs, timeout_s: float = 30.0) -> None:
    worker.start()
    try:
        _wait_for(
            lambda: all(
                load_job(j.job_id).state in ("live", "failed", "cancelled")
                for j in jobs
            ),
            timeout_s=timeout_s,
        )
    finally:
        worker.stop(timeout_s=30)


def _batched(runner) -> list[str]:
    return [doc_id for call in runner.calls for doc_id in call]


# --- 1: unset means today, exactly ------------------------------------------
#
# The most important tests in this file. Batching ships default-off because
# this is the live ingest path for a working office; if these ever go red the
# feature has stopped being safe to have merged.


def test_the_batching_code_is_never_reached_when_the_env_var_is_unset(
    data_dir, ctx, extractor, monkeypatch
):
    """Not "inert" — never reached. The runner explodes if anything calls it."""
    ctx.batch_runner = ExplodingBatchRunner()

    import ingest.worker as worker_mod

    def must_not_run(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("extract_batch() ran with JLBC_INGEST_BATCH unset")

    monkeypatch.setattr(worker_mod, "extract_batch", must_not_run)

    jobs = _queue(data_dir, 3)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    assert worker.batch_size == 1
    _drain(worker, jobs)

    assert [load_job(j.job_id).state for j in jobs] == ["live"] * 3
    # Every document went down the ordinary per-document extractor path.
    assert extractor.calls == 3


def test_an_explicit_batch_of_one_is_the_per_document_path(
    data_dir, ctx, extractor, runner, monkeypatch
):
    monkeypatch.setenv(BATCH_ENV_VAR, "1")
    jobs = _queue(data_dir, 3)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    assert worker.batch_size == 1
    _drain(worker, jobs)

    assert [load_job(j.job_id).state for j in jobs] == ["live"] * 3
    assert runner.calls == []
    assert extractor.calls == 3


@pytest.mark.parametrize(
    "value", [None, "", "   ", "1", "0", "-4", "abc", "2.5", "true"]
)
def test_anything_that_is_not_a_number_above_one_means_one_document(
    monkeypatch, value
):
    """Fails safe in every direction, exactly like JLBC_INGEST_WORKERS: a typo
    must not silently change what the office install does."""
    if value is None:
        monkeypatch.delenv(BATCH_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(BATCH_ENV_VAR, value)
    assert configured_batch_size() == DEFAULT_BATCH == 1


def test_an_unusable_batch_setting_says_so_on_stderr(data_dir, ctx, monkeypatch,
                                                     capsys):
    """A typo that silently does nothing would have the operator plan a night
    around a speed-up that never happens."""
    monkeypatch.setenv(BATCH_ENV_VAR, "twenty")
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    err = capsys.readouterr().err
    assert BATCH_ENV_VAR in err
    assert "twenty" in err
    assert "ONE document" in err


def test_an_empty_batch_setting_says_so_on_stderr(data_dir, ctx, monkeypatch,
                                                  capsys):
    """`JLBC_INGEST_BATCH=` in a launcher script is the same mistake."""
    monkeypatch.setenv(BATCH_ENV_VAR, "")
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    assert "ONE document" in capsys.readouterr().err


def test_the_default_path_says_nothing_about_batching(data_dir, ctx, monkeypatch,
                                                      capsys):
    """Silence is reserved for an unset variable."""
    monkeypatch.delenv(BATCH_ENV_VAR, raising=False)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    assert BATCH_ENV_VAR not in capsys.readouterr().err


def test_batch_mode_is_announced_loudly_at_startup(data_dir, ctx, monkeypatch,
                                                   capsys):
    monkeypatch.setenv(BATCH_ENV_VAR, "8")
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    err = capsys.readouterr().err
    assert "BATCH EXTRACTION" in err
    assert "8 documents" in err
    assert BATCH_ENV_VAR in err


def test_a_batch_size_above_the_ceiling_is_clamped_and_says_so(
    data_dir, ctx, monkeypatch, capsys
):
    monkeypatch.setenv(BATCH_ENV_VAR, str(MAX_BATCH * 10))
    assert configured_batch_size() == MAX_BATCH
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    assert f"clamped from {MAX_BATCH * 10}" in capsys.readouterr().err


# --- 2: a batch is one MinerU run -------------------------------------------


def test_a_batch_extracts_every_document_in_one_run(data_dir, ctx, runner,
                                                    extractor):
    """The point of the whole change: four documents, ONE model load."""
    jobs = _queue(data_dir, 4)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=4)
    _drain(worker, jobs)

    assert [load_job(j.job_id).state for j in jobs] == ["live"] * 4
    assert len(runner.calls) == 1, "the documents did not share one MinerU run"
    assert sorted(runner.calls[0]) == sorted(j.doc_id for j in jobs)
    assert extractor.calls == 0, "a batched document also ran per-document"
    assert ctx.store.count("budget_chunks") > 0
    assert not runner.lock_seen_while_extracting, \
        "batch extraction held the corpus lock — writes would serialize behind it"


def test_a_batch_holds_a_claim_for_every_document_it_processes(data_dir, ctx,
                                                               runner):
    """Claims are per job AND per doc_id. A batch that extracted a document it
    had not claimed would let a second worker extract it at the same time,
    into the same extractor-output directory."""
    jobs = _queue(data_dir, 4)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=4)
    _drain(worker, jobs)

    assert runner.claims_seen == [4]
    # And nothing is left behind afterwards.
    assert list(claims_dir().glob("*.claim")) == []


def test_every_claim_is_released_when_the_batch_dies(data_dir, ctx, runner):
    """A leaked claim parks its document for the whole 90-second stale window,
    and the retry button would appear to do nothing."""
    runner.raises = RuntimeError("mineru CLI failed: model weights not found")
    jobs = _queue(data_dir, 4)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=4)
    _drain(worker, jobs)

    for job in jobs:
        reloaded = load_job(job.job_id)
        assert reloaded.state == "failed"
        assert "model weights not found" in reloaded.error
    _wait_for(lambda: list(claims_dir().glob("*.claim")) == [])


def test_batching_composes_with_parallel_workers(data_dir, ctx, runner):
    """Each worker claims and runs its OWN batch. No document may appear in
    two batches — that is two MinerU runs writing one output directory."""
    jobs = _queue(data_dir, 6)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=2, batch=3)
    _drain(worker, jobs)

    assert [load_job(j.job_id).state for j in jobs] == ["live"] * 6
    batched = _batched(runner)
    assert len(batched) == len(set(batched)), "a document was extracted twice"
    assert set(batched) <= {j.doc_id for j in jobs}
    # Not pinned at exactly 6: which worker wins which lead is a race, and a
    # worker that finds every other document already claimed correctly falls
    # back to the per-document path rather than staging a batch of one.
    assert len(batched) >= 4, "parallel workers stopped batching"
    assert max(len(call) for call in runner.calls) >= 2


# --- 3: eligibility ---------------------------------------------------------


def test_a_document_larger_than_the_page_ceiling_is_not_batched(
    data_dir, ctx, runner, extractor
):
    """Batch mode is for whole small documents. A long book keeps the
    per-document path because its resume granularity — the page range — is
    what makes an overnight extraction survivable, and batching throws it
    away."""
    small = _queue(data_dir, 3)
    big = _queue_doc(data_dir, pages=BATCH_MAX_PAGES + 1)

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=8)
    _drain(worker, small + [big])

    assert sorted(_batched(runner)) == sorted(j.doc_id for j in small)
    assert big.doc_id not in _batched(runner)
    assert load_job(big.job_id).state == "live"
    assert extractor.calls == 1, "the oversized document skipped the per-doc path"


def test_a_document_part_way_through_its_pages_is_not_batched(
    data_dir, ctx, runner, extractor
):
    """Ground truth 3: do NOT batch page ranges. A job carrying
    `completed_ranges` is mid-extraction; batching it would re-extract the
    pages it already paid for."""
    small = _queue(data_dir, 3)
    partial = _queue_doc(data_dir, pages=4, completed_ranges=[[1, 2]])

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=8)
    _drain(worker, small + [partial])

    assert partial.doc_id not in _batched(runner)
    assert sorted(_batched(runner)) == sorted(j.doc_id for j in small)
    assert load_job(partial.job_id).state == "live"


def test_a_document_that_needs_a_different_extractor_is_not_batched(
    data_dir, ctx, runner, extractor
):
    """Same extractor only. An AFR routes to OpenDataLoader, which shares
    nothing with a MinerU invocation — putting one in the batch would hand a
    PDF to a tool that was never going to read it.

    Eligibility asks the REGISTRY, not the injected extractor: the override
    exists so tests can skip MinerU, not to re-route documents."""
    small = _queue(data_dir, 2)
    odl = _queue_doc(data_dir, pages=2)
    odl.doc_type = "afr"
    odl.publisher = "agao"
    save(odl)

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=8)
    _drain(worker, small + [odl])

    assert sorted(_batched(runner)) == sorted(j.doc_id for j in small)
    assert odl.doc_id not in _batched(runner)
    assert extractor.calls == 1, "the AFR skipped the per-document path"


# --- 4 + 5: per-document failure, and resume --------------------------------


def test_one_failing_document_is_quarantined_and_its_mates_go_live(
    data_dir, ctx, runner
):
    """MinerU is per-file tolerant in batch mode (Ground truth 2). One bad PDF
    must cost one document, not nineteen."""
    jobs = _queue(data_dir, 4)
    bad = jobs[1]
    runner.fail[bad.doc_id] = "this PDF has no extractable text"

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=4)
    _drain(worker, jobs)

    failed = load_job(bad.job_id)
    assert failed.state == "failed"
    assert "no extractable text" in failed.error
    for job in jobs:
        if job.job_id == bad.job_id:
            continue
        assert load_job(job.job_id).state == "live"
    assert ctx.store.count("budget_chunks") > 0


def test_a_document_already_extracted_is_not_re_extracted(data_dir, ctx, runner):
    """`<data_dir>/extractor-output/<doc_id>/` IS the resume signal — no new
    journal. A batch interrupted overnight must not pay for the documents it
    already finished."""
    jobs = _queue(data_dir, 4)
    done = jobs[2]
    _write_pages(
        data_dir / "extractor-output" / done.doc_id,
        2,
        data_dir / done.source_path,
    )

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=4)
    _drain(worker, jobs)

    assert done.doc_id not in _batched(runner), "an extracted document was re-run"
    assert sorted(_batched(runner)) == sorted(
        j.doc_id for j in jobs if j.job_id != done.job_id
    )
    # It still reaches live off the output already on the share.
    assert [load_job(j.job_id).state for j in jobs] == ["live"] * 4


def test_a_batched_document_records_the_pages_it_completed(data_dir, ctx, runner):
    """So a job that resumes on the per-document path after a batch run knows
    its extraction is done and does not start MinerU again."""
    (job,) = _queue(data_dir, 1)
    _queue(data_dir, 1)                     # a mate, so a batch actually forms
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=2)
    _drain(worker, [job])

    assert load_job(job.job_id).completed_ranges == [[1, 2]]


def test_a_batch_run_is_journalled_as_progress(data_dir, ctx, runner):
    """The queue page has one line per job; a batched document must not sit at
    0% while twenty of its mates extract."""
    jobs = _queue(data_dir, 3)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, batch=3)
    _drain(worker, jobs)
    assert all(load_job(j.job_id).pct == 100 for j in jobs)


def test_the_write_phase_still_takes_the_corpus_lock(data_dir, ctx, runner,
                                                     monkeypatch):
    """Batching changes extraction only. The single-writer invariant is
    untouched: every write still happens under IngestLock, one at a time."""
    import ingest.worker as worker_mod

    real_write_doc = worker_mod.write_doc
    state = {"live": 0, "max_live": 0, "writes": 0, "lock_missing": 0}
    guard = threading.Lock()

    def probing_write_doc(*args, **kwargs):
        with guard:
            state["live"] += 1
            state["max_live"] = max(state["max_live"], state["live"])
            state["writes"] += 1
            if not (data_dir / LOCK_FILENAME).exists():
                state["lock_missing"] += 1
        try:
            time.sleep(0.02)
            return real_write_doc(*args, **kwargs)
        finally:
            with guard:
                state["live"] -= 1

    monkeypatch.setattr(worker_mod, "write_doc", probing_write_doc)

    jobs = _queue(data_dir, 6)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=2, batch=3)
    _drain(worker, jobs)

    assert state["writes"] == 6
    assert state["max_live"] == 1, "two workers wrote the corpus at once"
    assert state["lock_missing"] == 0, "a write happened without the corpus lock"
