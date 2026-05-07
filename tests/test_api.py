"""Tests for retrieval/api.py — the FastAPI sidecar that fronts the
hybrid retrieval pipeline for the Phase 1c MCP server.

Two layers, mirroring the pattern used by test_pipeline.py / test_loader.py:

* Pure unit tests (no DB, no Voyage). monkeypatch `retrieve()` and the
  doc-title lookup so the route logic + Pydantic validation can be
  exercised in isolation. These run on every CI tick.
* Integration tests gated by `_has_full_stack()` — Postgres reachable
  with the embedded slice AND VOYAGE_API_KEY set. These exercise the
  real /retrieve and /cite/validate endpoints end-to-end.
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")
fastapi_testclient = pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient

import retrieval.api as api_module
from db.connection import close_pool
from retrieval.api import app
from retrieval.pipeline import RetrievalResult
from retrieval.types import RetrievedChunk

MIN_CHUNKS_FOR_PIPELINE = 50


def _has_database() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


def _has_embedded_corpus() -> bool:
    if not _has_database():
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()
            return bool(row and row[0] >= MIN_CHUNKS_FOR_PIPELINE)
    except Exception:
        return False


needs_full_stack = pytest.mark.skipif(
    not (_has_embedded_corpus() and os.environ.get("VOYAGE_API_KEY")),
    reason=(
        "API integration tests need DATABASE_URL with >=50 embedded chunks "
        "AND VOYAGE_API_KEY set."
    ),
)

needs_db = pytest.mark.skipif(
    not _has_database(),
    reason="cite/validate tests need a reachable Postgres.",
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_chunk(
    chunk_id: str,
    *,
    doc_id: str = "test-doc",
    score: float = 0.9,
    text: str = "Aviation Fund balance was $123,456.",
    page: int | None = 47,
) -> RetrievedChunk:
    """Build a RetrievedChunk fixture that satisfies every required
    field on RetrievedChunk.from_row's output. Used by unit tests that
    monkey-patch retrieve() — the values are never compared against
    a real DB, only marshaled into the API response.
    """
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        score=score,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=page,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor=None,
        agency_canonical_ids=["agency:ahcccs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
    )


# ---------------------------------------------------------------------------
# Unit tests — /health
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_ok():
    """Sanity check: /health is reachable and returns the expected shape.
    Used by the dev script to wait for the sidecar before launching the
    MCP server.
    """
    # TestClient runs the lifespan context manager, which constructs a
    # VoyageEmbedder. We patch the constructor so unit tests don't need
    # a Voyage key.
    with TestClient(app) as client:
        # Lifespan is set up only when the context manager is entered;
        # the embedder will exist on app.state.
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "voyage_key_present" in body


# ---------------------------------------------------------------------------
# Unit tests — /retrieve (monkeypatched)
# ---------------------------------------------------------------------------


def test_retrieve_marshals_chunks_to_schema_shape(monkeypatch):
    """The MCP `retrieve` tool's return shape is locked in
    citation-tool-schema.md. Confirm the FastAPI sidecar produces
    exactly that shape from a RetrievalResult.
    """
    fake_result = RetrievalResult(
        chunks=[_fake_chunk("c1", doc_id="d1"), _fake_chunk("c2", doc_id="d2")],
        top_score=0.9,
        reranker_scores=[0.9, 0.8],
        bm25_count=42,
        dense_count=37,
        fused_count=20,
    )

    monkeypatch.setattr(
        api_module, "retrieve", lambda req, embedder=None: fake_result
    )
    monkeypatch.setattr(
        api_module,
        "_lookup_doc_titles",
        lambda doc_ids: {"d1": "Doc One", "d2": "Doc Two"},
    )
    # Bypass the lazy Voyage SDK init — unit tests don't need a real
    # embedder since retrieve() is monkey-patched above.
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={
                "query": "Aviation Fund balance",
                "filters": {"fiscal_year": [2027]},
                "top_k": 5,
            },
        )

    assert resp.status_code == 200
    body = resp.json()

    # Top-level shape per schema doc.
    assert set(body.keys()) == {
        "chunks",
        "top_score",
        "retrieval_id",
        "bm25_count",
        "dense_count",
        "fused_count",
    }
    assert body["top_score"] == 0.9
    assert body["bm25_count"] == 42
    assert body["dense_count"] == 37
    assert body["fused_count"] == 20
    assert isinstance(body["retrieval_id"], str) and body["retrieval_id"]
    assert len(body["chunks"]) == 2

    # Per-chunk shape.
    c0 = body["chunks"][0]
    assert set(c0.keys()) == {
        "chunk_id",
        "doc_id",
        "doc_title",
        "publisher",
        "fiscal_year",
        "doc_type",
        "section_path",
        "page_start",
        "page_end",
        "text",
        "score",
    }
    assert c0["chunk_id"] == "c1"
    assert c0["doc_id"] == "d1"
    assert c0["doc_title"] == "Doc One"
    assert c0["publisher"] == "jlbc"
    assert c0["fiscal_year"] == 2027
    assert c0["doc_type"] == "baseline-cross-cut"
    assert c0["section_path"] == ["AHCCCS", "Operating Lump Sum"]
    assert c0["page_start"] == 47 and c0["page_end"] == 47
    assert c0["score"] == 0.9


def test_retrieve_empty_filters_omitted(monkeypatch):
    """Filters block is optional; sidecar should accept the bare
    `{ query }` body and pass through to retrieve()."""
    captured: dict = {}

    def fake_retrieve(req, embedder=None):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "x"})

    assert resp.status_code == 200
    req = captured["req"]
    assert req.query == "x"
    assert req.fiscal_year is None
    assert req.publisher is None
    assert req.is_table is None


def test_retrieve_empty_query_returns_zero_chunks(monkeypatch):
    """retrieve() short-circuits on whitespace queries — sidecar should
    pass the empty result through cleanly with retrieval_id still set
    (the audit log writer relies on its presence)."""
    monkeypatch.setattr(api_module, "retrieve", lambda req, embedder=None: RetrievalResult())
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "   "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks"] == []
    assert body["top_score"] == 0.0
    assert body["retrieval_id"]


def test_retrieve_rejects_malformed_filter_types():
    """fiscal_year must be a list of ints; a string should 422."""
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={"query": "x", "filters": {"fiscal_year": "2027"}},
        )
    assert resp.status_code == 422


def test_retrieve_filters_pass_through_to_pipeline(monkeypatch):
    """Each documented filter dimension reaches RetrievalRequest in the
    correct field. Catches accidental rename / drop bugs."""
    captured: dict = {}

    def fake_retrieve(req, embedder=None):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    payload = {
        "query": "x",
        "filters": {
            "fiscal_year": [2027, 2026],
            "doc_type": ["baseline-cross-cut"],
            "publisher": ["jlbc"],
            "agency_canonical_id": ["agency:ahcccs"],
            "fund_canonical_id": ["fund:ahcccs"],
            "is_table": True,
        },
        "top_k": 7,
    }

    with TestClient(app) as client:
        resp = client.post("/retrieve", json=payload)
    assert resp.status_code == 200

    req = captured["req"]
    assert req.fiscal_year == [2027, 2026]
    assert req.doc_type == ["baseline-cross-cut"]
    assert req.publisher == ["jlbc"]
    assert req.agency_canonical_id == ["agency:ahcccs"]
    assert req.fund_canonical_id == ["fund:ahcccs"]
    assert req.is_table is True
    assert req.top_k == 7


# ---------------------------------------------------------------------------
# Unit tests — /cite/validate (monkeypatched DB)
# ---------------------------------------------------------------------------


def test_cite_validate_rejects_unknown_chunk_id(monkeypatch):
    """`unknown chunk_id` is the dominant hallucination mode; the
    server-side check catches it cleanly so Claude sees the error in
    the tool result and self-corrects."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return None

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "made-up", "span_start": 0, "span_end": 10},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "unknown chunk_id"


def test_cite_validate_rejects_out_of_range_span(monkeypatch):
    """Returns the actual `chunk_text_length` so the model can self-correct."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"len": 50}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 0, "span_end": 100},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"
    assert body["chunk_text_length"] == 50


def test_cite_validate_accepts_valid_span(monkeypatch):
    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"len": 50}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 0, "span_end": 25},
        )

    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == 50


def test_cite_validate_rejects_inverted_span(monkeypatch):
    """span_end <= span_start is structurally invalid; we don't even
    need to know chunk_text_length to reject it. Belt-and-braces case
    in case Pydantic field constraints get relaxed in the future."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"len": 50}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 30, "span_end": 30},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"


# ---------------------------------------------------------------------------
# Integration tests — live DB + live Voyage
# ---------------------------------------------------------------------------


@needs_full_stack
def test_retrieve_against_live_corpus_returns_chunks():
    """Smoke test against the live slice. The Aviation Fund query is
    the canonical retrieval probe — surfaces s18 chunks under the
    bm25+dense+rerank pipeline. Validates that the FastAPI sidecar
    exposes the same behavior as calling retrieve() directly.
    """
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={"query": "Aviation Fund balance", "top_k": 5},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["chunks"]) > 0
    assert body["top_score"] > 0
    assert body["retrieval_id"]
    # doc_title is denormalized from documents — every chunk should have one.
    for c in body["chunks"]:
        assert c["doc_title"], f"chunk {c['chunk_id']} missing doc_title"


@needs_db
def test_cite_validate_against_live_chunk():
    """Pull a real chunk_id from the DB and confirm validate accepts
    a (0, 5) span on it. Catches schema drift between the cite
    endpoint and the chunks table.
    """
    from db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT chunk_id, length(text) AS len FROM chunks LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("chunks table is empty")

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": row["chunk_id"],
                "span_start": 0,
                "span_end": min(5, row["len"]),
            },
        )
    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == row["len"]
