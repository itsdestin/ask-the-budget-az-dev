"""Tests for ingest.url_conventions — the JLBC URL pattern library.

Patterns are documented in docs/cross-doc-relationships.md §7. The host
migration cutoff (LEGACY_HOST_MAX_FY = 2022) is empirically observed:
FY15-FY22 publish under http://www.azleg.gov/jlbc/<YY>AR/ (note the
uppercase AR), FY23+ under https://www.azjlbc.gov/<YY>ar/ (lowercase).
"""

from __future__ import annotations

import pytest

from ingest.url_conventions import (
    LEGACY_HOST_MAX_FY,
    approps_index_url,
    approps_per_agency_url,
    approps_toc_url,
    baseline_index_url,
    baseline_links_url,
    baseline_per_agency_url,
    per_agency_url,
)


# --- Index URLs (one per fiscal year, links into the per-agency PDF list) ---


@pytest.mark.parametrize(
    ("fy", "expected"),
    [
        # Modern host (FY23+): https + www.azjlbc.gov + lowercase <YY>baseline
        (2027, "https://www.azjlbc.gov/27baseline/agencyindex.pdf"),
        (2023, "https://www.azjlbc.gov/23baseline/agencyindex.pdf"),
    ],
)
def test_baseline_index_url_modern(fy: int, expected: str) -> None:
    assert baseline_index_url(fy) == expected


@pytest.mark.parametrize(
    ("fy", "expected"),
    [
        # Modern host (FY23+): https + www.azjlbc.gov + lowercase <YY>ar
        (2026, "https://www.azjlbc.gov/26ar/agencyindex.pdf"),
        (2023, "https://www.azjlbc.gov/23ar/agencyindex.pdf"),
        # Legacy host (FY15-FY22): http + www.azleg.gov/jlbc + uppercase <YY>AR
        (2022, "http://www.azleg.gov/jlbc/22AR/agencyindex.pdf"),
        (2015, "http://www.azleg.gov/jlbc/15AR/agencyindex.pdf"),
    ],
)
def test_approps_index_url_handles_host_migration(fy: int, expected: str) -> None:
    assert approps_index_url(fy) == expected


# --- Cross-cut TOC URLs (one per fiscal year, lists s/bh/bd-PDFs) ---


def test_baseline_links_url_fy27() -> None:
    # Note: baseline TOC lives under /budget/, NOT under /<YY>baseline/.
    # See cross-doc-relationships §7.
    assert baseline_links_url(2027) == "https://www.azjlbc.gov/budget/27baselinelinks.pdf"


def test_approps_toc_url_fy26() -> None:
    assert approps_toc_url(2026) == "https://www.azjlbc.gov/26ar/apprpttoc.pdf"


def test_approps_toc_url_legacy_host() -> None:
    # FY22 falls below the cutoff — uses the azleg.gov host with capital AR.
    assert approps_toc_url(2022) == "http://www.azleg.gov/jlbc/22AR/apprpttoc.pdf"


# --- Per-agency URLs (slug-keyed) ---


def test_per_agency_url_baseline_axs_fy27() -> None:
    assert (
        per_agency_url("baseline", 2027, "axs")
        == "https://www.azjlbc.gov/27baseline/axs.pdf"
    )


def test_per_agency_url_approps_modern_host() -> None:
    # FY23 approps: modern host, slug "rev" (the rev→dor rename happens
    # at FY27, not at the host migration). Caller passes the slug as-is;
    # this layer does NOT resolve aliases — that's the entity stamper's
    # job (chunk-shape D7 / cross-doc-relationships §5).
    assert (
        approps_per_agency_url(2023, "rev")
        == "https://www.azjlbc.gov/23ar/rev.pdf"
    )


def test_per_agency_url_approps_legacy_host() -> None:
    # FY22 approps: legacy host AND old slug — both migrations are inputs
    # to the URL pattern, the caller is responsible for slug correctness.
    assert (
        approps_per_agency_url(2022, "rev")
        == "http://www.azleg.gov/jlbc/22AR/rev.pdf"
    )


def test_baseline_per_agency_url_no_alias_resolution() -> None:
    # The URL layer does NOT resolve aliases. If the caller passes "rev"
    # for FY27 baseline (canonical slug there is "dor"), we honor the
    # input and return the URL — even though that PDF likely 404s.
    # Slug-alias resolution lives in chunking/entity_stamper.py.
    assert (
        baseline_per_agency_url(2027, "rev")
        == "https://www.azjlbc.gov/27baseline/rev.pdf"
    )


def test_per_agency_url_unified_dispatch() -> None:
    # The unified entry point should match the named wrappers for both
    # baseline and approps targets across the host migration.
    assert per_agency_url("baseline", 2027, "axs") == baseline_per_agency_url(2027, "axs")
    assert per_agency_url("approps", 2022, "rev") == approps_per_agency_url(2022, "rev")
    assert per_agency_url("approps", 2026, "axs") == approps_per_agency_url(2026, "axs")


def test_per_agency_url_rejects_unknown_doc_type() -> None:
    # Defensive: silently routing an unknown doc_type would let typos
    # leak through and produce wrong URLs.
    with pytest.raises(ValueError, match="doc_type"):
        per_agency_url("baseline-cross-cut", 2027, "axs")


# --- Constants ---


def test_legacy_host_max_fy_constant() -> None:
    # The cutoff is hardcoded based on observed JLBC behavior. If JLBC
    # ever republishes pre-FY23 docs at azjlbc.gov, this constant flips.
    assert LEGACY_HOST_MAX_FY == 2022
