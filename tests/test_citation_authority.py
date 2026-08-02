"""Authority ranking tests.

81% of ambiguity is the same figure appearing in several editions of the
same material. The analyst's rule — audited actuals beat enacted, enacted
beats proposed — resolves it deterministically, so the primary citation
is the one an analyst would have chosen.
"""
from __future__ import annotations

from citation.authority import rank_hits
from citation.matching import SourceHit


def hit(chunk_id):
    return SourceHit(chunk_id, "1,000,000", 0, 9, 1)


def test_afr_outranks_approps_outranks_baseline_outranks_governor():
    hits = [hit("g"), hit("b"), hit("a"), hit("f")]
    meta = {
        "g": {"doc_type": "governors-budget", "fiscal_year": 2026},
        "b": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
        "a": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
        "f": {"doc_type": "afr", "fiscal_year": 2026},
    }
    assert [h.chunk_id for h in rank_hits(hits, meta)] == ["f", "a", "b", "g"]


def test_matching_fiscal_year_wins_within_the_same_authority():
    hits = [hit("old"), hit("new")]
    meta = {
        "old": {"doc_type": "approps-per-agency", "fiscal_year": 2024},
        "new": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
    }
    ranked = rank_hits(hits, meta, prefer_fiscal_year=2026)
    assert ranked[0].chunk_id == "new"


def test_authority_beats_fiscal_year():
    # A figure confirmed in the audited FY2025 AFR outranks the same figure
    # in a FY2026 proposal even when the question is about FY2026.
    hits = [hit("proposal"), hit("audited")]
    meta = {
        "proposal": {"doc_type": "governors-budget", "fiscal_year": 2026},
        "audited": {"doc_type": "afr", "fiscal_year": 2025},
    }
    ranked = rank_hits(hits, meta, prefer_fiscal_year=2026)
    assert ranked[0].chunk_id == "audited"


def test_unknown_doc_type_ranks_last_but_is_kept():
    hits = [hit("weird"), hit("known")]
    meta = {
        "weird": {"doc_type": "something-new", "fiscal_year": 2026},
        "known": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
    }
    ranked = rank_hits(hits, meta)
    assert [h.chunk_id for h in ranked] == ["known", "weird"]


def test_missing_metadata_does_not_crash():
    ranked = rank_hits([hit("a")], {})
    assert [h.chunk_id for h in ranked] == ["a"]


def test_ranking_is_stable_for_equal_authority():
    hits = [hit("first"), hit("second")]
    meta = {
        "first": {"doc_type": "afr", "fiscal_year": 2025},
        "second": {"doc_type": "afr", "fiscal_year": 2025},
    }
    assert [h.chunk_id for h in rank_hits(hits, meta)] == ["first", "second"]


def test_every_doc_type_the_live_corpus_serves_has_an_authority():
    # Measured against the 2026-08-02 baseline's retrieve results: these
    # nine doc_types are everything the corpus actually returns. An
    # unranked type sinks to last SILENTLY, which would quietly demote a
    # whole publisher's documents below a Governor's proposal. If a new
    # doc_type is registered, it must be placed here deliberately.
    from citation.authority import _AUTHORITY

    live = {
        "baseline-per-agency", "approps-per-agency", "s-pdf",
        "governors-budget", "topic-pdf", "detailed-list-pdf", "bh-pdf",
        "budget-bill", "afr",
    }
    assert live <= set(_AUTHORITY), sorted(live - set(_AUTHORITY))
