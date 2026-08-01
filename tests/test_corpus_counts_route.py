"""GET /api/corpus/counts (Plan 5 Task 19).

The webapp footer used to state "382 docs". Plan 3's upload queue
falsifies any hardcoded count the first time somebody uploads, and
nothing in the app would notice — so the count was removed rather than
left to rot. This endpoint is what lets it come back as a true number.

Deliberately NOT behind the admin gate: it feeds a footer every analyst
sees, and corpus size is not sensitive.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return TestClient(create_app(ingest_worker=None))


def test_counts_are_zero_on_a_fresh_install(client):
    """A fresh data dir has no tables and no sidecar. Zero, not a 500 —
    this is the state the very first launch is in."""
    body = client.get("/api/corpus/counts").json()

    assert body == {
        "documents": 0,
        "budget_chunks": 0,
        "fiscal_note_chunks": 0,
    }


def test_documents_are_counted_from_the_sidecar(client, tmp_path):
    (tmp_path / "documents.json").write_text(
        json.dumps({f"doc-{i}": {"title": f"T{i}"} for i in range(7)}),
        encoding="utf-8",
    )

    assert client.get("/api/corpus/counts").json()["documents"] == 7


def test_a_corrupt_sidecar_reads_as_zero_rather_than_500ing(client, tmp_path):
    """The footer must never take the page down. Zero documents is a
    visible, honest degradation; a 500 in a footer fetch is not."""
    (tmp_path / "documents.json").write_text("{not json", encoding="utf-8")

    response = client.get("/api/corpus/counts")

    assert response.status_code == 200
    assert response.json()["documents"] == 0


def test_chunk_counts_come_from_the_live_tables(client, tmp_path):
    from store.chunk_store import ChunkStore
    from store.schema import chunk_schema

    store = ChunkStore()
    rows = [
        {
            **{f.name: None for f in chunk_schema(dim=768)},
            "chunk_id": f"c{i}",
            "doc_id": "doc-a",
            "text": "text",
            "section_path": [],
            "agency_canonical_ids": [],
            "fund_mentions": [],
            "doc_type": "baseline-per-agency",
            "is_table": False,
            "token_count": 4,
            "publisher": "jlbc",
            "vector": [0.0] * 768,
        }
        for i in range(3)
    ]
    store.upsert_chunks("budget_chunks", rows)

    body = client.get("/api/corpus/counts").json()

    assert body["budget_chunks"] == 3
    assert body["fiscal_note_chunks"] == 0


def test_the_route_is_not_admin_gated(client, monkeypatch):
    """Every analyst's footer calls this. Gating it would blank the count
    for everyone but one person."""
    monkeypatch.setenv("JLBC_USER", "some-analyst")

    assert client.get("/api/corpus/counts").status_code == 200
