"""Fund-name stamping must respect word boundaries.

The 2026-08-23 fund-identity audit found `fund:account` ("Account") stamped
on 5,238 chunks across 143 agencies because `_scan_for_names` did a plain
casefolded substring `find` and matched inside "Account**ing**" (the
"Summary of Significant Accounting Policies" heading in every AFR). The
agency path shares `_scan_for_names` and was calibrated by the 2026-08-16
relabel, so the boundary rule is a fund-path-only switch and the agency
table path is pinned byte-identical here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.entity_stamper import (
    _DEFAULT_ALIASES,
    _DEFAULT_CATALOG,
    EntityStamper,
    _scan_for_names,
)
from chunking.types import Chunk, ChunkProvenance


def _fund_catalog(tmp_path: Path) -> Path:
    p = tmp_path / "funds.yaml"
    p.write_text(
        "funds:\n"
        "- canonical_id: fund:account\n  canonical_name: Account\n"
        "- canonical_id: fund:corrections\n  canonical_name: Corrections Fund\n"
        "- canonical_id: fund:tobacco-tax-and-health-care\n"
        "  canonical_name: Tobacco Tax and Health Care Fund\n",
        encoding="utf-8",
    )
    return p


def _stamper(tmp_path: Path) -> EntityStamper:
    # The committed agency catalog is a real, load-bearing fixture here: the
    # test is that AGENCY resolution is untouched while FUND matching changes.
    return EntityStamper(
        catalog_path=_DEFAULT_CATALOG,
        aliases_path=_DEFAULT_ALIASES,
        fund_catalog_path=_fund_catalog(tmp_path),
    )


def _chunk(text: str) -> Chunk:
    # Same shape as tests/test_entity_stamper.py::_chunk.
    return Chunk(
        chunk_id="x-0001", doc_id="x", text=text, section_path=[],
        provenance=ChunkProvenance(page=1), fiscal_year=2027,
        doc_type="baseline-book", publisher="jlbc", token_count=10,
    )


def test_a_fund_name_does_not_match_inside_a_longer_word(tmp_path):
    stamper = _stamper(tmp_path)
    out = stamper.stamp(_chunk("Note 1. Summary of Significant Accounting Policies"))
    assert out.fund_canonical_id is None


def test_a_fund_name_still_matches_as_a_whole_word(tmp_path):
    stamper = _stamper(tmp_path)
    out = stamper.stamp(_chunk("Transfers from the Corrections Fund, $1,000,000."))
    assert out.fund_canonical_id == "fund:corrections"


def test_longest_name_still_wins_on_overlap(tmp_path):
    stamper = _stamper(tmp_path)
    out = stamper.stamp(_chunk("From the Tobacco Tax and Health Care Fund."))
    assert out.fund_canonical_id == "fund:tobacco-tax-and-health-care"


def test_scan_default_is_the_old_substring_behaviour_for_the_agency_path():
    # The agency table path calls _scan_for_names with the defaults; that
    # calibrated behaviour must not move. Pinned on the exact substring shape
    # the fund fix removes.
    found = _scan_for_names(
        corpus="significant accounting policies",
        names_longest_first=["account"],
        name_to_id={"account": "x:account"},
    )
    assert found == ["x:account"]
