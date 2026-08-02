"""Tests for the post-rerank weak-match penalty (spec Q4).

The penalty ships DISABLED (MATCH_PENALTY == 0.0) and stays that way until
plan Task 9's eval sweep picks a weight. So the load-bearing tests here are
the no-op one and the shipped-default one: until Task 9 lands, every
production retrieval runs through this function and must come out unchanged.

The other half is the property the whole file exists for: the adjustment is a
PENALTY on non-matching chunks, never a bonus on matching ones. Boosted scores
become `top_score`, and `top_score` is what `REFUSAL_THRESHOLD` compares
against — a bonus-shaped adjustment would inflate it and silently weaken
refusal.
"""
from __future__ import annotations

from retrieval.agency_boost import MATCH_PENALTY, apply_match_penalty
from retrieval.types import RetrievedChunk


def make_chunk(chunk_id: str, *, score: float, agency_ids: list[str]) -> RetrievedChunk:
    """Local helper — there is no shared tests/helpers.py in this repo.

    Modelled on `_chunk` in tests/test_recency.py, which is the house pattern
    for building a RetrievedChunk by hand; this one varies agency ids where
    that one varies fiscal_year.
    """
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        text=f"text of {chunk_id}",
        score=score,
        section_path=[],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=agency_ids,
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2026,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


def test_non_matching_chunks_are_penalised_and_matching_ones_are_untouched():
    """A PENALTY, never a bonus: top_score feeds REFUSAL_THRESHOLD, and
    inflating it would silently weaken refusal."""
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"]),
              make_chunk("b", score=4.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    by_id = {c.chunk_id: c.score for c in out}
    assert by_id["b"] == 4.0          # matching: unchanged
    assert by_id["a"] == 3.0          # non-matching: penalised


def test_the_top_score_can_only_fall():
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    assert max(c.score for c in out) <= 5.0


def test_zero_weight_is_a_no_op_and_does_not_resort():
    chunks = [make_chunk("a", score=4.0, agency_ids=["agency:ade"]),
              make_chunk("b", score=4.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=0.0)
    assert [c.chunk_id for c in out] == ["a", "b"]


def test_no_matches_means_no_change():
    chunks = [make_chunk("a", score=4.0, agency_ids=["agency:ade"])]
    out = apply_match_penalty(chunks, agency_ids=[], doc_types=[], weight=2.0)
    assert [c.score for c in out] == [4.0]


def test_an_unstamped_chunk_is_treated_as_non_matching():
    """20% of the corpus carries no agency stamp. 'We don't know' must not be
    rewarded as 'it matches' — that is how a Governor's budget outranked a
    DEMA query."""
    chunks = [make_chunk("a", score=5.0, agency_ids=[])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    assert out[0].score == 3.0


def test_a_doc_type_criterion_penalises_the_wrong_type():
    """The plan's own tests never exercise doc_types; this one does."""
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=[], doc_types=["afr"], weight=2.0)
    assert out[0].score == 3.0


def test_both_criteria_must_hold_for_a_chunk_to_escape_the_penalty():
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"],
                              doc_types=["afr"], weight=2.0)
    assert out[0].score == 3.0


def test_the_shipped_default_is_a_no_op_until_calibrated():
    """MATCH_PENALTY ships at 0.0 pending an eval sweep. If someone sets it
    without calibrating, REFUSAL_THRESHOLD silently drifts out of tune."""
    assert MATCH_PENALTY == 0.0
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[])
    assert out[0].score == 5.0


def test_results_are_resorted_when_the_penalty_changes_the_order():
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"]),
              make_chunk("b", score=4.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    assert [c.chunk_id for c in out] == ["b", "a"]


def test_an_empty_chunk_list_is_handled():
    assert apply_match_penalty([], agency_ids=["agency:adc"],
                               doc_types=[], weight=2.0) == []
