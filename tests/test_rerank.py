"""Tests for retrieval/rerank.py.

Two tiers:
- Unit tests with mock voyageai.Client — verifies the wrapper plumbing,
  no API calls.
- Live Voyage test — gated on VOYAGE_API_KEY, skips otherwise.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from retrieval.rerank import (
    DEFAULT_RERANK_MODEL,
    DEFAULT_RERANK_TOP_K,
    rerank_chunks,
)
from retrieval.types import RetrievedChunk

needs_voyage_key = pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="VOYAGE_API_KEY not set",
)


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="d1",
        text=text,
        score=0.0,
        section_path=[],
        page=1,
        bbox=[0.0, 0.0, 1.0, 1.0],
        source_anchor=None,
        agency_canonical_ids=[],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


def _mock_voyage_client(scored_indices: list[tuple[int, float]]) -> MagicMock:
    """Build a MagicMock voyageai.Client that returns scored_indices.

    `scored_indices` is a list of (original_index, relevance_score) tuples
    in the order Voyage would return them (descending score).
    """
    client = MagicMock()

    def _rerank(query, documents, model, top_k):
        results = []
        for original_idx, rel_score in scored_indices[:top_k]:
            r = MagicMock()
            r.index = original_idx
            r.relevance_score = rel_score
            results.append(r)
        response = MagicMock()
        response.results = results
        return response

    client.rerank.side_effect = _rerank
    return client


# ---------------------------------------------------------------------------
# Edge cases — no API call needed
# ---------------------------------------------------------------------------


def test_rerank_empty_candidates_returns_empty():
    """No candidates means no rerank call needed."""
    result = rerank_chunks("any query", [])
    assert result == []


def test_rerank_empty_query_returns_truncated_passthrough():
    """Empty query: return candidates unchanged, capped at top_k. Avoids a
    Voyage call when there's nothing semantic to rank against."""
    candidates = [_chunk(f"c{i}", f"text {i}") for i in range(5)]
    result = rerank_chunks("", candidates, top_k=3)
    assert len(result) == 3
    assert result[0].chunk_id == "c0"  # input order preserved


def test_rerank_no_client_no_api_key_raises(monkeypatch):
    """Without a client and without VOYAGE_API_KEY, instantiation must fail
    loudly rather than make a half-configured request."""
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    candidates = [_chunk("c0", "x")]
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        rerank_chunks("query", candidates, client=None)


# ---------------------------------------------------------------------------
# Plumbing tests with mock client
# ---------------------------------------------------------------------------


def test_rerank_reorders_by_voyage_response():
    """Voyage's response dictates the output order, not the input order.
    Verify rerank_chunks consumes response.results[i].index correctly."""
    candidates = [_chunk(f"c{i}", f"text {i}") for i in range(4)]
    # Voyage thinks c2 is most relevant, then c0, then c3 (skipping c1).
    client = _mock_voyage_client([(2, 0.95), (0, 0.7), (3, 0.4)])

    result = rerank_chunks("query", candidates, top_k=4, client=client)

    assert [c.chunk_id for c in result] == ["c2", "c0", "c3"]
    # Scores in returned chunks reflect Voyage's relevance_score, not the input.
    assert result[0].score == 0.95
    assert result[1].score == 0.7
    assert result[2].score == 0.4


def test_rerank_passes_query_documents_model_and_top_k_to_client():
    candidates = [_chunk("c0", "text 0"), _chunk("c1", "text 1")]
    client = _mock_voyage_client([(1, 0.9), (0, 0.3)])

    rerank_chunks(
        "find relevant docs",
        candidates,
        top_k=5,
        model="rerank-2.5",
        client=client,
    )

    # MagicMock side_effect call_args: positional + kw
    call = client.rerank.call_args
    assert call.kwargs["query"] == "find relevant docs"
    assert call.kwargs["documents"] == ["text 0", "text 1"]
    assert call.kwargs["model"] == "rerank-2.5"
    assert call.kwargs["top_k"] == 5


def test_rerank_default_model_and_top_k_match_constants():
    """Defaults match DEFAULT_RERANK_MODEL + DEFAULT_RERANK_TOP_K."""
    candidates = [_chunk("c0", "x")]
    client = _mock_voyage_client([(0, 0.5)])

    rerank_chunks("q", candidates, client=client)

    call_kwargs = client.rerank.call_args.kwargs
    assert call_kwargs["model"] == DEFAULT_RERANK_MODEL
    assert call_kwargs["top_k"] == DEFAULT_RERANK_TOP_K


def test_rerank_preserves_chunk_metadata_only_replaces_score():
    """Each returned chunk has the original metadata; only `.score` is new."""
    rich = RetrievedChunk(
        chunk_id="c0",
        doc_id="doc-rich",
        text="rich text",
        score=0.0,
        section_path=["A", "B"],
        page=42,
        bbox=[1.0, 2.0, 3.0, 4.0],
        source_anchor=None,
        agency_canonical_ids=["agency:adc"],
        fund_canonical_id="fund:general",
        fund_mentions=["fund:general"],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=True,
        table_html="<table/>",
        token_count=99,
        publisher="jlbc",
    )
    client = _mock_voyage_client([(0, 0.88)])

    result = rerank_chunks("q", [rich], client=client)
    out = result[0]
    assert out.score == 0.88
    assert out.section_path == ["A", "B"]
    assert out.page == 42
    assert out.agency_canonical_ids == ["agency:adc"]
    assert out.is_table is True
    assert out.table_html == "<table/>"


# ---------------------------------------------------------------------------
# Live Voyage test
# ---------------------------------------------------------------------------


@needs_voyage_key
def test_rerank_live_against_known_relevance_ordering():
    """Send 4 deliberately mixed-relevance chunks to the real reranker;
    the most-on-topic chunk should rank #1."""
    candidates = [
        _chunk("noise1", "Pizza recipe with mozzarella and basil"),
        _chunk("noise2", "Soccer match results from last weekend"),
        _chunk(
            "answer",
            "The Department of Corrections received a $1.74B General Fund "
            "appropriation in FY 2025 for inmate housing and operations.",
        ),
        _chunk("noise3", "Climate report for the Pacific Northwest"),
    ]
    result = rerank_chunks(
        "What was the FY 2025 General Fund appropriation for the Department of Corrections?",
        candidates,
        top_k=4,
    )
    assert result[0].chunk_id == "answer", (
        f"expected 'answer' to rank #1; got {[c.chunk_id for c in result]}"
    )
    # Real reranker scores in [0, 1]
    assert all(0.0 <= c.score <= 1.0 for c in result)
