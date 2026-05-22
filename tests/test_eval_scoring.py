"""Pure-function tests for eval/scoring.py.

Scoring lives in pure functions (no DB, no I/O) so it's trivially
testable. All functions take simple dicts and Pydantic models, return
tuples or floats.
"""
from __future__ import annotations

from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions
from eval.scoring import (
    aggregate_metrics,
    chunk_matches_expected,
    score_comparison,
    score_lookup,
    score_refusal,
)


def _expected(
    chunk_id: str,
    publisher: str = "jlbc",
    doc_type: str = "baseline-per-agency",
    fiscal_year: int = 2026,
    agency: str = "agency:ahccs",
) -> ExpectedChunk:
    return ExpectedChunk(
        chunk_id=chunk_id,
        dimensions=QueryDimensions(
            publisher=publisher,
            doc_type=doc_type,
            fiscal_year=fiscal_year,
            agency=agency,
        ),
    )


def _retrieved_chunk(
    chunk_id: str,
    publisher: str = "jlbc",
    doc_type: str = "baseline-per-agency",
    fiscal_year: int = 2026,
    agency: str = "agency:ahccs",
) -> dict:
    """Mirror the shape `retrieve()` returns per chunk (the fields
    relevant to dimension matching)."""
    return {
        "chunk_id": chunk_id,
        "publisher": publisher,
        "doc_type": doc_type,
        "fiscal_year": fiscal_year,
        # The DB column is `agency_canonical_ids TEXT[]`; the API
        # surface flattens to whatever the chunk stamps to. For tests
        # we pass a list to mirror reality.
        "agency_canonical_ids": [agency],
    }


def test_chunk_matches_chunk_id_exact():
    expected = _expected("abc::1")
    retrieved = _retrieved_chunk("abc::1")
    assert chunk_matches_expected(retrieved, expected) == "chunk_id"


def test_chunk_matches_dimensions_fallback():
    """chunk_id differs (likely re-ingest renamed it) but dimensions
    still match → fallback."""
    expected = _expected("abc::1", agency="agency:ahccs")
    retrieved = _retrieved_chunk("xyz::5", agency="agency:ahccs")
    assert chunk_matches_expected(retrieved, expected) == "dimensions_fallback"


def test_chunk_no_match_when_dimensions_differ():
    expected = _expected("abc::1", agency="agency:ahccs")
    retrieved = _retrieved_chunk("xyz::5", agency="agency:doa")
    assert chunk_matches_expected(retrieved, expected) is None


def test_chunk_matches_when_expected_agency_none():
    """When the expected dimensions don't constrain agency, any
    returned chunk satisfying the other three fields matches."""
    expected = ExpectedChunk(
        chunk_id="topic::3",
        dimensions=QueryDimensions(
            publisher="jlbc", doc_type="topic", fiscal_year=2026
        ),
    )
    retrieved = _retrieved_chunk(
        "topic::3", doc_type="topic", agency="agency:anything"
    )
    assert chunk_matches_expected(retrieved, expected) == "chunk_id"


def test_score_lookup_pass_at_rank_1():
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    retrieved = [_retrieved_chunk("abc::1"), _retrieved_chunk("other::1")]
    status, matched_via, rank = score_lookup(query, retrieved, k=5)
    assert status == "pass"
    assert matched_via == "chunk_id"
    assert rank == 1


def test_score_lookup_fail_when_not_in_top_k():
    """Lookup query whose expected chunk is at rank 6 fails at K=5."""
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    # "other" chunks must NOT share dimensions with the expected chunk,
    # otherwise the dimensions_fallback path inside chunk_matches_expected
    # would rescue them and the lookup would pass at rank 1.
    retrieved = [
        _retrieved_chunk(f"other::{i}", agency=f"agency:other-{i}")
        for i in range(5)
    ] + [_retrieved_chunk("abc::1")]
    status, matched_via, rank = score_lookup(query, retrieved, k=5)
    assert status == "fail"
    assert matched_via is None
    assert rank is None


def test_score_lookup_pass_at_rank_6_with_k_20():
    """Same lookup with K=20 passes."""
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    # Same dimension-mismatch requirement as above: the expected chunk
    # should be matched at exactly rank 6, not rank 1 via fallback.
    retrieved = [
        _retrieved_chunk(f"other::{i}", agency=f"agency:other-{i}")
        for i in range(5)
    ] + [_retrieved_chunk("abc::1")]
    status, matched_via, rank = score_lookup(query, retrieved, k=20)
    assert status == "pass"
    assert rank == 6


def test_score_comparison_requires_all_expected_chunks():
    """Comparison query passes only if ALL expected chunks are in top K."""
    query = EvalQuery(
        id="q-014",
        query="x",
        type="comparison",
        expected_chunks=[
            _expected("fy24::1", fiscal_year=2024),
            _expected("fy25::1", fiscal_year=2025),
        ],
    )
    # Both present → pass.
    retrieved = [
        _retrieved_chunk("fy24::1", fiscal_year=2024),
        _retrieved_chunk("fy25::1", fiscal_year=2025),
    ]
    status, _, _ = score_comparison(query, retrieved, k=5)
    assert status == "pass"

    # Only one present → fail.
    retrieved_partial = [_retrieved_chunk("fy24::1", fiscal_year=2024)]
    status, _, rank = score_comparison(query, retrieved_partial, k=5)
    assert status == "fail"
    assert rank is None


def test_score_refusal_passes_when_top_score_below_threshold():
    """Refusal queries pass when retrieval correctly declined."""
    query = EvalQuery(
        id="q-031", query="x", type="refusal", expected_refusal=True
    )
    assert score_refusal(query, top_score=0.15, threshold=0.30) == "pass"
    assert score_refusal(query, top_score=0.45, threshold=0.30) == "fail"


def test_aggregate_metrics_recall_at_k():
    """Aggregate computes recall as passes / total per K."""
    per_query = [
        # 3 lookups, 2 pass at K=5
        _make_per_query("q-1", "lookup", "pass", rank=2, top_score=0.8),
        _make_per_query("q-2", "lookup", "pass", rank=4, top_score=0.7),
        _make_per_query("q-3", "lookup", "fail", top_score=0.4),
        # 2 comparisons, 1 pass at K=5
        _make_per_query(
            "q-4", "comparison", "pass", rank=3, top_score=0.6
        ),
        _make_per_query("q-5", "comparison", "fail", top_score=0.5),
        # 2 refusals, both pass
        _make_per_query("q-6", "refusal", "pass", top_score=0.1),
        _make_per_query("q-7", "refusal", "pass", top_score=0.2),
    ]
    summary = aggregate_metrics(per_query, k_values=[5, 20])
    # Lookups + comparisons count toward recall@K (5 retrieval queries,
    # 3 pass).
    assert summary.recall_at_5 == 3 / 5
    # Refusal precision: 2 of 2 refusal-type queries passed.
    assert summary.refusal_precision == 1.0
    # by_type contains the per-type subdicts.
    assert summary.by_type["lookup"]["count"] == 3


def _make_per_query(
    id: str,
    type: str,
    status: str,
    rank: int | None = None,
    top_score: float = 0.5,
) -> dict:
    """Test helper — builds a PerQueryResult-shaped dict."""
    from eval.schema import PerQueryResult

    return PerQueryResult(
        id=id,
        type=type,
        status=status,
        matched_via="chunk_id" if status == "pass" else None,
        rank=rank,
        latency_ms=1000,
        top_score=top_score,
        top_chunk_ids=[],
    )
