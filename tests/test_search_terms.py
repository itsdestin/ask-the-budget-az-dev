"""Per-document search terms for the Budget Documents filter box.

Typing "dema" or "ema" returns 0 documents without these; both are already
reviewed vocabulary (a curated alias in samples/entity-catalog.yaml, and the
agency's own JLBC URL slug). See
docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md.
"""
from __future__ import annotations

from app.search_terms import search_terms


def test_a_per_agency_document_carries_its_slug_and_reviewed_aliases():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert "ema" in terms      # the JLBC URL slug
    assert "dema" in terms     # the reviewed alias — what an analyst says


def test_a_document_carries_its_type_shorthand_bare_and_year_prefixed():
    terms = search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)
    # Bare forms filter too (Destin, 2026-08-11): "pick 2026 in the rail,
    # type br".
    assert {"br", "baseline", "26br", "26baseline"} <= set(terms)


def test_the_budget_bill_gets_no_type_shorthand():
    assert search_terms("jlbc-budget-bill-fy2026", "budget-bill", 2026) == []


def test_a_raw_slug_doc_type_gets_no_type_shorthand():
    # s-pdf/bd-pdf/topic-pdf have no curated family and no shorthand.
    assert search_terms("jlbc-s-fy2027-01", "s-pdf", 2027) == []


def test_suppressed_and_ambiguous_aliases_never_become_terms():
    # "for" is Forestry's slug and SUPPRESSED; "bar" is the Board of Barbers'
    # and AMBIGUOUS. Both are ordinary English before they are agencies, and
    # both were measured against 247,607 tokens of real budget prose.
    assert "for" not in search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "bar" not in search_terms("jlbc-baseline-fy2026-bar", "baseline-per-agency", 2026)


def test_the_carve_out_survives_suppression():
    # D7: the lists were measured against document PROSE. In a box labelled
    # "Agency or keyword", "dot" is as unambiguous as "dema".
    #
    # The two arrive by different routes, verified against the catalog
    # 2026-08-11: "dot" IS Transportation's slug, while "doc" is a reviewed
    # ALIAS on Corrections, whose slug is "adc". Hence the two doc_ids.
    assert "dot" in search_terms("jlbc-baseline-fy2026-dot", "baseline-per-agency", 2026)
    assert "doc" in search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)


def test_an_alias_survives_its_agencys_slug_being_suppressed():
    # Forestry's slug "for" is SUPPRESSED, but its reviewed alias "dffm" is on
    # no list. The agency stays findable by the acronym an analyst actually
    # types — suppression removes a STRING, not an agency.
    terms = search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "for" not in terms
    assert "dffm" in terms


def test_an_ambiguous_agency_contributes_nothing():
    # agency:gov is demoted across every tier in retrieval — in a budget
    # question "the Governor" names a document or an actor far more often
    # than the Office of the Governor's own budget.
    assert "gov" not in search_terms("jlbc-baseline-fy2026-gov", "baseline-per-agency", 2026)


def test_an_unknown_trailing_segment_yields_no_agency_terms():
    # The FY2005-2012 sub-unit pages (adeassis, axsacute) have no catalog
    # entry. They must still list, and still match by title — their titles
    # ARE the slug uppercased.
    terms = search_terms("jlbc-approps-fy2005-adeassis", "approps-per-agency", 2005)
    assert "adeassis" not in terms
    assert "05ar" in terms  # the type shorthand still applies


def test_the_year_prefixed_form_stops_below_the_conventions_floor():
    # The shorthand is a 20xx-only convention (see _SHORTHAND_MIN_YEAR).
    terms = search_terms("jlbc-baseline-fy1998-adc", "baseline-per-agency", 1998)
    assert "98br" not in terms
    assert "br" in terms  # the bare form is ours and has no such floor


def test_a_missing_fiscal_year_still_yields_the_bare_form():
    terms = search_terms("jlbc-baseline-adc", "baseline-per-agency", None)
    assert "br" in terms
    assert not any(t[0].isdigit() for t in terms)


def test_terms_are_lowercase_sorted_and_unique():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert terms == sorted(set(terms))
    assert all(t == t.lower() for t in terms)


def test_an_unreadable_catalog_degrades_to_no_agency_terms(monkeypatch):
    # Same failure posture as budget_doc_ids: never take the page down.
    def boom(*_a, **_kw):
        raise OSError("catalog unreadable")

    monkeypatch.setattr("app.search_terms._catalog_by_slug", boom)
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert "ema" not in terms
    assert "26ar" in terms  # the type shorthand needs no catalog
