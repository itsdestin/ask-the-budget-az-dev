"""Tests for /api/books — catalog, discover, bulk enqueue."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from ingest.jobs import load_all
from store.config import documents_path


class NoopWorker:
    def start(self) -> None:
        pass

    def stop(self, timeout_s: float = 0) -> None:
        pass


class _StubProvider:
    name = "stub"

    def search(self, *a, **kw):
        return []


class AllLive:
    def head(self, url: str) -> bool:
        return True

    def get(self, url: str) -> bytes:
        return b"%PDF-1.4\n"


class Dead:
    def head(self, url: str) -> bool:
        return False

    def get(self, url: str) -> bytes:
        raise ConnectionError("azjlbc.gov unreachable")


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))

    def _make(prober=None):
        app = create_app(provider=_StubProvider(), static_dir=None,
                         ingest_worker=NoopWorker())
        app.state.book_prober = prober or AllLive()
        return TestClient(app)

    return _make


@pytest.fixture()
def client(make_client):
    return make_client()


# --- catalog ----------------------------------------------------------------


def test_catalog_lists_every_edition(client):
    editions = client.get("/api/books/catalog").json()["editions"]
    assert len(editions) == 62
    assert {"key", "family", "fiscal_year", "ingestable", "rolling",
            "era_note", "single_file_url", "linked_toc_url",
            "document_count"} == set(editions[0])


def test_catalog_is_newest_first(client):
    editions = client.get("/api/books/catalog").json()["editions"]
    assert editions[0]["fiscal_year"] >= editions[1]["fiscal_year"]


# --- discover ---------------------------------------------------------------


def test_discover_returns_the_roster_without_downloading(client):
    r = client.post("/api/books/discover",
                    json={"family": "baseline", "fiscal_year": 2027})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "catalog"
    assert body["count"] >= 100
    assert body["documents"][0]["url"].startswith("https://www.azjlbc.gov/")
    assert load_all() == []           # nothing queued


def test_discover_reports_an_unpublished_edition_honestly(make_client):
    client = make_client(Dead())
    r = client.post("/api/books/discover",
                    json={"family": "approps", "fiscal_year": 2029})
    assert r.status_code == 502
    assert "No FY2029" in r.json()["detail"]


def test_discover_rejects_an_unknown_family(client):
    r = client.post("/api/books/discover",
                    json={"family": "sasquatch", "fiscal_year": 2027})
    assert r.status_code == 422


def test_discover_explains_an_old_book_with_no_children(client):
    body = client.post("/api/books/discover",
                       json={"family": "approps", "fiscal_year": 1996}).json()
    assert body["count"] == 0
    assert any("did not publish per-agency pages" in n for n in body["notes"])
    assert body["single_file_url"]


# --- ingest -----------------------------------------------------------------


def test_ingest_queues_one_job_per_document(client):
    r = client.post("/api/books/ingest",
                    json={"family": "baseline", "fiscal_year": 2027})
    assert r.status_code == 202
    body = r.json()
    assert body["queued"] >= 100
    assert len(load_all()) == body["queued"]


def test_queued_jobs_carry_the_source_url_not_a_file(client):
    """130 downloads at enqueue time would hang the button for minutes."""
    client.post("/api/books/ingest",
                json={"family": "baseline", "fiscal_year": 2027})
    job = load_all()[0]
    assert job.source_url.startswith("https://www.azjlbc.gov/")
    assert job.source_path == ""
    assert job.corpus == "budget" and job.publisher == "jlbc"


def test_documents_already_in_the_corpus_are_skipped(client, tmp_path):
    plan = client.post("/api/books/discover",
                       json={"family": "baseline", "fiscal_year": 2027}).json()
    already = plan["documents"][0]["url"]
    documents_path().write_text(
        json.dumps({"some-doc": {"source_url": already}}), encoding="utf-8")

    body = client.post("/api/books/ingest",
                       json={"family": "baseline", "fiscal_year": 2027}).json()
    assert body["skipped_existing"] == 1
    assert body["queued"] == plan["count"] - 1


def test_a_second_ingest_skips_everything_it_already_queued(client):
    first = client.post("/api/books/ingest",
                        json={"family": "baseline", "fiscal_year": 2027}).json()
    second = client.post("/api/books/ingest",
                         json={"family": "baseline", "fiscal_year": 2027}).json()
    assert second["queued"] == 0
    assert second["skipped_existing"] == first["queued"]


def test_a_discovery_failure_queues_nothing(make_client):
    client = make_client(Dead())
    r = client.post("/api/books/ingest",
                    json={"family": "approps", "fiscal_year": 2029})
    assert r.status_code == 502
    assert load_all() == []
