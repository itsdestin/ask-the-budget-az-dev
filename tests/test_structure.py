"""The structural-quality measure (spec X1/X2/X3).

Pure text analysis -- no corpus, no models, no extractor output. Every
number here comes from the 2026-08-13 calibration recorded in the spec.
"""
from __future__ import annotations

import pytest

from ingest.structure import (
    MAX_UNLABELLED,
    STRUCTURE_TIE_BAND,
    choose_best,
    is_unlabelled,
    unlabelled_fraction,
)

# A real flagged chunk, verbatim from `agao-afr-fy2024-0033` (page 10):
# 0 letters of 697 non-whitespace characters.
BARE = (
    "34,863,017 34,863,017    -34,863,017    - - 4,423,700    -4,423,700  "
    "  - - 1,415,900    -1,415,900    - - 151,400    -151,400    - - "
    "1,661,900    -1,661,900    - - 924,400    -924,400    -"
)

# A MinerU table chunk: heading, then tab-joined rows. Heavy tab padding is
# exactly what made the naive (whitespace-counting) form score healthy AFR
# chunks at 5.5-12.9%.
LABELLED_TABLE = (
    "STATE OF ARIZONA GENERAL FUND\n"
    "NET APPROPRIATIONS\tEXPENDITURES\tLAPSED AUTHORITY\n"
    "\t200,000\t200,000\t\t\n\t1,000,000\t1,000,000\t\t\n"
)


def test_a_bare_figure_run_is_unlabelled():
    assert is_unlabelled(BARE) is True


def test_tab_padded_labelled_text_is_labelled():
    """The whitespace case the naive form gets wrong."""
    assert is_unlabelled(LABELLED_TABLE) is False


def test_a_short_chunk_is_not_judged_at_all():
    """Under MIN_JUDGED_CHARS the answer is None -- never False, which
    would claim a measurement that was not taken."""
    assert is_unlabelled("1,234") is None


def test_a_chunk_of_pure_whitespace_is_not_judged():
    assert is_unlabelled(" " * 200) is None


def test_markup_is_stripped_before_measuring():
    """A no-op on chunk text as the pipeline produces it today -- table
    markup lives on `chunk.table_html`, never in `chunk.text`. This is a
    guard against a future reader that stops parsing tables, NOT a fix for
    a defect that exists (spec X1)."""
    tagged = "<table><tr><td>" + BARE + "</td></tr></table>"
    assert is_unlabelled(tagged) is True


def test_fewer_than_ten_judged_chunks_yields_None():
    """The small-denominator trap: without this, 14 documents of 2-5 chunks
    score >= 15% because one numeric chunk out of three reads as 33%."""
    assert unlabelled_fraction([BARE] * 9) is None


def test_the_fraction_is_bare_over_judged():
    texts = [BARE] * 3 + [LABELLED_TABLE] * 7
    assert unlabelled_fraction(texts) == pytest.approx(0.3)


def test_unjudgeable_chunks_are_excluded_from_the_denominator():
    """Short chunks must not dilute the score toward zero."""
    texts = [BARE] * 3 + [LABELLED_TABLE] * 7 + ["1,234"] * 50
    assert unlabelled_fraction(texts) == pytest.approx(0.3)


def test_a_clean_document_measures_zero_not_None():
    assert unlabelled_fraction([LABELLED_TABLE] * 12) == 0.0


def test_structure_beats_coverage_inside_the_band():
    """The real measured pair: OpenDataLoader 49.03% coverage / 30.63%
    unlabelled against MinerU 44.77% / 0.00%. MinerU wins."""
    assert choose_best([(0.4903, 0.3063), (0.4477, 0.0)]) == 1


def test_structure_does_NOT_beat_coverage_outside_the_band():
    """The silent quarter-document guard. A perfectly clean attempt that
    recovered a quarter of the text loses to a tripped attempt that
    recovered all of it -- 0.12 / 0.49 = 0.24, far below the band."""
    assert choose_best([(0.49, 0.30), (0.12, 0.0)]) == 0


def test_the_band_edge_is_inclusive():
    """0.75 exactly is INSIDE the band."""
    assert choose_best([(0.40, 0.30), (0.30, 0.0)]) == 1


def test_just_outside_the_band_loses():
    assert choose_best([(0.40, 0.30), (0.29, 0.0)]) == 0


def test_coverage_breaks_a_structural_tie():
    """Preserves today's behaviour where structure says nothing."""
    assert choose_best([(0.44, 0.0), (0.49, 0.0)]) == 1


def test_an_unjudgeable_attempt_is_ranked_by_coverage():
    """`None` unlabelled means the attempt had too few judged chunks. It
    does not participate in structural ranking (spec X3)."""
    assert choose_best([(0.49, None), (0.44, None)]) == 0


def test_every_attempt_unjudgeable_still_returns_the_best_coverage():
    assert choose_best([(0.20, None), (0.90, None), (0.50, None)]) == 1


def test_an_unmeasurable_coverage_does_not_win_by_default():
    """`None` coverage is a scan-shaped accept, not a high score."""
    assert choose_best([(None, 0.0), (0.44, 0.0)]) == 1


def test_a_mixed_band_excludes_the_none_unlabelled_candidate():
    """Catches deleting the `unlabelled is not None` guard in choose_best's
    band filter. With both candidates' `unlabelled` real, `(0.49, None)
    and (0.44, None)`-shaped tests can't observe the guard at all --
    `None == None` lets the tie-break fall through to coverage regardless.
    Here index 1's `unlabelled` is real (0.10) and index 0's is `None`, so
    only a MIXED band exercises the clause: with the guard, index 0 never
    enters the band and index 1 wins on coverage (0.50) alone. Delete the
    guard and index 0 (cov 0.45, 90% of best) joins the band too -- its
    `(None, -0.45)` tie-break key then has to compare against index 1's
    `(0.10, -0.50)`, and `None < 0.10` raises TypeError, since `None` and
    `0.10` are unequal and Python cannot order them."""
    assert choose_best([(0.50, 0.10), (0.45, None)]) == 0


def test_an_empty_band_does_not_let_an_unmeasurable_coverage_win():
    """Drives an EMPTY band -- unlike `test_an_unmeasurable_coverage_does_
    not_win_by_default` above, where index 1 alone satisfies the band
    filter and the function returns from the BAND branch without ever
    evaluating the fallback. Here every measured coverage is exactly 0.0,
    so `best_coverage > 0` is false for every candidate and the band is
    empty regardless of the sentinel; only the fallback's own max() picks
    the winner. Catches changing the fallback's `-1.0` sentinel for a
    `None` coverage to a positive value like `999.0`, which would let an
    unmeasurable coverage beat a real measured 0.0."""
    assert choose_best([(None, 0.0), (0.0, 0.0)]) == 1


def test_choose_best_rejects_an_empty_candidate_list():
    """Asserts the GUARD's own message, not just the exception type.
    `max(range(0), key=...)` independently raises `ValueError: max()
    iterable argument is empty` once band and fallback both run on zero
    candidates, so a type-only assertion passes even after the explicit
    `if not candidates: raise ValueError(...)` guard is deleted."""
    with pytest.raises(ValueError, match="requires at least one candidate"):
        choose_best([])


def test_the_ceiling_is_a_ceiling():
    """Documented as an executable statement so a future `<=` typo fails
    here rather than silently inverting the gate."""
    assert MAX_UNLABELLED == 0.20
    assert 0.3063 > MAX_UNLABELLED   # the known-degraded document trips
    assert 0.0714 < MAX_UNLABELLED   # the highest healthy document does not
    assert STRUCTURE_TIE_BAND == 0.75
