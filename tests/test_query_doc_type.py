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
            "bh-pdf", "budget-bill", "budget-bill-summary"}
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


def test_the_name_of_a_law_is_not_a_request_for_the_bill():
    """"General Appropriation Act" names the law; analysts discuss what it did
    far more often than they want the bill document.

    Measured 2026-08-02 on the live corpus: the phrase appears in 6,253 chunks
    and ZERO are budget-bill, while the whole budget-bill type is a single
    document. Filtering on it discards every chunk that uses the phrase — and
    it SUCCEEDS, so the pipeline's empty-result fallback never rescues it.
    """
    assert _vals("Which appropriations did the Governor line-item veto from "
                 "the General Appropriation Act?") == []


def test_an_explicit_bill_request_still_resolves():
    """The guard above must not cost the case the type genuinely serves."""
    assert "budget-bill" in _vals("fy2026 budget bill")
    assert "budget-bill" in _vals("the appropriations bill")


def test_budget_bill_summary_resolves_to_its_own_type_not_the_docx_bill():
    """Review Finding 2: 'budget bill summary' used to hard-filter onto
    `budget-bill` (the 136-chunk DOCX feed bill) because 'budget bill' is an
    EXACT phrase and `budget-bill-summary` had no phrase of its own — so the
    longest-phrase rule couldn't rescue it. That silently returned zero rows
    for the summary type (Invariant 3: the pipeline's empty-result fallback
    never fires because the DOCX bill chunks are non-empty)."""
    assert _vals("what did the budget bill summary say about AHCCCS") == [
        "budget-bill-summary"
    ]
    assert _vals("FY2027 budget bill summary") == ["budget-bill-summary"]


def test_plain_budget_bill_still_resolves_to_the_docx_bill():
    """The new, longer phrase must not shadow the existing shorter one for a
    query that genuinely means the enacted bill."""
    assert _vals("fy2026 budget bill") == ["budget-bill"]
