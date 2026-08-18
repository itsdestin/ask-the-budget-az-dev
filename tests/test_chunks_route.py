"""GET /api/chunks/{chunk_id} — provenance fields for the source viewer.

Plan 4 Task 11. In AI Mode the viewer already has a chunk's doc_id, page,
bbox and text (they ride along with the `cite()` chip); on the SEARCH page a
click carries only a chunk_id, so this route is what makes "where does this
number come from?" answerable without an AI turn.

The store is faked throughout: these tests are about the route's contract —
which fields it returns, what it does with a missing chunk, an unreadable
store, and a source that has no page image — not about LanceDB, which
tests/test_chunk_store.py owns. Faking also means the suite passes on a
machine with no migrated corpus, like CI and a fresh clone.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.tools import reset_document_title_cache
from store.config import documents_path

CHUNK_ROW = {
    "chunk_id": "c1",
    "doc_id": "d1",
    "text": "The Aviation Fund got $2,587,400 in FY 2026.",
    "page": 47,
    "bbox": [10.5, 20.0, 100.25, 40.0],
    # Columns the store really returns but the viewer has no use for. They are
    # here so the test would catch the route growing into a chunk dump.
    "doc_type": "baseline-per-agency",
    "fiscal_year": 2027,
    "publisher": "jlbc",
    "token_count": 210,
}


class FakeStore:
    """Records what it was asked for and answers with canned rows."""

    def __init__(self, rows: list[dict] | None = None, raises: Exception | None = None):
        self.rows = rows if rows is not None else [CHUNK_ROW]
        self.raises = raises
        self.calls: list[tuple[str, list[str]]] = []

    def get_by_ids(self, table: str, chunk_ids: list[str]) -> list[dict]:
        self.calls.append((table, list(chunk_ids)))
        if self.raises is not None:
            raise self.raises
        return [r for r in self.rows if r["chunk_id"] in chunk_ids]


@pytest.fixture(autouse=True)
def isolated_share(tmp_path, monkeypatch):
    """Own share (documents.json) + a clean document-metadata cache per test."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    reset_document_title_cache()
    yield
    reset_document_title_cache()


@pytest.fixture
def store(monkeypatch):
    """Install a FakeStore in place of the process-wide LanceDB singleton."""
    fake = FakeStore()

    def use(new: FakeStore) -> FakeStore:
        monkeypatch.setattr("retrieval.pipeline._get_store", lambda: new)
        return new

    use(fake)
    fake.use = use  # type: ignore[attr-defined]
    return fake


def write_sidecar(entries: dict) -> None:
    documents_path().write_text(json.dumps(entries), encoding="utf-8")
    reset_document_title_cache()


def client() -> TestClient:
    return TestClient(
        create_app(provider=StubSearchProvider(), static_dir=None),
        raise_server_exceptions=False,
    )


def test_returns_the_fields_the_viewer_consumes(store):
    write_sidecar({"d1": {"source_format": "pdf", "source_blob_path": "pdfs/d1.pdf"}})
    r = client().get("/api/chunks/c1")
    assert r.status_code == 200
    assert r.json() == {
        "chunk_id": "c1",
        "doc_id": "d1",
        "page": 47,
        "bbox": [10.5, 20.0, 100.25, 40.0],
        "text": "The Aviation Fund got $2,587,400 in FY 2026.",
        # Absent on rows written before the locate work (spec L1) — null,
        # not missing, so the client's ChunkSource type stays total.
        "source_anchor": None,
        "source_format": "pdf",
        "pdf_unavailable_reason": None,
    }


def test_defaults_to_the_budget_corpus(store):
    client().get("/api/chunks/c1")
    assert store.calls == [("budget_chunks", ["c1"])]


def test_corpus_query_selects_the_fiscal_note_table(store):
    client().get("/api/chunks/c1?corpus=fiscal_notes")
    assert store.calls == [("fiscal_note_chunks", ["c1"])]


def test_unknown_corpus_is_rejected(store):
    # The wire names are the two the search route already admits; anything
    # else is a client bug, not an empty corpus.
    r = client().get("/api/chunks/c1?corpus=budget_chunks_typo")
    assert r.status_code == 422
    assert store.calls == []


def test_unknown_chunk_is_404_with_an_actionable_detail(store):
    r = client().get("/api/chunks/nope")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "nope" in detail
    # The likeliest real cause is a re-ingest, and the fix is to search again.
    assert "re-ingest" in detail.lower() or "re-run the search" in detail.lower()


def test_null_page_and_bbox_survive_as_null(store):
    store.use(FakeStore([{**CHUNK_ROW, "page": None, "bbox": None}]))
    body = client().get("/api/chunks/c1").json()
    assert body["page"] is None
    # Null bbox is MEANINGFUL to the viewer: it means "search the whole page"
    # rather than "restrict the search", so it must not collapse to [] or 0s.
    assert body["bbox"] is None


def test_non_pdf_source_reuses_the_pdf_route_s_own_wording(store):
    # One sentence, one source (app.routes.pdf.non_pdf_detail). If these two
    # ever drift, the viewer would say something different depending on which
    # route it happened to ask first.
    write_sidecar({"d1": {"source_format": "docx", "source_blob_path": "x.docx"}})
    c = client()
    chunk_body = c.get("/api/chunks/c1").json()
    pdf_body = c.get("/api/pdf/d1").json()
    assert chunk_body["source_format"] == "docx"
    assert chunk_body["pdf_unavailable_reason"] == pdf_body["detail"]
    assert "cited text" in chunk_body["pdf_unavailable_reason"].lower()


def test_chunk_whose_document_is_not_in_the_sidecar_still_resolves(store):
    # documents.json missing entirely (fresh machine, sidecar not copied).
    # The passage text is still worth showing, and "unknown format" is not a
    # reason to refuse to try the PDF route.
    body = client().get("/api/chunks/c1").json()
    assert body["source_format"] is None
    assert body["pdf_unavailable_reason"] is None
    assert body["text"].startswith("The Aviation Fund")


def test_source_anchor_is_decoded_for_the_viewer(store):
    # Rows written after the locate work (spec L1) carry per-paragraph
    # lines; the route hands them over decoded, not as the raw JSON string
    # the Arrow column stores.
    anchor = {"page": 47, "lines": [
        {"text": "The Aviation Fund got $2,587,400 in FY 2026.",
         "page": 47, "bbox": [10.0, 20.0, 100.0, 40.0]}]}
    store.use(FakeStore([{**CHUNK_ROW, "source_anchor": json.dumps(anchor)}]))
    body = client().get("/api/chunks/c1").json()
    assert body["source_anchor"] == anchor


def test_malformed_source_anchor_degrades_to_null_not_a_500(store):
    # A str()'d anchor (the migration-era writer bug) must not take the
    # provenance surface down: the viewer treats null as "no lines" and
    # falls back. The LOUD copy of this failure stays in
    # retrieval/search_lance.row_to_chunk, where retrieval reads the same
    # column for real.
    store.use(FakeStore([{**CHUNK_ROW, "source_anchor": "{'page': 47}"}]))
    r = client().get("/api/chunks/c1")
    assert r.status_code == 200
    assert r.json()["source_anchor"] is None


def test_store_failure_is_a_json_503_with_the_cause(store):
    store.use(FakeStore(raises=OSError("share is offline")))
    r = client().get("/api/chunks/c1")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "share is offline" in detail
    assert "OSError" in detail
