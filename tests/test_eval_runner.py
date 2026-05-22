"""Tests for eval/run_eval.py.

The runner's retrieve() call is mocked. Real retrieval-against-corpus
integration is exercised manually in Task 7 Step 5 (first real eval
run).
"""
from __future__ import annotations

import pathlib

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
