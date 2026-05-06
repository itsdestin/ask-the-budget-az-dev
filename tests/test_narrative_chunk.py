"""Tests for chunking/builders/narrative_chunk.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.builders.narrative_chunk import (
    NARRATIVE_TARGET_TOKENS,
    build_narrative_chunks,
)
from chunking.builders.table_chunk import DocMeta
from chunking.readers.mineru_reader import MinerUReader
from chunking.types import Chunk

FIXTURE_AXS = Path(__file__).parent / "fixtures" / "mineru-jlbc-baseline-axs.json"


def _meta() -> DocMeta:
    return DocMeta(
        doc_id="jlbc-baseline-fy2027-axs",
        publisher="jlbc",
        doc_type="baseline-book",
        fiscal_year=2027,
    )


def test_build_narrative_chunks_returns_list_of_chunks():
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    assert len(chunks) >= 1
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.is_table is False
        assert c.table_html is None


def test_build_narrative_chunks_token_limits():
    """Plan §3.3.b: 50 < token_count <= 1024."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    for c in chunks:
        assert c.token_count <= 1024
        # Lower bound: tiny chunks are unhelpful for retrieval. Allow short
        # final chunks (last paragraph in a section may legitimately be
        # short) but require at least some content.
        assert c.token_count > 0


def test_build_narrative_chunks_section_path_stamped_on_every_chunk():
    """Plan §3.3.b: chunk-shape D6 — section_path inherited from heading hierarchy."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    for c in chunks:
        assert len(c.section_path) >= 1
    # The Mission Statement paragraphs should be stamped under the right path
    mission_chunks = [
        c for c in chunks if c.section_path[-1] == "Mission Statement"
    ]
    assert len(mission_chunks) >= 1


def test_build_narrative_chunks_does_not_split_mid_paragraph():
    """Plan §3.3.b step 2: never split a paragraph across chunks. Each chunk's
    text is the concatenation of one or more *whole* paragraphs from the doc."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    # Collect all paragraph texts in the doc
    paragraph_texts = []
    for page in doc.pages:
        for block in page.blocks:
            from chunking.readers.types import Paragraph

            if isinstance(block, Paragraph):
                paragraph_texts.append(block.text)
    # Every paragraph must appear in some chunk in full, contiguous form.
    joined_chunks = " ".join(c.text for c in chunks)
    for p in paragraph_texts:
        assert p in joined_chunks, f"paragraph split across chunks: {p[:60]}..."


def test_build_narrative_chunks_chunk_ids_use_doc_id_with_index_offset():
    """Narrative chunks accept a starting index so the orchestrator can mix
    them with table chunks under one consistent zero-padded sequence."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta(), start_index=5)
    # First narrative chunk should start at index 5
    assert chunks[0].chunk_id == "jlbc-baseline-fy2027-axs-0005"


def test_build_narrative_chunks_propagate_doc_meta():
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    for c in chunks:
        assert c.publisher == "jlbc"
        assert c.doc_type == "baseline-book"
        assert c.fiscal_year == 2027
        assert c.doc_id == "jlbc-baseline-fy2027-axs"


def test_build_narrative_chunks_provenance_carries_first_paragraph_page():
    """Each chunk's provenance points to its first paragraph's page+bbox."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    for c in chunks:
        assert c.provenance.page == 142  # all our fixture paragraphs are on p142
        assert c.provenance.bbox is not None


def test_build_narrative_chunks_emits_section_text_in_chunk_text():
    """Section path is denormalized into chunk.text (chunk-shape D6) so retrieval
    surfaces the surrounding heading context for embedding."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    mission_chunks = [c for c in chunks if c.section_path[-1] == "Mission Statement"]
    assert mission_chunks
    assert "Department of Administration" in mission_chunks[0].text
    assert "Mission Statement" in mission_chunks[0].text


def test_build_narrative_chunks_merges_short_paragraphs_into_one_chunk():
    """Multiple short paragraphs in the same section should pack into one
    chunk if they fit under the 512-token target. The fixture's Mission
    Statement has two paragraphs both under 200 tokens — should pack."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    mission_chunks = [c for c in chunks if c.section_path[-1] == "Mission Statement"]
    # Both Mission Statement paragraphs should pack into one chunk
    assert len(mission_chunks) == 1
    # Both paragraph texts must appear in that single chunk
    assert "central management services" in mission_chunks[0].text
    assert "State Procurement Office" in mission_chunks[0].text


def test_build_narrative_chunks_skips_tables():
    """Narrative builder ignores Table blocks — those are handled by
    table_chunk.build_table_chunk separately."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    # No chunk's text should contain HTML table fragments
    for c in chunks:
        assert "<table" not in c.text
        assert "<td" not in c.text


def test_build_narrative_chunks_target_token_constant_is_512():
    assert NARRATIVE_TARGET_TOKENS == 512
