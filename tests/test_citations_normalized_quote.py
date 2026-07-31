"""S23 — normalization-tolerant quote validation.

Models emit quotes that are FAITHFUL to the chunk but differ from it by
formatting artifacts: a smart quote where the PDF had one and the model
typed a straight one, a collapsed newline, a lowercased word, an em dash
retyped as a hyphen, or MinerU's `\\$` escape dropped. Exact-substring
validation called every one of those "quote not found in chunk.text" and
sent the model back around the retry loop for a citation that was never
wrong.

These tests pin the fallback that fixes it, and — more importantly — the
property that makes it safe: **`resolved_span_start` / `resolved_span_end`
always index the ORIGINAL chunk text**, never the normalized form. The
PDF bbox highlight and the cited-text panel both slice `chunk.text` with
those offsets, so a normalized offset leaking out would silently
highlight the wrong words.

Validation gets formatting-tolerant here, never semantically looser:
the quote must still really be in the chunk, and it must still be
unambiguous.
"""
from __future__ import annotations

import pytest

from retrieval.citations import (
    CiteValidateBody,
    validate_cite_against_text,
)


def _cite(quote: str, **over) -> CiteValidateBody:
    return CiteValidateBody(chunk_id="c1", quote=quote, claim_span="a claim", **over)


def _assert_resolves_to(text: str, quote: str, expected: str) -> None:
    """The core property: the resolved span, sliced out of the ORIGINAL
    text, is the passage the model meant to quote."""
    result = validate_cite_against_text(_cite(quote), text, None)
    assert result.ok, result.error
    assert result.resolved_span_start is not None
    assert result.resolved_span_end is not None
    assert text[result.resolved_span_start : result.resolved_span_end] == expected


# ---------------------------------------------------------------------------
# Exact match keeps working exactly as before
# ---------------------------------------------------------------------------


def test_exact_match_is_still_preferred_and_unchanged():
    text = "AHCCCS receives $17,337,200 from the General Fund in FY 2027."
    result = validate_cite_against_text(_cite("$17,337,200 from the General Fund"), text, None)
    assert result.ok
    assert result.resolved_span_start == text.index("$17,337,200")
    assert result.resolved_span_end == result.resolved_span_start + len(
        "$17,337,200 from the General Fund"
    )


def test_exact_duplicate_still_rejected_before_normalization_runs():
    text = "The increase is $5.0 million. Elsewhere the increase is $5.0 million too."
    result = validate_cite_against_text(_cite("$5.0 million"), text, None)
    assert not result.ok
    assert "multiple times" in (result.error or "")


# ---------------------------------------------------------------------------
# The formatting drifts the fallback exists for
# ---------------------------------------------------------------------------


def test_smart_quotes_fold_to_straight_quotes():
    text = 'The committee called it “fully funded” for FY 2027.'
    _assert_resolves_to(text, 'called it "fully funded"', 'called it “fully funded”')


def test_apostrophe_folds():
    text = "The agency’s request was reduced."
    _assert_resolves_to(text, "The agency's request", "The agency’s request")


def test_collapsed_whitespace_matches_across_a_newline():
    text = "AHCCCS receives $17,337,200\n   from the General Fund."
    _assert_resolves_to(
        text,
        "$17,337,200 from the General Fund",
        "$17,337,200\n   from the General Fund",
    )


def test_case_insensitive_match():
    text = "General Fund appropriations total $2.1 billion."
    _assert_resolves_to(text, "GENERAL FUND APPROPRIATIONS", "General Fund appropriations")


def test_em_dash_folds_to_hyphen():
    text = "The FY 2026–2027 biennium carries the increase."
    _assert_resolves_to(text, "FY 2026-2027 biennium", "FY 2026–2027 biennium")


def test_non_breaking_space_folds():
    text = "The total is $5.0\u00a0million this year."
    _assert_resolves_to(text, "$5.0 million", "$5.0\u00a0million")


def test_mineru_dollar_escape_is_tolerated():
    # MinerU emits `\$` so `$…$` is not read as LaTeX math. The model
    # quotes what it SEES rendered, which has no backslash.
    text = "The adjustment is \\$17,337,200 in FY 2027."
    # The span starts at the `$`, NOT at the backslash: the backslash is
    # ingest noise that the PDF text layer does not contain, so including
    # it in the highlight range would push the bbox search off by one.
    _assert_resolves_to(text, "$17,337,200 in FY 2027", "$17,337,200 in FY 2027")


def test_markdown_bold_markers_are_tolerated():
    text = "The increase of **$5.0 million** applies to the operating lump sum."
    _assert_resolves_to(
        text,
        "increase of $5.0 million applies",
        "increase of **$5.0 million** applies",
    )


def test_trailing_period_on_the_quote_does_not_break_the_match():
    text = "Total appropriations are $2.1 billion"
    _assert_resolves_to(text, "$2.1 billion.", "$2.1 billion")


# ---------------------------------------------------------------------------
# THE property most likely to be got subtly wrong
# ---------------------------------------------------------------------------


def test_resolved_offsets_reference_original_text_when_they_differ_from_normalized():
    """A chunk whose leading whitespace collapses hard, so the normalized
    offset of the quote and its ORIGINAL offset cannot coincide.

    If this test ever passes with the normalized offset, the PDF viewer
    highlights the wrong words while reporting success — the exact
    silent-wrong-answer failure Invariant 1 exists to prevent."""
    text = "Section 47.\n\n\n\n\n\n\n\n\n\n     AHCCCS receives $17,337,200 in FY 2027."
    quote = "AHCCCS  receives $17,337,200"  # doubled space -> not an exact match
    result = validate_cite_against_text(_cite(quote), text, None)
    assert result.ok, result.error

    original_index = text.index("AHCCCS")
    normalized_index = "section 47. ahcccs receives $17,337,200 in fy 2027.".index("ahcccs")
    assert original_index != normalized_index  # the test would be vacuous otherwise
    assert result.resolved_span_start == original_index
    assert text[result.resolved_span_start : result.resolved_span_end] == (
        "AHCCCS receives $17,337,200"
    )


def test_resolved_span_end_covers_the_whole_original_run():
    text = "Fund   sources:   $5.0 million"
    result = validate_cite_against_text(_cite("Fund sources: $5.0 million"), text, None)
    assert result.ok, result.error
    assert result.resolved_span_end == len(text)


# ---------------------------------------------------------------------------
# Never semantically looser (Invariant 2 unchanged)
# ---------------------------------------------------------------------------


def test_quote_that_is_genuinely_absent_is_still_rejected():
    text = "AHCCCS receives $17,337,200 from the General Fund."
    result = validate_cite_against_text(_cite("ADC receives $99,000,000"), text, None)
    assert not result.ok
    assert "quote not found" in (result.error or "")


def test_reordered_words_are_still_rejected():
    """Normalization folds FORMATTING. It must never turn a paraphrase
    into a match."""
    text = "The General Fund appropriation is $2.1 billion."
    result = validate_cite_against_text(
        _cite("appropriation of $2.1 billion from the General Fund"), text, None
    )
    assert not result.ok
    assert "quote not found" in (result.error or "")


def test_ambiguity_rejection_applies_after_normalization():
    """Two occurrences that differ only by a smart quote are still two
    occurrences — binding to the first would highlight the wrong one."""
    text = (
        'The board called it “fully funded” in March. '
        'The board called it "fully funded" in June.'
    )
    result = validate_cite_against_text(_cite('called it "FULLY FUNDED"'), text, None)
    assert not result.ok
    assert "multiple times" in (result.error or "")


def test_ambiguity_error_reports_original_positions():
    text = "Increase of $5.0 million. Later: Increase of $5.0 million."
    # Lowercased, so it matches NEITHER occurrence exactly — the
    # normalized path is what has to catch this ambiguity.
    result = validate_cite_against_text(_cite("increase of $5.0 million"), text, None)
    assert not result.ok
    error = result.error or ""
    assert "multiple times" in error
    # Positions must be indices into the ORIGINAL text, so that a model
    # (or a human auditing the transcript) reading them against
    # chunk.text lands on the right characters.
    assert str(text.index("Increase")) in error
    assert str(text.rindex("Increase")) in error


def test_empty_quote_is_rejected():
    result = validate_cite_against_text(_cite(""), "some chunk text", None)
    assert not result.ok
    assert "requires either" in (result.error or "")


# ---------------------------------------------------------------------------
# The downstream sanity checks still apply to a normalized resolution
# ---------------------------------------------------------------------------


def test_span_too_broad_still_fires_on_a_normalized_match():
    from retrieval.citations import SPAN_BREADTH_LIMIT

    body = "word " * (SPAN_BREADTH_LIMIT // 2)
    text = "Header.\n\n" + body
    quote = body.replace("word word", "word  word")  # forces the normalized path
    result = validate_cite_against_text(_cite(quote), text, None)
    assert not result.ok
    assert "span too broad" in (result.error or "")


def test_explicit_offsets_still_win_over_a_quote():
    text = "AHCCCS receives $17,337,200 from the General Fund."
    result = validate_cite_against_text(
        _cite("GENERAL FUND", span_start=0, span_end=6), text, None
    )
    assert result.ok
    assert (result.resolved_span_start, result.resolved_span_end) == (0, 6)
