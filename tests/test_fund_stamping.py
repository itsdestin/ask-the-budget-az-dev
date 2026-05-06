"""Tests for fund stamping inside chunking/entity_stamper.py.

Plan §3.4 step 3 (deferred until WS4 fund catalog exists, now done):
  - Stamp the primary fund (first detected with highest confidence) into
    `chunk.fund_canonical_id`.
  - List every other fund mention in `chunk.fund_mentions`.
  - Same alias-aware/fuzzy-tolerant pattern as agency stamping, but the
    catalog source is data/fund-catalog.yaml (or a path passed in).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chunking.entity_stamper import EntityStamper
from chunking.types import Chunk, ChunkProvenance


@pytest.fixture
def fund_catalog_yaml(tmp_path) -> Path:
    """A minimal fund-catalog.yaml covering the names the tests reference."""
    payload = {
        "_meta": {"sources_processed": ["test"], "unique_funds": 5},
        "funds": [
            {
                "canonical_name": "Aviation Fund",
                "canonical_id": "fund:aviation",
                "slug": "aviation",
                "observed_in_agencies": [],
                "present_in": ["test"],
            },
            {
                "canonical_name": "General Fund",
                "canonical_id": "fund:general",
                "slug": "general",
                "observed_in_agencies": [],
                "present_in": ["test"],
            },
            {
                "canonical_name": "State Highway Fund",
                "canonical_id": "fund:state-highway",
                "slug": "state-highway",
                "observed_in_agencies": [],
                "present_in": ["test"],
            },
            {
                "canonical_name": "Tobacco Tax Health Care Fund",
                "canonical_id": "fund:tobacco-tax-health-care",
                "slug": "tobacco-tax-health-care",
                "observed_in_agencies": [],
                "present_in": ["test"],
            },
            {
                "canonical_name": "Building Renewal Fund",
                "canonical_id": "fund:building-renewal",
                "slug": "building-renewal",
                "observed_in_agencies": [],
                "present_in": ["test"],
            },
        ],
    }
    out = tmp_path / "fund-catalog.yaml"
    out.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return out


def _chunk(text: str = "", section_path: list[str] | None = None) -> Chunk:
    return Chunk(
        chunk_id="x-0001",
        doc_id="x",
        text=text,
        section_path=section_path or [],
        provenance=ChunkProvenance(page=1),
        fiscal_year=2027,
        doc_type="baseline-book",
        publisher="jlbc",
        token_count=10,
    )


def _stamper(fund_catalog_yaml: Path) -> EntityStamper:
    return EntityStamper.from_default_paths(fund_catalog_path=fund_catalog_yaml)


# --- single-fund stamping ---------------------------------------------------


def test_stamp_single_fund_in_text(fund_catalog_yaml):
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(text="Appropriated from the Aviation Fund for FY 2027.")
    stamped = stamper.stamp(chunk)
    assert stamped.fund_canonical_id == "fund:aviation"
    assert stamped.fund_mentions == []  # only one fund seen


def test_stamp_single_fund_in_section_path(fund_catalog_yaml):
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(
        section_path=["Department of Administration", "Aviation Fund"],
        text="Operating budget detail.",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.fund_canonical_id == "fund:aviation"


def test_stamp_no_fund_match(fund_catalog_yaml):
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(text="No fund mentioned in this chunk.")
    stamped = stamper.stamp(chunk)
    assert stamped.fund_canonical_id is None
    assert stamped.fund_mentions == []


# --- multi-fund stamping (primary + mentions) ------------------------------


def test_stamp_multiple_funds_primary_plus_mentions(fund_catalog_yaml):
    """Plan §3.4 step 3: 'stamp the primary fund only … list secondary funds
    in a fund_mentions: list[str] metadata field.'"""
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(
        text=(
            "$100,000,000 from the General Fund and $5,000,000 from the "
            "Aviation Fund and $2,000,000 from the State Highway Fund."
        )
    )
    stamped = stamper.stamp(chunk)
    # Primary = first-detected (General Fund appears first in text)
    assert stamped.fund_canonical_id == "fund:general"
    # Other two appear in fund_mentions in their text-order
    assert stamped.fund_mentions == ["fund:aviation", "fund:state-highway"]


def test_stamp_dedupes_repeated_fund_mention(fund_catalog_yaml):
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(
        text="General Fund detail. The General Fund total is $X. General Fund summary."
    )
    stamped = stamper.stamp(chunk)
    assert stamped.fund_canonical_id == "fund:general"
    assert stamped.fund_mentions == []  # all mentions are the same fund


# --- already-stamped passthrough -------------------------------------------


def test_stamp_preserves_existing_fund_canonical_id(fund_catalog_yaml):
    """When a chunk already has fund_canonical_id, don't re-resolve it.
    Same passthrough rule as agency stamping."""
    stamper = _stamper(fund_catalog_yaml)
    chunk = _chunk(text="Aviation Fund mentioned here.")
    chunk = chunk.model_copy(update={"fund_canonical_id": "fund:preset"})
    stamped = stamper.stamp(chunk)
    assert stamped.fund_canonical_id == "fund:preset"
    assert stamped.fund_mentions == []


# --- catalog file not found is silent ---------------------------------------


def test_stamper_works_without_fund_catalog(tmp_path):
    """When no fund catalog is provided, fund stamping silently no-ops —
    chunks just don't get a fund_canonical_id stamped. Required so the
    chunking layer can run before WS4 finishes (during initial bring-up)
    or in tests that don't care about funds."""
    stamper = EntityStamper.from_default_paths(fund_catalog_path=None)
    chunk = _chunk(text="Aviation Fund mentioned here.")
    stamped = stamper.stamp(chunk)
    # Agency stamping still runs; fund stamping just doesn't emit anything
    assert stamped.fund_canonical_id is None
    assert stamped.fund_mentions == []


def test_stamper_handles_missing_catalog_path(tmp_path):
    """If a path is passed but doesn't exist, raise — that's a config error,
    not a silent fallback. Distinct from the no-path case above."""
    with pytest.raises(FileNotFoundError):
        EntityStamper.from_default_paths(
            fund_catalog_path=tmp_path / "does-not-exist.yaml"
        )
