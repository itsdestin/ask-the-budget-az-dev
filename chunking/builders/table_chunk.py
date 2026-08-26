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

from chunking.builders._tokens import count_tokens
from chunking.readers.types import ExtractedDocument, Table

# DocMeta moved to chunking.types (it's doc-level, not table-level); re-exported
# here so the existing import sites keep working.
from chunking.types import Chunk, ChunkProvenance, DocMeta

log = logging.getLogger(__name__)

BIG_TABLE_TOKEN_THRESHOLD = 3000

__all__ = ["BIG_TABLE_TOKEN_THRESHOLD", "DocMeta", "build_table_chunk"]


def build_table_chunk(
    table: Table,
    doc: ExtractedDocument,
    doc_meta: DocMeta,
    *,
    chunk_index: int,
    section_path: list[str] | None = None,
) -> Chunk:
    """Emit one Chunk for a logical Table.

    `section_path`, when omitted, is the heading the table PHYSICALLY sits
    under — `doc.owner_path(table)`, the same fact `narrative_chunk.visit`
    reads for paragraphs, so two chunks on one page can no longer disagree
    about their section.

    It used to be resolved by searching the whole document for the table's
    own cell text (`outline_path`). Measured 2026-08-26 on the live corpus:
    that put tables a MEDIAN of 93 pages from the heading they were given,
    and filed 1,079 of the 1,246 tables in the FY2026 Governor's Budget
    under its table of contents, because the contents page names every
    agency in the book and matched first. Do not reintroduce a text search
    here. Spec: docs/superpowers/specs/2026-08-26-table-section-path-design.md
    """
    if section_path is None:
        section_path = doc.owner_path(table)

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
