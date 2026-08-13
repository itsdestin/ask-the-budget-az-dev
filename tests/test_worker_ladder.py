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


def _fake_chunks(job, count: int, total_chars: int, *, filler: str = "x") -> list[Chunk]:
    """`count` chunks whose text sums to exactly `total_chars` characters.

    `filler` decides whether those characters are LETTERS (the default --
    a structurally healthy reading) or DIGITS, which is how a rung is
    scripted to trip the structure ceiling. The chunk text is real text
    measured by the real `unlabelled_fraction`, not a handed-in score.
    """
    if count <= 0:
        return []
    per = total_chars // count
    lengths = [per] * count
    lengths[-1] += total_chars - per * count
    return [
        Chunk(
            chunk_id=f"{job.doc_id}-{i:04d}",
            doc_id=job.doc_id,
            text=filler * length,
            section_path=[],
            provenance=ChunkProvenance(page=1),
            fiscal_year=job.fiscal_year,
            doc_type=job.doc_type,
            publisher=job.publisher,
            token_count=max(1, length // 4),
        )
        for i, length in enumerate(lengths)
    ]


def _ctx(monkeypatch, scripted, *, has_text_layer=True, chunks=12, bare=()):
    """A context whose extraction is scripted per rung.

    `_extract` records which rung ran and asks the script for its ratio;
    `_chunk` turns that ratio into real characters of chunk text against the
    real source file. Everything between them -- the ladder, the coverage
    measurement, the floor -- is the production code.

    `bare` names the rungs whose chunk text is digits rather than letters,
    i.e. the rungs scripted to trip the structure ceiling.
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
        filler = "7" if extractor in bare else "x"
        return _fake_chunks(job, chunks, target, filler=filler)

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
    # error message and raises ValueError without one (see the
    # `new_state == "failed"` branch in `ingest/jobs.py::advance`). A
    # message written only to stage_detail would leave `error` empty on the
    # one screen that exists to explain the failure.
    assert job.error
    assert "2%" in job.error
    # This IS the ladder losing -- every rung scored below the floor -- so
    # the admin-panel marker must be set. See ingest/jobs.py::held_out and
    # Blocking 1 of this plan's final review for why this can't be inferred
    # from `extraction_attempts` alone.
    assert job.held_out is True


def test_run_job_records_which_rung_was_kept_on_success(monkeypatch, ladder_job):
    """Catches deleting `job.kept_extractor = outcome.extractor` from
    `run_job` (ingest/worker.py). Without that line a document whose
    extractor changed -- every passage id re-minted, every chunk's text
    replaced -- would leave no trace of which rung actually wrote it, and
    the admin page (and the ranking behaviour built on this field) would
    have nothing to read."""
    _capture_writes(monkeypatch)
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})

    job = worker.run_job(ladder_job, _ctx(monkeypatch, scripted))

    assert job.state == "live"
    assert job.kept_extractor == "mineru"


def test_a_document_held_out_of_search_records_no_kept_extractor(
    monkeypatch, ladder_job
):
    """Nothing was written for a held-out document, so nothing should be
    named as having written it -- `kept_extractor` describes what's on
    disk, and for this job that's still nothing."""
    written = _capture_writes(monkeypatch)
    scripted = _ScriptedLadder(
        {"opendataloader": 0.02, "mineru": 0.02, "mineru-ocr": 0.01}
    )

    job = worker.run_job(ladder_job, _ctx(monkeypatch, scripted))

    assert job.state == "failed"
    assert written == []
    assert job.kept_extractor is None


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


def test_a_cancel_during_a_rung_stops_the_ladder_and_is_not_recorded_as_a_crash(
    monkeypatch, ladder_job
):
    """`JobCancelled` is a cancel, not a crashed rung -- it must propagate
    past the `except Exception` handler above, not be swallowed by it.

    This is the one exception type that must NOT fall through to the next
    rung. Reviewed with a throwaway probe: with the `except JobCancelled:
    raise` line in place, a cancel during rung 1 stops the ladder here; strip
    that line and the cancel is caught by the generic handler, filed as a
    crashed attempt, and rungs 2 and 3 run anyway -- potentially hours of
    MinerU on a document the user already gave up on, plus fabricated crash
    entries in `extraction_attempts`.
    """
    calls: list[str] = []

    def scripted(name):
        calls.append(name)
        raise worker.JobCancelled("user cancelled")

    with pytest.raises(worker.JobCancelled):
        worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert calls == ["opendataloader"], "rung 2 must never run after a cancel"
    assert ladder_job.extraction_attempts == [], "a cancel is not a crashed attempt"


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


def test_every_rung_that_runs_records_its_unlabelled_fraction(
    monkeypatch, ladder_job
):
    """Spec X11. Recorded for a rung that PASSES too, not only a loser --
    the near-miss band is the only path out of "calibrated against one
    example", and a threshold that never records its inputs can only be
    re-argued, never re-tuned."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.unlabelled == 0.0
    assert outcome.attempts[0]["unlabelled"] == 0.0


def test_a_rung_with_too_few_judged_chunks_records_None_not_zero(
    monkeypatch, ladder_job
):
    """None means "not measured". Zero would claim a perfect reading."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted, chunks=3)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.unlabelled is None
    assert outcome.attempts[0]["unlabelled"] is None


def test_a_document_with_unmeasured_structure_still_short_circuits(
    monkeypatch, ladder_job
):
    """`unlabelled is None` must NOT be treated as tripped. A one-character
    edit that flips `tripped`'s `is not None` to `is None` (or drops it)
    leaves every ladder test here green but sends every document with fewer
    than MIN_JUDGED_CHUNKS judgeable passages -- roughly 5,200 of the 7,434
    documents in the live corpus, per `ingest/structure.py` -- through every
    remaining rung for nothing. Reproduced against that exact mutation: the
    same script that calls only `opendataloader` here calls
    `opendataloader`, `mineru`, `mineru-ocr` under it."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.94, "mineru": 0.99, "mineru-ocr": 0.99}
    )
    ctx = _ctx(monkeypatch, scripted, chunks=3)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.unlabelled is None
    assert scripted.calls == ["opendataloader"]


# --- X4: a passing-but-tripped rung must not short-circuit -----------------


def test_a_document_over_the_ceiling_advances_to_the_next_rung(
    monkeypatch, ladder_job
):
    """Spec X4. FY2024's exact shape: rung 1 passes on VOLUME and is
    structurally useless, so the ladder keeps going instead of stopping."""
    scripted = _ScriptedLadder({"opendataloader": 0.49, "mineru": 0.4477})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls[:2] == ["opendataloader", "mineru"]
    assert outcome.extractor == "mineru"
    assert outcome.passed


def test_a_tripped_document_with_nothing_better_is_STILL_WRITTEN(
    monkeypatch, ladder_job
):
    """🔴 The regression guard for the worst way this change goes wrong.

    Every rung trips the ceiling, so the loop reaches its end with no
    untripped winner. The document must still be WRITTEN -- a degraded
    reading that is the best available reading is still the best available
    reading. If this returns a failing outcome, `run_job` hides the
    document from search, and an analyst who could previously find its
    figures (badly labelled) can now find nothing at all."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.49, "mineru": 0.45, "mineru-ocr": 0.44}
    )
    ctx = _ctx(
        monkeypatch, scripted, chunks=20,
        bare=("opendataloader", "mineru", "mineru-ocr"),
    )
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.passed, "a tripped document must not be held out of search"
    # All three land in the band together (each >= 0.75 * 0.49): tied on
    # unlabelled (all 1.0, everything bare), so the -coverage tie-break
    # inside the band picks the highest-coverage rung, not a band-empty
    # fallback.
    assert outcome.extractor == "opendataloader"
    assert len(outcome.attempts) == 3


def test_structure_picks_the_winner_among_comparable_attempts(
    monkeypatch, ladder_job
):
    """The real measured pair. Coverage prefers OpenDataLoader (49.03% vs
    44.77%) because a third of its text is the bare digit runs; structure
    prefers MinerU, and structure is right."""
    scripted = _ScriptedLadder({"opendataloader": 0.4903, "mineru": 0.4477})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.extractor == "mineru"
    assert outcome.unlabelled == 0.0


def test_a_clean_attempt_that_collapsed_in_SIZE_does_not_win(
    monkeypatch, ladder_job
):
    """The silent quarter-document guard, end to end. 0.12/0.49 = 0.24 is
    far outside the 0.75 band, so the tripped-but-complete reading is
    kept."""
    scripted = _ScriptedLadder({"opendataloader": 0.49, "mineru": 0.12})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.extractor == "opendataloader"


def test_a_healthy_document_still_short_circuits(monkeypatch, ladder_job):
    """What keeps 2,227 of 2,228 documents paying exactly what they pay
    today. Fails if X4 is written as "always run every rung"."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted, chunks=20)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["opendataloader"]
    assert outcome.extractor == "opendataloader"
