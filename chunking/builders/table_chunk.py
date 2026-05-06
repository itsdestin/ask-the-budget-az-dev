"""Table chunk builder.

Per chunk-shape D1 + D6: a whole logical table (possibly spanning multiple
pages — see MinerU reader's reassembly) becomes ONE chunk. Headers + section
path are stamped into both `text` (for embedding signal) and structured
metadata (`section_path`, `table_html`).

Embedded text format:

    {section path joined by ' > '}
    {caption (optional)}
    {header row, tab-joined}
    {row 1, tab-joined}
    {row 2, tab-joined}
    ...

One row per line so retrieval surfaces row-keyword queries against
individual rows. Original HTML is preserved on `chunk.table_html` for UI
rendering.

Big-table guard (chunk-shape D-defer-2): when the resulting text exceeds
3K tokens, a warning is logged and the chunk is still emitted with a
`needs_review` flag. The threshold + flag are intentionally simple — a
real subdivision rule waits on Phase 1b retrieval-quality signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from chunking.builders._tokens import count_tokens
from chunking.readers.types import ExtractedDocument, Heading, Table
from chunking.types import Chunk, ChunkProvenance

log = logging.getLogger(__name__)

BIG_TABLE_TOKEN_THRESHOLD = 3000


@dataclass
class DocMeta:
    """The minimum doc-level metadata each chunk needs.

    Mirrors the public fields on `chunk.types.Chunk` that aren't derivable
    from the table itself. `doc_id` is what the dispatcher's `make_doc_id`
    produced for this document.

    `extractor` / `source_format` are used by the orchestrator to dispatch
    to the right reader. `source_url` is consumed by the entity stamper
    (JLBC URL → per-agency slug).
    """

    doc_id: str
    publisher: str
    doc_type: str
    fiscal_year: int
    extractor: str = ""  # 'mineru' | 'opendataloader' | 'python-docx'
    source_format: str = ""  # 'pdf' | 'docx'
    source_url: str | None = None


def build_table_chunk(
    table: Table,
    doc: ExtractedDocument,
    doc_meta: DocMeta,
    *,
    chunk_index: int,
    section_path: list[str] | None = None,
) -> Chunk:
    """Emit one Chunk for a logical Table.

    `section_path`, when omitted, is resolved from `doc.outline` by finding
    the deepest heading whose body content includes any cell text from the
    table. (See `_resolve_section_path` for the search rule.)
    """
    if section_path is None:
        section_path = _resolve_section_path(table, doc)

    text = _build_text(table, section_path)
    token_count = count_tokens(text)

    if token_count > BIG_TABLE_TOKEN_THRESHOLD:
        # Plan §3.3.a step 3: warn, ship, flag for review. Real subdivision
        # rule deferred to Phase 1b once we see retrieval behavior.
        log.warning(
            "table chunk exceeds %d tokens (%d) — chunk_id=%s, "
            "section_path=%s; flagging for manual review",
            BIG_TABLE_TOKEN_THRESHOLD,
            token_count,
            f"{doc_meta.doc_id}-{chunk_index:04d}",
            section_path,
        )

    provenance = ChunkProvenance(
        page=table.page if table.page is not None else (table.pages[0] if table.pages else None),
        bbox=[table.bbox.x0, table.bbox.y0, table.bbox.x1, table.bbox.y1] if table.bbox else None,
    )

    return Chunk(
        chunk_id=f"{doc_meta.doc_id}-{chunk_index:04d}",
        doc_id=doc_meta.doc_id,
        text=text,
        section_path=section_path,
        is_table=True,
        table_html=table.html,
        provenance=provenance,
        fiscal_year=doc_meta.fiscal_year,
        doc_type=doc_meta.doc_type,
        publisher=doc_meta.publisher,
        token_count=token_count,
    )


def _build_text(table: Table, section_path: list[str]) -> str:
    """Format the chunk's embedded text.

    Lines:
      0: section path, joined by ' > '
      1: caption (when present)
      2..: header row, then each body row, all tab-joined
    """
    lines: list[str] = []
    if section_path:
        lines.append(" > ".join(section_path))
    if table.caption:
        lines.append(table.caption)
    for row in table.rows:
        cells = [_clean(c.text) for c in row.cells]
        lines.append("\t".join(cells))
    return "\n".join(lines)


def _clean(s: str) -> str:
    return " ".join(s.split())


def _resolve_section_path(table: Table, doc: ExtractedDocument) -> list[str]:
    """Best-effort section path for a table.

    Strategy: walk the document's outline searching for any of the table's
    cell text. Use `outline_path(query)` for the first non-trivial cell text
    that yields a non-empty match. If nothing matches, fall back to the
    nearest preceding heading on the table's first page.
    """
    candidate_texts: list[str] = []
    for row in table.rows[:3]:  # only need to probe a few cells
        for cell in row.cells:
            t = _clean(cell.text)
            if len(t) >= 4:  # avoid 1-2 char tokens that match too many headings
                candidate_texts.append(t)
    for q in candidate_texts:
        path = doc.outline_path(q)
        if path:
            return path

    # Fallback: nearest-preceding-heading on the table's first page
    target_page = table.pages[0] if table.pages else table.page
    if target_page is not None:
        latest_heading: list[str] = []
        stack: list[str] = []
        for page in doc.pages:
            for block in page.blocks:
                if isinstance(block, Heading):
                    while stack and len(stack) >= block.level:
                        stack.pop()
                    stack.append(block.text)
                    latest_heading = list(stack)
                if page.page_number == target_page and block is table:
                    return latest_heading
        if latest_heading:
            return latest_heading

    return []
