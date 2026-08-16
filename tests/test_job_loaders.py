"""Each `load_all()` caller asks for the set it actually means.

Spec T13 moved finished jobs into `jobs/done/`, so every one of the seven
callers had to be re-read and re-pointed. Six are equivalent by construction
-- their filters already excluded every archived state, so `load_active()`
returns the same set without reading the 7,104-file archive.

`last_ingest_at` on the admin health panel is the one that genuinely
changes, and the obvious swap breaks it SILENTLY: every `live` job is
archived, so a summary built from the main folder alone reports "nothing has
ever finished" on a corpus of 7,434 documents. That one has a test of its
own, and it is the reason this file exists.
"""
import pytest

from ingest import jobs as J


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _job(doc_id="d", sha="s", url=None):
    return J.new_job(
        doc_id=doc_id,
        title="T",
        corpus="budget",
        source_path="/x.pdf",
        source_sha256=sha,
        publisher="jlbc",
        doc_type="jlbc-approps-per-agency",
        fiscal_year=2026,
        source_url=url,
    )


def _finished(doc_id="d", sha="s", url=None):
    job = _job(doc_id, sha, url)
    J.save(job)
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)
    return job


# --- the caller that genuinely changes -------------------------------------


def test_the_admin_panel_still_reports_the_last_finished_ingest(data_dir):
    """The regression a naive `load_active()` swap would have shipped.

    Every `live` job is archived by spec T13, so a summary built only from
    the main folder reports `last_ingest_at: None` forever -- the admin
    health panel saying nothing has ever been ingested, on a corpus of
    7,434 documents. It is silent: no error, no empty list, just a date
    that never appears.
    """
    from app.queue_status import queue_summary

    job = _finished("d1", "sha1")
    summary, last_live = queue_summary()

    assert last_live == job.updated_at
    assert summary == {"queued": 0, "running": 0, "failed": 0}


def test_the_last_finished_ingest_is_not_answered_by_a_dismissed_failure(data_dir):
    """`cancelled` is archived too, but a dismissed failure is not an ingest.

    Reporting one as "the corpus last grew at..." is a quietly false
    reassurance on the one screen an admin checks to find out otherwise.
    """
    from app.queue_status import queue_summary

    junk = _job("junk", "sha-junk")
    J.save(junk)
    J.advance(junk, "cancelled")

    _summary, last_live = queue_summary()
    assert last_live is None


def test_the_queue_summary_still_counts_queued_running_and_failed(data_dir):
    from app.queue_status import queue_summary

    failed = _job("f", "sha-f")
    J.save(failed)
    J.advance(failed, "failed", error="boom")

    J.save(_job("q", "sha-q"))

    running = _job("r", "sha-r")
    J.save(running)
    J.advance(running, "extracting")

    summary, _ = queue_summary()
    assert summary == {"queued": 1, "running": 1, "failed": 1}


# --- the callers that are equivalent by construction -----------------------


def test_a_finished_upload_is_still_recognised_as_a_duplicate(data_dir, monkeypatch):
    """The correctness trap in this task.

    The job loop in `_find_duplicate` only ever meant "already queued" --
    `documents.json` is what catches an already-INGESTED file. This pins
    that the pair together still refuse a re-upload after the job has been
    archived, which is the case a wrong loader would break by making the
    app silently re-ingest documents it already holds.
    """
    from app.routes import upload as U

    _finished("doc-x", "sha-dup")
    monkeypatch.setattr(
        U,
        "_documents",
        lambda: {
            "doc-x": {
                "source_sha256": "sha-dup",
                "ingested_at": "2026-08-13T00:00:00Z",
                "uploaded_by": "someone",
            }
        },
    )

    dup = U._find_duplicate("sha-dup")
    assert dup is not None and dup["existing_doc_id"] == "doc-x"


def test_a_still_queued_upload_is_recognised_as_a_duplicate(data_dir, monkeypatch):
    """The double-click case -- the one only the job list can answer, since
    nothing is in documents.json yet."""
    from app.routes import upload as U

    J.save(_job("doc-y", "sha-pending"))
    monkeypatch.setattr(U, "_documents", dict)

    dup = U._find_duplicate("sha-pending")
    assert dup is not None and dup["existing_doc_id"] == "doc-y"


def test_book_ingest_still_skips_a_url_that_is_merely_QUEUED(data_dir):
    """The book route's `pending` set means "queued but not yet in
    documents.json". An archived job's URL is in documents.json, so it is
    the other check's job -- but a still-queued one is only knowable here.
    """
    url = "https://www.azjlbc.gov/27ar/508.pdf"
    J.save(_job("d", "s", url))

    pending = {
        j.source_url
        for j in J.load_active()
        if j.state not in J.TERMINAL_STATES and j.source_url
    }
    assert url in pending


def test_the_worker_still_finds_queued_work_and_ignores_the_archive(data_dir):
    _finished("done", "s1")
    J.save(_job("waiting", "s2"))

    queued = [j for j in reversed(J.load_active()) if j.state == "queued"]
    assert [j.doc_id for j in queued] == ["waiting"]


def test_the_attention_panel_still_sees_a_held_out_failure(data_dir):
    """`failed` never leaves the main folder -- that is exactly what T13's
    storage shape guarantees -- so this panel sees every held-back document
    without reading the archive."""
    from app.routes.admin import get_attention

    job = _job("held", "s-held")
    J.save(job)
    J.advance(job, "failed", error="every extraction method scored too low")
    job.held_out = True
    J.save(job)

    payload = get_attention()
    assert [d["job_id"] for d in payload["documents"]] == [job.job_id]
