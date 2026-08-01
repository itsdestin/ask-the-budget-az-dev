"""Tests for the chronological-order metric (spec S21 layer 3, Phase D).

The metric answers Destin's acceptance criterion in one number: "for a
simple inquiry — just an agency name, no year, no topic — results should
feel like they come back in roughly chronological order, newest first."

Everything here is pure arithmetic over year lists. No corpus, no models.
"""
from __future__ import annotations

import pytest

from eval.chronological import (
    CHANCE_RATE,
    fiscal_year_of,
    fiscal_years_of,
    interpret_rate,
    mean_fiscal_year_at_k,
    newest_first_rate,
    order_report,
)
from retrieval.types import RetrievedChunk


# ---------------------------------------------------------------------------
# Reading a fiscal year off a chunk
# ---------------------------------------------------------------------------


def _chunk(chunk_id: str, fiscal_year: int | None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="doc",
        text="",
        score=1.0,
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
        token_count=1,
        publisher="jlbc",
    )


def test_the_metadata_fiscal_year_is_preferred():
    assert fiscal_year_of(_chunk("jlbc-baseline-fy2026-adc-0001", 2026)) == 2026


def test_the_chunk_id_is_the_fallback_when_metadata_is_missing():
    """Ingest has left a handful of chunks with a null fiscal_year. Their
    doc_id-derived chunk_id still carries the edition, and dropping those
    rows would understate how much of the result list is actually dated."""
    assert fiscal_year_of(_chunk("jlbc-baseline-fy2026-adc-0001", None)) == 2026


def test_a_chunk_with_neither_reads_as_undated():
    assert fiscal_year_of(_chunk("hand-upload-0001", None)) is None


def test_plain_dicts_work_too():
    """run_eval normalises chunks to dicts for scoring; the metric has to
    accept the same two shapes or it would only ever run on one path."""
    assert fiscal_year_of({"chunk_id": "x-fy2019-1", "fiscal_year": 2019}) == 2019
    assert fiscal_year_of({"chunk_id": "x-fy2019-1"}) == 2019


def test_a_four_digit_run_that_is_not_a_fiscal_year_stamp_is_ignored():
    """The pattern is anchored on the literal `-fy` prefix so a document
    slug that merely contains four digits (a bill number, a page id)
    cannot be mistaken for an edition."""
    assert fiscal_year_of({"chunk_id": "legislature-hb2026-0001"}) is None


def test_fiscal_years_of_preserves_rank_order():
    chunks = [_chunk("a-fy2027-1", 2027), _chunk("b-fy2010-1", 2010)]
    assert fiscal_years_of(chunks) == [2027, 2010]


# ---------------------------------------------------------------------------
# newest_first_rate — the headline number
# ---------------------------------------------------------------------------


def test_a_perfectly_newest_first_list_scores_one():
    assert newest_first_rate([2027, 2026, 2025, 2024]) == 1.0


def test_an_exactly_backwards_list_scores_zero():
    assert newest_first_rate([2024, 2025, 2026, 2027]) == 0.0


def test_ties_are_excluded_from_the_denominator_not_punished():
    """The load-bearing property. Many chunks share a fiscal year — that
    is the expected shape of this corpus, not a failure of ordering. A
    metric that counted a tie as a miss would cap the achievable score
    at whatever fraction of pairs happened to differ, and the number
    would move when the corpus grew rather than when ranking changed."""
    # Six results, three editions, two chunks each, perfectly grouped.
    assert newest_first_rate([2027, 2027, 2026, 2026, 2025, 2025]) == 1.0


def test_a_list_of_one_single_year_is_undefined_not_perfect():
    """Every pair is tied, so there is no evidence either way. Returning
    1.0 would let a query that retrieved twenty copies of one edition
    inflate the average as if it had ordered them well."""
    assert newest_first_rate([2026, 2026, 2026]) is None


def test_an_empty_or_undated_list_is_undefined():
    assert newest_first_rate([]) is None
    assert newest_first_rate([None, None]) is None


def test_undated_chunks_are_skipped_rather_than_ranked():
    """An undated chunk carries no year evidence, so pairing it with a
    dated one would invent a comparison. Note this differs on purpose
    from apply_recency_boost, which PENALISES undated chunks as if they
    were the oldest — that is a ranking policy; this is a measurement,
    and a measurement must not assert a year it does not know."""
    assert newest_first_rate([2027, None, 2026]) == 1.0


def test_one_element_out_of_place_costs_a_readable_amount():
    # 2026 2027 2025: pairs (2026,2027) discordant, (2026,2025) concordant,
    # (2027,2025) concordant -> 2 of 3.
    assert newest_first_rate([2026, 2027, 2025]) == pytest.approx(2 / 3)


def test_chance_is_one_half_by_construction():
    """Half concordant, half discordant. This is the reference point the
    report prints beside every score: 50% means the ranking carries no
    year signal at all, not that it is 'half right'."""
    assert newest_first_rate([2026, 2027]) == 0.0
    assert newest_first_rate([2027, 2026]) == 1.0
    assert CHANCE_RATE == 0.5


def test_the_rate_counts_all_pairs_not_just_neighbours():
    """A single very old document parked at rank 2 has to cost more than
    one adjacent inversion, because it sits ahead of everything after
    it. Adjacent-pair counting would charge it once."""
    # The FY2005 document at rank 2 is discordant with each of the three
    # newer documents it jumped ahead of -> 3 discordant of 10 pairs.
    assert newest_first_rate([2027, 2005, 2026, 2025, 2024]) == pytest.approx(7 / 10)
    # Adjacent-pair counting would charge that same document exactly once
    # (only the 2027->2005 step is a descent) and score it 3 of 4 = 75%,
    # i.e. BETTER than the all-pairs 70%, which is the wrong direction.
    # Pushing it one rank later must improve the score; under adjacent
    # counting it would not move at all.
    assert newest_first_rate([2027, 2026, 2005, 2025, 2024]) == pytest.approx(8 / 10)


# ---------------------------------------------------------------------------
# mean_fiscal_year_at_k — the companion figure
# ---------------------------------------------------------------------------


def test_mean_fiscal_year_at_k_reads_the_vintage_of_the_top_of_the_list():
    """newest_first_rate measures ORDER and nothing else: 2010, 2009,
    2008 is perfectly ordered and completely useless to an analyst
    asking about an agency today. This second figure is what catches
    that — it says how recent the top of the list actually is."""
    assert mean_fiscal_year_at_k([2010, 2009, 2008], k=3) == pytest.approx(2009.0)
    assert mean_fiscal_year_at_k([2027, 2026, 2025], k=3) == pytest.approx(2026.0)


def test_mean_fiscal_year_at_k_only_looks_at_the_first_k():
    assert mean_fiscal_year_at_k([2027, 2027, 2000, 2000], k=2) == pytest.approx(2027.0)


def test_mean_fiscal_year_at_k_skips_undated_positions():
    assert mean_fiscal_year_at_k([None, 2026, 2024], k=3) == pytest.approx(2025.0)


def test_mean_fiscal_year_at_k_is_undefined_with_nothing_dated():
    assert mean_fiscal_year_at_k([None, None], k=5) is None
    assert mean_fiscal_year_at_k([], k=5) is None


# ---------------------------------------------------------------------------
# order_report — one query in, one row out
# ---------------------------------------------------------------------------


def test_order_report_carries_the_years_so_a_number_can_be_checked_by_eye():
    """Destin's baseline was written as a list of years in rank order.
    The report keeps that list beside the score, because a bare
    percentage is not something a non-developer can sanity-check."""
    chunks = [_chunk("a-fy2027-1", 2027), _chunk("b-fy2025-1", 2025)]

    row = order_report("r-1", "Department of Corrections", chunks)

    assert row.query_id == "r-1"
    assert row.fiscal_years == [2027, 2025]
    assert row.newest_first_rate == 1.0
    assert row.mean_fiscal_year_at_5 == pytest.approx(2026.0)


def test_order_report_survives_a_query_that_returned_nothing():
    row = order_report("r-2", "nonsense", [])

    assert row.fiscal_years == []
    assert row.newest_first_rate is None
    assert row.mean_fiscal_year_at_5 is None


# ---------------------------------------------------------------------------
# interpret_rate — the plain-English gloss
# ---------------------------------------------------------------------------


def test_the_gloss_names_chance_rather_than_calling_it_a_middling_score():
    assert "no year" in interpret_rate(0.50).lower()


def test_the_gloss_distinguishes_the_two_ends():
    assert interpret_rate(0.97) != interpret_rate(0.10)


def test_an_undefined_rate_says_so_instead_of_printing_a_number():
    assert "not measurable" in interpret_rate(None).lower()
