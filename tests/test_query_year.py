"""Tests for the query fiscal-year parser (S21 layer 1).

The parser's output becomes a HARD fiscal-year filter, which is why it is
deliberately stricter than the mockup's in-browser engine it was ported
from. In the mockup a wrong guess was harmless — it only added a +0.15
score bump to docs whose fiscal_year matched, so a non-year number lifted
nothing. Here a wrong guess DELETES every other year from the result set.
So: bare two-digit numbers ("26 caseworkers") are NOT read as years, and
digits that sit inside a larger token (bill numbers, dollar amounts) are
never harvested.
"""
from __future__ import annotations

import pytest

from retrieval.query_year import (
    ADJACENT_YEAR_WINDOW,
    MAX_PLAUSIBLE_YEAR,
    MIN_PLAUSIBLE_YEAR,
    fiscal_year_filter,
    parse_jlbc_shorthand,
    parse_query_years,
)


@pytest.mark.parametrize(
    "query,expected",
    [
        # -- forms that ARE years ------------------------------------------
        ("dcs caseworkers fy26", [2026]),
        ("FY 2019 DES funding", [2019]),
        ("fy2019 DES funding", [2019]),
        ("appropriations 2013", [2013]),
        ("FY19 baseline", [2019]),
        ("fy 19 baseline", [2019]),
        ("'19 baseline", [2019]),
        ("’19 baseline", [2019]),  # curly apostrophe — real user paste
        # multiple years, returned sorted ascending and de-duplicated
        ("compare fy24 and fy25", [2024, 2025]),
        ("compare FY 2025 to fy25 spending", [2025]),
        # Ranges are NOT expanded — "through" is not parsed, so the middle
        # year is absent. Documented limitation, not an oversight.
        ("trend from 2019 through 2021", [2019, 2021]),
        # -- forms that are NOT years --------------------------------------
        ("HB2001", []),          # bill number
        ("SB 1001 fiscal note", []),
        # Arizona House bills are numbered from 2001 up, so the SPACED
        # form collides head-on with the plausible-year window. Bill
        # lookup is the fiscal-note corpus's main access path.
        ("HB 2019 fiscal note", []),
        ("HB 2001", []),
        ("H.B. 2026 summary", []),
        ("HCR 2004 analysis", []),
        ("A.R.S. 41-1994", []),          # statute cite
        ("ARS 15-2001 requirements", []),
        ("chapter 2019 laws", []),
        ("$2,019,000 for programs", []),  # dollar amount
        ("26 caseworkers", []),  # bare two-digit — too ambiguous to filter on
        ("chapter 19 of title 41", []),
        ("", []),
        ("   ", []),
        ("ADC General Fund appropriation", []),
    ],
)
def test_parse_query_years(query: str, expected: list[int]) -> None:
    assert parse_query_years(query) == expected


def test_four_digit_years_outside_the_plausible_range_are_dropped() -> None:
    # 1776 and 3000 are not fiscal years anyone is filtering on; harvesting
    # them would empty the result set for a query that merely mentions them.
    assert parse_query_years("since 1776 the state has") == []
    assert parse_query_years("projections to 3000") == []
    assert parse_query_years(f"budget {MIN_PLAUSIBLE_YEAR}") == [MIN_PLAUSIBLE_YEAR]
    assert parse_query_years(f"budget {MAX_PLAUSIBLE_YEAR}") == [MAX_PLAUSIBLE_YEAR]
    assert parse_query_years(f"budget {MIN_PLAUSIBLE_YEAR - 1}") == []
    assert parse_query_years(f"budget {MAX_PLAUSIBLE_YEAR + 1}") == []


def test_two_digit_shorthand_expands_into_the_plausible_range() -> None:
    # "fy84" is FY1984 (data/jlbc-book-catalog.json's oldest edition is
    # approps-fy1984), "fy26" is FY2026. The split point is the plausible
    # range, not a hardcoded 40.
    assert parse_query_years("fy84 appropriations") == [1984]
    assert parse_query_years("fy99 appropriations") == [1999]
    assert parse_query_years("fy00 appropriations") == [2000]
    assert parse_query_years("fy35 appropriations") == [2035]
    # 36..79 expands to neither 19xx nor 20xx inside the plausible range.
    assert parse_query_years("fy50 appropriations") == []


def test_years_are_sorted_ascending_and_deduplicated() -> None:
    assert parse_query_years("fy27 vs fy25 vs FY 2027") == [2025, 2027]


def test_year_digits_inside_a_larger_token_are_never_harvested() -> None:
    # The word-boundary guards are the whole defense against bill numbers
    # and account codes. If one regex loses its \b this test fails.
    for query in ("HB2019", "SB2026-A", "account 42026 balance", "2026A"):
        assert parse_query_years(query) == [], query


def test_a_dollar_amount_that_looks_like_a_year_is_not_a_year() -> None:
    assert parse_query_years("appropriated $2,026,000 to DES") == []
    assert parse_query_years("a $2026 grant") == []


def test_uppercase_and_punctuation_do_not_matter() -> None:
    assert parse_query_years("FY2026?") == [2026]
    assert parse_query_years("(FY 2026)") == [2026]
    assert parse_query_years("FY-2026 spending") == [2026]


# ---------------------------------------------------------------------------
# fiscal_year_filter — named years -> the years actually filtered on
# ---------------------------------------------------------------------------


def test_fiscal_year_filter_admits_the_adjacent_years() -> None:
    """WHY: chunks carry the DOCUMENT's fiscal year, not the year the
    passage is about. A FY 2025 supplemental is enacted in the FY 2026
    budget bill; an exact-year filter drops it and the eval's recall@20
    fell below gate G1 on exactly that shape."""
    assert fiscal_year_filter([2019]) == [2018, 2019, 2020]


def test_fiscal_year_filter_merges_overlapping_windows() -> None:
    assert fiscal_year_filter([2024, 2025]) == [2023, 2024, 2025, 2026]


def test_fiscal_year_filter_of_no_years_is_no_filter() -> None:
    # [] must stay [] — the pipeline reads it as "don't filter at all".
    assert fiscal_year_filter([]) == []


def test_the_window_is_one_year_either_side() -> None:
    # Pinned: ±2 measured no better than filtering nothing at all
    # (recall@5 back to the unfiltered 72.41%), ±0 failed gate G1.
    assert ADJACENT_YEAR_WINDOW == 1


# ---------------------------------------------------------------------------
# parse_jlbc_shorthand — JLBC's own URL convention (spec Q5)
# ---------------------------------------------------------------------------


def test_the_corpus_url_convention_is_understood():
    """azjlbc.gov/26AR/508.pdf and /21baseline/adc.pdf — this is how an
    analyst who lives in these files writes a citation."""
    assert parse_jlbc_shorthand("ahcccs 27ar") == [(2027, "approps-per-agency")]
    assert parse_jlbc_shorthand("adc 21baseline") == [(2021, "baseline-per-agency")]


def test_shorthand_feeds_the_year_parser():
    assert 2027 in parse_query_years("ahcccs 27ar")


def test_shorthand_is_case_insensitive():
    assert parse_jlbc_shorthand("AHCCCS 27AR") == [(2027, "approps-per-agency")]


def test_a_bare_two_digit_number_is_not_shorthand():
    """'27' alone is not a JLBC file reference and must not become FY2027
    here — the existing two-digit rule already governs that case."""
    assert parse_jlbc_shorthand("27 positions") == []


def test_an_implausible_year_is_rejected():
    assert parse_jlbc_shorthand("99ar") == []


def test_a_citation_designator_is_not_read_as_jlbc_shorthand():
    """"chapter 21 baseline" must not become a FY2021 hard filter.

    This one is nastier than a nonsense year: FY2021 baselines EXIST, so the
    pipeline's empty-result fallback never fires and the analyst silently gets
    one year's documents for a question about something else.
    """
    assert parse_jlbc_shorthand("chapter 21 baseline") == []
    assert parse_jlbc_shorthand("laws 2025, chapter 26 ar") == []
    assert 2021 not in parse_query_years("chapter 21 baseline")


def test_the_real_url_convention_still_resolves_after_the_guard():
    """The guard must not cost the shape it exists to serve."""
    assert parse_jlbc_shorthand("ahcccs 27ar") == [(2027, "approps-per-agency")]
    assert parse_jlbc_shorthand("adc 21baseline") == [(2021, "baseline-per-agency")]


def test_the_new_forms_parse_like_jlbcs_own_two():
    # br/afr/exec are OUR additions (Destin, 2026-08-11), not JLBC directory
    # names — analysts asked for them because the published convention only
    # covers two of the corpus's report types.
    assert parse_jlbc_shorthand("dema 26br") == [(2026, "baseline-per-agency")]
    assert parse_jlbc_shorthand("26afr") == [(2026, "afr")]
    assert parse_jlbc_shorthand("27exec") == [(2027, "governors-budget")]


def test_br_and_baseline_are_the_same_report_type():
    assert parse_jlbc_shorthand("26br") == parse_jlbc_shorthand("26baseline")


def test_the_budget_bill_has_no_shorthand():
    # Deliberate (Destin, 2026-08-11): JLBC never published one, and the
    # corpus holds a single budget bill per year — shorthand earns nothing.
    assert parse_jlbc_shorthand("26bill") == []


def test_the_new_forms_keep_the_designator_guard():
    # The guard that stops "chapter 21 baseline" must cover the new forms too,
    # since the regex's optional space applies to all of them equally.
    assert parse_jlbc_shorthand("chapter 26 afr") == []
    assert parse_jlbc_shorthand("laws 2025, chapter 26 br") == []


def test_a_longer_form_is_not_shadowed_by_a_shorter_one():
    # "afr" must not be read as "ar" plus a stray letter, in either
    # alternation order.
    assert parse_jlbc_shorthand("26afr") == [(2026, "afr")]
    assert parse_jlbc_shorthand("26arf") == []
