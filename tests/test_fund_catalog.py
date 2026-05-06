"""Tests for funds/catalog.py — aggregate FundAgencyRows → FundEntry list,
emit data/fund-catalog.yaml.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from funds.catalog import (
    FundEntry,
    build_fund_catalog,
    write_catalog_yaml,
)
from funds.parser import FundAgencyRow


# --- aggregate -------------------------------------------------------------


def test_build_catalog_returns_one_entry_per_canonical_name():
    rows = [
        FundAgencyRow("Department of Administration", "Aviation Fund", {2026: "$5,000"}),
        FundAgencyRow("Department of Health Services", "General Fund", {2026: "$200,000,000"}),
        FundAgencyRow("Department of Administration", "General Fund", {2026: "$100,000,000"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    names = sorted(e.canonical_name for e in catalog)
    assert names == ["Aviation Fund", "General Fund"]


def test_build_catalog_assigns_canonical_id_and_slug():
    rows = [FundAgencyRow("Dept X", "Aviation Fund", {2027: "$1"})]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    aviation = catalog[0]
    assert aviation.canonical_id == "fund:aviation"
    assert aviation.slug == "aviation"


def test_build_catalog_collects_observed_agencies():
    rows = [
        FundAgencyRow("Dept A", "Aviation Fund", {2026: "$1"}),
        FundAgencyRow("Dept B", "Aviation Fund", {2026: "$2"}),
        FundAgencyRow("Dept A", "Aviation Fund", {2027: "$3"}),  # dupe
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    aviation = catalog[0]
    # Each agency listed once, in first-seen order
    assert aviation.observed_in_agencies == ["Dept A", "Dept B"]


def test_build_catalog_present_in_records_source_id():
    rows = [FundAgencyRow("Dept X", "Aviation Fund", {2026: "$1"})]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    assert catalog[0].present_in == ["jlbc-s18-fy2027"]


def test_build_catalog_skips_funds_with_empty_slug():
    """Bare 'Fund' or whitespace-only names slugify to '' — we cannot stamp
    them, so they're dropped with no entry rather than a bogus 'fund:' id."""
    rows = [
        FundAgencyRow("Dept X", "Fund", {2026: "$0"}),  # slugifies to ''
        FundAgencyRow("Dept X", "  ", {2026: "$0"}),    # whitespace only
        FundAgencyRow("Dept Y", "Aviation Fund", {2026: "$1"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    assert [e.canonical_name for e in catalog] == ["Aviation Fund"]


def test_build_catalog_collision_detection():
    """Two distinct fund names that slugify identically are a collision —
    catalog still emits both entries but they share no canonical_id; the
    builder logs a warning. Stamping logic owns the policy of which wins."""
    rows = [
        FundAgencyRow("Dept X", "Aviation Fund", {2026: "$1"}),
        FundAgencyRow("Dept Y", "AVIATION   fund", {2026: "$2"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    # Same slug → merged into one canonical entry
    assert len(catalog) == 1
    aviation = catalog[0]
    # Both name forms recorded
    assert "AVIATION   fund" in aviation.name_variants


def test_build_catalog_sorted_by_canonical_name():
    rows = [
        FundAgencyRow("Dept X", "Tobacco Tax Fund", {2026: "$1"}),
        FundAgencyRow("Dept X", "Aviation Fund", {2026: "$2"}),
        FundAgencyRow("Dept X", "General Fund", {2026: "$3"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    assert [e.canonical_name for e in catalog] == [
        "Aviation Fund",
        "General Fund",
        "Tobacco Tax Fund",
    ]


# --- multi-source merge ----------------------------------------------------


def test_build_catalog_multi_source_merges_present_in():
    """Same fund seen in multiple sources merges to one entry with the
    union of their present_in lists."""
    s18_rows = [FundAgencyRow("Dept X", "Aviation Fund", {2027: "$1"})]
    bd2_rows = [FundAgencyRow("Dept X", "Aviation Fund", {2026: "$2"})]
    catalog = build_fund_catalog(
        sources=[
            ("jlbc-s18-fy2027", s18_rows),
            ("jlbc-bd2-fy2026", bd2_rows),
        ],
    )
    assert len(catalog) == 1
    assert sorted(catalog[0].present_in) == ["jlbc-bd2-fy2026", "jlbc-s18-fy2027"]


def test_build_catalog_multi_source_records_only_in_one():
    """Funds present in s18 but not bd2 keep present_in = ['jlbc-s18-fy2027']."""
    s18_rows = [FundAgencyRow("Dept X", "Aviation Fund", {2027: "$1"})]
    bd2_rows = [FundAgencyRow("Dept X", "General Fund", {2026: "$2"})]
    catalog = build_fund_catalog(
        sources=[
            ("jlbc-s18-fy2027", s18_rows),
            ("jlbc-bd2-fy2026", bd2_rows),
        ],
    )
    by_name = {e.canonical_name: e for e in catalog}
    assert by_name["Aviation Fund"].present_in == ["jlbc-s18-fy2027"]
    assert by_name["General Fund"].present_in == ["jlbc-bd2-fy2026"]


def test_build_catalog_either_kwarg_required():
    with pytest.raises(ValueError, match="source"):
        build_fund_catalog(rows=[], source_id=None, sources=None)


# --- YAML emit -------------------------------------------------------------


def test_write_catalog_yaml_round_trips(tmp_path):
    rows = [
        FundAgencyRow("Dept A", "Aviation Fund", {2026: "$1"}),
        FundAgencyRow("Dept A", "General Fund", {2027: "$2"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    out_path = tmp_path / "fund-catalog.yaml"
    write_catalog_yaml(out_path, catalog, sources=["jlbc-s18-fy2027"])

    raw = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert "_meta" in raw
    assert raw["_meta"]["sources_processed"] == ["jlbc-s18-fy2027"]
    assert raw["_meta"]["unique_funds"] == 2
    funds_block = raw["funds"]
    assert len(funds_block) == 2
    by_name = {e["canonical_name"]: e for e in funds_block}
    assert by_name["Aviation Fund"]["canonical_id"] == "fund:aviation"
    assert by_name["Aviation Fund"]["slug"] == "aviation"
    assert by_name["Aviation Fund"]["observed_in_agencies"] == ["Dept A"]
    assert by_name["Aviation Fund"]["present_in"] == ["jlbc-s18-fy2027"]


def test_write_catalog_yaml_emits_meta_stats(tmp_path):
    rows = [FundAgencyRow("Dept A", "Aviation Fund", {2026: "$1"})]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    out_path = tmp_path / "fund-catalog.yaml"
    write_catalog_yaml(out_path, catalog, sources=["jlbc-s18-fy2027"])

    raw = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    meta = raw["_meta"]
    assert meta["unique_funds"] == 1
    assert meta["sources_processed"] == ["jlbc-s18-fy2027"]
    assert "instructions" in meta


def test_write_catalog_yaml_keys_funds_alphabetically(tmp_path):
    rows = [
        FundAgencyRow("Dept A", "Tobacco Tax Fund", {2026: "$1"}),
        FundAgencyRow("Dept A", "Aviation Fund", {2026: "$2"}),
        FundAgencyRow("Dept A", "General Fund", {2026: "$3"}),
    ]
    catalog = build_fund_catalog(rows, source_id="jlbc-s18-fy2027")
    out_path = tmp_path / "fund-catalog.yaml"
    write_catalog_yaml(out_path, catalog, sources=["jlbc-s18-fy2027"])

    raw = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    names = [e["canonical_name"] for e in raw["funds"]]
    assert names == sorted(names)
