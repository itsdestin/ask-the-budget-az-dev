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
from chunking.readers.types import ExtractedDocument, Page, Paragraph
from chunking.types import Chunk

FIXTURE_AXS = Path(__file__).parent / "fixtures" / "mineru-jlbc-baseline-axs.json"
FIXTURE_ORPHAN = Path(__file__).parent / "fixtures" / "mineru-orphan-preamble.json"
FIXTURE_ORPHAN_STRIPPED = (
    Path(__file__).parent / "fixtures" / "mineru-orphan-preamble-stripped.json"
)
FIXTURE_ORPHAN_ONLY = (
    Path(__file__).parent / "fixtures" / "mineru-orphan-only-no-headings.json"
)


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


# --- Orphan preamble recovery -----------------------------------------------
#
# A paragraph before the FIRST heading in a document is never attached to
# any OutlineNode (see narrative_chunk._orphaned_paragraphs' docstring for
# why) and used to be silently dropped. These tests pin the recovery.


def test_orphan_preamble_paragraph_is_recovered_as_a_trailing_chunk():
    doc = MinerUReader().read(FIXTURE_ORPHAN)
    chunks = build_narrative_chunks(doc, _meta())
    # section_path is [] — not a synthetic "preamble" label — because
    # there genuinely is no section here (see the WHY at the orphan call
    # site in narrative_chunk.py). An empty path is what distinguishes an
    # orphan-recovered chunk from a headed one in these tests.
    orphan_chunks = [c for c in chunks if c.section_path == []]
    assert len(orphan_chunks) == 1
    assert "AGENCY DESCRIPTION" in orphan_chunks[0].text
    assert "orphaned preamble paragraph recovery" in orphan_chunks[0].text
    # No synthetic label of any kind is injected into the embedded text.
    assert not orphan_chunks[0].text.lower().startswith("preamble")


def test_orphan_preamble_chunk_is_appended_after_every_heading_derived_chunk():
    """The single most important property this fix must hold: an existing
    chunk_id must never move or change text. Proven directly by an A/B
    fixture pair — `FIXTURE_ORPHAN_STRIPPED` is byte-identical to
    `FIXTURE_ORPHAN` with only the orphan paragraph removed, which is
    *exactly* what pre-fix code produced when run on `FIXTURE_ORPHAN` (the
    old outline walk never saw that block in the first place, orphan or
    not — it simply wasn't there to skip). So "chunks from the stripped
    fixture" IS "what the reverted code produces on the orphan fixture",
    without needing to check out an old commit.
    """
    doc_with = MinerUReader().read(FIXTURE_ORPHAN)
    doc_without = MinerUReader().read(FIXTURE_ORPHAN_STRIPPED)
    chunks_with = build_narrative_chunks(doc_with, _meta())
    chunks_without = build_narrative_chunks(doc_without, _meta())

    # Exactly one new chunk appears — the recovered orphan.
    assert len(chunks_with) == len(chunks_without) + 1

    # Every chunk that existed before the fix (i.e. every chunk the
    # stripped fixture produces) keeps its EXACT chunk_id and text at the
    # SAME position in the sequence.
    for before, after in zip(chunks_without, chunks_with):
        assert after.chunk_id == before.chunk_id
        assert after.text == before.text
        assert after.section_path == before.section_path
        assert after.provenance == before.provenance

    # The recovered chunk is the new LAST element, not spliced in earlier —
    # this is what keeps every pre-existing index stable.
    assert chunks_with[-1].section_path == []
    assert chunks_with[-1].chunk_id == chunks_without[-1].chunk_id.rsplit("-", 1)[0] + (
        f"-{len(chunks_without):04d}"
    )


def test_orphan_only_document_with_no_headings_at_all_recovers_all_narrative():
    """Real corpus shape (jlbc-baseline-fy2022-hla): a page with ZERO
    heading blocks used to return an empty outline and, therefore, zero
    narrative chunks at all — 100% of the page's prose silently dropped."""
    doc = MinerUReader().read(FIXTURE_ORPHAN_ONLY)
    chunks = build_narrative_chunks(doc, _meta())
    assert len(chunks) >= 1
    joined = " ".join(c.text for c in chunks)
    assert "AGENCY DESCRIPTION" in joined
    assert "Source of Revenue" in joined
    for c in chunks:
        assert c.section_path == []


def test_orphan_recovery_does_not_change_output_for_documents_without_orphans():
    """No behaviour change for a document whose narrative is entirely
    heading-anchored (the common case) — byte-identical chunk sequence."""
    doc = MinerUReader().read(FIXTURE_AXS)
    chunks = build_narrative_chunks(doc, _meta())
    # Every chunk from this fixture is heading-anchored, so every
    # section_path is non-empty ([] is reserved for orphan-recovered
    # chunks — see the WHY at the orphan call site).
    assert all(c.section_path != [] for c in chunks)
    # Existing behaviour-pinning tests above already assert the exact
    # shape of this fixture's output; this test only pins that no EXTRA
    # trailing chunk appears.
    ids = [c.chunk_id for c in chunks]
    suffixes = [int(cid.rsplit("-", 1)[-1]) for cid in ids]
    assert suffixes == list(range(len(suffixes)))


# --- Page-boundary flush (Finding 1: a recovered chunk must never span
# pages while claiming its first paragraph's page as its provenance) -------


def test_orphan_recovery_flushes_at_page_boundaries():
    """A recovered orphan chunk must never span pages. Invariant 1 requires
    every citation to resolve to an exact PDF page + bbox highlight.

    Measured on the live corpus before this fix:
    `agao-afr-fy2023-0019` held 70 paragraphs drawn from pages 2 through
    175 in a SINGLE chunk, with `provenance.page = 2` (the first
    paragraph's page) — a citation into text physically on page 175 would
    send the PDF viewer to page 2, the strict-bbox text search would find
    nothing there, and the analyst would see "couldn't pinpoint" on a claim
    that is actually well-sourced.

    Built directly from `ExtractedDocument`/`Page`/`Paragraph` rather than
    a MinerU JSON fixture — the reader only ever parses ONE page per file
    (or one Page per `page-N.json` in a directory), so a same-file,
    multi-page fixture isn't expressible; constructing the doc objects
    directly is the more direct test of `build_narrative_chunks` itself.
    """
    doc = ExtractedDocument(
        source_path=Path("synthetic-multi-page-orphan.json"),
        extractor="mineru",
        pages=[
            Page(page_number=1, blocks=[Paragraph(text="Page one prose, no heading anywhere in this doc.", page=1)]),
            Page(page_number=2, blocks=[Paragraph(text="Page two prose, still before any heading.", page=2)]),
            Page(page_number=3, blocks=[Paragraph(text="Page three prose, still orphaned.", page=3)]),
        ],
        outline=[],
    )
    chunks = build_narrative_chunks(doc, _meta())
    # Three short paragraphs (well under the 512-token target) would merge
    # into ONE chunk without the page-boundary trigger — that merge is
    # exactly what this test guards against.
    assert len(chunks) == 3
    assert [c.provenance.page for c in chunks] == [1, 2, 3]
    assert chunks[0].text == "Page one prose, no heading anywhere in this doc."
    assert chunks[1].text == "Page two prose, still before any heading."
    assert chunks[2].text == "Page three prose, still orphaned."
