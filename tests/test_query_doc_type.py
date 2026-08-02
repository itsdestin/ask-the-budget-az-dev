"""Tests for the query document-type parser (spec Q1).

Same safety story as the year parser: an EXACT match becomes a HARD
`doc_type` filter, and `doc_type` is the one filter dimension where a wrong
value is silently fatal — there is no fuzzy fallback in LanceDB, so a value
the corpus does not use returns zero rows. Hence the two properties pinned
hardest here: longest phrase wins (so "appropriations report" is never read
as a bare "report"), and nothing but the ten real corpus values is ever
emitted.
"""
from __future__ import annotations

from retrieval.query_doc_type import parse_query_doc_types
from retrieval.query_match import Confidence


def _vals(q):
    return [m.value for m in parse_query_doc_types(q)]


def test_baseline_resolves():
    assert "baseline-per-agency" in _vals("ahcccs baseline")


def test_appropriations_report_resolves():
    assert "approps-per-agency" in _vals("ahcccs appropriations report")


def test_approps_report_shorthand_resolves():
    assert "approps-per-agency" in _vals("ahcccs approps report")


def test_afr_resolves_and_is_not_confused_with_ar():
    assert _vals("agao afr") == ["afr"]
    assert "afr" not in _vals("dema ar")


def test_bare_ar_is_weak_because_it_is_two_letters():
    ms = parse_query_doc_types("dema ar")
    assert [m.value for m in ms] == ["approps-per-agency"]
    assert ms[0].confidence is Confidence.WEAK


def test_executive_budget_resolves():
    assert "governors-budget" in _vals("governor's executive budget fy2027")


def test_a_query_naming_no_type_returns_nothing():
    assert parse_query_doc_types("ahcccs provider rates") == []


def test_longest_phrase_wins_over_a_substring():
    """'appropriations report' must not be shadowed by a bare 'report'."""
    ms = parse_query_doc_types("ahcccs appropriations report")
    assert [m.value for m in ms] == ["approps-per-agency"]


def test_a_multi_word_phrase_is_exact():
    ms = parse_query_doc_types("ahcccs appropriations report")
    assert ms[0].confidence is Confidence.EXACT


def test_only_real_doc_type_values_are_ever_emitted():
    """A value the corpus does not use would hard-filter to zero results."""
    real = {"approps-per-agency", "baseline-per-agency", "detailed-list-pdf",
            "governors-budget", "s-pdf", "afr", "bd-pdf", "topic-pdf",
            "bh-pdf", "budget-bill"}
    for q in ["baseline", "appropriations report", "afr", "executive budget",
              "budget bill", "detailed list", "annual financial report"]:
        for m in parse_query_doc_types(q):
            assert m.value in real, f"{q!r} emitted {m.value!r}"


def test_shorthand_yields_the_document_type_too():
    assert "approps-per-agency" in _vals("ahcccs 27ar")


def test_shorthand_doc_type_is_exact_unlike_bare_ar():
    """The '27' suffix disambiguates what a bare 'ar' cannot."""
    ms = parse_query_doc_types("ahcccs 27ar")
    assert ms[0].confidence is Confidence.EXACT
