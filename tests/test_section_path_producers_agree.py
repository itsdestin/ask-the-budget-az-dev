"""G-T1 — the two `section_path` producers must agree.

Every existing test asks "is this chunk's label correct?". None asked "do
our two labellers agree with each other?", and that is exactly the gap that
let the defect live: `narrative_chunk.visit` read the answer positionally
while `table_chunk` searched for it by text. CLAUDE.md, measurement
discipline: *a per-item check cannot find a cross-item defect... when a
field has more than one producer, the test that matters compares the
producers' output.*
"""
from __future__ import annotations

from pathlib import Path

from chunking.builders.narrative_chunk import build_narrative_chunks
from chunking.builders.table_chunk import DocMeta, build_table_chunk
from chunking.readers.odl_reader import ODLReader
from chunking.readers.types import Paragraph

FIXTURE = Path(__file__).parent / "fixtures" / "odl-gov-toc-slice"
TRAP = "Acupuncture Examiners, Board of"


def _meta() -> DocMeta:
    return DocMeta(
        doc_id="governor-governors-budget-fy2026",
        publisher="governor",
        doc_type="governors-budget",
        fiscal_year=2026,
        extractor="opendataloader",
    )


def test_the_fixture_really_contains_the_trap():
    """The first draft of this plan copied the COVER page instead of the
    contents page, and every test below would have passed against it while
    proving nothing. This spec fails if the fixture is ever re-copied wrong."""
    doc = ODLReader().read(FIXTURE)
    toc = [n for n in doc.outline if n.text == "Table of Contents"]
    assert len(toc) == 1, "page-2.json must carry the Table of Contents heading"
    body = " ".join(b.text for b in toc[0].body_blocks if isinstance(b, Paragraph))
    assert TRAP in body, "the contents page must name the agency whose table is on page 10"
    late_tables = [t for t in doc.tables if (t.pages[0] if t.pages else t.page) >= 10]
    assert late_tables, "page-10.json must carry the agency's table"


def test_every_table_chunk_agrees_with_the_owner_lookup():
    doc = ODLReader().read(FIXTURE)
    assert doc.tables, "fixture must contain tables"
    for index, table in enumerate(doc.tables):
        chunk = build_table_chunk(table, doc, _meta(), chunk_index=index)
        assert chunk.section_path == doc.owner_path(table), (
            f"table {index} on page {table.page}: builder said "
            f"{chunk.section_path!r}, owner lookup says {doc.owner_path(table)!r}"
        )


def test_every_narrative_chunk_agrees_with_the_owner_lookup():
    """The narrative builder reaches its path through `visit()`, never
    through `owner_path`. If the two ever diverge, one of them is wrong."""
    doc = ODLReader().read(FIXTURE)
    paragraph_owner: dict[int, list[str]] = {}

    def walk(node, ancestors):
        here = ancestors + [node.text]
        for block in node.body_blocks:
            if isinstance(block, Paragraph):
                paragraph_owner[id(block)] = here
        for child in node.children:
            walk(child, here)

    for root in doc.outline:
        walk(root, [])

    for chunk in build_narrative_chunks(doc, _meta(), start_index=0):
        # A chunk merges several paragraphs from ONE node, so any one of the
        # node's paragraphs answers for it; an orphan chunk has no owner and
        # an empty path (narrative_chunk.py's `_orphaned_paragraphs`).
        assert chunk.section_path == [] or chunk.section_path in paragraph_owner.values()


def test_the_contents_page_does_not_capture_the_agency_table():
    """The defect, pinned against the real slice it was measured on: the
    page-10 table must be filed under its own page-10 heading, not under
    the page-2 contents node whose body names the same agency."""
    doc = ODLReader().read(FIXTURE)
    late = [t for t in doc.tables if (t.pages[0] if t.pages else t.page) >= 10]
    assert late, "fixture must contain a table from page 10"
    for table in late:
        chunk = build_table_chunk(table, doc, _meta(), chunk_index=0)
        assert "Table of Contents" not in chunk.section_path
        assert chunk.section_path == [TRAP]
