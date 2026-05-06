"""Tests for ingest.discovery — the TOC-walking layer.

Each walker reads link annotations off a JLBC TOC PDF and returns a
typed list of (filename, url, title, section_kind) entries. URL conventions
documented in docs/cross-doc-relationships.md §7; filename → section_kind
classification is the JLBC convention `s<N>` / `bh<N>` / `bd<N>` /
`<page-N>` (page-keyed) / topic.

These tests use real JLBC TOC PDFs fetched on demand via the download
cache (``data/cached-pdfs/``). First run hits the network; subsequent
runs read from local cache. Marked ``@pytest.mark.network`` so they can
be skipped offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.cache import DownloadCache
from ingest.discovery import (
    AgencyIndexEntry,
    ApproprsTOCEntry,
    BaselineLinksEntry,
    walk_agency_index,
    walk_approps_toc,
    walk_baseline_links,
)
from ingest.url_conventions import (
    approps_toc_url,
    baseline_index_url,
    baseline_links_url,
)

# Cache used by all tests; pre-populated by the WS2-T2.1 smoke fetch.
_CACHE_ROOT = Path("data/cached-pdfs")


@pytest.fixture(scope="module")
def cache() -> DownloadCache:
    return DownloadCache(_CACHE_ROOT)


# --- walk_agency_index ---


@pytest.mark.network
def test_walk_agency_index_fy27_baseline(cache: DownloadCache) -> None:
    entries = walk_agency_index(baseline_index_url(2027), cache=cache)

    # All entries are typed dataclass records.
    assert all(isinstance(e, AgencyIndexEntry) for e in entries)

    # Sanity-bound the count. JLBC could reissue the index with a
    # different agency count; a tight equals would be brittle.
    # Phase 0 work observed 110 FY27 baseline agencies.
    assert 90 <= len(entries) <= 130, f"unexpected agency count: {len(entries)}"

    # Spot-check known agencies. AHCCCS = axs is JLBC-stable.
    axs = next((e for e in entries if e.slug == "axs"), None)
    assert axs is not None, "missing axs (AHCCCS)"
    assert axs.url.endswith("/27baseline/axs.pdf")
    # Health Care Cost Containment System — name text should mention HCCCS or Health.
    assert "Health" in axs.name or "HCCCS" in axs.name

    # Department of Transportation — slug `dot`.
    dot = next((e for e in entries if e.slug == "dot"), None)
    assert dot is not None, "missing dot (ADOT)"
    assert "Transportation" in dot.name


@pytest.mark.network
def test_walk_agency_index_filters_non_agency_links(cache: DownloadCache) -> None:
    """The agency-index PDF also links to a few non-per-agency PDFs
    (whole-document like capitaloutlay, summary-sections like s7).
    The walker must filter those out — they aren't agencies."""
    entries = walk_agency_index(baseline_index_url(2027), cache=cache)
    slugs = {e.slug for e in entries}
    # These slugs are the documented non-agency links per Phase 0's
    # build_agency_catalog filter list.
    forbidden = {"capitaloutlay", "agencyindex", "crr", "tobacco", "csbg"}
    assert not (forbidden & slugs), f"non-agency slugs leaked: {forbidden & slugs}"
    # Summary-section slugs (s\d+) are also not agencies.
    assert not any(s.startswith("s") and len(s) <= 3 and s[1:].isdigit() for s in slugs)


# --- walk_approps_toc ---


@pytest.mark.network
def test_walk_approps_toc_fy26(cache: DownloadCache) -> None:
    entries = walk_approps_toc(approps_toc_url(2026), cache=cache)

    assert all(isinstance(e, ApproprsTOCEntry) for e in entries)
    assert len(entries) > 10, f"unexpectedly few TOC entries: {len(entries)}"

    # bh-PDFs are budget-highlights cross-cuts.
    bh_entries = [e for e in entries if e.section_kind == "budget-highlights"]
    assert len(bh_entries) > 0, "expected at least one bh-* entry"

    # bd-PDFs are budget-detail cross-cuts.
    bd_entries = [e for e in entries if e.section_kind == "budget-detail"]
    assert len(bd_entries) > 0, "expected at least one bd-* entry"

    # bd2.pdf is "Summary of Appropriated Funds by Agency" per Phase 0
    # cross-doc-relationships §7. Title text should reflect that.
    bd2 = next((e for e in entries if e.filename == "bd2.pdf"), None)
    assert bd2 is not None, "missing bd2.pdf entry"
    # Be permissive on exact wording — JLBC could change it. Just look
    # for the load-bearing concept words.
    title_lower = bd2.title.lower()
    assert any(t in title_lower for t in ("fund", "agency"))


@pytest.mark.network
def test_walk_approps_toc_includes_page_keyed_detailed_list(
    cache: DownloadCache,
) -> None:
    """Approps TOCs include `<page>.pdf` entries for the Detailed List
    of GF / Other Fund Changes — page-keyed because the section starts
    on a different page each year."""
    entries = walk_approps_toc(approps_toc_url(2026), cache=cache)
    detailed = [e for e in entries if e.section_kind == "detailed-list"]
    assert len(detailed) >= 1, "expected page-keyed detailed-list PDFs"
    # Filenames are bare integers + .pdf, e.g. "452.pdf".
    for e in detailed:
        stem = e.filename.removesuffix(".pdf")
        assert stem.isdigit(), f"detailed-list filename should be digits: {e.filename}"


# --- walk_baseline_links ---


@pytest.mark.network
def test_walk_approps_toc_classifies_cross_cutting_topics(
    cache: DownloadCache,
) -> None:
    """`capitaloutlay.pdf` and `crr.pdf` appear in BOTH the baseline-links
    TOC and the approps TOC. Both walkers must give them the same
    section_kind ('topic') so downstream chunkers can reason uniformly
    across publisher artifacts."""
    entries = walk_approps_toc(approps_toc_url(2026), cache=cache)
    by_filename = {e.filename: e for e in entries}
    assert "capitaloutlay.pdf" in by_filename
    assert by_filename["capitaloutlay.pdf"].section_kind == "topic"
    assert "crr.pdf" in by_filename
    assert by_filename["crr.pdf"].section_kind == "topic"


@pytest.mark.network
def test_walk_baseline_links_fy27(cache: DownloadCache) -> None:
    entries = walk_baseline_links(baseline_links_url(2027), cache=cache)

    assert all(isinstance(e, BaselineLinksEntry) for e in entries)
    # Baseline TOC has at least the s-section list (s1..sN) plus topic
    # PDFs (capitaloutlay, crr, etc.).
    assert len(entries) > 10

    # s18.pdf is "Other Funds by Agency" — a stable JLBC summary section.
    s18 = next((e for e in entries if e.filename == "s18.pdf"), None)
    assert s18 is not None, "missing s18.pdf in baseline-links TOC"
    assert s18.section_kind == "summary-section"

    # At least one topic-PDF (capitaloutlay, crr, tobacco, csbg).
    topic_entries = [e for e in entries if e.section_kind == "topic"]
    assert len(topic_entries) >= 1, "expected at least one topic PDF entry"
