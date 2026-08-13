"""The extract -> check -> fall back loop (spec T5).

No real extractor and no real corpus: the ladder is driven with a stub whose
per-rung output is scripted, which is the only way to exercise "rung 1 was
empty and rung 2 was fine" deterministically.

What is NOT faked, deliberately: the source file, `inspect_source`,
`ladder_for` and `coverage_ratio` all run for real against a PDF this module
generates. The scripted number is turned into that many characters of chunk
text, so the coverage the loop reads is genuinely measured rather than
handed to it -- a fake `coverage_ratio` would make every test here pass
against a loop that never measured anything.
"""
from __future__ import annotations

import pytest

from chunking.types import Chunk, ChunkProvenance
from ingest import worker
from ingest.coverage import source_text_chars
from ingest.jobs import new_job, save
from ingest.worker import WorkerContext
from store.config import data_dir

# One path, shared by the fixture that builds the job and the helper that
# writes the file, so the REAL `_ensure_source` resolves it.
SOURCE_REL = "uploads/ladder-source.pdf"


class FakeEmbedder:
    """Deterministic 8-dim vectors. Same shape the worker suite uses."""

    dim = 8

    def embed_batch(self, texts, *, input_type: str = "document"):
        return [[float(len(t) % 7)] + [0.0] * 7 for t in texts]


class _ScriptedLadder:
    """Returns a coverage ratio per extractor name, in call order."""

    def __init__(self, by_extractor):
        self.by_extractor = by_extractor
        self.calls = []

    def __call__(self, name):
        self.calls.append(name)
        return self.by_extractor[name]


# --- source files -----------------------------------------------------------


def _write_pdf(*, text: bool) -> "object":
    """A real PDF at the job's source path, with or without a text layer.

    The no-text-layer file is a genuinely blank page rather than a
    monkeypatched inspection result: it makes `inspect_source` return a
    POSITIVE `has_text_layer=False` and `coverage_ratio` return None for the
    real reason (no denominator), which is the exact pair the OCR rung and
    the `passed` rule are built around.
    """
    import fitz

    path = data_dir() / SOURCE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        page = doc.new_page()
        if text:
            for line in range(40):
                page.insert_text((40, 40 + line * 15), "budget " * 8)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _fake_chunks(job, count: int, total_chars: int) -> list[Chunk]:
    """`count` chunks whose text sums to exactly `total_chars` characters."""
    if count <= 0:
        return []
    per = total_chars // count
    lengths = [per] * count
    lengths[-1] += total_chars - per * count
    return [
        Chunk(
            chunk_id=f"{job.doc_id}-{i:04d}",
            doc_id=job.doc_id,
            text="x" * length,
            section_path=[],
            provenance=ChunkProvenance(page=1),
            fiscal_year=job.fiscal_year,
            doc_type=job.doc_type,
            publisher=job.publisher,
            token_count=max(1, length // 4),
        )
        for i, length in enumerate(lengths)
    ]


def _ctx(monkeypatch, scripted, *, has_text_layer=True, chunks=3):
    """A context whose extraction is scripted per rung.

    `_extract` records which rung ran and asks the script for its ratio;
    `_chunk` turns that ratio into real characters of chunk text against the
    real source file. Everything between them -- the ladder, the coverage
    measurement, the floor -- is the production code.
    """
    source = _write_pdf(text=has_text_layer)
    total = source_text_chars(source)
    pending: dict = {}

    def fake_extract(job, ctx, *, extractor=None, method=None):
        pending["ratio"] = scripted(method)

    def fake_chunk(job, ctx, *, extractor):
        ratio = pending.get("ratio")
        if chunks <= 0:
            return []
        # A blank source has no denominator, so the ratio is meaningless
        # there; any non-empty text stands for "OCR produced passages".
        target = 200 * chunks if ratio is None else round(ratio * total)
        return _fake_chunks(job, chunks, target)

    monkeypatch.setattr(worker, "_extract", fake_extract)
    monkeypatch.setattr(worker, "_chunk", fake_chunk)
    return WorkerContext(store=None, embedder=FakeEmbedder(), stamper=None)


def _capture_writes(monkeypatch) -> list:
    """Stand in for the corpus write and record every call.

    Returned rather than asserted on here so both directions are covered:
    the terminal-failure test asserts it stayed EMPTY and the accepted-scan
    test asserts it was called, which is what stops "no writes" passing
    vacuously because the stub was installed.
    """
    written: list = []
    monkeypatch.setattr(worker, "_write", lambda *a, **k: written.append(a))
    return written


@pytest.fixture()
def ladder_job(tmp_path, monkeypatch):
    """An AFR: the one real document this whole plan exists for.

    `afr` is also the only doc_type whose ladder has all three rungs, since
    it prefers OpenDataLoader and everything below it stays available.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    job = new_job(
        doc_id="agao-afr-fy2024",
        title="FY 2024 Annual Financial Report",
        corpus="budget",
        source_path=SOURCE_REL,
        source_sha256="ab" * 32,
        publisher="agao",
        doc_type="afr",
        fiscal_year=2024,
    )
    save(job)
    return job


# --- the ladder -------------------------------------------------------------


def test_a_document_that_passes_on_rung_one_never_runs_rung_two(monkeypatch, ladder_job):
    """The no-regression case, and the reason the ladder is safe to ship:
    a healthy document does exactly what it does today."""
    scripted = _ScriptedLadder({"opendataloader": 0.94, "mineru": 0.99})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert scripted.calls == ["opendataloader"]
    assert outcome.fell_back is False
    # abs= rather than the default relative tolerance: the ratio is realized
    # as a whole number of characters against a measured denominator, so it
    # lands within a character of the scripted value, not within 1e-6.
    assert outcome.coverage == pytest.approx(0.94, abs=1e-3)


def test_a_below_floor_first_rung_falls_back_and_the_second_wins(monkeypatch, ladder_job):
    """The FY2024 AFR: OpenDataLoader yields 2%, MinerU recovers it."""
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert scripted.calls == ["opendataloader", "mineru"]
    assert outcome.extractor == "mineru"
    assert outcome.fell_back is True
    assert [a["extractor"] for a in outcome.attempts] == ["opendataloader", "mineru"]


def test_the_best_attempt_is_kept_when_every_rung_is_below_the_floor(monkeypatch, ladder_job):
    """Keep the highest-scoring result, not the last one tried.

    Without this, a document whose OCR rung scores 1% would discard a
    MinerU attempt that scored 9% -- throwing away the better evidence a
    human is about to look at."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.02, "mineru": 0.09, "mineru-ocr": 0.01}
    )
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.extractor == "mineru"
    assert outcome.coverage == pytest.approx(0.09, abs=1e-3)
    assert len(outcome.attempts) == 3


def test_a_terminal_failure_never_reaches_live_and_writes_no_chunks(monkeypatch, ladder_job):
    """The whole point. A job that reports success while delivering nothing
    is worse than a job that fails."""
    written = _capture_writes(monkeypatch)
    scripted = _ScriptedLadder(
        {"opendataloader": 0.02, "mineru": 0.02, "mineru-ocr": 0.01}
    )

    job = worker.run_job(ladder_job, _ctx(monkeypatch, scripted))

    assert job.state == "failed"
    assert written == []
    assert len(job.extraction_attempts) == 3
    # `job.error`, NOT `stage_detail`: `advance(job, "failed")` REQUIRES an
    # error message and raises ValueError without one (jobs.py:307). A
    # message written only to stage_detail would leave `error` empty on the
    # one screen that exists to explain the failure.
    assert job.error
    assert "2%" in job.error


def test_no_text_layer_routes_straight_to_ocr(monkeypatch, ladder_job):
    scripted = _ScriptedLadder({"mineru-ocr": 0.88})
    outcome = worker._extract_and_chunk(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False)
    )
    assert scripted.calls == ["mineru-ocr"]
    assert outcome.fell_back is False


def test_a_rung_that_CRASHES_falls_through_to_the_next(monkeypatch, ladder_job):
    """The likeliest real trigger, and the half "resilient" was missing.

    A malformed PDF makes an extractor raise; without this the exception
    takes the job down with no rung 2, which is the same silent-ish dead end
    the ladder exists to remove. The crash is recorded as an attempt so the
    admin panel can show WHY a rung was abandoned.
    """
    def scripted(name):
        if name == "opendataloader":
            raise RuntimeError("pdfium: Data format error")
        return 0.91

    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.extractor == "mineru"
    assert outcome.attempts[0]["extractor"] == "opendataloader"
    assert outcome.attempts[0]["coverage"] is None
    assert "Data format error" in outcome.attempts[0]["error"]


def test_every_rung_crashing_is_a_terminal_failure_not_a_traceback(
    monkeypatch, ladder_job
):
    def boom(name):
        raise RuntimeError("nope")

    job = worker.run_job(ladder_job, _ctx(monkeypatch, boom))
    assert job.state == "failed"
    assert job.error


def test_an_ocr_run_that_produces_NOTHING_is_not_treated_as_success(
    monkeypatch, ladder_job
):
    """A scan has no text layer, so coverage has no denominator and returns
    None. None must not mean "pass" unconditionally -- otherwise a scanned
    PDF whose OCR produced zero passages is written live and empty, which is
    precisely the silent-empty failure this plan exists to kill, for exactly
    the document class the OCR rung serves.
    """
    written = _capture_writes(monkeypatch)
    scripted = _ScriptedLadder({"mineru-ocr": None})  # no denominator, 0 chunks
    job = worker.run_job(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False, chunks=0)
    )
    assert job.state == "failed"
    assert written == []


def test_a_scan_that_DOES_produce_passages_is_accepted(monkeypatch, ladder_job):
    """The other side of the same rule -- an unmeasurable document that
    plainly worked must not be rejected for being unmeasurable."""
    written = _capture_writes(monkeypatch)
    scripted = _ScriptedLadder({"mineru-ocr": None})
    job = worker.run_job(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False, chunks=140)
    )
    assert job.state == "live"
    assert written, "an accepted document was never written to the corpus"


def test_the_chunker_is_told_WHICH_rung_produced_the_output(monkeypatch, ladder_job):
    """The seam a review caught: `_chunk` used to derive the reader from the
    doc_type's DEFAULT extractor, so a job that fell back to MinerU would
    parse MinerU output with the OpenDataLoader reader."""
    seen = []
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    ctx = _ctx(monkeypatch, scripted)
    # Wrap, don't replace: a replacement returning [] would make every rung
    # score zero and the ladder would run all three, so the assertion below
    # would be measuring the stub instead of the fallback.
    inner = worker._chunk
    monkeypatch.setattr(
        worker,
        "_chunk",
        lambda job, ctx, extractor: seen.append(extractor)
        or inner(job, ctx, extractor=extractor),
    )

    worker._extract_and_chunk(ladder_job, ctx)

    assert seen == ["opendataloader", "mineru"]


# --- what the loop records, and what it re-runs ------------------------------


def test_a_coverage_the_source_cannot_measure_is_not_a_failure(monkeypatch, ladder_job):
    """An unreadable SOURCE is a measurement failure, not an extraction one.

    The floor rejects; it never approves. If the denominator cannot be read
    -- a PDF PyMuPDF refuses, a format with no text-layer reader -- the
    check has learned nothing and must not hold the document out of search
    on the strength of that.
    """
    (data_dir() / SOURCE_REL).parent.mkdir(parents=True, exist_ok=True)
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted)
    # Replace the good file with bytes no text-layer reader can open.
    (data_dir() / SOURCE_REL).write_bytes(b"%PDF-1.4\nnot really a pdf\n")

    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.coverage is None
    assert outcome.passed is True
    assert outcome.attempts[0]["coverage_error"]


def test_a_rung_already_recorded_is_not_extracted_again(monkeypatch, ladder_job):
    """`extraction_attempts` is the resume marker for which rung we reached.

    A reboot during embedding must not re-run an extraction that already
    finished -- that is hours on an office machine, and the output is on the
    share where the chunker can still read it.
    """
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted)
    ladder_job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": 0.94, "chunks": 3}
    ]

    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == []      # nothing was extracted a second time
    assert outcome.extractor == "opendataloader"
    assert outcome.passed is True    # ...but it was re-chunked and re-measured


def test_a_rung_that_crashed_before_is_not_retried_on_resume(monkeypatch, ladder_job):
    """And it is not chunked either: there is no output to read."""
    scripted = _ScriptedLadder({"mineru": 0.93})
    ctx = _ctx(monkeypatch, scripted)
    ladder_job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": None, "chunks": 0,
         "error": "RuntimeError: pdfium: Data format error"}
    ]

    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["mineru"]
    assert [a["extractor"] for a in outcome.attempts] == ["opendataloader", "mineru"]


def test_moving_to_a_new_rung_clears_the_completed_page_ranges(monkeypatch, ladder_job):
    """`completed_ranges` is scoped to ONE rung's output directory.

    Carrying it forward makes the next rung skip pages it has never
    extracted, producing a partial document that then fails coverage for a
    reason that has nothing to do with the extractor.
    """
    seen_ranges = []
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    ctx = _ctx(monkeypatch, scripted)
    inner = worker._extract

    def recording_extract(job, ctx, *, extractor=None, method=None):
        seen_ranges.append(list(job.completed_ranges))
        inner(job, ctx, extractor=extractor, method=method)
        job.completed_ranges = [[1, 191]]

    monkeypatch.setattr(worker, "_extract", recording_extract)

    worker._extract_and_chunk(ladder_job, ctx)

    assert seen_ranges == [[], []]


def test_the_attempts_are_journalled_as_they_happen(monkeypatch, ladder_job):
    """Persisted per rung, not at the end: a machine that dies during rung 2
    must not come back believing rung 1 was never tried."""
    from ingest.jobs import load_job

    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    ctx = _ctx(monkeypatch, scripted)
    inner = worker._chunk
    seen_on_disk = []

    def peeking_chunk(job, ctx, *, extractor):
        seen_on_disk.append(
            [a["extractor"] for a in load_job(job.job_id).extraction_attempts]
        )
        return inner(job, ctx, extractor=extractor)

    monkeypatch.setattr(worker, "_chunk", peeking_chunk)

    worker._extract_and_chunk(ladder_job, ctx)

    # Rung 2 chunks only after rung 1's attempt is already on disk.
    assert seen_on_disk == [[], ["opendataloader"]]
