"""MinerU reader.

Consumes the per-page JSON written by `scripts/run_mineru.py`:

    {
      "extractor": "mineru-3.1.6",
      "source_pdf": "...",
      "page": <1-indexed int>,
      "blocks": [<entries from MinerU's _content_list.json>]
    }

Block kinds observed (per `samples/extractor-output/mineru/README.md`):
- type='text' with `text_level: 1/2/3` → heading
- type='text' without text_level (or text_level=0) → paragraph
- type='table' with `table_body` (HTML <table>) → table
- type='image' with `img_path` → image

Reader API (mirrors ODL):
    MinerUReader().read(path) -> ExtractedDocument

Multi-page table reassembly (chunk-shape D2): consecutive tables on adjacent
pages with identical column-headers reassemble into one logical table. A
heading between two such tables prevents merging — a heading marks a new
section, so even matching column-headers belong to a separate logical table.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

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

_PAGE_FILE_RE = re.compile(r"^page-(\d+)\.json$", re.IGNORECASE)


class MinerUReader:
    """Reads MinerU per-page output → ExtractedDocument."""

    def read(self, path: Path | str) -> ExtractedDocument:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"MinerU output path does not exist: {path}")

        if path.is_dir():
            page_files = self._collect_page_files(path)
            pages = [self._read_page_file(pf) for pf in page_files]
        else:
            pages = [self._read_page_file(path)]

        # Multi-page table reassembly happens after all pages are loaded.
        pages = self._reassemble_multi_page_tables(pages)

        outline = self._build_outline(pages)

        return ExtractedDocument(
            source_path=path,
            extractor="mineru",
            pages=pages,
            outline=outline,
        )

    # --- file-level helpers --------------------------------------------------

    @staticmethod
    def _collect_page_files(directory: Path) -> list[Path]:
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
        # Outer `page` is authoritative — block-internal page_idx may carry
        # the CLI's local re-indexing within a per-range invocation.
        page_number = int(raw.get("page") or 0)
        blocks: list[Block] = []
        for el in raw.get("blocks", []) or []:
            block = self._parse_block(el, page=page_number)
            if block is not None:
                blocks.append(block)
        return Page(page_number=page_number, blocks=blocks)

    # --- block parsing -------------------------------------------------------

    def _parse_block(self, el: dict, *, page: int) -> Block | None:
        btype = el.get("type")
        bbox = Bbox.from_list(el.get("bbox"))

        if btype == "text":
            text = str(el.get("text") or el.get("content") or "").strip()
            if not text:
                return None
            level = el.get("text_level")
            if level is not None:
                try:
                    lvl = int(level)
                    if lvl > 0:
                        return Heading(text=text, level=lvl, page=page, bbox=bbox)
                except (TypeError, ValueError):
                    pass
            return Paragraph(text=text, page=page, bbox=bbox)

        if btype == "table":
            html = str(el.get("table_body") or "")
            table = self._parse_html_table(html, page=page, bbox=bbox)
            return table

        if btype == "image":
            return Image(
                page=page,
                bbox=bbox,
                source=el.get("img_path") or el.get("image_path") or el.get("source"),
            )

        # page_number, footer, equation, etc. — drop for now. WS6 surfaces gaps.
        return None

    @staticmethod
    def _parse_html_table(html: str, *, page: int, bbox: Bbox | None) -> Table:
        """Parse MinerU's HTML <table> string into Row/Cell records.

        MinerU sometimes wraps headers in <thead>, sometimes inlines them as
        the first <tr>. We treat the first row as the header row regardless;
        downstream chunk-builder logic (chunk-shape D6) just needs to know
        the column labels.
        """
        soup = BeautifulSoup(html, "html.parser")
        rows: list[Row] = []
        # bs4's soup.find_all("tr") returns rows in document order across
        # <thead>/<tbody>/<tfoot>, which is exactly what we want.
        for r_idx, tr in enumerate(soup.find_all("tr")):
            cells: list[Cell] = []
            # Both <th> and <td> count as cells; preserve source order.
            for c_idx, td in enumerate(tr.find_all(["td", "th"])):
                row_span = _safe_int(td.get("rowspan"), default=1)
                col_span = _safe_int(td.get("colspan"), default=1)
                cells.append(
                    Cell(
                        text=td.get_text(separator=" ", strip=True),
                        row=r_idx,
                        col=c_idx,
                        row_span=row_span,
                        col_span=col_span,
                        page=page,
                    )
                )
            if cells:
                rows.append(Row(cells=cells))
        return Table(
            rows=rows,
            bbox=bbox,
            page=page,
            pages=[page],
            html=html,
        )

    # --- multi-page table reassembly ----------------------------------------

    def _reassemble_multi_page_tables(self, pages: list[Page]) -> list[Page]:
        """Merge tables on consecutive pages with matching header rows.

        Walks blocks in document order across pages. Tracks "the last table
        seen with no intervening heading" — when a new table appears whose
        header row matches that last table's, append the new table's body
        rows to the older table and drop the new table from its page's
        block list. A heading anywhere between two tables breaks the chain.
        """
        # Flat walk in document order to detect chains; mutate in place.
        last_table: Table | None = None
        last_table_owner_page: Page | None = None

        for page in pages:
            new_blocks: list[Block] = []
            for block in page.blocks:
                if isinstance(block, Heading):
                    last_table = None  # heading breaks the chain
                    new_blocks.append(block)
                    continue
                if isinstance(block, Table):
                    if (
                        last_table is not None
                        and _same_header(last_table, block)
                    ):
                        # Merge: append body rows (skip header), extend pages
                        body_rows = list(block.rows[1:])  # all rows after header
                        # Re-number row indices for consistency in the merged table
                        offset = len(last_table.rows)
                        for i, row in enumerate(body_rows):
                            for cell in row.cells:
                                cell.row = offset + i
                        last_table.rows.extend(body_rows)
                        if block.page is not None and block.page not in last_table.pages:
                            last_table.pages = sorted(set(last_table.pages + [block.page]))
                        # Don't add this block — it's been absorbed
                        continue
                    last_table = block
                    last_table_owner_page = page
                new_blocks.append(block)
            page.blocks = new_blocks

        return pages

    # --- outline tree --------------------------------------------------------

    def _build_outline(self, pages: list[Page]) -> list[OutlineNode]:
        """Stack-based outline construction. Same algorithm as ODL reader —
        but MinerU heading levels start at 1 and are used directly.
        """
        roots: list[OutlineNode] = []
        stack: list[OutlineNode] = []
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
        return roots


def _safe_int(v, *, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _same_header(a: Table, b: Table) -> bool:
    """Tables share a header row when both have rows AND the first row's
    cell texts match exactly. Casefolded equality — MinerU OCR may shift
    casing across pages but column names are stable."""
    if not a.rows or not b.rows:
        return False
    a_cells = [c.text.casefold().strip() for c in a.rows[0].cells]
    b_cells = [c.text.casefold().strip() for c in b.rows[0].cells]
    return a_cells == b_cells and len(a_cells) > 0
