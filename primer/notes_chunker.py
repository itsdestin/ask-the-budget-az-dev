"""AFR Notes section chunker.

Per plan §5.3, the AGAO Annual Financial Report's Notes section
(typically pp. 174-181 of the FY25 AFR) describes and contextualizes
the financial-statement tables. Each Note gets ingested as one
narrative chunk under doc_id `agao-afr-fy25-notes` with section_path =
`["Notes to Financial Statements", "Note N — <title>"]`.

Most Notes are short (< 500 tokens), so each Note maps cleanly to one
narrative-sized chunk. Bigger Notes still emit a single chunk — bounding
the size at the per-Note granularity is intentional so retrieval can
return one Note at a time.

Step 3: defined-table-name → chunk-id mapping. When a Note's body cites
a named financial statement (e.g. 'Statement of Revenues, Expenditures
and Changes in Fund Balance'), capture the mapping. Phase 1b retrieval
will use it to surface the relevant Note chunk when retrieving the
matching table chunks.

Public API:
    chunk_afr_notes(doc, doc_meta) -> tuple[list[Chunk], dict[str, str]]

Returns:
    chunks         — one Chunk per Note section
    table_map      — { "Statement of …": chunk_id, … }
"""
from __future__ import annotations

import re
from typing import Iterable

from chunking.builders._tokens import count_tokens
from chunking.builders.table_chunk import DocMeta
from chunking.readers.types import (
    ExtractedDocument,
    OutlineNode,
    Paragraph,
)
from chunking.types import Chunk, ChunkProvenance

# Outline heading text that opens the Notes section. Case-insensitive
# match in `_find_section_node` so 'NOTES TO FINANCIAL STATEMENTS' or
# 'Notes To Financial Statements' both work.
NOTES_HEADING = "Notes to Financial Statements"

# Heading-level regex for Note 1..Note N. Allows several dash forms
# (em-dash, en-dash, hyphen, colon) between the number and the title.
_NOTE_HEADING_RE = re.compile(
    r"^Note\s+(\d+)\s*[—–\-:]\s*(.+)$",
    re.IGNORECASE,
)

# Names of financial statements that Notes commonly cite. Detection is
# case-sensitive substring search since these are formal, capitalized
# titles in the AFR.
_TRACKED_STATEMENTS = (
    "Statement of Revenues, Expenditures and Changes in Fund Balance",
    "Statement of Net Position",
    "Statement of Activities",
    "Statement of Cash Flows",
    "Statement of Fiduciary Net Position",
    "Statement of Changes in Fiduciary Net Position",
)


def chunk_afr_notes(
    doc: ExtractedDocument,
    doc_meta: DocMeta,
) -> tuple[list[Chunk], dict[str, str]]:
    """Walk the Notes section of an AFR doc, emit one chunk per Note.

    Returns (chunks, table_name_to_chunk_id_map).
    """
    section = _find_section_node(doc.outline, NOTES_HEADING)
    if section is None:
        return [], {}

    chunks: list[Chunk] = []
    table_map: dict[str, str] = {}

    for idx, child in enumerate(_iter_note_nodes(section)):
        body_paragraphs = [
            block for block in child.body_blocks if isinstance(block, Paragraph)
        ]
        body_paragraphs = [p for p in body_paragraphs if p.text.strip()]
        if not body_paragraphs:
            # Empty heading (e.g. 'Note 7 — TBD' with no body) — drop.
            continue

        section_path = [section.text.strip(), child.text.strip()]
        section_header = " > ".join(section_path)
        body = "\n\n".join(p.text.strip() for p in body_paragraphs)
        text = f"{section_header}\n\n{body}"

        first_para = body_paragraphs[0]
        bbox = (
            [first_para.bbox.x0, first_para.bbox.y0, first_para.bbox.x1, first_para.bbox.y1]
            if first_para.bbox
            else None
        )
        chunk = Chunk(
            chunk_id=f"{doc_meta.doc_id}-{idx:04d}",
            doc_id=doc_meta.doc_id,
            text=text,
            section_path=section_path,
            is_table=False,
            table_html=None,
            provenance=ChunkProvenance(page=first_para.page, bbox=bbox),
            fiscal_year=doc_meta.fiscal_year,
            doc_type=doc_meta.doc_type,
            publisher=doc_meta.publisher,
            token_count=count_tokens(text),
        )
        chunks.append(chunk)

        for stmt in _find_referenced_statements(body):
            # First-Note-wins: don't overwrite a prior chunk's ownership.
            # If a statement is cited in multiple Notes, the Phase 1b
            # join can be enriched later — for now, the most-likely
            # owner is the Note that first defines/references it.
            if stmt not in table_map:
                table_map[stmt] = chunk.chunk_id

    return chunks, table_map


# --- helpers ---------------------------------------------------------------


def _find_section_node(outline: list[OutlineNode], heading: str) -> OutlineNode | None:
    target = heading.casefold().strip()

    def walk(node: OutlineNode) -> OutlineNode | None:
        if node.text.casefold().strip() == target:
            return node
        for child in node.children:
            found = walk(child)
            if found is not None:
                return found
        return None

    for root in outline:
        found = walk(root)
        if found is not None:
            return found
    return None


def _iter_note_nodes(section: OutlineNode) -> Iterable[OutlineNode]:
    """Yield each child whose heading matches the 'Note N — title' pattern.

    Uses the regex to filter — guards against unrelated H2 headings that
    might live under the Notes section (e.g. introductory paragraphs).
    """
    for child in section.children:
        if _NOTE_HEADING_RE.match(child.text.strip()):
            yield child


def _find_referenced_statements(body_text: str) -> list[str]:
    """Return any tracked statement names that appear verbatim in `body_text`."""
    return [stmt for stmt in _TRACKED_STATEMENTS if stmt in body_text]
