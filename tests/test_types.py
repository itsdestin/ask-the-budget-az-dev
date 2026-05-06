"""Tests for chunking/types.py — Pydantic Chunk + ChunkProvenance models.

Mirrors spec §6 SQL schema and chunk-shape D3-D7 invariants.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chunking.types import Chunk, ChunkProvenance


# --- ChunkProvenance ---------------------------------------------------------


def test_provenance_pdf_shape_accepts_page_and_bbox():
    p = ChunkProvenance(page=163, bbox=[72.0, 100.5, 540.0, 700.25])
    assert p.page == 163
    assert p.bbox == [72.0, 100.5, 540.0, 700.25]
    assert p.paragraph_id is None
    assert p.table_cell_id is None


def test_provenance_docx_shape_accepts_paragraph_id():
    # w14:paraId is an 8-char hex string in DOCX spec
    p = ChunkProvenance(paragraph_id="00A14B33")
    assert p.paragraph_id == "00A14B33"
    assert p.page is None


def test_provenance_docx_table_cell():
    p = ChunkProvenance(paragraph_id="00A14B33", table_cell_id="r3c2")
    assert p.table_cell_id == "r3c2"


def test_provenance_rejects_empty():
    """spec §6 CHECK constraint: provenance requires page or paragraph_id."""
    with pytest.raises(ValidationError) as excinfo:
        ChunkProvenance()
    # Surface the rule plainly so the error is debuggable
    assert "page or paragraph_id" in str(excinfo.value)


def test_provenance_rejects_bbox_only():
    """bbox alone is not enough — page is required for PDF provenance."""
    with pytest.raises(ValidationError):
        ChunkProvenance(bbox=[0, 0, 10, 10])


# --- Chunk -------------------------------------------------------------------


def _sample_chunk_kwargs() -> dict:
    return {
        "chunk_id": "jlbc-baseline-fy2027-axs-0001",
        "doc_id": "jlbc-baseline-fy2027-axs",
        "text": "Department of Administration\n\nOperating Lump Sum Appropriation: $123,456,700.",
        "section_path": ["Department of Administration", "Operating Lump Sum"],
        "is_table": False,
        "table_html": None,
        "provenance": ChunkProvenance(page=12, bbox=[72.0, 100.0, 540.0, 700.0]),
        "agency_canonical_id": "agency:axs",
        "fund_canonical_id": None,
        "fiscal_year": 2027,
        "doc_type": "baseline-book",
        "publisher": "jlbc",
        "token_count": 18,
    }


def test_chunk_minimal_fields():
    c = Chunk(**_sample_chunk_kwargs())
    assert c.chunk_id == "jlbc-baseline-fy2027-axs-0001"
    assert c.section_path == ["Department of Administration", "Operating Lump Sum"]
    assert c.is_table is False
    assert c.table_html is None
    assert c.agency_canonical_id == "agency:axs"


def test_chunk_table_variant():
    kwargs = _sample_chunk_kwargs()
    kwargs.update(
        is_table=True,
        table_html="<table><tr><td>Parks</td><td>$1.2M</td></tr></table>",
    )
    c = Chunk(**kwargs)
    assert c.is_table is True
    assert c.table_html and "Parks" in c.table_html


def test_chunk_round_trip_json():
    """Phase 1b's storage layer needs Chunk → JSON → Chunk round-trip equality."""
    original = Chunk(**_sample_chunk_kwargs())
    raw = original.model_dump_json()
    revived = Chunk.model_validate_json(raw)
    assert revived == original
    # And the JSON itself is valid + has the expected top-level keys
    parsed = json.loads(raw)
    for key in ("chunk_id", "doc_id", "text", "section_path", "provenance", "fiscal_year"):
        assert key in parsed


def test_chunk_round_trip_docx_provenance():
    kwargs = _sample_chunk_kwargs()
    kwargs.update(
        chunk_id="legislature-budget-bill-fy2026-sb1735-0042",
        doc_id="legislature-budget-bill-fy2026-sb1735",
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        provenance=ChunkProvenance(paragraph_id="00A14B33"),
    )
    original = Chunk(**kwargs)
    revived = Chunk.model_validate_json(original.model_dump_json())
    assert revived == original
    assert revived.provenance.page is None
    assert revived.provenance.paragraph_id == "00A14B33"


def test_chunk_section_path_is_a_list():
    """section_path is a list[str], not a single string — chunk-shape D6 propagation."""
    kwargs = _sample_chunk_kwargs()
    kwargs["section_path"] = "Department of Administration / Operating Lump Sum"  # wrong shape
    with pytest.raises(ValidationError):
        Chunk(**kwargs)


def test_chunk_token_count_required():
    kwargs = _sample_chunk_kwargs()
    del kwargs["token_count"]
    with pytest.raises(ValidationError):
        Chunk(**kwargs)


def test_chunk_extra_fields_forbidden():
    """Schema is closed — typos in field names should fail loudly, not silently dropped."""
    kwargs = _sample_chunk_kwargs()
    kwargs["embeding"] = [0.1, 0.2]  # typo for embedding (which is in 1b anyway)
    with pytest.raises(ValidationError):
        Chunk(**kwargs)
