"""Guards on the committed fund catalog after the 2026-08-23 repair.

The catalog's fund column was found polluted with schedule total rows,
agency names, budget-adjustment lines and truncated fragments (see the
fund-identity spec). These pins stop that pollution from returning
unnoticed — through a hand edit or a regeneration from source PDFs.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from funds.names import _looks_like_a_fund_name, id_to_name

CATALOG = Path(__file__).resolve().parent.parent / "data" / "fund-catalog.yaml"


def _entries() -> list[dict]:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["funds"]


def test_every_catalog_entry_reads_as_a_complete_fund_name():
    bad = [e["canonical_name"] for e in _entries() if not _looks_like_a_fund_name(e["canonical_name"])]
    assert bad == [], f"non-fund rows crept back into the catalog: {bad}"


def test_the_two_pinned_fragments_are_gone():
    ids = {e["canonical_id"] for e in _entries()}
    # Both PASS the shape rule, which is exactly why they are pinned.
    assert "fund:block-grant" not in ids
    assert "fund:species" not in ids


def test_the_measured_junk_classes_are_gone():
    ids = {e["canonical_id"] for e in _entries()}
    assert "fund:account" not in ids
    assert not any(i.startswith(("fund:total-", "fund:subtotal-")) for i in ids)
    assert not any("unallocated" in i or "remove-one-time" in i for i in ids)
    assert "fund:department-of-juvenile-corrections" not in ids


def test_the_restored_names_are_present_and_served():
    names = id_to_name()
    assert names["fund:department-of-education-empowerment"] == (
        "Department of Education Empowerment Scholarship Account"
    )
    assert names["fund:special-employee-health-insurance"] == (
        "Special Employee Health Insurance Trust Fund"
    )
    assert names["fund:game-nongame-fish-and-endangered"] == (
        "Game, Nongame, Fish and Endangered Species Fund"
    )
    assert names["fund:federal-temporary-assistance-for-needy"] == (
        "Federal Temporary Assistance for Needy Families Block Grant"
    )


def test_no_name_variant_is_a_truncated_prefix_of_its_own_name():
    # A variant that is a prefix of the canonical name re-mints the exact
    # substring-stamping bug this repair removes.
    for e in _entries():
        for v in e.get("name_variants") or []:
            assert not e["canonical_name"].lower().startswith(v.lower()) or v.lower() == e["canonical_name"].lower(), (e["canonical_id"], v)
