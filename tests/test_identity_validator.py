"""One predicate: does this string look like a name? (spec I3)

Two verdicts, not one. A DECORATION sits at the edge of the string and is
provably additive, so stripping it is deterministic, not a guess. CORRUPTION
sits inside the string, and trimming it IS a guess — those quarantine.

The two deleted rules are pinned here as negatives, because both were in the
first spec draft and both were measured wrong: `AHCCCS` is the only all-caps
stored title in the corpus and it is CORRECT, and every HTML-bearing title is
a fiscal note, where the markup is a rendered feature.
"""
from __future__ import annotations

import pytest

from identity.validator import distinctive_words, validate_name


def test_a_clean_name_passes_untouched():
    v = validate_name("Agriculture, Arizona Department of")
    assert v.ok is True
    assert v.value == "Agriculture, Arizona Department of"
    assert v.stripped is False
    assert v.reason is None


def test_a_leading_bullet_is_a_decoration_and_is_stripped():
    v = validate_name("• General Fund Revenue")
    assert v.ok is True
    assert v.value == "General Fund Revenue"
    assert v.stripped is True


def test_trailing_dot_leaders_and_page_code_are_decorations():
    raw = "• State Personnel Summary by Agency ......................BD-13"
    v = validate_name(raw)
    assert v.ok is True
    assert v.value == "State Personnel Summary by Agency"
    assert v.stripped is True


def test_noise_INSIDE_the_string_quarantines_and_says_why():
    raw = (
        "Osteopathic Examiners in Medicine and Surgery, Arizona ...   342  "
        "Board of........................................"
    )
    v = validate_name(raw)
    assert v.ok is False
    assert "dot leaders" in v.reason


def test_an_embedded_page_number_quarantines():
    v = validate_name("Parents Comm. on Drug Education and Prevention, Arizona  286")
    assert v.ok is False
    assert "page number" in v.reason


def test_a_real_ballot_measure_number_is_NOT_rejected():
    """Measured 2026-08-16: the narrower "any number preceded by a single
    space" version of the page-number rule quarantined this. Proposition 123
    is a real Arizona education-funding measure named verbatim in these
    budget books — a single word-space is how a name legitimately writes a
    number, and only a multi-space TOC column gap should quarantine."""
    v = validate_name("Proposition 123")
    assert v.ok is True
    assert v.value == "Proposition 123"


def test_a_real_law_chapter_number_is_NOT_rejected():
    """Same rejected-rule fixture: "Laws 2008 Ch. 53" is a real citation to
    a session law, not a TOC-scraped page number."""
    v = validate_name("Laws 2008 Ch. 53")
    assert v.ok is True
    assert v.value == "Laws 2008 Ch. 53"


def test_a_real_fiscal_year_number_is_NOT_rejected():
    """Same rejected-rule fixture: "Fiscal Year 2027 Budget" names a real
    fiscal year, not a scraped page number."""
    v = validate_name("Fiscal Year 2027 Budget")
    assert v.ok is True
    assert v.value == "Fiscal Year 2027 Budget"


def test_a_doubled_internal_space_quarantines():
    v = validate_name("Osteopathic Examiners in Medicine and Surgery, Arizona  Board of")
    assert v.ok is False
    assert "doubled space" in v.reason


def test_over_ninety_characters_quarantines():
    v = validate_name("A" + " b" * 60)
    assert v.ok is False
    assert "too long" in v.reason


def test_an_empty_or_blank_string_quarantines():
    assert validate_name("   ").ok is False


# --- the two rules that were MEASURED and REJECTED -------------------------

def test_an_all_caps_acronym_is_NOT_rejected():
    """Measured 2026-08-16: `AHCCCS` is the ONLY all-caps stored title in the
    corpus, and it is correct. An all-caps rule rejects a right answer."""
    assert validate_name("AHCCCS").ok is True


def test_a_slug_title_is_uninformative_but_NOT_rejected():
    """`AXSACUTE` is 20 documents. The audit's own verdict is "uninformative,
    not wrong" — reported by the check, never quarantined."""
    assert validate_name("AXSACUTE").ok is True


def test_html_in_a_fiscal_note_title_is_NOT_rejected():
    """All 240 HTML-bearing titles are fiscal notes, where `<strike>…</strike>
    (NOW: …)` is how an analyst sees an amended bill. Rejecting it would
    quarantine every amended note on the next refresh."""
    raw = "Fiscal Note - HB 2527: <strike>tax subtraction</strike> (NOW: sales tax)"
    assert validate_name(raw).ok is True


# --- distinctive_words -------------------------------------------------
# Controller decision: shared here because two later tasks each need it and
# the plan duplicated its body verbatim in both — one home avoids that drift.

def test_distinctive_words_drops_the_stopword_scaffolding():
    assert distinctive_words("Agriculture, Arizona Department of") == {"agriculture"}


def test_distinctive_words_matches_reordered_names_of_the_same_agency():
    """Same agency, name printed two different ways — the overlap is what lets
    the composer recognize them as one thing without a lookup table."""
    assert distinctive_words("Board of Barbers") & distinctive_words("Barbers Board")


def test_distinctive_words_does_not_match_unrelated_agencies():
    assert not (
        distinctive_words("Board of Barbers")
        & distinctive_words("Agriculture, Arizona Department of")
    )
