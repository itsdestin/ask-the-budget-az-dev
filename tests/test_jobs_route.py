"""Tests for the queue-control API: GET /api/jobs, retry, cancel."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from ingest.jobs import advance, load_job, new_job, save


class NoopWorker:
    def start(self) -> None:
        pass

    def stop(self, timeout_s: float = 0) -> None:
        pass


class _StubProvider:
    name = "stub"

    def search(self, *a, **kw):
        return []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return TestClient(create_app(provider=_StubProvider(), static_dir=None,
                                 ingest_worker=NoopWorker()))


def _job(**over):
    base = dict(
        doc_id="jlbc-baseline-fy2027-axs", title="FY 2027 Baseline — AHCCCS",
        corpus="budget", source_path="uploads/ab/ab.pdf",
        source_sha256="ab" * 32, publisher="jlbc",
        doc_type="baseline-per-agency", fiscal_year=2027,
    )
    base.update(over)
    job = new_job(**base)
    save(job)
    return job


# --- listing ----------------------------------------------------------------


def test_jobs_lists_newest_first(client):
    older = _job()
    older.created_at = "2026-01-01T00:00:00+00:00"
    save(older)
    newer = _job(doc_id="jlbc-baseline-fy2027-dps")
    newer.created_at = "2026-07-30T00:00:00+00:00"
    save(newer)

    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["job_id"] for j in jobs] == [newer.job_id, older.job_id]


def test_job_view_carries_exactly_the_contract_fields(client):
    _job()
    job = client.get("/api/jobs").json()["jobs"][0]
    # "stage" joined the contract with Plan A Task 5: the queue page needs to
    # show which rung of a doc_type's ladder (e.g. Introduced/Engrossed) an
    # upload is on, the same way it already shows doc_type and fiscal_year.
    assert set(job) == {
        "job_id", "doc_id", "title", "corpus", "state", "pct", "stage_detail",
        "error", "machine", "user", "created_at", "updated_at", "stage",
    }


def test_other_machines_jobs_are_listed_too(client):
    """One shared queue — a colleague's upload must be visible here."""
    theirs = _job()
    theirs.machine = "SOMEONE-ELSES-PC"
    save(theirs)
    assert client.get("/api/jobs").json()["jobs"][0]["machine"] == "SOMEONE-ELSES-PC"


def test_empty_queue_returns_an_empty_list(client):
    assert client.get("/api/jobs").json() == {"jobs": []}


# --- retry ------------------------------------------------------------------


def test_retry_requeues_a_failed_job(client):
    job = _job()
    advance(job, "extracting")
    advance(job, "failed", error="mineru exploded")

    r = client.post(f"/api/jobs/{job.job_id}/retry")
    assert r.status_code == 200
    assert r.json()["job"]["state"] == "queued"
    assert load_job(job.job_id).error is None


def test_retry_on_a_running_job_is_409(client):
    job = _job()
    advance(job, "extracting")
    assert client.post(f"/api/jobs/{job.job_id}/retry").status_code == 409


def test_retry_on_a_live_job_is_409(client):
    job = _job()
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        advance(job, state)
    assert client.post(f"/api/jobs/{job.job_id}/retry").status_code == 409


def test_retry_of_an_unknown_job_is_404(client):
    assert client.post("/api/jobs/20260101T000000Z-deadbeef/retry").status_code == 404


# --- cancel -----------------------------------------------------------------


def test_cancel_stops_a_running_job(client):
    job = _job()
    advance(job, "extracting")
    r = client.post(f"/api/jobs/{job.job_id}/cancel")
    assert r.status_code == 200
    assert load_job(job.job_id).state == "cancelled"


def test_cancel_a_queued_job(client):
    job = _job()
    assert client.post(f"/api/jobs/{job.job_id}/cancel").status_code == 200


def test_cancel_on_a_live_job_is_409(client):
    job = _job()
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        advance(job, state)
    r = client.post(f"/api/jobs/{job.job_id}/cancel")
    assert r.status_code == 409
    assert load_job(job.job_id).state == "live"


def test_a_traversal_job_id_is_rejected(client):
    """job_id lands in a filesystem path; a dotted segment must never reach it."""
    assert client.post("/api/jobs/../cancel").status_code in (400, 404, 405)
    assert client.post("/api/jobs/.hidden/cancel").status_code == 400
