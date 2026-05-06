"""Tests for chunking/entity_stamper.py."""
from __future__ import annotations

import pytest

from chunking.entity_stamper import EntityStamper, slug_from_jlbc_url
from chunking.types import Chunk, ChunkProvenance


def _chunk(
    *,
    section_path: list[str] | None = None,
    text: str = "",
    publisher: str = "jlbc",
    doc_type: str = "baseline-book",
    fiscal_year: int = 2027,
) -> Chunk:
    return Chunk(
        chunk_id="x-0001",
        doc_id="x",
        text=text,
        section_path=section_path or [],
        provenance=ChunkProvenance(page=1),
        fiscal_year=fiscal_year,
        doc_type=doc_type,
        publisher=publisher,
        token_count=10,
    )


# --- URL slug extraction ----------------------------------------------------


def test_slug_from_jlbc_url_baseline():
    assert slug_from_jlbc_url("https://www.azjlbc.gov/27baseline/axs.pdf") == "axs"


def test_slug_from_jlbc_url_approps():
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26ar/rev.pdf") == "rev"


def test_slug_from_jlbc_url_legacy_host():
    """FY15-FY22 historical host: http://www.azleg.gov/jlbc/<YY>AR/<slug>.pdf."""
    assert slug_from_jlbc_url("http://www.azleg.gov/jlbc/22AR/dor.pdf") == "dor"


def test_slug_from_jlbc_url_returns_none_for_non_jlbc():
    assert slug_from_jlbc_url("https://gao.az.gov/sites/default/files/x.pdf") is None
    assert slug_from_jlbc_url("https://example.com/foo/bar.pdf") is None


def test_slug_from_jlbc_url_returns_none_for_topic_files():
    """Cross-cutting topic PDFs (capitaloutlay/crr/tobacco/csbg) don't map
    to a single agency — they're cross-cuts, not per-agency entries."""
    assert slug_from_jlbc_url("https://www.azjlbc.gov/27baseline/capitaloutlay.pdf") is None


# --- Direct slug match ------------------------------------------------------


def test_stamp_jlbc_url_direct_slug():
    """Plan §3.4 step 1: rule 1 — direct slug match from JLBC URL."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk()
    stamped = stamper.stamp(
        chunk, source_url="https://www.azjlbc.gov/27baseline/axs.pdf"
    )
    assert stamped.agency_canonical_id == "agency:axs"
    # Direct match: no alias hops
    assert stamped.alias_chain == []


def test_stamp_jlbc_url_direct_slug_dor_baseline():
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(
        _chunk(), source_url="https://www.azjlbc.gov/27baseline/dor.pdf"
    )
    assert stamped.agency_canonical_id == "agency:dor"


# --- Alias map lookup -------------------------------------------------------


def test_stamp_alias_old_slug():
    """Plan §3.4 step 2: rule 2 — alias map lookup. `rev` URL → `agency:dor`."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk()
    stamped = stamper.stamp(
        chunk, source_url="https://www.azjlbc.gov/26ar/rev.pdf"
    )
    assert stamped.agency_canonical_id == "agency:dor"
    assert "rev" in stamped.alias_chain


# --- Name-based match (no URL) ----------------------------------------------


def test_stamp_name_based_governor_section_path():
    """Plan §3.4 step 2 rule 3: name-based match against entity catalog.
    Gov SAD doesn't carry slugs — resolve by section_path canonical name."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Corrections, Department of", "Operating Lump Sum"],
        publisher="governor",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:adc"


def test_stamp_name_based_inverted_form():
    """Catalog canonical names use 'X, Department of' or 'Department of X' —
    the stamper should match either form."""
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(
        _chunk(section_path=["Department of Corrections"], publisher="governor")
    )
    assert stamped.agency_canonical_id == "agency:adc"


# --- Fuzzy / OCR-drift match ------------------------------------------------


def test_stamp_ocr_drift_fuzzy_match():
    """Plan §3.4 step 2 rule 3 fallback: rapidfuzz at ratio ≥ 85 catches
    OCR drift (Boseline / Deportment)."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Boseline Book", "Deportment of Revenue"],
        publisher="governor",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:dor"


def test_stamp_all_caps_bill_heading_with_nbsp_resolves_via_fuzzy():
    """Real-bill headings have non-breaking spaces (\\xa0) instead of regular
    spaces between tokens — Word writes them that way. WS6 finding 2026-05-06:
    rapidfuzz `token_set_ratio` does NOT tokenize on NBSP, so
    'Sec.\\xa025.\\xa0\\xa0DEPARTMENT OF CHILD SAFETY' gets tokenized as
    `[..., 'sec.\\xa025.\\xa0\\xa0department', 'of', 'child', 'safety']` —
    the dept-name token is fused with the section number prefix and never
    matches catalog. Fix: normalize NBSP to space in the fuzzy processor.
    """
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Sec.\xa025.\xa0\xa0DEPARTMENT OF CHILD SAFETY"],
        publisher="legislature",
    )
    stamped = stamper.stamp(chunk)
    # Both Child Safety canonical_ids in the catalog are valid resolutions —
    # accept any agency:cs* match. The bug is None, not which-of-two-cs-ids.
    assert stamped.agency_canonical_id is not None
    assert stamped.agency_canonical_id.startswith("agency:")
    assert "cs" in stamped.agency_canonical_id or "cfs" in stamped.agency_canonical_id


def test_stamp_all_caps_bill_heading_resolves_via_fuzzy():
    """Real-bill Part-1 dept headings are ALL-CAPS (e.g. 'DEPARTMENT OF
    CORRECTIONS' from SB 1735). The catalog stores them as 'Corrections,
    Department of' / 'Department of Corrections'. WS6 finding 2026-05-06:
    rapidfuzz `token_set_ratio` is case-sensitive in v3.x without an explicit
    processor — every ALL-CAPS heading scored ~19, far below the 85 threshold,
    leaving 65 of 91 dept-heading chunks in the bill unstamped.
    """
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["DEPARTMENT OF CORRECTIONS"],
        publisher="legislature",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:adc"


# --- No match -> None + observability ---------------------------------------


def test_stamp_no_match_leaves_canonical_id_none():
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(section_path=["Some Random Heading"], publisher="governor")
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id is None


# --- Idempotency ------------------------------------------------------------


def test_stamp_does_not_mutate_input_chunk():
    stamper = EntityStamper.from_default_paths()
    original = _chunk(section_path=["Department of Corrections"], publisher="governor")
    assert original.agency_canonical_id is None
    stamped = stamper.stamp(original)
    assert original.agency_canonical_id is None  # input untouched
    assert stamped.agency_canonical_id == "agency:adc"


def test_stamp_already_stamped_chunk_is_passthrough():
    """If the chunk already has an agency_canonical_id, stamp() should not
    re-run resolution (it could only weaken the signal)."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(section_path=["Department of Corrections"], publisher="governor")
    chunk = chunk.model_copy(update={"agency_canonical_id": "agency:preset"})
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:preset"
    assert stamped.alias_chain == []


# --- Construction with explicit paths --------------------------------------


def test_stamper_constructor_accepts_explicit_paths(tmp_path):
    catalog = tmp_path / "cat.yaml"
    aliases = tmp_path / "al.yaml"
    catalog.write_text(
        "agencies:\n"
        "- canonical_name: Custom Agency\n"
        "  canonical_id: agency:custom\n"
        "  slug: custom\n",
        encoding="utf-8",
    )
    aliases.write_text("renames: []\n", encoding="utf-8")
    stamper = EntityStamper(catalog_path=catalog, aliases_path=aliases)
    stamped = stamper.stamp(
        _chunk(), source_url="https://www.azjlbc.gov/27baseline/custom.pdf"
    )
    assert stamped.agency_canonical_id == "agency:custom"
