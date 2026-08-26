"""OpenDataLoader-PDF reader.

Consumes the per-page JSON shape written by `scripts/run_opendataloader.py`:

    {
      "extractor": "opendataloader-2.4.1",
      "source_pdf": "...",
      "page": <int>,
      "blocks": [<element>, ...]
    }

Each block is a dict with `type` ∈ {paragraph, heading, image, table}, a
`page number` field (literal key — note the space), `bounding box`, and
type-specific fields. See `samples/extractor-output/opendataloader/README.md`
for the full schema.

Reader API:

    ODLReader().read(path) -> ExtractedDocument

`path` may be either a single page-N.json file or a directory containing
`page-*.json` files. Directory mode collects every page and orders them
numerically (page-2 before page-10).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from chunking.readers.types import (
    Bbox,
    Block,
    Cell,
    ExtractedDocument,
    Heading,
    Image,
    OutlineNode,
    Page,
    Paragraph,
    Row,
    Table,
)

# Map ODL's PDF structure-tree tag names to a numeric heading level. ODL's
# own `heading level` field is mostly correct, but Doctitle in particular
# isn't always tagged with a numeric level — fall back to this map when the
# numeric level is missing or zero.
_STRUCTURE_TAG_LEVEL = {
    "Doctitle": 1,
    "Subtitle": 1,
    "H1": 2,
    "H2": 3,
    "H3": 4,
    "H4": 5,
    "H5": 6,
    "H6": 6,
}

_PAGE_FILE_RE = re.compile(r"^page-(\d+)\.json$", re.IGNORECASE)


class ODLReader:
    """Reads OpenDataLoader-PDF output → ExtractedDocument."""

    def read(self, path: Path | str) -> ExtractedDocument:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"ODL output path does not exist: {path}")

        if path.is_dir():
            page_files = self._collect_page_files(path)
            pages = [self._read_page_file(pf) for pf in page_files]
        else:
            pages = [self._read_page_file(path)]

        # Source PDF reference taken from the first page's record (all pages
        # in one extractor run share the same source).
        source_pdf = self._first_source_pdf(pages, fallback=path)

        outline = self._build_outline(pages)

        return ExtractedDocument(
            source_path=Path(source_pdf),
            extractor="opendataloader",
            pages=pages,
            outline=outline,
        )

    # --- file-level helpers --------------------------------------------------

    @staticmethod
    def _collect_page_files(directory: Path) -> list[Path]:
        """Return page-N.json files sorted by N (numeric, not lexicographic)."""
        candidates: list[tuple[int, Path]] = []
        for p in directory.iterdir():
            if not p.is_file():
                continue
            m = _PAGE_FILE_RE.match(p.name)
            if not m:
                continue
            candidates.append((int(m.group(1)), p))
        candidates.sort(key=lambda pair: pair[0])
        return [p for _, p in candidates]

    def _read_page_file(self, path: Path) -> Page:
        raw = json.loads(path.read_text(encoding="utf-8"))
        page_number = int(raw.get("page") or 0)
        blocks: list[Block] = []
        for el in raw.get("blocks", []) or []:
            block = self._parse_block(el, default_page=page_number)
            if block is not None:
                blocks.append(block)
        return Page(page_number=page_number, blocks=blocks)

    @staticmethod
    def _first_source_pdf(pages: list[Page], fallback: Path) -> Path:
        # If any page record had a source_pdf (we don't currently keep it
        # on the Page dataclass — we lose it after parsing), use the
        # caller's path as a safe fallback. This is purely informational
        # provenance on ExtractedDocument; the chunk builder doesn't depend
        # on it being the actual PDF.
        return fallback

    # --- block parsing -------------------------------------------------------

    def _parse_block(self, el: dict, *, default_page: int) -> Block | None:
        btype = el.get("type")
        page = self._page_of(el, default_page)
        bbox = Bbox.from_list(el.get("bounding box"))

        if btype == "heading":
            tag = el.get("level")
            level_raw = el.get("heading level")
            level = self._resolve_heading_level(level_raw, tag)
            return Heading(
                text=str(el.get("content") or "").strip(),
                level=level,
                page=page,
                bbox=bbox,
                structure_tag=tag,
            )
        if btype == "paragraph":
            text = str(el.get("content") or "").strip()
            if not text:
                return None
            return Paragraph(text=text, page=page, bbox=bbox)
        if btype == "image":
            return Image(page=page, bbox=bbox, source=el.get("source"))
        if btype == "table":
            return self._parse_table(el, default_page=page, table_bbox=bbox)
        # Other types (footnote, etc.) — not yet observed in real corpus;
        # silently drop. WS6 will surface anything we missed.
        return None

    def _parse_table(
        self, el: dict, *, default_page: int, table_bbox: Bbox | None
    ) -> Table:
        rows: list[Row] = []
        all_pages: set[int] = set()
        for r_idx, row_dict in enumerate(el.get("rows", []) or []):
            cells: list[Cell] = []
            for c_idx, cell_dict in enumerate(row_dict.get("cells", []) or []):
                cell_page = self._page_of(cell_dict, default_page)
                all_pages.add(cell_page)
                cells.append(
                    Cell(
                        text=_concat_cell_text(cell_dict),
                        row=r_idx,
                        col=c_idx,
                        row_span=int(cell_dict.get("row_span") or 1),
                        col_span=int(cell_dict.get("column_span") or cell_dict.get("col_span") or 1),
                        bbox=Bbox.from_list(cell_dict.get("bounding box")),
                        page=cell_page,
                    )
                )
            rows.append(Row(cells=cells))
        return Table(
            rows=rows,
            bbox=table_bbox,
            page=default_page,
            pages=sorted(all_pages) if all_pages else [default_page],
        )

    @staticmethod
    def _page_of(d: dict, default: int) -> int:
        # ODL uses the literal key 'page number' (with a space) in its JSON
        v = d.get("page number")
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _resolve_heading_level(level_raw, structure_tag: str | None) -> int:
        try:
            n = int(level_raw)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
        if structure_tag and structure_tag in _STRUCTURE_TAG_LEVEL:
            return _STRUCTURE_TAG_LEVEL[structure_tag]
        return 1

    # --- outline tree --------------------------------------------------------

    def _build_outline(self, pages: list[Page]) -> list[OutlineNode]:
        """Stack-based outline construction from the heading levels.

        Walk every block in document order. On a Heading, pop the stack down
        to the parent of the new node (last heading whose level < new's level)
        and push the new node. Non-heading blocks attach to the current
        deepest section's body_blocks.
        
        THIS IS WHERE A CHUNK'S `section_path` COMES FROM. Both builders
        read the `body_blocks` this method fills:
        `narrative_chunk.visit` walks the tree for paragraphs, and
        `table_chunk.build_table_chunk` asks
        `ExtractedDocument.owner_path(table)`.

        Until 2026-08-26 the table side instead SEARCHED the outline by
        text and this docstring warned that the walk below was not
        load-bearing. It is now. A bounded version of the walk was built,
        calibrated and shipped against the old design on 2026-08-16, was
        measured to change ZERO chunks, and was reverted (`1292030`) —
        because it bounded a mechanism nothing read. That no longer
        applies, which cuts both ways: **whatever you change here now
        DOES move production chunks.** Run `chunk_doc` end-to-end over
        cached extractor output and diff the section paths first
        (`uv run python -m chunking.repair_section_paths --doc <doc_id>`
        is a dry run that prints old vs new per table).
        """
        roots: list[OutlineNode] = []
        stack: list[OutlineNode] = []  # current ancestor chain, deepest last

        for page in pages:
            for block in page.blocks:
                if isinstance(block, Heading):
                    node = OutlineNode(text=block.text, level=block.level, page=block.page)
                    while stack and stack[-1].level >= node.level:
                        stack.pop()
                    if stack:
                        stack[-1].children.append(node)
                    else:
                        roots.append(node)
                    stack.append(node)
                else:
                    if stack:
                        stack[-1].body_blocks.append(block)
                    # Body blocks before the first heading are dropped from
                    # the outline tree (they have no parent section). They
                    # still live on the Page; just not addressable via
                    # outline_path. Acceptable for AZ budget docs which all
                    # start with a Doctitle.
        return roots


def _concat_cell_text(cell: dict) -> str:
    """ODL cells nest their text in a `kids` array of paragraph/heading
    descendants. Concatenate every descendant's `content` field with single
    spaces — same convention as `scripts/run_opendataloader.py::_cell_text`.
    """
    parts: list[str] = []

    def walk(node: dict) -> None:
        c = node.get("content")
        if c:
            parts.append(str(c))
        for child in node.get("kids", []) or []:
            walk(child)

    walk(cell)
    return " ".join(p.strip() for p in parts if p.strip()).strip()
