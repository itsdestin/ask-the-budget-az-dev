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
    assert doc["attempts"] == [
        {"extractor": "opendataloader", "coverage": pytest.approx(0.02)},
        {"extractor": "mineru", "coverage": pytest.approx(0.02)},
        {"extractor": "mineru-ocr", "coverage": pytest.approx(0.01)},
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

    monkeypatch.setattr(jobs_module, "load_all", _boom)

    body = _attention(client)

    assert body["documents"] == []
    assert body["error"]


# ---------------------------------------------------------------------------
# The soft admin gate
# ---------------------------------------------------------------------------


def test_the_route_is_admin_gated(client, monkeypatch):
    monkeypatch.setenv("JLBC_USER", ANALYST)
    fresh = TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))

    r = fresh.get("/api/admin/attention")

    assert r.status_code == 403
