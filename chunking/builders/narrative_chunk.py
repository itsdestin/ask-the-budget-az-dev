"""Narrative chunk builder.

Per chunk-shape D5: target ~512 tokens, hard max 1024. Paragraph-level
merge — never split mid-paragraph (entity boundaries inside a single
paragraph break retrieval signal).

Algorithm:
  1. Walk the document outline tree depth-first. For each node, gather the
     `Paragraph` blocks in its `body_blocks` list (skips `Table` and
     `Image` blocks — tables are handled by `table_chunk.build_table_chunk`).
  2. Within each section, greedily merge consecutive paragraphs into a
     buffer. Flush when the buffer's token count crosses the 512 target
     OR when the next paragraph would push the total past 1024.
  3. Each emitted chunk's text begins with the section path (section >
     subsection > ...) so the embedding signal carries the surrounding
     heading context.

Section path is the breadcrumb of outline-node texts from root to current
node, identical to what `ExtractedDocument.outline_path` would return for
content matched inside this section.
"""
from __future__ import annotations

import logging

from chunking.builders._tokens import count_tokens
from chunking.builders.table_chunk import DocMeta
from chunking.readers.types import (
    ExtractedDocument,
    OutlineNode,
    Paragraph,
)
from chunking.types import Chunk, ChunkProvenance

log = logging.getLogger(__name__)

NARRATIVE_TARGET_TOKENS = 512
NARRATIVE_MAX_TOKENS = 1024


def build_narrative_chunks(
    doc: ExtractedDocument,
    doc_meta: DocMeta,
    *,
    start_index: int = 0,
) -> list[Chunk]:
    """Walk the document outline and emit narrative chunks.

    `start_index` lets the orchestrator interleave narrative + table chunks
    under one zero-padded sequence per doc.
    """
    chunks: list[Chunk] = []
    next_index = start_index

    def emit(text: str, *, section_path: list[str], first_para: Paragraph) -> None:
        nonlocal next_index
        token_count = count_tokens(text)
        if token_count > NARRATIVE_MAX_TOKENS:
            log.warning(
                "narrative chunk exceeds %d tokens (%d) — chunk_id=%s, "
                "section_path=%s",
                NARRATIVE_MAX_TOKENS,
                token_count,
                f"{doc_meta.doc_id}-{next_index:04d}",
                section_path,
            )
        bbox = (
            [first_para.bbox.x0, first_para.bbox.y0, first_para.bbox.x1, first_para.bbox.y1]
            if first_para.bbox
            else None
        )
        chunks.append(
            Chunk(
                chunk_id=f"{doc_meta.doc_id}-{next_index:04d}",
                doc_id=doc_meta.doc_id,
                text=text,
                section_path=section_path,
                is_table=False,
                table_html=None,
                provenance=ChunkProvenance(
                    page=first_para.page,
                    bbox=bbox,
                ),
                fiscal_year=doc_meta.fiscal_year,
                doc_type=doc_meta.doc_type,
                publisher=doc_meta.publisher,
                token_count=token_count,
            )
        )
        next_index += 1

    def visit(node: OutlineNode, ancestors: list[str]) -> None:
        section_path = ancestors + [node.text]
        # Body paragraphs in this node only (outline_path filtering)
        paragraphs = [b for b in node.body_blocks if isinstance(b, Paragraph)]
        if paragraphs:
            _flush_section_into_chunks(
                paragraphs=paragraphs,
                section_path=section_path,
                emit=emit,
            )
        for child in node.children:
            visit(child, section_path)

    for root in doc.outline:
        visit(root, [])

    return chunks


def _flush_section_into_chunks(
    *,
    paragraphs: list[Paragraph],
    section_path: list[str],
    emit,
) -> None:
    """Greedy paragraph-merge until target/max thresholds are crossed."""
    section_header = " > ".join(section_path)
    buffer_paragraphs: list[Paragraph] = []
    buffer_text_parts: list[str] = []
    buffer_tokens = count_tokens(section_header) if section_header else 0

    def flush() -> None:
        nonlocal buffer_paragraphs, buffer_text_parts, buffer_tokens
        if not buffer_paragraphs:
            return
        text = section_header + "\n\n" + "\n\n".join(buffer_text_parts) if section_header else "\n\n".join(buffer_text_parts)
        emit(text, section_path=section_path, first_para=buffer_paragraphs[0])
        buffer_paragraphs = []
        buffer_text_parts = []
        buffer_tokens = count_tokens(section_header) if section_header else 0

    for para in paragraphs:
        para_tokens = count_tokens(para.text)
        # If a single paragraph by itself exceeds the max, flush whatever's
        # buffered and emit the oversize paragraph alone — never split a
        # paragraph across chunks.
        if para_tokens > NARRATIVE_MAX_TOKENS:
            flush()
            emit(
                (section_header + "\n\n" + para.text) if section_header else para.text,
                section_path=section_path,
                first_para=para,
            )
            continue

        # If adding this paragraph would push the buffer past the target AND
        # the buffer already contains content, flush first.
        if buffer_paragraphs and buffer_tokens + para_tokens > NARRATIVE_TARGET_TOKENS:
            flush()

        buffer_paragraphs.append(para)
        buffer_text_parts.append(para.text)
        buffer_tokens += para_tokens

    flush()
