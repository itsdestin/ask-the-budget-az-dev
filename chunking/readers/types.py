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
    # The blocks that physically sit under this heading, recorded at read
    # time by `_build_outline`. Read by `ExtractedDocument.owner_path`
    # (which section is this block in?) and by
    # `narrative_chunk.visit` (which paragraphs belong to this section?).
    body_blocks: list[Block] = field(default_factory=list)


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
    # Memo for `owner_path`, built on first call. Readers construct the
    # outline as the LAST step of `read()` and never mutate it afterwards,
    # so one build is safe; `init=False` + `compare=False` keep it out of
    # the dataclass's constructor, equality and repr.
    _owner_memo: dict[int, list[str]] | None = field(
        default=None, init=False, compare=False, repr=False
    )

    @property
    def has_tables(self) -> bool:
        return any(isinstance(b, Table) for p in self.pages for b in p.blocks)

    @property
    def tables(self) -> list[Table]:
        return [b for p in self.pages for b in p.blocks if isinstance(b, Table)]

    def owner_path(self, block: Block) -> list[str]:
        """Breadcrumb of the outline node that PHYSICALLY owns `block`.

        `_build_outline` (both PDF readers) appends every non-`Heading`
        block to `stack[-1].body_blocks` — the innermost heading open at
        that point in the document. So the answer to "which section is this
        block in?" was recorded at read time and needs no searching.

        Matching is by IDENTITY (`is`), never by text. That is the whole
        point: on 2026-08-26 the text-searching `outline_path` was measured
        binding tables to headings a median of 93 pages away, because two
        different blocks routinely carry the same string — a contents page
        lists every agency name in the book, so an agency's own table finds
        its name there first (spec §1.1).

        Returns `[]` when no node owns `block` — a block appearing before
        the document's first heading, which `_build_outline` attaches to
        nothing. Spec D2 makes that an empty `section_path` rather than a
        guess.
        """
        if self._owner_memo is None:
            memo: dict[int, list[str]] = {}

            def walk(node: "OutlineNode", ancestors: list[str]) -> None:
                here = ancestors + [node.text]
                for b in node.body_blocks:
                    memo[id(b)] = here
                for child in node.children:
                    walk(child, here)

            for root in self.outline:
                walk(root, [])
            self._owner_memo = memo
        return list(self._owner_memo.get(id(block), []))
