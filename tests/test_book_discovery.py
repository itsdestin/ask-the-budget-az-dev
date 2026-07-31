"""Tests for ingest/book_discovery.py — catalog-first, probe-verified."""
from __future__ import annotations

import pytest

from ingest.book_discovery import (
    DiscoveryError,
    EditionPlan,
    list_editions,
    plan_edition,
    walk_edition,
)


class FakeProber:
    """Answers 200 for a fixed URL set; records every call."""

    def __init__(self, live: set[str] | None = None, bodies: dict | None = None):
        self.live = {u.lower() for u in (live or set())}
        self.bodies = bodies or {}
        self.heads: list[str] = []
        self.gets: list[str] = []

    def head(self, url: str) -> bool:
        self.heads.append(url)
        return url.lower() in self.live

    def get(self, url: str) -> bytes:
        self.gets.append(url)
        return self.bodies.get(url, b"%PDF-1.4\n")


class AllLive(FakeProber):
    def head(self, url: str) -> bool:
        self.heads.append(url)
        return True


# --- the picker -------------------------------------------------------------


def test_list_editions_is_newest_first_and_flags_ingestability():
    editions = list_editions()
    assert len(editions) == 62
    assert editions[0]["fiscal_year"] >= editions[-1]["fiscal_year"]
    assert any(e["ingestable"] for e in editions)
    assert any(not e["ingestable"] for e in editions)


def test_list_editions_carries_a_document_count():
    fy2027 = next(e for e in list_editions() if e["key"] == "baseline-fy2027")
    assert fy2027["document_count"] >= 100


# --- catalog hits -----------------------------------------------------------


def test_a_catalog_hit_makes_no_network_calls():
    prober = FakeProber()
    plan = plan_edition("baseline", 2027, prober=prober)
    assert plan.source == "catalog"
    assert prober.heads == [] and prober.gets == []


def test_a_catalog_hit_carries_its_verified_roster():
    plan = plan_edition("baseline", 2027, prober=FakeProber())
    assert len(plan.documents) >= 100
    assert any(d.doc_type == "baseline-per-agency" for d in plan.documents)
    assert any(d.doc_type == "s-pdf" for d in plan.documents)
    assert plan.linked_toc_url.endswith("27baselinelinks.pdf")


def test_walking_a_catalog_plan_is_a_no_op():
    """The catalog roster came from a verified crawl; re-walking would trade a
    known-good answer for a live one that can only be worse."""
    prober = FakeProber()
    plan = plan_edition("approps", 2025, prober=prober)
    before = list(plan.documents)
    walk_edition(plan, prober=prober)
    assert plan.documents == before
    assert prober.gets == []


def test_an_old_edition_with_no_children_says_why():
    plan = plan_edition("approps", 1996, prober=FakeProber())
    assert plan.documents == []
    assert any("did not publish per-agency pages" in n for n in plan.notes)
    assert plan.single_file_url


def test_an_unknown_family_is_rejected():
    with pytest.raises(DiscoveryError):
        plan_edition("baselines", 2027, prober=FakeProber())


# --- probing a new edition --------------------------------------------------


def test_a_catalog_miss_climbs_the_ladder_and_verifies_each_rung():
    live = {
        "https://www.azjlbc.gov/28baseline/agencyindex.pdf",
        "https://www.azjlbc.gov/28baseline/28baselinelinks.pdf",
        "https://www.azjlbc.gov/28baseline/28baselinesinglefile.pdf",
    }
    prober = FakeProber(live)
    plan = plan_edition("baseline", 2028, prober=prober)
    assert plan.source == "probed"
    assert plan.agency_index_url == "https://www.azjlbc.gov/28baseline/agencyindex.pdf"
    assert plan.linked_toc_url.endswith("28baselinelinks.pdf")
    assert plan.single_file_url.endswith("28baselinesinglefile.pdf")
    # Every accepted URL was HEAD-checked first — nothing is guessed.
    assert set(live) <= {u.lower() for u in prober.heads}


def test_the_ladder_falls_through_to_older_naming_conventions():
    live = {"https://www.azjlbc.gov/28baseline/28BaselineAgencyIndex.pdf"}
    plan = plan_edition("baseline", 2028, prober=FakeProber(live))
    assert plan.agency_index_url.endswith("28BaselineAgencyIndex.pdf")


def test_an_edition_that_does_not_exist_raises_with_a_usable_message():
    with pytest.raises(DiscoveryError, match="No FY2028 approps book"):
        plan_edition("approps", 2028, prober=FakeProber(set()))


def test_probing_never_accepts_an_unverified_url():
    """The whole point of the ladder: a 404 rung is not used."""
    prober = FakeProber(set())
    with pytest.raises(DiscoveryError):
        plan_edition("baseline", 2028, prober=prober)
    assert prober.heads  # it did try


# --- walking ----------------------------------------------------------------


def _plan(**over) -> EditionPlan:
    base = dict(family="baseline", fiscal_year=2028, source="probed")
    base.update(over)
    return EditionPlan(**base)


def test_walk_reads_both_indexes(monkeypatch):
    """Per-agency pages and statewide sections are disjoint sets — walking one
    index silently loses half the book."""
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_agency_index", lambda src, cache=None: [
        _agency("axs", "AHCCCS", "https://www.azjlbc.gov/28baseline/axs.pdf"),
    ])
    monkeypatch.setattr(bd, "walk_baseline_links", lambda src, cache=None: [
        _section("s18.pdf", "Summary 18",
                 "https://www.azjlbc.gov/28baseline/s18.pdf", "summary-section"),
    ])
    plan = _plan(
        agency_index_url="https://www.azjlbc.gov/28baseline/agencyindex.pdf",
        linked_toc_url="https://www.azjlbc.gov/28baseline/28baselinelinks.pdf",
    )
    walk_edition(plan, prober=AllLive())
    assert {d.doc_type for d in plan.documents} == {"baseline-per-agency", "s-pdf"}


def test_walk_drops_children_that_do_not_resolve(monkeypatch):
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_agency_index", lambda src, cache=None: [
        _agency("axs", "AHCCCS", "https://www.azjlbc.gov/28baseline/axs.pdf"),
        _agency("gone", "Gone", "https://www.azjlbc.gov/28baseline/gone.pdf"),
    ])
    plan = _plan(agency_index_url="https://www.azjlbc.gov/28baseline/agencyindex.pdf")
    walk_edition(plan, prober=FakeProber(
        {"https://www.azjlbc.gov/28baseline/axs.pdf"}))
    assert [d.code for d in plan.documents] == ["axs"]
    assert plan.unreachable == ["https://www.azjlbc.gov/28baseline/gone.pdf"]


def test_walk_dedupes_case_insensitively(monkeypatch):
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_agency_index", lambda src, cache=None: [
        _agency("axs", "AHCCCS", "https://www.azjlbc.gov/28baseline/axs.pdf"),
        _agency("axs", "AHCCCS", "https://www.azjlbc.gov/28baseline/AXS.pdf"),
    ])
    plan = _plan(agency_index_url="https://www.azjlbc.gov/28baseline/agencyindex.pdf")
    walk_edition(plan, prober=AllLive())
    assert len(plan.documents) == 1


def test_walk_rewrites_dead_hosts(monkeypatch):
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_agency_index", lambda src, cache=None: [
        _agency("axs", "AHCCCS", "http://www.azleg.gov/jlbc/28baseline/axs.pdf"),
    ])
    plan = _plan(agency_index_url="https://www.azjlbc.gov/28baseline/agencyindex.pdf")
    walk_edition(plan, prober=AllLive())
    assert plan.documents[0].url == "https://www.azjlbc.gov/28baseline/axs.pdf"


# --- the rolling /budget/ guard ---------------------------------------------


def test_a_rolling_index_holding_another_years_links_is_rejected(monkeypatch):
    """`/budget/apprpttoc.pdf` has no year in its path. Following it blindly
    would ingest last year's book under this year's label."""
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_approps_toc", lambda src, cache=None: [
        _section("bh1.pdf", "Highlights",
                 "https://www.azjlbc.gov/27ar/bh1.pdf", "budget-highlights"),
        _section("bd1.pdf", "Detail",
                 "https://www.azjlbc.gov/27ar/bd1.pdf", "budget-detail"),
    ])
    plan = _plan(family="approps", fiscal_year=2028,
                 linked_toc_url="https://www.azjlbc.gov/budget/apprpttoc.pdf")
    with pytest.raises(DiscoveryError, match="different year"):
        walk_edition(plan, prober=AllLive())
    assert plan.documents == []


def test_a_rolling_index_holding_this_years_links_is_accepted(monkeypatch):
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_approps_toc", lambda src, cache=None: [
        _section("bh1.pdf", "Highlights",
                 "https://www.azjlbc.gov/28ar/bh1.pdf", "budget-highlights"),
    ])
    plan = _plan(family="approps", fiscal_year=2028,
                 linked_toc_url="https://www.azjlbc.gov/budget/apprpttoc.pdf")
    walk_edition(plan, prober=AllLive())
    assert [d.doc_type for d in plan.documents] == ["bh-pdf"]


def test_an_unconfirmable_rolling_index_says_so_instead_of_guessing(monkeypatch):
    import ingest.book_discovery as bd

    monkeypatch.setattr(bd, "walk_approps_toc", lambda src, cache=None: [
        _section("bh1.pdf", "Highlights",
                 "https://www.azjlbc.gov/budget/bh1.pdf", "budget-highlights"),
    ])
    plan = _plan(family="approps", fiscal_year=2028,
                 linked_toc_url="https://www.azjlbc.gov/budget/apprpttoc.pdf")
    walk_edition(plan, prober=AllLive())
    assert any("could not be confirmed" in n for n in plan.notes)


# --- fixtures ---------------------------------------------------------------


def _agency(slug, name, url):
    from ingest.discovery import AgencyIndexEntry
    return AgencyIndexEntry(slug=slug, name=name, url=url, page_in_doc=None)


def _section(filename, title, url, kind):
    from ingest.discovery import BaselineLinksEntry
    return BaselineLinksEntry(title=title, filename=filename, url=url,
                              section_kind=kind, page_in_doc=None)
