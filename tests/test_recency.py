"""Tests for the post-rerank recency bonus (spec S21, layer 3).

The bonus ships DISABLED (RECENCY_BOOST_PER_YEAR == 0.0) and stays that
way until the S20 backfill exists to calibrate against. So the load-
bearing test here is the no-op one: at weight 0.0 the function must not
change scores OR order, because until Phase D every production retrieval
runs through it.

The other half is the interaction nobody should rediscover the hard way:
boosted scores become `top_score`, and `top_score` is what the refusal
threshold compares against. Turning the weight on without recalibrating
`harness.constants.REFUSAL_THRESHOLD` silently moves the refusal line.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from harness.constants import REFUSAL_THRESHOLD
from retrieval.recency import (
    RECENCY_BOOST_PER_YEAR,
    anchor_fiscal_year,
    apply_recency_boost,
    recency_weight,
)
from retrieval.types import RetrievedChunk


def _chunk(chunk_id: str, *, score: float, fiscal_year: int | None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        text=f"text of {chunk_id}",
        score=score,
        section_path=[],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=[],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=fiscal_year,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


# ---------------------------------------------------------------------------
# It ships CALIBRATED (was: it ships off)
# ---------------------------------------------------------------------------


def test_the_shipped_weight_and_refusal_threshold_move_together():
    """The boost is a PENALTY on age, so switching it on can only lower
    `top_score` — and REFUSAL_THRESHOLD is compared against `top_score`.
    Changing one without the other makes the system refuse more (or less)
    for reasons nobody intended.

    This guard used to assert the weight was 0.0 ("ships inert"). It was
    calibrated on 2026-08-01 (0.0 -> 2.064) and REFUSAL_THRESHOLD moved with
    it (1.9 -> 1.04) in the same change. The pairing is what matters, not
    either number alone, so the test now pins BOTH — a future recalibration
    that touches only one of them fails here.
    """
    assert RECENCY_BOOST_PER_YEAR == 2.064
    assert REFUSAL_THRESHOLD == 1.04


def test_zero_weight_changes_neither_scores_nor_order():
    chunks = [
        _chunk("c1", score=5.0, fiscal_year=2019),
        _chunk("c2", score=4.0, fiscal_year=2027),
        _chunk("c3", score=3.0, fiscal_year=None),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.0)

    assert [c.chunk_id for c in out] == ["c1", "c2", "c3"]
    assert [c.score for c in out] == [5.0, 4.0, 3.0]


def test_zero_weight_does_not_resort_equal_scores():
    """A re-sort at weight 0.0 would still be a behaviour change: ties would
    be re-ordered by the chunk_id tiebreak. 'No-op' means no-op."""
    chunks = [
        _chunk("zzz", score=4.0, fiscal_year=2019),
        _chunk("aaa", score=4.0, fiscal_year=2027),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.0)

    assert [c.chunk_id for c in out] == ["zzz", "aaa"]


# ---------------------------------------------------------------------------
# What it does once it IS on
# ---------------------------------------------------------------------------


def test_the_bonus_is_weight_times_years_from_the_anchor():
    chunks = [
        _chunk("old", score=5.0, fiscal_year=2024),
        _chunk("new", score=5.0, fiscal_year=2027),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.4)
    by_id = {c.chunk_id: c.score for c in out}

    # 0.4 * (2024 - 2027) = -1.2; the anchor year gets exactly 0.
    assert by_id["old"] == pytest.approx(5.0 - 1.2)
    assert by_id["new"] == pytest.approx(5.0)


def test_a_big_enough_bonus_reorders_the_list():
    chunks = [
        _chunk("old", score=5.0, fiscal_year=2024),
        _chunk("new", score=4.5, fiscal_year=2027),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.4)

    assert [c.chunk_id for c in out] == ["new", "old"]


def test_ties_break_on_chunk_id_so_the_order_is_deterministic():
    chunks = [
        _chunk("zzz", score=5.0, fiscal_year=2027),
        _chunk("aaa", score=5.0, fiscal_year=2027),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.4)

    assert [c.chunk_id for c in out] == ["aaa", "zzz"]


def test_an_unstamped_chunk_takes_the_oldest_penalty_in_the_set():
    """A chunk with no fiscal_year must not out-rank a dated one just by
    being undated — 'unknown age' is not 'current'."""
    chunks = [
        _chunk("dated_old", score=5.0, fiscal_year=2020),
        _chunk("undated", score=5.0, fiscal_year=None),
        _chunk("dated_new", score=5.0, fiscal_year=2027),
    ]

    out = apply_recency_boost(chunks, anchor_fy=2027, weight=0.4)
    by_id = {c.chunk_id: c.score for c in out}

    # Oldest fiscal year present is 2020 -> the same -2.8 the 2020 chunk got.
    assert by_id["undated"] == pytest.approx(by_id["dated_old"])
    assert by_id["undated"] < by_id["dated_new"]


def test_an_all_undated_set_is_left_alone():
    """No dated chunk means no meaningful penalty to apply — penalising
    everything identically would only churn the sort order."""
    chunks = [
        _chunk("c1", score=5.0, fiscal_year=None),
        _chunk("c2", score=4.0, fiscal_year=None),
    ]

    out = apply_recency_boost(chunks, anchor_fy=None, weight=0.4)

    assert [c.chunk_id for c in out] == ["c1", "c2"]
    assert [c.score for c in out] == [5.0, 4.0]


def test_an_empty_list_is_returned_empty():
    assert apply_recency_boost([], anchor_fy=2027, weight=0.4) == []


def test_the_input_chunks_are_not_mutated():
    chunks = [_chunk("c1", score=5.0, fiscal_year=2024)]

    apply_recency_boost(chunks, anchor_fy=2027, weight=0.4)

    assert chunks[0].score == 5.0


# ---------------------------------------------------------------------------
# Anchor derivation
# ---------------------------------------------------------------------------


def test_the_anchor_is_the_newest_year_in_the_set_not_the_wall_clock():
    """Corpus-relative by design: on a corpus whose newest edition is
    FY2027, a wall-clock anchor would penalise every chunk in it."""
    chunks = [
        _chunk("c1", score=1.0, fiscal_year=2019),
        _chunk("c2", score=1.0, fiscal_year=2026),
        _chunk("c3", score=1.0, fiscal_year=None),
    ]

    assert anchor_fiscal_year(chunks) == 2026


def test_the_anchor_is_none_when_nothing_is_dated():
    assert anchor_fiscal_year([_chunk("c1", score=1.0, fiscal_year=None)]) is None
    assert anchor_fiscal_year([]) is None


# ---------------------------------------------------------------------------
# Weight injection (used by eval/calibrate_recency.py)
# ---------------------------------------------------------------------------


def test_the_default_weight_is_read_at_call_time():
    """The sweep changes the module global and calls retrieve(); if the
    default were bound at def-time the sweep would silently measure 0.0
    at every step."""
    chunks = [_chunk("c1", score=5.0, fiscal_year=2024)]

    with recency_weight(0.4):
        out = apply_recency_boost(chunks, anchor_fy=2027)

    assert out[0].score == pytest.approx(5.0 - 1.2)


def test_the_weight_context_manager_restores_the_previous_value():
    with recency_weight(0.4):
        pass
    from retrieval import recency

    assert recency.RECENCY_BOOST_PER_YEAR == RECENCY_BOOST_PER_YEAR


def test_the_weight_is_restored_even_when_the_body_raises():
    from retrieval import recency

    with pytest.raises(RuntimeError):
        with recency_weight(0.4):
            raise RuntimeError("sweep step blew up")

    assert recency.RECENCY_BOOST_PER_YEAR == RECENCY_BOOST_PER_YEAR


def test_replace_keeps_every_other_field_intact():
    """apply_recency_boost rewrites only `score`; a chunk that lost its
    bbox or page on the way through would break citation highlighting."""
    original = _chunk("c1", score=5.0, fiscal_year=2024)
    original = replace(original, bbox=[1.0, 2.0, 3.0, 4.0], page=7)

    out = apply_recency_boost([original], anchor_fy=2027, weight=0.4)

    assert out[0].bbox == [1.0, 2.0, 3.0, 4.0]
    assert out[0].page == 7
    assert out[0].text == original.text
