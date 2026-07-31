"""Tests for the recency-weight calibration sweep (spec S21, plan Task 4).

Everything here runs against a synthetic corpus: `eval.run_eval.retrieve`
is replaced by a fake that holds a handful of fixed chunks and applies
the real `apply_recency_boost` to them. No LanceDB, no ONNX weights.

That fake is doing real work, not just returning canned rows — it reads
the module-level weight the same way the pipeline does, which is the
only way to prove the sweep's weight injection reaches retrieval at all.
A sweep that silently measured weight 0.0 at every step would look
perfectly healthy and recommend the wrong number.
"""
from __future__ import annotations

import pytest

from eval import run_eval
from eval.calibrate_recency import (
    G1_RECALL_AT_15,
    GRID_STEPS,
    EmptyQuerySetError,
    load_calibration_sets,
    recommend_weight,
    split_by_named_year,
    sweep_weights,
    weights_from_spread,
)
from eval.schema import EvalQuery
from retrieval.pipeline import RetrievalResult
from retrieval.recency import RECENCY_BOOST_PER_YEAR, apply_recency_boost
from retrieval.types import RetrievedChunk


# ---------------------------------------------------------------------------
# Synthetic corpus
# ---------------------------------------------------------------------------


def _chunk(chunk_id: str, *, score: float, fiscal_year: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{fiscal_year}",
        text="provider rate increase",
        score=score,
        section_path=[],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=["agency:axs"],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=fiscal_year,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


def _query(qid: str, text: str, chunk_id: str, fiscal_year: int) -> EvalQuery:
    return EvalQuery.model_validate(
        {
            "id": qid,
            "query": text,
            "type": "lookup",
            "expected_chunks": [
                {
                    "chunk_id": chunk_id,
                    "dimensions": {
                        "publisher": "jlbc",
                        "doc_type": "baseline-per-agency",
                        "fiscal_year": fiscal_year,
                        "agency": "agency:axs",
                    },
                    "anchor_text": "provider rate increase",
                }
            ],
            "expected_refusal": False,
        }
    )


@pytest.fixture()
def synthetic_corpus(monkeypatch):
    """Twenty editions of the same page — the shape the S20 backfill
    creates. The fake reranker likes the OLDEST one best, so the newest
    edition sits at rank 20 (outside recall@15) until a recency boost
    lifts it. That is the exact failure S21 layer 3 exists to fix."""
    editions = [
        _chunk(f"c-{fy}", score=5.0 - 0.1 * (fy - 2008), fiscal_year=fy)
        for fy in range(2008, 2028)
    ]

    def fake_retrieve(req, **kwargs):
        from retrieval.query_year import fiscal_year_filter, parse_query_years
        from retrieval.recency import anchor_fiscal_year

        named = parse_query_years(req.query)
        allowed = fiscal_year_filter(named)
        rows = [c for c in editions if not allowed or c.fiscal_year in allowed]
        # Same stage order as retrieval/pipeline.py: rank the whole pool,
        # boost, THEN trim. A fixture that trimmed first would model a
        # rescue the real pipeline cannot perform, and the sweep would be
        # calibrating against fiction.
        rows = sorted(rows, key=lambda c: (-c.score, c.chunk_id))
        if not named:
            rows = apply_recency_boost(rows, anchor_fy=anchor_fiscal_year(rows))
        rows = rows[: req.top_k]
        return RetrievalResult(
            chunks=rows,
            top_score=rows[0].score if rows else -1e9,
            reranker_scores=[c.score for c in rows],
            inferred_fiscal_years=named,
        )

    monkeypatch.setattr(run_eval, "retrieve", fake_retrieve)
    return editions


# ---------------------------------------------------------------------------
# Splitting the calibration set
# ---------------------------------------------------------------------------


def test_the_split_is_by_whether_the_query_names_a_year():
    """Split by the SAME parser retrieval uses, so the sweep's idea of
    'this one is year-filtered' can never disagree with the pipeline's."""
    queries = [
        _query("h-1", "fy2014 ADC private prison per diem", "c-2014", 2014),
        _query("n-1", "what is the AHCCCS provider rate increase", "c-2027", 2027),
    ]

    no_year, historical = split_by_named_year(queries)

    assert [q.id for q in no_year] == ["n-1"]
    assert [q.id for q in historical] == ["h-1"]


def test_an_empty_calibration_file_is_an_error_with_an_explanation(tmp_path):
    """The file ships empty on purpose until the S20 backfill lands. A
    sweep over nothing would print a confident recommendation of 0.0."""
    path = tmp_path / "queries_historical.yaml"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(EmptyQuerySetError) as excinfo:
        load_calibration_sets(str(path))

    assert "backfill" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# The weight grid
# ---------------------------------------------------------------------------


def test_the_grid_starts_at_zero_and_is_derived_from_the_score_spread():
    weights = weights_from_spread(5.0)

    assert weights[0] == 0.0
    assert len(weights) == GRID_STEPS + 1
    # Ceiling = spread / 5: at that weight a five-year gap is worth the
    # whole within-query score spread, i.e. enough to reorder anything.
    assert weights[-1] == pytest.approx(1.0)


def test_the_grid_is_ascending_so_minimal_means_first():
    weights = weights_from_spread(5.0)
    assert weights == sorted(weights)


def test_a_degenerate_spread_still_yields_the_zero_weight():
    """Every query returning identically-scored chunks is pathological,
    but it must not produce an empty grid — 0.0 is always measurable."""
    assert weights_from_spread(0.0) == [0.0]


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_the_sweep_injects_the_weight_into_real_retrieval(synthetic_corpus):
    """The load-bearing test. The fake corpus's reranker prefers the
    OLDEST edition, so a no-year query can only find the FY2027 chunk if
    the swept weight actually reached apply_recency_boost."""
    no_year = [_query("n-1", "what is the provider rate increase", "c-2027", 2027)]

    table = sweep_weights(
        current=[], no_year=no_year, historical=[], weights=[0.0, 1.0]
    )

    assert table[0]["no_year_recall_at_15"] == 0.0
    assert table[1]["no_year_recall_at_15"] == 1.0


def test_the_sweep_restores_the_module_weight_afterwards(synthetic_corpus):
    from retrieval import recency

    sweep_weights(
        current=[],
        no_year=[_query("n-1", "provider rate increase", "c-2027", 2027)],
        historical=[],
        weights=[0.0, 1.0],
    )

    assert recency.RECENCY_BOOST_PER_YEAR == RECENCY_BOOST_PER_YEAR


def test_historical_queries_are_invariant_across_the_sweep(synthetic_corpus):
    """They name a year, so layer 1 filters them and layer 3 is skipped.
    If this column ever moves, the skip rule is broken — which is the
    whole reason the sweep measures it."""
    historical = [_query("h-1", "fy2024 provider rate increase", "c-2024", 2024)]

    table = sweep_weights(
        current=[], no_year=[], historical=historical, weights=[0.0, 0.5, 1.0]
    )

    recalls = {row["historical_recall_at_15"] for row in table}
    assert recalls == {1.0}
    assert all(row["historical_invariant"] for row in table)


# ---------------------------------------------------------------------------
# The recommendation
# ---------------------------------------------------------------------------


def _row(weight, current, no_year, *, invariant=True):
    return {
        "weight": weight,
        "current_recall_at_15": current,
        "current_recall_at_20": current,
        "no_year_recall_at_15": no_year,
        "no_year_recall_at_20": no_year,
        "historical_recall_at_15": 1.0,
        "historical_invariant": invariant,
    }


def test_the_recommendation_is_the_smallest_weight_clearing_both_bars():
    table = [
        _row(0.0, 1.0, 0.20),
        _row(0.2, 1.0, 0.80),
        _row(0.4, 1.0, 1.00),
        _row(0.6, 1.0, 1.00),
    ]

    assert recommend_weight(table)["weight"] == 0.4


def test_a_weight_that_breaks_the_current_set_is_not_recommended():
    """The boost is not allowed to buy no-year recall with regressions on
    the set that gates G1 today."""
    table = [
        _row(0.0, 1.0, 0.20),
        _row(0.2, G1_RECALL_AT_15 - 0.05, 1.00),
        _row(0.4, 1.0, 1.00),
    ]

    assert recommend_weight(table)["weight"] == 0.4


def test_no_recommendation_when_nothing_clears_the_bars():
    """Returning the least-bad weight would look like a pass. The sweep
    says 'none' and the operator decides."""
    table = [_row(0.0, 1.0, 0.20), _row(0.4, 1.0, 0.30)]

    assert recommend_weight(table) is None


def test_a_weight_that_moved_the_historical_set_is_never_recommended():
    table = [_row(0.4, 1.0, 1.0, invariant=False), _row(0.6, 1.0, 1.0)]

    assert recommend_weight(table)["weight"] == 0.6
