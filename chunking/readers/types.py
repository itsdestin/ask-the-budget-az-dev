"""Uniform internal records emitted by every reader.

Three readers (`odl_reader`, `mineru_reader`, `docx_reader`) all return
`ExtractedDocument`. Chunk builders consume only this shape. Decouples
format details from chunking logic.

Plain dataclasses (not Pydantic) — these are pipeline records, not a
serialized contract. The serialization contract is `chunking.types.Chunk`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Bbox:
    """PDF user-space bounding box: [x0, y0, x1, y1]."""

    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_list(cls, raw: list[float] | None) -> "Bbox | None":
        if raw is None:
            return None
        if len(raw) != 4:
            raise ValueError(f"bbox must have 4 values, got {len(raw)}: {raw}")
        return cls(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))


@dataclass
class Cell:
    """One table cell. row/col are 0-indexed."""

    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    bbox: Bbox | None = None
    page: int | None = None  # set on multi-page tables so cell→page provenance survives


@dataclass
class Row:
    """A row of cells. Wrapping cells in a Row object — rather than a bare
    list[Cell] — lets the chunk builder iterate `for row in table.rows for cell in row.cells`
    naturally and matches the plan's tests."""

    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    """A logical table — possibly spanning multiple pages (chunk-shape D2)."""

    rows: list[Row] = field(default_factory=list)
    caption: str | None = None
    bbox: Bbox | None = None
    page: int | None = None
    pages: list[int] = field(default_factory=list)
    html: str | None = None  # Original HTML if available (MinerU emits HTML)


@dataclass
class Heading:
    """A section heading. `level` is numeric 1-6; `structure_tag` is the
    PDF structure-tree tag name (Doctitle/H1/H2/...) when the extractor
    surfaced one."""

    text: str
    level: int
    page: int
    bbox: Bbox | None = None
    structure_tag: str | None = None


@dataclass
class Paragraph:
    """A body-text block."""

    text: str
    page: int
    bbox: Bbox | None = None


@dataclass
class Image:
    page: int
    bbox: Bbox | None = None
    source: str | None = None  # path to extracted image file


# Block discriminator — every reader emits one of these per top-level element.
Block = Heading | Paragraph | Table | Image


@dataclass
class Page:
    page_number: int
    blocks: list[Block] = field(default_factory=list)


@dataclass
class DocxParagraph:
    """A paragraph from a DOCX bill. DOCX provenance is `paragraph_id`
    (Word's w14:paraId), not (page, bbox)."""

    text: str
    paragraph_id: str
    style: str = "Normal"
    cells: list[str] | None = None  # tab-split line-item row, when present


@dataclass
class DocxTableCell:
    """One cell from a DOCX table. table_cell_id is deterministic from
    position (e.g. 't1-r1-c1' in run_docx_ingest.py)."""

    text: str
    table_cell_id: str
    row: int
    col: int


# Either kind of DOCX body block can appear inside a Section's body.
DocxBlock = DocxParagraph | DocxTableCell


@dataclass
class Section:
    """A DOCX section — a heading paragraph and the body blocks under it.

    Bill structure (cross-doc-relationships §9):
      - Part 1: agency tables. Heading style 'Normal' with all-caps
        department name. Body paragraphs in 'P 06-*' styles.
      - Part 2: provisions. Heading style 'SEC 06-18' / 'SEC 06-19' / etc.
        Body in 'Normal' style.
    """

    style: str  # 'SEC 06-18' / 'Normal' / 'P 06-1' / etc.
    heading_text: str
    heading_paragraph_id: str
    body_blocks: list[DocxBlock] = field(default_factory=list)
    parsed_heading: dict = field(default_factory=dict)
    # Captured A.R.S. refs across heading + body, for Phase 1b citation enrichment
    ars_refs: list[str] = field(default_factory=list)


@dataclass
class OutlineNode:
    """One node in the document outline tree."""

    text: str
    level: int
    page: int
    children: list["OutlineNode"] = field(default_factory=list)
    # Block indices belonging to this section's body. Lets `outline_path`
    # search section content without re-scanning every block per query.
    body_blocks: list[Block] = field(default_factory=list)


# How many pages a single heading may govern before the outline gives up on
# it. CALIBRATED 2026-08-16 against the live 97,358-chunk corpus with BOTH
# sides of the trade measured, because both sides genuinely degrade:
# too loose keeps wrong headings, too tight strips right ones.
#
#   bound | real sections truncated | agao-afr-fy2024 blocks left under a
#         |     (of 48,382 runs)    | heading that is wrong by 1,000x
#   ------+-------------------------+-------------------------------------
#      3  |    1,211  (2.50%)       |   5
#      5  |      427  (0.88%)       |   5   <-- shipped
#      8  |       98  (0.20%)       |  12
#     10  |       55  (0.11%)       |  14
#     15  |       27  (0.06%)       |  21
#     20  |       24  (0.05%)       |  27
#   none  |        0                |  53   <-- before this change
#
# 5 is the LOOSE EDGE OF THE HARM PLATEAU: bounds 3 and 5 both reach 5
# residual blocks -- the floor, pages genuinely adjacent to the heading --
# and 5 pays a third of 3's price. Going to 8 more than doubles the residual
# to buy back 329 sections. Not a plateau centre and not a safe edge, because
# this metric has a plateau on one axis and is monotonic on the other.
#
# The distribution it is drawn against: 86.5% of contiguous heading runs
# govern ONE page, 94.8% one or two, 99.1% five or fewer. ALL 24 runs longer
# than 20 pages were read and every one is wrong -- "Table of Contents"
# governing 408 consecutive pages of the FY2027 Governor's budget, "Note 3.
# -- Description of Selected Columns" governing 27-49 pages of five separate
# AFRs, and a garbled fused fragment governing 65.
#
# WHY A BOUND AT ALL: `_build_outline` in both readers is a level-stacked
# walk with no distance limit, so a heading stays on the stack until a
# same-or-lower-level heading appears. A document whose real section breaks
# the extractor did not mark as headings -- an AFR's appropriations schedule
# is ~180 consecutive pages of bare `<table>` blocks -- inherits one heading
# for the rest of the book. Measured on agao-afr-fy2024: 121 of 450 passages
# claimed "(expressed in thousands)" over whole-dollar figures, inherited
# from a heading four pages earlier belonging to a DIFFERENT statement.
#
# THE TWO FAILURE MODES ARE NOT SYMMETRIC, which is why the pick leans
# tight. A bound that is too tight yields a chunk with NO heading -- exactly
# what the OpenDataLoader reader already produces for these pages, and what
# the corpus lived with before. A bound that is too loose yields a chunk with
# a CONFIDENTLY WRONG heading, which is citable. Under Invariant 1 those are
# not comparable.
#
# THIS IS A BACKSTOP, NOT A COMPLETE FIX. It cannot help the pages
# immediately after a stale heading, and 5 such blocks remain in the AFR.
# Fixing those needs a real section-boundary signal -- a page that is
# entirely a table carrying its own header row is a new table, whatever the
# last prose heading said -- which is its own design.
MAX_SECTION_PAGES = 5


def drop_stale_sections(stack: list[OutlineNode], page: int) -> None:
    """Pop sections whose heading is too far back to still govern `page`.

    Mutates `stack` in place, popping from the deepest end only. A FRESH
    child therefore protects a stale ancestor, which is deliberate: if a
    heading two pages back sits under one fifty pages back, the nesting is
    real and the ancestor is a genuine parent, not an inheritance accident.
    Only a run of blocks with no nearer heading at all can strand a section.
    """
    while stack and page - stack[-1].page > MAX_SECTION_PAGES:
        stack.pop()


@dataclass
class ExtractedDocument:
    """Output of every reader. Consumed by chunk builders."""

    source_path: Path
    extractor: str  # 'opendataloader' | 'mineru' | 'python-docx'
    pages: list[Page] = field(default_factory=list)
    outline: list[OutlineNode] = field(default_factory=list)
    # DOCX-only — bill sections (Part 1 agency tables + Part 2 provisions).
    # PDF readers leave this empty; the chunk-orchestrator branches on
    # whichever surface is populated.
    sections: list[Section] = field(default_factory=list)

    @property
    def has_tables(self) -> bool:
        return any(isinstance(b, Table) for p in self.pages for b in p.blocks)

    @property
    def tables(self) -> list[Table]:
        return [b for p in self.pages for b in p.blocks if isinstance(b, Table)]

    def outline_path(self, query: str) -> list[str]:
        """Return the breadcrumb of section titles to the deepest section
        whose heading text OR body content contains `query` (case-insensitive
        substring match). Empty list when no match.

        Used by chunk builders / entity stamper to ask "which section does
        this content live under?"
        """
        q = query.casefold()
        best_path: list[str] = []

        def walk(node: OutlineNode, ancestors: list[str]) -> None:
            nonlocal best_path
            here = ancestors + [node.text]
            # Recurse first — children are deeper, prefer them on a match.
            for child in node.children:
                walk(child, here)
            if best_path and len(best_path) >= len(here):
                # A deeper or equal-depth match was already found via descendants.
                return
            if q in node.text.casefold() or any(
                q in _block_text(b).casefold() for b in node.body_blocks
            ):
                best_path = here

        for root in self.outline:
            walk(root, [])

        return best_path


def _block_text(block: Block) -> str:
    """Surface searchable text for a block. Tables flatten cell text."""
    if isinstance(block, Heading) or isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Table):
        return " ".join(c.text for r in block.rows for c in r.cells)
    return ""
