"""Tests for chunking/agency_catalog.py."""
from __future__ import annotations

from chunking.agency_catalog import id_to_name, load_agency_catalog


def test_loads_157_agencies_with_ids():
    cat = load_agency_catalog()
    assert len(cat) >= 150
    # AHCCCS's canonical_id is `agency:axs` — the JLBC slug, not the acronym.
    # (The plan's draft test guessed `agency:ahcccs`; the real catalog keys on
    # the publisher's own slug, which is what every stored chunk carries.)
    entry = cat["agency:axs"]
    assert "AHCCCS" in entry.canonical_name or "Health Care" in entry.canonical_name
    assert entry.slug == "axs"


def test_id_to_name_map():
    names = id_to_name()
    assert names["agency:axs"]
    assert all(k.startswith("agency:") for k in names)


def test_slug_is_none_for_gov_only_entries():
    """Gov-outline entries have no JLBC slug — consumers must not assume one."""
    cat = load_agency_catalog()
    entry = cat["agency:gov:arizona-health-care-cost-containment-system"]
    assert entry.slug is None


def test_catalog_is_cached_across_calls():
    """The YAML is ~10k lines; repeated id→name lookups must not re-parse it."""
    assert load_agency_catalog() is load_agency_catalog()


def test_name_variants_come_from_names_observed_jlbc():
    """`names_observed_jlbc` maps printed-name → docs-seen-in; the KEYS are the
    alternate names the stamper matches against."""
    entry = load_agency_catalog()["agency:sba"]
    assert "Accountancy, Arizona State Board of" in entry.name_variants
