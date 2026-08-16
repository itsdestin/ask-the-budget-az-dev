"""Tests for scripts/build_book_catalog.py and the committed catalog.

The counts here are PINS, not estimates: they come from a real crawl of
azjlbc.gov (2026-06-16) that verified every URL. If one changes, the harvest
changed, and that's a fact worth failing a build over.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from scripts.build_book_catalog import (
    BOTH_FORMATS_FROM,
    CHILDREN_FROM,
    build_catalog,
    normalize_url,
)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "jlbc-book-catalog.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def editions(catalog) -> dict:
    return catalog["editions"]


def _by_family(editions: dict) -> Counter:
    return Counter(e["family"] for e in editions.values())


# --- edition inventory ------------------------------------------------------


def test_committed_catalog_has_the_pinned_edition_counts(editions):
    assert _by_family(editions) == {"approps": 41, "baseline": 21}


def _without_row_titles(editions: dict) -> dict:
    """Deep-copy `editions` with every per_agency/summary_sections `title`
    blanked out, so a title-only difference from the harvest doesn't fail
    the comparison below."""
    out = copy.deepcopy(editions)
    for entry in out.values():
        for key in ("per_agency", "summary_sections"):
            for row in entry.get(key, []):
                row.pop("title", None)
    return out


def test_the_builder_reproduces_the_committed_catalog(editions):
    """The generated file must be exactly what the script produces — otherwise
    a hand-edit could ship URLs the harvest never verified.

    WHY `title` is excluded from this comparison (2026-08-16): titles now
    have TWO legitimate sources layered on top of each other. `build_catalog()`
    still reproduces the raw harvest's title for every row — necessarily,
    since it has no access to the corpus — but the COMMITTED file's titles
    are then corrected by `scripts/repair_supplier_titles.py`, which
    overwrites them from the corpus's own (content-derived, already-repaired)
    `documents.json`. That script is what fixed the harvest's actual defect:
    `05app/bar.pdf` (the Board of Barbers) was recorded under the title of
    the row above it, "Agriculture, Arizona Department of" —
    `tests/test_book_catalog.py::test_no_edition_has_two_agencies_sharing_a_title`
    is the regression guard for that. This test's own remaining job — no
    hand-edited URL, code, era_note, or any other harvest field ships
    unverified — is unweakened, because only `title` is stripped before the
    comparison below; a hand-edited URL still fails it exactly as before.
    """
    assert _without_row_titles(build_catalog()["editions"]) == _without_row_titles(editions)


def test_edition_keys_and_shape(editions):
    for key, entry in editions.items():
        assert re.fullmatch(r"(approps|baseline)-fy\d{4}", key)
        assert set(entry) == {
            "family", "fiscal_year", "single_file_url", "linked_toc_url",
            "agency_index_url", "per_agency", "summary_sections",
            "ingestable", "rolling", "era_note",
        }
        assert key == f"{entry['family']}-fy{entry['fiscal_year']}"


def test_approps_span_the_harvested_years(editions):
    years = sorted(e["fiscal_year"] for e in editions.values()
                   if e["family"] == "approps")
    assert years[0] == 1984 and years[-1] == 2026
    assert 2000 not in years and 2001 not in years   # the known gap


def test_baseline_spans_the_harvested_years(editions):
    years = sorted(e["fiscal_year"] for e in editions.values()
                   if e["family"] == "baseline")
    assert years[0] == 2007 and years[-1] == 2027


def test_known_gaps_are_recorded_not_silent(catalog):
    text = " ".join(catalog["known_gaps"])
    assert "FY2000" in text and "FY2001" in text
    assert "FY2027" in text and "Appropriations" in text


# --- children ---------------------------------------------------------------


def test_children_only_exist_from_the_pinned_years(editions):
    for entry in editions.values():
        has_children = bool(entry["per_agency"] or entry["summary_sections"])
        if has_children:
            assert entry["fiscal_year"] >= CHILDREN_FROM[entry["family"]]


def test_every_year_in_range_has_children(editions):
    for family, first in CHILDREN_FROM.items():
        years = [e["fiscal_year"] for e in editions.values()
                 if e["family"] == family and e["per_agency"]]
        assert min(years) == first


def test_ingestable_means_there_is_something_to_ingest(editions):
    for entry in editions.values():
        assert entry["ingestable"] == bool(
            entry["per_agency"] or entry["summary_sections"]
        )


def test_both_full_report_formats_exist_from_the_pinned_years(editions):
    for family, first in BOTH_FORMATS_FROM.items():
        both = sorted(
            e["fiscal_year"] for e in editions.values()
            if e["family"] == family and e["linked_toc_url"] and e["single_file_url"]
        )
        assert min(both) == first


def test_a_recent_baseline_carries_its_full_agency_roster(editions):
    entry = editions["baseline-fy2027"]
    assert len(entry["per_agency"]) >= 100
    assert any(a["code"] == "axs" for a in entry["per_agency"])
    assert entry["linked_toc_url"].endswith("27baselinelinks.pdf")


# --- URL hygiene ------------------------------------------------------------


def test_no_url_points_at_a_dead_host(editions):
    for entry in editions.values():
        urls = [entry["single_file_url"], entry["linked_toc_url"],
                entry["agency_index_url"]]
        urls += [c["url"] for c in entry["per_agency"]]
        urls += [s["url"] for s in entry["summary_sections"]]
        for url in urls:
            assert url is None or "azleg" not in url.lower()


def test_normalize_rewrites_both_dead_hosts():
    assert normalize_url("http://www.azleg.gov/jlbc/25ar/axs.pdf") == \
        "https://www.azjlbc.gov/25ar/axs.pdf"
    assert normalize_url("https://www.azleg.state.az.us/jlbc/06app/axsadmn.pdf") == \
        "https://www.azjlbc.gov/06app/axsadmn.pdf"


def test_normalize_never_re_encodes_a_url():
    """One AFR URL only resolves double-encoded; 'cleaning' it breaks it."""
    weird = "https://www.azjlbc.gov/25ar/a%2520b.pdf"
    assert normalize_url(weird) == weird


def test_urls_are_deduped_case_insensitively(editions):
    """IIS is case-insensitive, so .../AXS.pdf and .../axs.pdf are one file."""
    for entry in editions.values():
        for field in ("per_agency", "summary_sections"):
            lowered = [i["url"].lower() for i in entry[field]]
            assert len(lowered) == len(set(lowered))


# --- the agency-index leak --------------------------------------------------


def test_agency_index_pdfs_are_evidence_not_sections(editions):
    """9 agency-index PDFs leaked into summary-corpus.json titled 'INDIVIDUAL
    AGENCY INDEX…'. They're the index, not content — used to locate children,
    excluded from the sections list."""
    indexed = [e for e in editions.values() if e["agency_index_url"]]
    assert len(indexed) == 9
    for entry in editions.values():
        for section in entry["summary_sections"]:
            assert "agencyindex" not in section["url"].lower()
            assert "INDIVIDUAL AGENCY INDEX" not in section["title"].upper()


# --- the rolling /budget/ directory -----------------------------------------


def test_rolling_budget_editions_are_flagged_not_trusted(editions):
    """`/budget/apprpttoc.pdf` carries no year and gets repurposed each cycle.
    The URL is real and verified for the edition it was harvested against, so
    it's kept — but flagged, so discovery re-checks rather than trusting it."""
    rolling = {k for k, e in editions.items() if e["rolling"]}
    assert "approps-fy2023" in rolling
    for key, entry in editions.items():
        urls = [entry["single_file_url"] or "", entry["linked_toc_url"] or ""]
        if any("/budget/" in u.lower() for u in urls):
            assert entry["rolling"], key
        else:
            assert not entry["rolling"], key


def test_rolling_editions_say_so_in_plain_language(editions):
    entry = editions["approps-fy2023"]
    assert "repurposes each cycle" in entry["era_note"]


# --- per-agency titles are supplier data, and were WRONG ------------------


def test_no_edition_has_two_agencies_sharing_a_title(editions):
    """The exact shape of the off-by-one harvest defect: `data/jlbc-book-
    catalog.json` is a scrape of JLBC's own agency-index page, and it once
    recorded `05app/bar.pdf` (the Board of Barbers) under the title
    "Agriculture, Arizona Department of" — the row above it in the index —
    because the harvest read one row's label against a neighbouring row's
    URL. Two distinct agency codes in the same book edition can never
    legitimately share a display title (every agency gets its own page), so
    a duplicate title within one edition IS the defect signature. Fixed by
    `scripts/repair_supplier_titles.py`, which rewrites this file's titles
    from the corpus's own (content-derived, already-repaired)
    `documents.json`, joined by source_url exactly the way
    `app/search_provider.py::_info` does. Before that repair ran, 33 of the
    62 editions had at least one duplicate pair — this test failed against
    the pre-repair file, which is how it was confirmed to catch the real
    defect rather than pass vacuously.
    """
    offenders = {}
    for key, entry in editions.items():
        titles = Counter(row["title"] for row in entry.get("per_agency", []))
        dupes = {title: count for title, count in titles.items() if count > 1}
        if dupes:
            offenders[key] = dupes
    assert offenders == {}, f"editions with two agencies sharing a title: {offenders}"
