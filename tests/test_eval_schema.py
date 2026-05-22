"""Pydantic schema tests for eval/queries.yaml + eval/results/*.json.

Round-trip tests: parse from dict, serialize back, parse again. If the
schema is correct the second parse equals the first. Catches missing
fields, wrong types, and serialization quirks (e.g., enum vs string).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eval.schema import (
    EvalQuery,
    EvalResult,
    EvalSummary,
    ExpectedChunk,
    PerQueryResult,
    QueryDimensions,
)


def test_query_dimensions_round_trip():
    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    assert dims.publisher == "jlbc"
    assert dims.fiscal_year == 2026
    # Agency is optional (some chunks are cross-agency).
    no_agency = QueryDimensions(
        publisher="jlbc", doc_type="topic", fiscal_year=2026
    )
    assert no_agency.agency is None


def test_expected_chunk_with_anchor_text():
    chunk = ExpectedChunk(
        chunk_id="fy26-jlbc-baseline-ahccs::3",
        dimensions=QueryDimensions(
            publisher="jlbc",
            doc_type="baseline-per-agency",
            fiscal_year=2026,
            agency="agency:ahccs",
        ),
        anchor_text="$2,587,400 from the General Fund",
    )
    assert chunk.chunk_id == "fy26-jlbc-baseline-ahccs::3"
    assert chunk.anchor_text is not None


def test_eval_query_lookup_round_trip():
    """Lookup queries carry expected_chunks; expected_refusal=False."""
    raw = {
        "id": "q-001",
        "query": "What was AHCCCS's FY26 General Fund appropriation?",
        "type": "lookup",
        "expected_chunks": [
            {
                "chunk_id": "fy26-jlbc-baseline-ahccs::3",
                "dimensions": {
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency": "agency:ahccs",
                },
                "anchor_text": "$2,587,400 from the General Fund",
            }
        ],
        "expected_refusal": False,
        "synthesized_by": "claude-opus-4-7",
        "synthesized_at": "2026-05-20T18:00Z",
    }
    q = EvalQuery.model_validate(raw)
    assert q.id == "q-001"
    assert q.type == "lookup"
    assert len(q.expected_chunks) == 1
    # Round-trip back to dict; should be stable.
    again = EvalQuery.model_validate(q.model_dump())
    assert again == q


def test_eval_query_refusal_no_expected_chunks():
    """Refusal queries carry expected_refusal=True and no expected_chunks."""
    raw = {
        "id": "q-031",
        "query": "What's the right tax policy for Arizona?",
        "type": "refusal",
        "expected_refusal": True,
    }
    q = EvalQuery.model_validate(raw)
    assert q.type == "refusal"
    assert q.expected_refusal is True
    assert q.expected_chunks == []


def test_eval_query_rejects_invalid_type():
    """The `type` field is a Literal — non-allowed values must fail."""
    with pytest.raises(ValidationError):
        EvalQuery.model_validate(
            {
                "id": "q-099",
                "query": "x",
                "type": "synthesis",  # not allowed in v1
                "expected_refusal": False,
            }
        )


def test_per_query_result_pass_with_chunk_id_match():
    r = PerQueryResult(
        id="q-001",
        type="lookup",
        status="pass",
        matched_via="chunk_id",
        rank=2,
        latency_ms=850,
        top_score=0.84,
        top_chunk_ids=["fy26-jlbc-baseline-ahccs::3"],
    )
    assert r.status == "pass"
    assert r.matched_via == "chunk_id"


def test_per_query_result_fail_has_no_rank():
    r = PerQueryResult(
        id="q-024",
        type="lookup",
        status="fail",
        latency_ms=920,
        top_score=0.41,
        top_chunk_ids=["different::1", "other::2"],
    )
    assert r.status == "fail"
    assert r.matched_via is None
    assert r.rank is None


def test_per_query_result_round_trip_preserves_none_fields():
    """A fail PerQueryResult has matched_via=None and rank=None. Round-
    tripping through model_dump → model_validate must preserve those
    Nones — otherwise the runner's JSON output would drift the moment
    we reload a saved result."""
    r = PerQueryResult(
        id="q-024",
        type="lookup",
        status="fail",
        latency_ms=920,
        top_score=0.41,
        top_chunk_ids=["different::1", "other::2"],
    )
    again = PerQueryResult.model_validate(r.model_dump())
    assert again == r
    assert again.matched_via is None
    assert again.rank is None


def test_eval_result_full_round_trip():
    """Full EvalResult: summary + per_query list."""
    raw = {
        "git_sha": "cc0dcb2",
        "timestamp": "2026-05-20T18:30Z",
        "summary": {
            "recall_at_5": 0.76,
            "recall_at_20": 0.84,
            "fallback_rate": 0.1,
            "latency_p50_ms": 1200,
            "latency_p95_ms": 2100,
            "refusal_precision": 0.8,
            "refusal_recall": 0.86,
            "by_type": {
                "lookup": {
                    "recall_at_5": 0.83,
                    "recall_at_20": 0.92,
                    "count": 25,
                },
                "comparison": {
                    "recall_at_5": 0.6,
                    "recall_at_20": 0.8,
                    "count": 5,
                },
                "refusal": {"precision": 0.8, "count": 5},
            },
        },
        "per_query": [
            {
                "id": "q-001",
                "type": "lookup",
                "status": "pass",
                "matched_via": "chunk_id",
                "rank": 2,
                "latency_ms": 850,
                "top_score": 0.84,
                "top_chunk_ids": ["fy26-jlbc-baseline-ahccs::3"],
            }
        ],
    }
    result = EvalResult.model_validate(raw)
    again = EvalResult.model_validate(result.model_dump())
    assert again == result
