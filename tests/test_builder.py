"""Tests for chunking/builder.py — top-level chunking orchestrator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunking.builder import chunk_doc
from chunking.builders.table_chunk import DocMeta
from chunking.types import Chunk

FIXTURES = Path(__file__).parent / "fixtures"


def _approps_meta(**overrides) -> DocMeta:
    base = dict(
        doc_id="jlbc-approps-fy2026",
        publisher="jlbc",
        doc_type="bh-pdf",
        fiscal_year=2026,
        extractor="mineru",
        source_format="pdf",
        source_url="https://www.azjlbc.gov/26ar/doa.pdf",
    )
    base.update(overrides)
    return DocMeta(**base)


def _baseline_axs_meta(**overrides) -> DocMeta:
    base = dict(
        doc_id="jlbc-baseline-fy2027-axs",
        publisher="jlbc",
        doc_type="baseline-book",
        fiscal_year=2027,
        extractor="mineru",
        source_format="pdf",
        source_url="https://www.azjlbc.gov/27baseline/axs.pdf",
    )
    base.update(overrides)
    return DocMeta(**base)


def _bill_meta(**overrides) -> DocMeta:
    base = dict(
        doc_id="legislature-budget-bill-fy2026-sb1735",
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        extractor="python-docx",
        source_format="docx",
    )
    base.update(overrides)
    return DocMeta(**base)


# --- Reader dispatch -------------------------------------------------------


def test_chunk_doc_mineru_dispatch_returns_chunks():
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
        doc_meta=_approps_meta(),
    )
    assert chunks
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_doc_odl_dispatch_returns_chunks():
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "odl-afr-p163.json",
        doc_meta=DocMeta(
            doc_id="agao-afr-fy2025",
            publisher="agao",
            doc_type="afr",
            fiscal_year=2025,
            extractor="opendataloader",
            source_format="pdf",
        ),
    )
    assert chunks


def test_chunk_doc_docx_dispatch_returns_chunks():
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "docx-sb1735-sample.json",
        doc_meta=_bill_meta(),
    )
    assert chunks


def test_chunk_doc_unknown_extractor_raises():
    with pytest.raises(ValueError, match="Unknown extractor"):
        chunk_doc(
            extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
            doc_meta=_approps_meta(extractor="bogus"),
        )


# --- Mixed table + narrative chunks ----------------------------------------


def test_chunk_doc_mineru_mixes_table_and_narrative_chunks():
    """The approps p513 fixture has a table AND narrative paragraphs — both
    should appear in the output."""
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
        doc_meta=_approps_meta(),
    )
    table_chunks = [c for c in chunks if c.is_table]
    narrative_chunks = [c for c in chunks if not c.is_table]
    assert len(table_chunks) >= 1
    assert len(narrative_chunks) >= 1


def test_chunk_doc_zero_padded_sequential_chunk_ids():
    """Tables come first (by orchestrator convention), then narratives. All
    share one zero-padded sequence per doc."""
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
        doc_meta=_approps_meta(),
    )
    ids = [c.chunk_id for c in chunks]
    # First chunk is index 0, sequence is dense and ascending
    assert ids[0] == "jlbc-approps-fy2026-0000"
    # Every chunk_id is unique
    assert len(set(ids)) == len(ids)
    # IDs are dense (no gaps): the integer suffixes form 0, 1, 2, ...
    suffixes = [int(cid.rsplit("-", 1)[-1]) for cid in ids]
    assert suffixes == list(range(len(suffixes)))


# --- Entity stamping integrated --------------------------------------------


def test_chunk_doc_stamps_agency_canonical_id_via_url():
    """Plan §3.5 — orchestrator calls the entity stamper. URL-based slug
    should resolve."""
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-baseline-axs.json",
        doc_meta=_baseline_axs_meta(),
    )
    for c in chunks:
        assert c.agency_canonical_id == "agency:axs"


# --- DOCX path: section → chunk ---------------------------------------------


def test_chunk_doc_docx_emits_one_chunk_per_section():
    """For bills, every Section becomes a chunk (subject to size limits)."""
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "docx-sb1735-sample.json",
        doc_meta=_bill_meta(),
    )
    # Fixture has 5 sections (2 Part 1 + 2 SEC 06-18 + 1 SEC 06-19)
    assert len(chunks) == 5


def test_chunk_doc_docx_provenance_uses_paragraph_id():
    """DOCX chunks use paragraph_id, not (page, bbox)."""
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "docx-sb1735-sample.json",
        doc_meta=_bill_meta(),
    )
    for c in chunks:
        assert c.provenance.paragraph_id is not None
        assert c.provenance.page is None


def test_chunk_doc_docx_section_path_carries_style_and_heading():
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "docx-sb1735-sample.json",
        doc_meta=_bill_meta(),
    )
    sec_06_18_chunks = [c for c in chunks if "SEC 06-18" in c.text]
    assert sec_06_18_chunks


# --- NDJSON output ---------------------------------------------------------


def test_chunk_doc_writes_ndjson(tmp_path):
    out_dir = tmp_path / "chunks"
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
        doc_meta=_approps_meta(),
        output_dir=out_dir,
    )
    out_path = out_dir / "jlbc-approps-fy2026.json"
    assert out_path.exists()
    lines = out_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(chunks)
    # Each line is a valid Chunk JSON
    for line in lines:
        record = json.loads(line)
        assert "chunk_id" in record
        assert record["doc_id"] == "jlbc-approps-fy2026"


def test_chunk_doc_no_output_dir_skips_write(tmp_path):
    """When output_dir is None, no file is created."""
    out_dir = tmp_path / "chunks"
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
        doc_meta=_approps_meta(),
        output_dir=None,
    )
    assert chunks
    assert not out_dir.exists()


# --- doc_meta validation ----------------------------------------------------


def test_chunk_doc_requires_extractor_field():
    with pytest.raises(ValueError, match="extractor"):
        chunk_doc(
            extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
            doc_meta=_approps_meta(extractor=""),
        )
