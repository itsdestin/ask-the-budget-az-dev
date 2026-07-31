"""The fiscal-notes route once its data source can change under it (Plan 3)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from ingest.jobs import load_all


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
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # The route caches by file signature in a module global; clear it so one
    # test's directory can't be served to the next.
    import app.routes.fiscal_notes as mod
    mod._cache = None
    return tmp_path


@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(provider=_StubProvider(), static_dir=None,
                                 ingest_worker=NoopWorker()))


def _directory(sessions) -> str:
    return json.dumps({"sessions": sessions})


def test_serves_the_committed_snapshot_when_no_live_directory(client):
    body = client.get("/api/fiscal-notes").json()
    assert len(body["sessions"]) >= 20
    assert body["sessions"][0]["year"] > body["sessions"][-1]["year"]


def test_prefers_the_live_directory_when_present(client, data_dir):
    (data_dir / "fiscal-notes-directory.json").write_text(
        _directory([{"year": 2026, "name": "live", "bills": []}]), encoding="utf-8"
    )
    body = client.get("/api/fiscal-notes").json()
    assert [s["name"] for s in body["sessions"]] == ["live"]


def test_a_refresh_is_visible_without_restarting(client, data_dir):
    """The Plan 2 lru_cache would have pinned the first read forever — a
    refresh that nobody can see is a refresh that didn't happen."""
    live = data_dir / "fiscal-notes-directory.json"
    live.write_text(_directory([{"year": 2026, "name": "before", "bills": []}]),
                    encoding="utf-8")
    assert client.get("/api/fiscal-notes").json()["sessions"][0]["name"] == "before"

    live.write_text(_directory([{"year": 2026, "name": "after", "bills": []}]),
                    encoding="utf-8")
    assert client.get("/api/fiscal-notes").json()["sessions"][0]["name"] == "after"


def test_sessions_come_back_newest_first(client, data_dir):
    (data_dir / "fiscal-notes-directory.json").write_text(
        _directory([
            {"year": 2024, "name": "old", "bills": []},
            {"year": 2026, "name": "new", "bills": []},
        ]),
        encoding="utf-8",
    )
    body = client.get("/api/fiscal-notes").json()
    assert [s["year"] for s in body["sessions"]] == [2026, 2024]


def test_contract_shape_is_unchanged(client):
    session = client.get("/api/fiscal-notes").json()["sessions"][0]
    assert set(session) == {"year", "name", "bills"}
    assert set(session["bills"][0]) == {
        "bill_number", "title", "chamber", "fiscal_note_url"
    }


# --- corpus status ----------------------------------------------------------


def test_status_reports_an_empty_fiscal_note_corpus(client):
    assert client.get("/api/fiscal-notes/status").json() == {"chunks": 0}


# --- refresh ----------------------------------------------------------------


def test_refresh_queues_a_refresh_job(client):
    r = client.post("/api/fiscal-notes/refresh")
    assert r.status_code == 202
    jobs = load_all()
    assert [j.kind for j in jobs] == ["refresh"]
    assert jobs[0].job_id == r.json()["job_id"]
    assert jobs[0].state == "queued"


def test_a_refresh_job_shows_up_in_the_queue_api(client):
    client.post("/api/fiscal-notes/refresh")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert jobs[0]["title"].startswith("Fiscal notes")
