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
