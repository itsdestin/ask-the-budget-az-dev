"""ExtractedDocument.owner_path — which section does this block physically sit in?

The counterpart to the deleted `outline_path`: that one SEARCHED the outline
by text and could return a node hundreds of pages away (spec
`2026-08-26-table-section-path-design.md` §1). This one READS the answer the
reader already recorded when it built the outline.
"""
from __future__ import annotations

from pathlib import Path

from chunking.readers.types import (
    Cell,
    ExtractedDocument,
    Heading,
    OutlineNode,
    Page,
    Paragraph,
    Row,
    Table,
)


def _table(text: str, page: int) -> Table:
    return Table(
        page=page,
        pages=[page],
        rows=[Row(cells=[Cell(text=text, row=0, col=0)])],
        html=f"<table><tr><td>{text}</td></tr></table>",
    )


def _doc_with_a_toc_trap() -> tuple[ExtractedDocument, Table, Table]:
    """Mirrors the real defect: a contents page whose body names every
    agency, and an agency table 9 pages later whose first cell is that
    same name."""
    contents = _table("Acupuncture Examiners, Board of", 1)
    agency = _table("Acupuncture Examiners, Board of", 10)
    orphan = _table("FY 2026 Executive Budget", 1)

    toc_node = OutlineNode(text="Table of Contents", level=1, page=1, body_blocks=[contents])
    agency_node = OutlineNode(
        text="Acupuncture Examiners, Board of", level=1, page=9, body_blocks=[agency]
    )
    doc = ExtractedDocument(
        source_path=Path("fake"),
        extractor="opendataloader",
        pages=[
            Page(page_number=1, blocks=[orphan, Heading(text="Table of Contents", level=1, page=1), contents]),
            Page(page_number=9, blocks=[Heading(text="Acupuncture Examiners, Board of", level=1, page=9)]),
            Page(page_number=10, blocks=[agency]),
        ],
        outline=[toc_node, agency_node],
    )
    return doc, agency, orphan


def test_owner_path_returns_the_node_that_physically_holds_the_block():
    doc, agency, _ = _doc_with_a_toc_trap()
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]


def test_owner_path_is_identity_not_text_so_a_duplicate_string_cannot_win():
    """Both tables carry the identical cell string. A text search returns the
    contents page for BOTH (that is the shipped defect); identity cannot."""
    doc, agency, _ = _doc_with_a_toc_trap()
    contents = doc.outline[0].body_blocks[0]
    assert contents.rows[0].cells[0].text == agency.rows[0].cells[0].text
    assert doc.owner_path(contents) == ["Table of Contents"]
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]


def test_owner_path_is_empty_for_a_block_before_the_first_heading():
    """`_build_outline` appends to `stack[-1]` only when the stack is
    non-empty, so a block before the first heading belongs to no node.
    Spec D2: that is an empty path, not a guess."""
    doc, _, orphan = _doc_with_a_toc_trap()
    assert doc.owner_path(orphan) == []


def test_owner_path_includes_ancestors_deepest_last():
    child = _table("row", 3)
    parent = OutlineNode(
        text="Financial Statements",
        level=1,
        page=2,
        children=[OutlineNode(text="Note 3", level=2, page=3, body_blocks=[child])],
    )
    doc = ExtractedDocument(source_path=Path("fake"), extractor="mineru", outline=[parent])
    assert doc.owner_path(child) == ["Financial Statements", "Note 3"]


def test_owner_path_also_owns_paragraphs_not_just_tables():
    """The narrative builder reaches the same answer through `visit()`; this
    is the same fact from the other side, and Task 3 pins that they agree."""
    para = Paragraph(text="The Baseline includes $1.0 M for the program.", page=4)
    node = OutlineNode(text="Operating Budget", level=1, page=4, body_blocks=[para])
    doc = ExtractedDocument(source_path=Path("fake"), extractor="mineru", outline=[node])
    assert doc.owner_path(para) == ["Operating Budget"]
