"""GET /api/admin/attention — Plan B Task 7.

The panel this route feeds exists because a document can report `live` with
almost nothing in it (the FY2024 AFR: 20 passages from 191 pages, queue
green, an analyst searching gets nothing — see ingest/coverage.py). T5's
extraction ladder now HOLDS such a document out of search instead of
writing it, and this route is the human surface for that: which documents
were held back, and what was tried.

No new job state exists here. A held-back document is an ordinary `failed`
job with `job.held_out` set; [Try again] is the existing retry
(`POST /api/jobs/{id}/retry`), [Dismiss] is the existing cancel
(`POST /api/jobs/{id}/cancel`). This file only has to prove the LISTING
gets the right jobs onto the panel and leaves everyone else off it.

The filter is `held_out`, an explicit marker set in exactly one place
(`ingest/worker.py::run_job`, the branch that decided every rung lost) —
NOT `extraction_attempts`, which was tried first and found wrong (Blocking
1, this plan's final review): that list is journalled after every rung
INCLUDING a winning one, so a job that passed extraction and then crashed
at embed/write/lock also carries a non-empty `extraction_attempts`, and
would have shown up here as "held out" with a raw traceback for its
sentence.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import (
    ProviderConfig,
    Settings,
    reset_settings_cache,
    save_settings,
)
from ingest.jobs import advance, new_job, save
from ingest.structure import MAX_UNLABELLED

ADMIN = "Destin"
ANALYST = "analyst1"

# The exact fixture from tests/test_worker_ladder.py's
# test_a_terminal_failure_never_reaches_live_and_writes_no_chunks and
# STATUS.md's real FY2024 AFR incident — not invented numbers.
HELD_BACK_ATTEMPTS = [
    {"extractor": "opendataloader", "coverage": 0.02, "chunks": 20},
    {"extractor": "mineru", "coverage": 0.02, "chunks": 20},
    {"extractor": "mineru-ocr", "coverage": 0.01, "chunks": 10},
]
HELD_BACK_MESSAGE = (
    "Held out of search — only 2% of this document's text produced any "
    "content, after 3 extraction methods were tried."
)


@pytest.fixture(autouse=True)
def _share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        admin_username=ADMIN,
    ))
    reset_settings_cache()
    yield tmp_path
    reset_settings_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def _held_back_job(title: str = "AGAO Annual Financial Report FY2024"):
    """A job that failed AFTER the ladder ran and lost every rung."""
    job = new_job(
        doc_id="agao-afr-fy2024", title=title, corpus="budget",
        source_path="afr24.pdf", source_sha256="a" * 64, publisher="agao",
        doc_type="afr", fiscal_year=2024,
    )
    job.extraction_attempts = list(HELD_BACK_ATTEMPTS)
    job.held_out = True
    save(job)
    advance(job, "failed", error=HELD_BACK_MESSAGE)
    return job


def _ordinary_crash():
    """A `failed` job the ladder never reached — no attention here."""
    job = new_job(
        doc_id="d2", title="A bill", corpus="budget",
        source_path="x.docx", source_sha256="b" * 64, publisher="leg",
        doc_type="budget-bill", fiscal_year=2027,
    )
    save(job)
    advance(job, "failed", error="Connection reset while downloading the source.")
    return job


def _crash_after_a_passing_extraction():
    """The hard half of Blocking 1: a document whose extraction PASSED (one
    high-scoring attempt is journalled) but a LATER stage -- embedding,
    writing, losing the ingest-lock race -- crashed. `extraction_attempts`
    is non-empty, exactly the shape that made the old `extraction_attempts`
    filter mislabel it, but `held_out` was never set: the ladder did not
    lose, it never got the chance to."""
    job = new_job(
        doc_id="jlbc-baseline-fy2027-dps", title="A baseline book",
        corpus="budget", source_path="dps.pdf", source_sha256="c" * 64,
        publisher="jlbc", doc_type="baseline-per-agency", fiscal_year=2027,
    )
    job.extraction_attempts = [
        {"extractor": "mineru", "coverage": 0.94, "chunks": 500},
    ]
    save(job)
    advance(job, "failed", error="RuntimeError: lost the corpus lock after 1800s")
    return job


def _attention(client) -> dict:
    return client.get("/api/admin/attention").json()


# ---------------------------------------------------------------------------
# The listing itself
# ---------------------------------------------------------------------------


def test_attention_lists_a_held_back_document_with_what_was_tried(client):
    _held_back_job()

    docs = _attention(client)["documents"]

    assert len(docs) == 1
    doc = docs[0]
    assert doc["title"] == "AGAO Annual Financial Report FY2024"
    assert doc["best_coverage"] == pytest.approx(0.02)
    # HELD_BACK_ATTEMPTS predates the `unlabelled` field, so `.get()`
    # reads None for all three rather than 500ing the page.
    assert doc["attempts"] == [
        {"extractor": "opendataloader", "coverage": pytest.approx(0.02),
         "unlabelled": None},
        {"extractor": "mineru", "coverage": pytest.approx(0.02),
         "unlabelled": None},
        {"extractor": "mineru-ocr", "coverage": pytest.approx(0.01),
         "unlabelled": None},
    ]
    # The job's OWN sentence, not a rebuilt one — see ingest/worker.py's
    # `_held_out_message`, which is the one place calibrated to say what was
    # measured and never that anything was verified or checked.
    assert doc["message"] == HELD_BACK_MESSAGE


def test_an_ordinary_crash_is_not_a_needs_attention_document(client):
    """A failed job with no extraction_attempts is a crash, not a held-back
    document, and belongs on the queue where it already is."""
    _ordinary_crash()

    assert _attention(client)["documents"] == []


def test_a_crash_after_a_passing_extraction_is_not_a_needs_attention_document(client):
    """The HARD half of Blocking 1 (this plan's final review): a crash
    whose job carries a non-empty, PASSING `extraction_attempts` entry must
    still read as an ordinary crash, because the ladder never lost -- it
    ran, won, and something unrelated crashed afterward. The old filter
    (`job.state == "failed" and job.extraction_attempts`) could not tell
    this apart from a genuinely held-back document; `held_out` can."""
    _crash_after_a_passing_extraction()

    assert _attention(client)["documents"] == []


def test_a_cancelled_document_leaves_the_panel(client):
    """Dismiss is cancel. No new state, no new field to forget to clear."""
    job = _held_back_job()
    assert len(_attention(client)["documents"]) == 1

    advance(job, "cancelled")

    assert _attention(client)["documents"] == []


def test_retrying_a_held_back_document_leaves_the_panel_too(client):
    """Try again is the existing retry (failed -> queued). Once it is back
    in the queue it is not a held-back document either — it is running."""
    job = _held_back_job()

    advance(job, "queued")

    assert _attention(client)["documents"] == []


def test_the_panel_is_empty_when_nothing_has_failed(client):
    assert _attention(client)["documents"] == []


def test_a_still_running_job_with_prior_attempts_is_not_listed(client):
    """`extraction_attempts` also carries a still-mid-flight job's resume
    marker (a reboot mid-ladder). That is not a held-back document — it
    hasn't failed, it's still going."""
    job = new_job(
        doc_id="d3", title="A baseline book", corpus="budget",
        source_path="y.pdf", source_sha256="c" * 64, publisher="jlbc",
        doc_type="baseline-per-agency", fiscal_year=2027,
    )
    job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": 0.02, "chunks": 20},
    ]
    save(job)
    advance(job, "extracting")

    assert _attention(client)["documents"] == []


def test_newest_failure_first(client):
    """Mirrors the Notices panel it sits beside: a glance at what just went
    wrong, not a chronicle in file order."""
    first = _held_back_job(title="Older FY2022 AFR")
    # Force a real ordering distinction rather than trusting two calls in
    # the same millisecond to land on different `updated_at` values.
    first.updated_at = "2026-01-01T00:00:00+00:00"
    save(first)
    second = _held_back_job(title="Newer FY2024 AFR")
    second.updated_at = "2026-06-01T00:00:00+00:00"
    save(second)

    titles = [d["title"] for d in _attention(client)["documents"]]

    assert titles == ["Newer FY2024 AFR", "Older FY2022 AFR"]


def test_the_happy_path_reports_no_error(client):
    _held_back_job()

    assert _attention(client)["error"] is None


def test_attention_reports_each_attempts_unlabelled_fraction(client):
    """Both numbers per rung, because they DISAGREE: the whole reason this
    feature exists is a document where coverage said 49% and structure said
    30.63% bare (see ingest/structure_scan.py)."""
    job = new_job(
        doc_id="agao-afr-fy2024", title="FY 2024 Annual Financial Report",
        corpus="budget", source_path="afr24.pdf", source_sha256="a" * 64,
        publisher="agao", doc_type="afr", fiscal_year=2024,
    )
    job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": 0.05,
         "unlabelled": 0.31, "chunks": 20},
        {"extractor": "mineru", "coverage": 0.04,
         "unlabelled": None, "chunks": 3},
    ]
    job.held_out = True
    save(job)
    advance(job, "failed", error=(
        "Held out of search — only 5% of this document's text produced "
        "any content, after 2 extraction methods were tried."
    ))

    tried = _attention(client)["documents"][0]["attempts"]

    assert tried[0]["unlabelled"] == 0.31
    assert tried[1]["unlabelled"] is None


def test_an_unreadable_jobs_directory_is_a_visible_error_not_silence(client, monkeypatch):
    """Minor finding on this plan's final review: swallowing an unreadable
    jobs directory into an empty `documents` list read IDENTICALLY to
    "nothing needs attention" -- the overwhelmingly common, entirely fine
    case. A share that has gone away is the one case where silence is the
    wrong answer, because it reads as "the corpus is healthy" on the one
    screen an admin would check to find out otherwise."""
    import ingest.jobs as jobs_module

    def _boom():
        raise OSError("share unavailable")

    # `load_active`, not `load_all`: spec T13 moved finished jobs into
    # jobs/done/ and this panel now reads only the main folder, since
    # `failed` never leaves it. The BEHAVIOUR under test is unchanged --
    # an unreadable share must say so rather than read as "all clear".
    monkeypatch.setattr(jobs_module, "load_active", _boom)

    body = _attention(client)

    assert body["documents"] == []
    assert body["swapped"] == []
    assert body["error"]


# ---------------------------------------------------------------------------
# "swapped" — documents the ladder saved by changing extractor
# ---------------------------------------------------------------------------


def _live_job(
    *, doc_id: str, title: str, kept_extractor: str | None, attempts: list[dict]
):
    """A job that finished successfully, possibly on a LATER ladder rung.

    Set directly rather than walked through `advance()` — this file's other
    helpers reach `failed` through the real state machine because Dismiss/
    Retry behaviour depends on it, but nothing about `swapped` depends on
    the path a job took to `live`, and `advance()` only steps one
    `PIPELINE_STATES` hop at a time.
    """
    job = new_job(
        doc_id=doc_id, title=title, corpus="budget",
        source_path="x.pdf", source_sha256="d" * 64, publisher="agao",
        doc_type="afr", fiscal_year=2024,
    )
    job.extraction_attempts = attempts
    job.kept_extractor = kept_extractor
    job.state = "live"
    save(job)
    return job


def test_a_document_whose_extractor_changed_is_listed_as_swapped(client):
    """A swap re-mints every chunk_id and replaces the document's text. A
    change that size leaving no trace is how a corpus becomes
    unexplainable a year later."""
    _live_job(
        doc_id="agao-afr-fy2024", title="FY 2024 Annual Financial Report",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.31, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.0, "chunks": 450},
        ],
    )

    body = _attention(client)

    assert len(body["swapped"]) == 1
    row = body["swapped"][0]
    assert row["kept"] == "mineru"
    assert [a["extractor"] for a in row["attempts"]] == [
        "opendataloader", "mineru",
    ]
    assert row["attempts"][0]["unlabelled"] == 0.31


def test_a_document_kept_on_its_first_rung_is_not_listed_as_swapped(client):
    """Nothing changed, so there is nothing to explain. A list that fills
    up with ordinary uploads teaches an admin to scroll past it."""
    _live_job(
        doc_id="jlbc-baseline-fy2027-adoa", title="A baseline book",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.94,
             "unlabelled": 0.0, "chunks": 200},
        ],
    )

    assert _attention(client)["swapped"] == []


def test_a_held_back_document_is_not_listed_as_swapped(client):
    """`swapped` is a success list — the ladder chose a later rung and it
    WORKED. A document every rung of which failed belongs on the
    `documents` panel above, never here."""
    _held_back_job()

    assert _attention(client)["swapped"] == []


def test_a_not_yet_live_job_with_a_real_swap_shape_is_not_listed(client):
    """Isolates `job.state != "live"`. Every OTHER swap condition holds —
    `kept_extractor` is set, there are 2+ attempts, and the first attempt's
    extractor differs from `kept` — so this fixture trips nothing except
    the state check. `_held_back_job` (above) also fails this way, but it
    ALSO leaves `kept_extractor` unset, so it would still pass with the
    state check deleted; this fixture would not."""
    job = new_job(
        doc_id="agao-afr-fy2025", title="Still mid-ladder",
        corpus="budget", source_path="x.pdf", source_sha256="e" * 64,
        publisher="agao", doc_type="afr", fiscal_year=2025,
    )
    job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": 0.49,
         "unlabelled": 0.31, "chunks": 388},
        {"extractor": "mineru", "coverage": 0.45,
         "unlabelled": 0.0, "chunks": 450},
    ]
    job.kept_extractor = "mineru"
    job.state = "queued"
    save(job)

    assert _attention(client)["swapped"] == []


def test_a_job_kept_on_its_first_rung_with_a_later_retry_attempt_is_not_listed(client):
    """Isolates `attempts[0].get("extractor") == kept`. State is live, kept
    is set, and there ARE 2+ attempts — the guard this fixture must trip is
    the first-rung comparison alone, so the second attempt exists but the
    first already matches `kept`."""
    _live_job(
        doc_id="jlbc-baseline-fy2027-adoa-retry",
        title="Kept on the first rung despite a later retry",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.94,
             "unlabelled": 0.0, "chunks": 200},
            {"extractor": "mineru", "coverage": 0.10,
             "unlabelled": 0.5, "chunks": 5},
        ],
    )

    assert _attention(client)["swapped"] == []


def test_a_null_titled_swapped_job_does_not_500_the_whole_route(client):
    """This project has already shipped the exact "one bad file costs the
    whole rail" defect once (STATUS.md's IngestLock heartbeat incident).
    `swapped.sort(key=lambda row: row["title"])` raises TypeError comparing
    None to str the moment a second, ordinarily-titled job is also present
    to sort against -- and an uncaught exception here 500s the whole route,
    blanking BOTH the swaps panel and the held-out panel above it."""
    job = _live_job(
        doc_id="agao-afr-fy2024", title="A null title",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.31, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.0, "chunks": 450},
        ],
    )
    job.title = None  # a malformed job file, not something the API can write
    save(job)
    _live_job(
        doc_id="agao-afr-fy2023", title="An ordinary title",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.31, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.0, "chunks": 450},
        ],
    )

    r = client.get("/api/admin/attention")

    assert r.status_code == 200
    assert len(r.json()["swapped"]) == 2


def test_a_job_with_only_one_recorded_attempt_is_not_listed_as_swapped(client):
    """Isolates `len(attempts) < 2`. State is live, kept is set, and the
    lone attempt's extractor differs from `kept` — so if the length guard
    were the only thing missing, `attempts[0]` would still fail its
    equality check and this fixture would slip through as swapped."""
    _live_job(
        doc_id="agao-afr-fy2023", title="Only one attempt was ever recorded",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.10,
             "unlabelled": 0.5, "chunks": 5},
        ],
    )

    assert _attention(client)["swapped"] == []


# ---------------------------------------------------------------------------
# "degraded" — documents that ARE in search and were read badly anyway
#
# The blind spot the two lists above leave between them. `held_out` catches
# only documents the ladder REFUSED to write; `swapped` catches only
# documents whose extractor CHANGED. A document that is bad AND saved
# satisfies neither, and there are two ordinary ways to get there: a
# single-rung source (a DOCX has one extractor, so nothing can change), and
# a PDF where every rung trips the ceiling and the least-bad is rung 1.
# ---------------------------------------------------------------------------


def _degraded(client):
    return _attention(client)["degraded"]


def test_a_single_rung_document_over_the_ceiling_is_listed(client):
    """The DOCX case, and the reason this list exists. One extractor means
    nothing can ever change, so `swapped` can never show it; it was
    written, so `held_out` can never show it either. Before this list it
    appeared on no admin surface at all."""
    _live_job(
        doc_id="bill-fy2026", title="FY 2026 budget bill",
        kept_extractor="docx",
        attempts=[
            {"extractor": "docx", "coverage": 0.88,
             "unlabelled": 0.44, "chunks": 120},
        ],
    )

    rows = _degraded(client)

    assert len(rows) == 1
    assert rows[0]["title"] == "FY 2026 budget bill"
    assert rows[0]["kept"] == "docx"
    assert rows[0]["unlabelled"] == 0.44
    # Coverage rides along because the two DISAGREE — that disagreement is
    # the entire reason the structure measure exists, and showing only the
    # flattering number is how this failure stayed invisible.
    assert rows[0]["coverage"] == 0.88
    # And it is genuinely on NEITHER of the other lists — the assertion
    # that makes this a blind-spot test rather than a listing test.
    body = _attention(client)
    assert body["swapped"] == []
    assert body["documents"] == []


def test_a_document_whose_every_rung_tripped_the_ceiling_is_listed(client):
    """`choose_best` still has to return something, and it returns the
    LEAST bad. When that is rung 1, `attempts[0] == kept` drops it from
    `swapped` too — so a PDF can trip every rung and still show nowhere."""
    _live_job(
        doc_id="agao-afr-fy2019", title="FY 2019 Annual Financial Report",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.50,
             "unlabelled": 0.30, "chunks": 300},
            {"extractor": "mineru", "coverage": 0.48,
             "unlabelled": 0.55, "chunks": 280},
        ],
    )

    rows = _degraded(client)

    assert len(rows) == 1
    assert rows[0]["unlabelled"] == 0.30
    assert _attention(client)["swapped"] == []


def test_a_swapped_document_still_over_the_ceiling_appears_on_BOTH_lists(client):
    """Deliberate overlap. "We changed how this was read" and "what we kept
    is still poor" are different facts and an admin needs both; suppressing
    either hides the more actionable one behind the less."""
    _live_job(
        doc_id="agao-afr-fy2018", title="FY 2018 Annual Financial Report",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.80, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.35, "chunks": 450},
        ],
    )

    body = _attention(client)

    assert len(body["swapped"]) == 1
    assert len(body["degraded"]) == 1
    # The KEPT rung's number, not the first rung's — a row reporting 80%
    # here would be describing a reading that was thrown away.
    assert body["degraded"][0]["unlabelled"] == 0.35


def test_a_clean_document_is_not_listed(client):
    """Isolates the `unlabelled <= MAX_UNLABELLED` comparison. Everything
    else about this fixture matches a listed document — live, kept set,
    the kept attempt present and measured."""
    _live_job(
        doc_id="jlbc-baseline-fy2027-ahcccs", title="FY 2027 Baseline — AHCCCS",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.95,
             "unlabelled": 0.01, "chunks": 200},
        ],
    )

    assert _degraded(client) == []


def test_a_document_exactly_AT_the_ceiling_is_not_listed(client):
    """MAX_UNLABELLED is a CEILING and the ladder fails by scoring ABOVE
    it (`ingest/structure.py`), so the boundary value passes. A route that
    used `<` would list documents the pipeline itself considers acceptable
    — the panel and the pipeline disagreeing about the same number."""
    _live_job(
        doc_id="edge", title="Exactly at the ceiling",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.90,
             "unlabelled": MAX_UNLABELLED, "chunks": 200},
        ],
    )

    assert _degraded(client) == []


def test_an_unmeasured_reading_is_not_listed(client):
    """`unlabelled: None` means NOT MEASURED (too few judgeable passages),
    never "measured and clean" — the contract mirrored from
    ingest/coverage.py. This panel ACCUSES a document, so it must never do
    so on absent evidence."""
    _live_job(
        doc_id="tiny", title="A four-page document nobody could judge",
        kept_extractor="opendataloader",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.90,
             "unlabelled": None, "chunks": 4},
        ],
    )

    assert _degraded(client) == []


def test_a_job_file_written_before_the_field_existed_is_not_listed(client):
    """The whole existing corpus. Every job file predating the structure
    measure has NO `unlabelled` key at all, and `.get` returns None — so
    the day this ships the panel is empty rather than accusing 7,000
    documents it never measured. Distinct from the None case above: that
    one has the key."""
    _live_job(
        doc_id="legacy", title="Ingested before any of this existed",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.90, "chunks": 200}],
    )

    assert _degraded(client) == []


def test_a_held_back_document_is_not_listed_as_degraded(client):
    """It is not in search, so it does not belong on a list whose whole
    claim is "analysts are getting answers from these". It has its own
    panel, with its own actions."""
    _held_back_job(title="FY 2024 AFR")

    body = _attention(client)

    assert len(body["documents"]) == 1
    assert body["degraded"] == []


def test_a_job_that_crashed_after_a_bad_extraction_is_not_listed(client):
    """`kept_extractor` is set BEFORE embed and write (worker.py), so a job
    that chose a rung and then died at the write step carries both a kept
    extractor and a bad number while having written nothing. Isolates the
    `state != "live"` guard: every other condition here would list it."""
    job = new_job(
        doc_id="crashed", title="Chose a rung, then died writing",
        corpus="budget", source_path="x.pdf", source_sha256="e" * 64,
        publisher="agao", doc_type="afr", fiscal_year=2024,
    )
    job.extraction_attempts = [
        {"extractor": "opendataloader", "coverage": 0.50,
         "unlabelled": 0.60, "chunks": 300},
    ]
    job.kept_extractor = "opendataloader"
    job.state = "failed"
    job.error = "Ran out of disk while writing."
    save(job)

    assert _degraded(client) == []


def test_a_job_with_no_kept_extractor_recorded_is_not_listed(client):
    """A live job from before `kept_extractor` existed. The route cannot
    tell WHICH of its attempts was written, so it cannot honestly report
    one — and picking the best-looking attempt would invent a fact."""
    _live_job(
        doc_id="nokept", title="Live, but nothing recorded which rung won",
        kept_extractor=None,
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.50,
             "unlabelled": 0.60, "chunks": 300},
        ],
    )

    assert _degraded(client) == []


def test_the_KEPT_rungs_number_decides_not_any_rungs(client):
    """A job whose DISCARDED rung was terrible and whose kept rung is fine
    must not be listed. Isolates the attempt lookup: a route that scanned
    for "any attempt over the ceiling" would list this, and would be
    describing a reading that was thrown away."""
    _live_job(
        doc_id="discarded", title="The bad reading was the one we dropped",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.90, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.02, "chunks": 450},
        ],
    )

    assert _degraded(client) == []


def test_a_kept_extractor_naming_no_recorded_attempt_is_not_listed(client):
    """Isolates the `kept_attempt is None` guard. `kept_extractor` names a
    rung that is not in `extraction_attempts` at all — inconsistent job
    data, which must produce an omission rather than a KeyError that 500s
    the route and blanks all three panels (this project has shipped the
    "one bad file costs the whole rail" defect once already)."""
    _live_job(
        doc_id="mismatch", title="Kept a rung it never recorded trying",
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.50,
             "unlabelled": 0.60, "chunks": 300},
        ],
    )

    assert _degraded(client) == []


def test_a_corrupt_unlabelled_value_does_not_500_the_whole_route(client):
    """This is the route's only ARITHMETIC on job-file data. Everything else
    copies values straight through, so a corrupt field costs one blank cell
    — but `"0.4" <= 0.20` raises TypeError, and an unhandled TypeError here
    blanks all three panels over one bad file. That shape has shipped in
    this project before (IngestLock; the null-title sort above)."""
    _live_job(
        doc_id="corrupt", title="Somebody hand-edited a job file",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.9,
                   "unlabelled": "0.44", "chunks": 200}],
    )
    _live_job(
        doc_id="fine", title="An ordinary bad document beside it",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.9,
                   "unlabelled": 0.44, "chunks": 200}],
    )

    r = client.get("/api/admin/attention")

    # 200, AND the healthy neighbour still listed — a route that returned
    # 200 with an empty list would pass a status-code-only assertion while
    # having lost the panel's whole contents.
    assert r.status_code == 200
    assert [row["title"] for row in r.json()["degraded"]] == [
        "An ordinary bad document beside it",
    ]


def test_degraded_documents_are_ordered_worst_first(client):
    """Unlike the two lists above — chronological and alphabetical, because
    they are a queue and a record — this one is an ALERT, and the document
    with the most unlabelled figures is the one most worth opening.
    Alphabetical order would bury it at random; the titles here are
    deliberately in the OPPOSITE order to the scores."""
    _live_job(
        doc_id="a", title="A comes first alphabetically",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.9,
                   "unlabelled": 0.25, "chunks": 200}],
    )
    _live_job(
        doc_id="z", title="Z comes last alphabetically",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.9,
                   "unlabelled": 0.75, "chunks": 200}],
    )

    assert [row["unlabelled"] for row in _degraded(client)] == [0.75, 0.25]


def test_the_route_uses_the_pipelines_own_ceiling_constant(client):
    """A copy of the threshold in the route would drift from the ladder's
    and quietly stop listing documents the pipeline considers bad. Pinned
    by driving a value just over whatever `ingest.structure` currently
    says, so moving that constant moves this test with it."""
    _live_job(
        doc_id="justover", title="A hair over whatever the ceiling is",
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.9,
                   "unlabelled": MAX_UNLABELLED + 0.001, "chunks": 200}],
    )

    assert len(_degraded(client)) == 1


# ---------------------------------------------------------------------------
# The soft admin gate
# ---------------------------------------------------------------------------


def test_the_route_is_admin_gated(client, monkeypatch):
    monkeypatch.setenv("JLBC_USER", ANALYST)
    fresh = TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))

    r = fresh.get("/api/admin/attention")

    assert r.status_code == 403
