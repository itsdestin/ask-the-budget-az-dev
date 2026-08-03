"""HTTP routes over the local chat-history store (Plan: chat history, H1/H4).

No API key, no corpus, no SPA build — create_app(provider=StubSearchProvider(),
static_dir=None, ingest_worker=None) keeps this file off every real resource.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history


@pytest.fixture
def client(tmp_path, monkeypatch):
    # provider + static_dir are not optional here, they are what keeps this
    # file off the real corpus: create_app() with neither runs the LanceDB
    # startup probe and looks for a built SPA. Same call shape as
    # tests/test_conversations_route.py:108.
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    return TestClient(
        create_app(
            provider=StubSearchProvider(), static_dir=None, ingest_worker=None
        )
    )


def _seed(cid="c1", title="ADC vacancy savings", n=2):
    history.save(history.Transcript(
        id=cid, title=title, corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:05:00+00:00",
        messages=[{"role": "user", "content": "q"}] * n,
    ))


def test_list_returns_rows_without_message_bodies(client):
    _seed()
    r = client.get("/api/history")
    assert r.status_code == 200
    row = r.json()["conversations"][0]
    assert row["id"] == "c1"
    assert row["message_count"] == 2
    assert "messages" not in row


def test_get_one_returns_the_full_transcript(client):
    _seed()
    r = client.get("/api/history/c1")
    assert r.status_code == 200
    assert len(r.json()["messages"]) == 2


def test_get_one_missing_is_404(client):
    assert client.get("/api/history/nope").status_code == 404


def test_rename(client):
    _seed()
    r = client.patch("/api/history/c1", json={"title": "Corrections vacancies"})
    assert r.status_code == 200
    assert history.load("c1").title == "Corrections vacancies"
    assert history.load("c1").title_is_manual is True


def test_rename_rejects_an_empty_title(client):
    _seed()
    assert client.patch("/api/history/c1", json={"title": "   "}).status_code == 422


def test_delete(client):
    _seed()
    assert client.delete("/api/history/c1").status_code == 200
    assert history.load("c1") is None


def test_a_traversal_id_is_rejected_not_served(client):
    assert client.get("/api/history/..%2F..%2Fsettings").status_code in (400, 404)


def test_history_works_with_no_api_key(client, monkeypatch):
    """No paid API is load-bearing — listing must not need AI Mode at all."""
    _seed()
    assert client.get("/api/history").status_code == 200


def test_search_is_not_swallowed_by_the_id_route(client):
    """Route order is load-bearing; a refactor that reorders them breaks this."""
    assert client.get("/api/history/search?q=anything").status_code == 200
