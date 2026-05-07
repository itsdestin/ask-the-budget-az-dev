"""End-to-end tests for retrieval/pipeline.py.

Mostly integration-style: the pipeline composes BM25 + dense + RRF +
rerank, all of which exercise real systems (Postgres + Voyage). Tests
gate appropriately:
- Empty-query fast-path: pure unit, no DB, no API.
- Live retrieval: requires DATABASE_URL with embedded corpus AND a
  Voyage key (the rerank step is real).
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from db.connection import close_pool
from retrieval.pipeline import (
    BM25_TOP_K,
    DENSE_TOP_K,
    FUSED_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    retrieve,
)

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
        "Pipeline tests need DATABASE_URL with >=50 embedded chunks AND "
        "VOYAGE_API_KEY set (rerank step is real)."
    ),
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Defaults + types
# ---------------------------------------------------------------------------


def test_top_k_defaults_match_spec():
    """Spec §3.4: BM25 top 200, dense top 100, fused top 50, rerank top 20."""
    assert BM25_TOP_K == 200
    assert DENSE_TOP_K == 100
    assert FUSED_TOP_K == 50
    assert RetrievalRequest(query="x").top_k == 20


def test_request_to_filters_round_trip():
    """RetrievalRequest.to_filters() should mirror every filter dimension."""
    req = RetrievalRequest(
        query="anything",
        fiscal_year=[2026, 2027],
        publisher=["jlbc", "agao"],
        agency_canonical_id=["agency:adc"],
        is_table=True,
    )
    filters = req.to_filters()
    assert filters.fiscal_year == [2026, 2027]
    assert filters.publisher == ["jlbc", "agao"]
    assert filters.agency_canonical_id == ["agency:adc"]
    assert filters.is_table is True
    assert filters.fund_canonical_id is None  # unset stays None


# ---------------------------------------------------------------------------
# Empty-query fast path (no DB, no API call)
# ---------------------------------------------------------------------------


def test_empty_query_short_circuits():
    """Whitespace-only query should return an empty result without hitting
    the DB or Voyage. The function must construct neither a connection nor
    an embedder."""
    result = retrieve(RetrievalRequest(query=""))
    assert isinstance(result, RetrievalResult)
    assert result.chunks == []
    assert result.top_score == 0.0
    assert result.bm25_count == 0


def test_empty_query_with_whitespace_short_circuits():
    result = retrieve(RetrievalRequest(query="   \t\n  "))
    assert result.chunks == []


# ---------------------------------------------------------------------------
# End-to-end retrieval against the live stack
# ---------------------------------------------------------------------------


@needs_full_stack
def test_retrieve_returns_top_k_chunks_for_real_query():
    """Plan smoke query: 'aviation fund balance' should retrieve s18 chunks
    via the full pipeline (BM25 + dense + RRF + rerank)."""
    result = retrieve(
        RetrievalRequest(query="Aviation Fund balance", top_k=5)
    )
    assert len(result.chunks) > 0
    assert len(result.chunks) <= 5
    # Reranker scores in [0, 1] descending
    assert result.top_score == result.chunks[0].score
    scores = [c.score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    # Counts populate
    assert result.bm25_count > 0
    assert result.dense_count > 0
    assert result.fused_count > 0
    assert result.fused_count <= FUSED_TOP_K


@needs_full_stack
def test_retrieve_surfaces_s18_for_known_query():
    """At least one s18 chunk should be in the final top-5 for 'Aviation Fund'."""
    result = retrieve(
        RetrievalRequest(query="Aviation Fund balance by agency", top_k=5)
    )
    assert any(
        "jlbc-baseline-fy2027-s18" in c.doc_id for c in result.chunks
    ), f"s18 not in top-5; got {[c.chunk_id for c in result.chunks]}"


@needs_full_stack
def test_retrieve_filter_narrows_to_publisher():
    """publisher filter is applied uniformly across BM25 + dense paths."""
    result = retrieve(
        RetrievalRequest(
            query="appropriation",
            publisher=["legislature"],
            top_k=10,
        )
    )
    assert result.chunks, "no legislature chunks for 'appropriation'"
    assert all(c.publisher == "legislature" for c in result.chunks)


@needs_full_stack
def test_retrieve_top_k_is_respected():
    result = retrieve(RetrievalRequest(query="appropriation", top_k=3))
    assert len(result.chunks) <= 3


@needs_full_stack
def test_retrieve_diagnostic_counts_are_consistent():
    """fused_count <= bm25_count + dense_count (deduped). top-K final
    chunks <= fused_count."""
    result = retrieve(RetrievalRequest(query="fund", top_k=20))
    assert result.fused_count <= result.bm25_count + result.dense_count
    assert len(result.chunks) <= result.fused_count
    assert len(result.reranker_scores) == len(result.chunks)
