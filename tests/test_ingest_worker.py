"""Tests for ingest/worker.py.

No models and no MinerU: a fake extractor writes MinerU-shaped per-page JSON
and a fake 8-dim embedder stands in for arctic-embed-m, so the whole
extract → chunk → embed → write pipeline runs in milliseconds.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ingest.jobs import advance, load_job, new_job, save
from ingest.worker import (
    SNAPSHOT_ENV_VAR,
    SNAPSHOT_OFF,
    SNAPSHOT_PER_DOC,
    IngestWorker,
    JobCancelled,
    WorkerContext,
    run_job,
)
from store.backup import list_snapshots
from store.chunk_store import ChunkStore

PAGE_BLOCKS = [
    {"type": "text", "text_level": 1, "text": "AHCCCS"},
    {"type": "text", "text": "Appropriations to AHCCCS increase in FY 2027."},
    {
        "type": "table",
        "table_body": (
            "<table><tr><td>Agency</td><td>FY 2027</td></tr>"
            "<tr><td>AHCCCS</td><td>1,000,000</td></tr>"
            "<tr><td>Public Safety, Department of</td><td>800,000</td></tr>"
            "</table>"
        ),
    },
]


class FakeExtractor:
    """Writes the per-page contract without running MinerU."""

    name = "mineru"

    def __init__(self, pages: int = 2) -> None:
        self.pages = pages
        self.calls = 0

    def get_version(self) -> str:
        return "fake-1.0"

    def extract(self, *, source_path: Path, output_dir: Path, pages) -> None:
        self.calls += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        for page in range(1, self.pages + 1):
            (output_dir / f"page-{page}.json").write_text(
                json.dumps({
                    "extractor": "mineru-fake",
                    "source_pdf": str(source_path),
                    "page": page,
                    "blocks": PAGE_BLOCKS,
                }),
                encoding="utf-8",
            )


class FakeEmbedder:
    """Deterministic 8-dim vectors; records how it was called."""

    dim = 8

    def __init__(self) -> None:
        self.batches: list[int] = []
        self.input_types: list[str] = []

    def embed_batch(self, texts, *, input_type: str = "document"):
        self.batches.append(len(texts))
        self.input_types.append(input_type)
        return [[float(len(t) % 7)] + [0.0] * 7 for t in texts]


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def ctx(data_dir):
    from chunking.entity_stamper import EntityStamper

    return WorkerContext(
        store=ChunkStore(root=data_dir, dim=8),
        embedder=FakeEmbedder(),
        stamper=EntityStamper.from_default_paths(fund_catalog_path=None),
        extractor=FakeExtractor(),
    )


@pytest.fixture()
def job(data_dir):
    source = data_dir / "uploads" / "ab" / f"{'ab' * 32}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n")
    j = new_job(
        doc_id="jlbc-baseline-fy2027-axs",
        title="FY 2027 Baseline — AHCCCS",
        corpus="budget",
        source_path=str(source.relative_to(data_dir)),
        source_sha256="ab" * 32,
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2027,
    )
    save(j)
    return j


# --- happy path -------------------------------------------------------------


def test_run_job_reaches_live_and_is_searchable(job, ctx, data_dir):
    run_job(job, ctx)
    assert job.state == "live"
    assert ctx.store.count("budget_chunks") > 0
    assert ctx.store.fts_search("budget_chunks", "appropriations", top_k=5)
    docs = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    assert docs["jlbc-baseline-fy2027-axs"]["title"] == "FY 2027 Baseline — AHCCCS"


def test_documents_json_records_the_extraction_method_and_coverage(job, ctx, data_dir):
    """Plan B Task 5, wired end to end through the REAL `_write` -> `write_doc`
    call (not the ladder suite's stubbed `_write`, which never reaches
    documents.json at all).

    `coverage` is `None` here, not a measured number -- this fixture's source
    is a 9-byte placeholder (`b"%PDF-1.4\\n"`), which PyMuPDF cannot open as a
    real PDF, so the denominator in `ingest/coverage.py::source_text_chars`
    is unreadable. That is the correct, unmeasurable-but-accepted outcome
    (see `ExtractionOutcome.passed`), not a bug in this test -- confirmed by
    running this exact fixture shape and reading back what it actually wrote
    before pinning the value here.
    """
    run_job(job, ctx)
    docs = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    assert docs["jlbc-baseline-fy2027-axs"]["extraction"] == {
        "method": "mineru",
        "coverage": None,
        "attempts": 1,
        "fell_back": False,
    }


def test_write_phase_snapshots_before_touching_the_corpus(job, ctx):
    run_job(job, ctx)
    assert list_snapshots()  # S17: a restore point exists


def test_a_jobs_stage_reaches_the_stored_document_title(data_dir, ctx):
    # This is the wiring correction that made the stage field worth adding:
    # job.stage must reach documents.json's title, or the AI Mode prompt's
    # "Engrossed supersedes Introduced" rule has nothing to read from a
    # retrieved chunk (doc_title is the only stage-carrying field on one).
    source = data_dir / "uploads" / "cd" / f"{'cd' * 32}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n")
    j = new_job(
        doc_id="jlbc-budget-bill-summary-fy2027-hb2001",
        title="FY 2027 Budget Bill Summary",
        corpus="budget",
        source_path=str(source.relative_to(data_dir)),
        source_sha256="cd" * 32,
        publisher="jlbc",
        doc_type="budget-bill-summary",
        fiscal_year=2027,
        stage="engrossed",
    )
    save(j)

    run_job(j, ctx)

    docs = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    assert docs["jlbc-budget-bill-summary-fy2027-hb2001"]["title"] \
        .endswith("(Engrossed)")


# --- bulk-ingest mode (JLBC_INGEST_SNAPSHOT) --------------------------------
#
# The whole point of these tests is that the DEFAULT never changes: a future
# maintainer must not be able to lose S17 snapshot protection by accident.


def test_snapshot_is_on_when_the_env_var_is_unset(job, ctx, monkeypatch):
    """Default path — no env var at all — still snapshots every document."""
    monkeypatch.delenv(SNAPSHOT_ENV_VAR, raising=False)
    run_job(job, ctx)
    assert list_snapshots()


def test_snapshot_is_on_when_the_env_var_says_per_doc(job, ctx, monkeypatch):
    monkeypatch.setenv(SNAPSHOT_ENV_VAR, SNAPSHOT_PER_DOC)
    run_job(job, ctx)
    assert list_snapshots()


def test_snapshot_is_suppressed_when_the_env_var_says_off(job, ctx, monkeypatch):
    """Bulk backfill: zipping a growing corpus once per document is O(n²)."""
    monkeypatch.setenv(SNAPSHOT_ENV_VAR, SNAPSHOT_OFF)
    run_job(job, ctx)
    assert list_snapshots() == []
    assert job.state == "live"                    # the ingest itself is unaffected
    assert ctx.store.count("budget_chunks") > 0


def test_an_unrecognised_env_value_keeps_snapshots_on(job, ctx, monkeypatch):
    """Fail safe: only the exact word `off` may disable the safety net, so a
    typo (`JLBC_INGEST_SNAPSHOT=false`) can't silently drop protection."""
    monkeypatch.setenv(SNAPSHOT_ENV_VAR, "false")
    run_job(job, ctx)
    assert list_snapshots()


def test_suppression_is_announced_once_per_document(job, ctx, monkeypatch, capsys):
    monkeypatch.setenv(SNAPSHOT_ENV_VAR, SNAPSHOT_OFF)
    run_job(job, ctx)
    err = capsys.readouterr().err
    assert "JLBC_INGEST_SNAPSHOT=off" in err
    assert "snapshot suppressed" in err.lower()
    assert "external archive" in err.lower()


def test_suppression_is_announced_when_the_worker_starts(ctx, monkeypatch, capsys):
    """Loud at startup too — the operator must know before the run, not after."""
    monkeypatch.setenv(SNAPSHOT_ENV_VAR, SNAPSHOT_OFF)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    err = capsys.readouterr().err
    assert "JLBC_INGEST_SNAPSHOT=off" in err
    assert "snapshot suppressed" in err.lower()


def test_worker_start_is_silent_on_the_default_path(ctx, monkeypatch, capsys):
    monkeypatch.delenv(SNAPSHOT_ENV_VAR, raising=False)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    assert SNAPSHOT_ENV_VAR not in capsys.readouterr().err


def test_chunk_text_is_embedded_as_a_document_not_a_query(job, ctx):
    """Asymmetric model: embedding passages with the query instruction
    silently degrades every future search against this document."""
    run_job(job, ctx)
    assert set(ctx.embedder.input_types) == {"document"}


def test_table_chunks_carry_every_named_agency(job, ctx):
    """D2 end-to-end: the writer receives resolve_all's list for tables."""
    run_job(job, ctx)
    rows = ctx.store.scan("budget_chunks", ["is_table", "agency_canonical_ids"])
    table_rows = [r for r in rows if r["is_table"]]
    assert table_rows
    assert any(len(r["agency_canonical_ids"]) > 1 for r in table_rows)


def test_source_file_is_copied_into_the_shared_pdfs_dir(job, ctx, data_dir):
    """The PDF viewer streams from <data_dir>/pdfs; an upload that stayed in
    uploads/ would be searchable but not viewable."""
    run_job(job, ctx)
    expected = data_dir / "pdfs" / "ab" / f"{'ab' * 32}.pdf"
    assert expected.is_file()
    docs = json.loads((data_dir / "documents.json").read_text(encoding="utf-8"))
    assert docs["jlbc-baseline-fy2027-axs"]["source_blob_path"] == \
        "pdfs/ab/" + "ab" * 32 + ".pdf"


def test_extractor_output_lands_on_the_share_for_cross_machine_resume(
    job, ctx, data_dir
):
    """Still on the share, now under the RUNG that produced it: two attempts
    on one document must never write into the same directory, or the chunker
    reads a mixture of the two with nothing recording which is which."""
    run_job(job, ctx)
    assert (
        data_dir / "extractor-output" / job.doc_id / "mineru" / "page-1.json"
    ).is_file()


def doc_id_of_output_dir(output_dir: Path) -> str:
    """The doc_id an extractor's output directory belongs to.

    Output is rung-scoped (`extractor-output/<doc_id>/<rung>/`) but a
    directory written before rungs existed has no suffix, so this walks up to
    whichever directory is the child of `extractor-output` rather than
    assuming a depth. Used by the fakes in the parallel suite, which
    identify a document by where it was asked to write.
    """
    path = Path(output_dir)
    while path.parent.name and path.parent.name != "extractor-output":
        path = path.parent
    return path.name


def test_progress_is_journalled_during_the_run(job, ctx):
    run_job(job, ctx)
    assert load_job(job.job_id).pct == 100


def test_a_fresh_job_extracts_into_a_rung_scoped_directory(job, data_dir):
    from ingest import worker

    assert worker._extract_dir(job, "mineru") == (
        data_dir / "extractor-output" / job.doc_id / "mineru"
    )


def test_output_written_before_rungs_existed_is_still_found(job, data_dir):
    """Thousands of jobs on the share have un-suffixed output. An interrupted
    overnight book must resume from it, not re-extract from page 1 — but only
    the extractor that WROTE it may claim it, or a MinerU fallback would be
    pointed at a directory full of OpenDataLoader pages."""
    from ingest import worker

    base = data_dir / "extractor-output" / job.doc_id
    base.mkdir(parents=True)
    (base / "page-1.json").write_text("{}", encoding="utf-8")

    # baseline-per-agency declares `mineru`, so `mineru` wrote this.
    assert worker._extract_dir(job, "mineru") == base
    # A later rung gets its own directory even so.
    assert worker._extract_dir(job, "mineru-ocr") == base / "mineru-ocr"


def test_the_ocr_rung_runs_mineru_in_ocr_mode(data_dir, monkeypatch):
    """`MineruRunner` takes MinerU's `-m` flag at CONSTRUCTION, and the worker
    builds the runner itself rather than going through `dispatcher.extract` —
    so a rung that failed to pass its method through would run byte-identical
    work to the rung that already came back empty, under a different name."""
    import fitz

    from ingest import dispatcher, worker

    source = data_dir / "uploads" / "ef" / f"{'ef' * 32}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page()
    doc.save(str(source))
    doc.close()

    j = new_job(
        doc_id="agao-afr-fy2024", title="scan", corpus="budget",
        source_path=str(source.relative_to(data_dir)), source_sha256="ef" * 32,
        publisher="agao", doc_type="afr", fiscal_year=2024,
    )
    save(j)

    built: list[str] = []

    class FakeRunner:
        def __init__(self, *args, method: str = "auto", **kwargs) -> None:
            built.append(method)

        def run(self, **kwargs):
            return []

        def cancel(self) -> None:  # pragma: no cover - never reached here
            pass

    monkeypatch.setattr(worker, "MineruRunner", FakeRunner)
    ctx = WorkerContext(store=None, embedder=None, stamper=None)

    worker._extract(
        j, ctx,
        extractor=dispatcher.pick_named("mineru-ocr"),
        method="mineru-ocr",
    )
    worker._extract(
        j, ctx, extractor=dispatcher.pick_named("mineru"), method="mineru"
    )

    assert built == ["ocr", "auto"]


# --- resume -----------------------------------------------------------------


def test_a_job_that_failed_at_embedding_does_not_re_extract(job, ctx):
    """Extraction is the hours-long stage; everything after it is minutes and
    is re-derived from the extractor output on the share."""
    run_job(job, ctx)
    first_calls = ctx.extractor.calls

    resumed = load_job(job.job_id)
    resumed.state = "embedding"
    save(resumed)
    run_job(resumed, ctx)

    assert resumed.state == "live"
    assert ctx.extractor.calls == first_calls  # no re-extraction


def test_reingest_replaces_rather_than_duplicates(job, ctx):
    run_job(job, ctx)
    count = ctx.store.count("budget_chunks")
    again = new_job(
        doc_id=job.doc_id, title=job.title, corpus="budget",
        source_path=job.source_path, source_sha256=job.source_sha256,
        publisher="jlbc", doc_type="baseline-per-agency", fiscal_year=2027,
    )
    save(again)
    run_job(again, ctx)
    assert ctx.store.count("budget_chunks") == count


# --- cancel + failure -------------------------------------------------------


def test_cancel_between_stages_leaves_no_rows(job, ctx):
    advance(job, "cancelled")
    with pytest.raises(JobCancelled):
        run_job(job, ctx)
    assert ctx.store.count("budget_chunks") == 0


def test_failure_lands_in_job_error_verbatim(job, ctx):
    class Boom(FakeExtractor):
        def extract(self, **kwargs):
            raise RuntimeError("mineru CLI failed: model weights not found")

    ctx.extractor = Boom()
    worker = IngestWorker(ctx=ctx)
    worker.run_one(job)
    reloaded = load_job(job.job_id)
    assert reloaded.state == "failed"
    assert "model weights not found" in reloaded.error


def test_a_failed_job_does_not_kill_the_worker_thread(job, ctx, data_dir):
    class Boom(FakeExtractor):
        def extract(self, **kwargs):
            raise RuntimeError("boom")

    ctx.extractor = Boom()
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "failed")
        ctx.extractor = FakeExtractor()
        good = new_job(
            doc_id="jlbc-baseline-fy2027-dps", title="t", corpus="budget",
            source_path=job.source_path, source_sha256="cd" * 32,
            publisher="jlbc", doc_type="baseline-per-agency", fiscal_year=2027,
        )
        save(good)
        _wait_for(lambda: load_job(good.job_id).state == "live")
    finally:
        worker.stop()


# --- worker loop ------------------------------------------------------------


def test_worker_picks_up_queued_jobs(job, ctx):
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "live")
    finally:
        worker.stop()


def test_worker_resumes_this_machines_unfinished_jobs_at_startup(job, ctx):
    advance(job, "extracting")   # simulates a crash mid-extraction
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "live")
    finally:
        worker.stop()


def test_claiming_stamps_this_machine_on_the_job(job, ctx):
    import socket
    job.machine = "SOMEONE-ELSES-PC"
    save(job)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "live")
    finally:
        worker.stop()
    assert load_job(job.job_id).machine == socket.gethostname()


def _wait_for(predicate, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")
