"""Tests for eval/run_eval.py.

The runner's retrieve() call is mocked. Real retrieval-against-corpus
integration is exercised manually in Task 7 Step 5 (first real eval
run).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from eval.run_eval import (
    load_queries,
    run_one_query,
)


def test_load_queries_parses_fixture_yaml():
    path = pathlib.Path(__file__).parent / "fixtures" / "eval_queries_sample.yaml"
    queries = load_queries(str(path))
    assert len(queries) == 2
    assert queries[0].id == "q-001"
    assert queries[0].type == "lookup"
    assert queries[1].type == "refusal"


def test_run_one_query_lookup_pass(monkeypatch):
    """A lookup query whose expected chunk is at rank 1 → pass at K=5."""
    from eval.run_eval import run_one_query
    from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions

    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id="chunk-A",
                dimensions=QueryDimensions(
                    publisher="jlbc",
                    doc_type="baseline-per-agency",
                    fiscal_year=2026,
                    agency="agency:ahccs",
                ),
            )
        ],
        expected_refusal=False,
    )

    def fake_retrieve(req, **_):
        # The real retrieve() takes a RetrievalRequest; mocks accept it
        # via the `req` positional. Returning plain dicts is fine —
        # _chunk_to_dict in run_one_query passes them through.
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "chunk-A",
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency_canonical_ids": ["agency:ahccs"],
                    "score": 0.82,
                }
            ],
            top_score=0.82,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "pass"
    assert result.matched_via == "chunk_id"
    assert result.rank == 1
    assert result.top_score == 0.82


def test_run_one_query_lookup_fail(monkeypatch):
    """Lookup query whose expected chunk doesn't appear → fail."""
    from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions

    query = EvalQuery(
        id="q-024",
        query="x",
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id="chunk-A",
                dimensions=QueryDimensions(
                    publisher="jlbc",
                    doc_type="baseline-per-agency",
                    fiscal_year=2026,
                    agency="agency:ahccs",
                ),
            )
        ],
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "other-chunk",
                    "publisher": "agao",
                    "doc_type": "afr",
                    "fiscal_year": 2024,
                    "agency_canonical_ids": [],
                    "score": 0.41,
                }
            ],
            top_score=0.41,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "fail"
    assert result.matched_via is None
    assert result.rank is None


def test_run_one_query_refusal_pass(monkeypatch):
    """Refusal query where top_score < threshold → pass (correctly
    declined)."""
    from eval.schema import EvalQuery

    query = EvalQuery(
        id="q-031",
        query="What's the right tax policy?",
        type="refusal",
        expected_refusal=True,
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "weakly-related",
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency_canonical_ids": [],
                    "score": 0.18,
                }
            ],
            top_score=0.18,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "pass"


def test_run_one_query_refusal_fail(monkeypatch):
    """Refusal query where top_score >= threshold → fail (model would
    have answered, but should have refused)."""
    from eval.schema import EvalQuery

    query = EvalQuery(
        id="q-032", query="x", type="refusal", expected_refusal=True
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(chunks=[], top_score=0.55)

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "fail"


def test_write_json_output(tmp_path):
    """The JSON writer emits a file readable by EvalResult.model_validate."""
    from eval.run_eval import write_json_output
    from eval.schema import EvalSummary, PerQueryResult

    summary = EvalSummary(
        recall_at_5=0.8,
        recall_at_20=0.9,
        fallback_rate=0.1,
        latency_p50_ms=1000,
        latency_p95_ms=2000,
        refusal_precision=1.0,
        refusal_recall=1.0,
        by_type={
            "lookup": {"recall_at_5": 0.83, "recall_at_20": 0.92, "count": 1},
            "refusal": {"precision": 1.0, "count": 1},
        },
    )
    per_query = [
        PerQueryResult(
            id="q-001",
            type="lookup",
            status="pass",
            matched_via="chunk_id",
            rank=2,
            latency_ms=850,
            top_score=0.84,
            top_chunk_ids=["chunk-A"],
        )
    ]
    out_path = tmp_path / "result.json"
    write_json_output(
        out_path,
        git_sha="abc1234",
        timestamp="2026-05-20T18:30Z",
        summary=summary,
        per_query=per_query,
    )

    # Round-trip the file: write then re-load via EvalResult.
    with open(out_path) as f:
        loaded = json.load(f)
    from eval.schema import EvalResult
    result = EvalResult.model_validate(loaded)
    assert result.git_sha == "abc1234"
    assert result.summary.recall_at_5 == 0.8
    assert len(result.per_query) == 1


def test_write_md_output_includes_metrics_and_failures(tmp_path):
    """The MD writer produces a human-readable summary with the key
    metrics + a per-failure analysis section."""
    from eval.run_eval import write_md_output
    from eval.schema import EvalSummary, PerQueryResult

    summary = EvalSummary(
        recall_at_5=0.8,
        recall_at_20=0.9,
        fallback_rate=0.1,
        latency_p50_ms=1000,
        latency_p95_ms=2000,
        refusal_precision=1.0,
        refusal_recall=1.0,
        by_type={
            "lookup": {"recall_at_5": 0.83, "recall_at_20": 0.92, "count": 2}
        },
    )
    per_query = [
        PerQueryResult(
            id="q-001",
            type="lookup",
            status="pass",
            matched_via="chunk_id",
            rank=2,
            latency_ms=850,
            top_score=0.84,
            top_chunk_ids=["chunk-A"],
        ),
        PerQueryResult(
            id="q-024",
            type="lookup",
            status="fail",
            latency_ms=920,
            top_score=0.41,
            top_chunk_ids=["unrelated::1", "unrelated::2"],
        ),
    ]
    out_path = tmp_path / "result.md"
    write_md_output(
        out_path,
        git_sha="abc1234",
        timestamp="2026-05-20T18:30Z",
        summary=summary,
        per_query=per_query,
        previous=None,
    )
    content = out_path.read_text()
    assert "recall@5" in content.lower()
    assert "80%" in content or "0.80" in content
    # Failures section lists q-024.
    assert "q-024" in content
    # Top chunks for the failure are shown for diagnosis.
    assert "unrelated::1" in content


def test_compute_delta_vs_previous():
    """compute_delta returns a dict of metric deltas + per-query
    pass/fail transitions."""
    from eval.run_eval import compute_delta
    from eval.schema import EvalSummary, PerQueryResult

    prev_summary = EvalSummary(
        recall_at_5=0.7, recall_at_20=0.85,
        fallback_rate=0.1, latency_p50_ms=1100, latency_p95_ms=1900,
        refusal_precision=0.8, refusal_recall=0.8,
        by_type={},
    )
    curr_summary = EvalSummary(
        recall_at_5=0.8, recall_at_20=0.85,
        fallback_rate=0.1, latency_p50_ms=1000, latency_p95_ms=2000,
        refusal_precision=1.0, refusal_recall=1.0,
        by_type={},
    )
    prev_per_query = [
        PerQueryResult(
            id="q-001", type="lookup", status="pass",
            latency_ms=900, top_score=0.8, top_chunk_ids=[]
        ),
        PerQueryResult(
            id="q-019", type="lookup", status="fail",
            latency_ms=1000, top_score=0.3, top_chunk_ids=[]
        ),
    ]
    curr_per_query = [
        PerQueryResult(
            id="q-001", type="lookup", status="pass",
            latency_ms=850, top_score=0.84, top_chunk_ids=[]
        ),
        PerQueryResult(
            id="q-019", type="lookup", status="pass",
            latency_ms=950, top_score=0.7, top_chunk_ids=[]
        ),
    ]
    delta = compute_delta(
        curr_summary, prev_summary, curr_per_query, prev_per_query
    )
    assert delta["recall_at_5_delta"] == pytest.approx(0.1)
    assert "q-019" in delta["new_passes"]
    assert delta["new_failures"] == []
