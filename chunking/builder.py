"""Top-level chunking orchestrator.

Walks one document's extractor output, builds the appropriate chunks
(table + narrative for PDFs; section-per-chunk for DOCX bills), stamps
every chunk via the entity stamper, and optionally writes them as NDJSON
to `data/chunks/<doc-id>.json`.

Public API:

    chunk_doc(*, extractor_output_path, doc_meta, output_dir=None,
              stamper=None) -> list[Chunk]

Reader dispatch is by `doc_meta.extractor`. Four extractors known:
    - 'mineru'           → MinerUReader
    - 'mineru-ocr'       → MinerUReader (OCR mode; same output shape)
    - 'opendataloader'   → ODLReader
    - 'python-docx'      → DocxReader

DOCX bills (`extractor='python-docx'`) emit one chunk per `Section` from
the reader. PDFs (`mineru` / `opendataloader`) emit table chunks first,
then narrative chunks, all under one zero-padded sequence per doc.
"""
from __future__ import annotations

import logging
from pathlib import Path

from chunking.builders.narrative_chunk import build_narrative_chunks
from chunking.builders.table_chunk import DocMeta, build_table_chunk
from chunking.builders._tokens import count_tokens
from chunking.entity_stamper import EntityStamper
from chunking.readers.docx_reader import DocxReader
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.odl_reader import ODLReader
from chunking.readers.types import (
    DocxParagraph,
    DocxTableCell,
    ExtractedDocument,
    Section,
)
from chunking.table_text import OPERATING_TABLE_DOC_TYPES
from chunking.types import Chunk, ChunkProvenance

log = logging.getLogger(__name__)


_READER_REGISTRY = {
    "mineru": MinerUReader,
    # MinerU's OCR mode (ingest/ladder.py's last PDF rung) writes the SAME
    # output format -- page-N.json files that MinerUReader reads via
    # `_PAGE_FILE_RE` regardless of which rung produced them -- so the OCR
    # rung needs a NAME here, not a second reader. (The "discover whichever
    # method subdirectory MinerU produced" step -- auto / txt / ocr -- is a
    # DIFFERENT layer: it lives in scripts/run_mineru.py's
    # `_read_mineru_output`, upstream of what this reader ever sees; by the
    # time a page reaches `_extract_dir(job, method)` it is already the
    # flat page-N.json shape this reader expects. Two different modules,
    # cited correctly here so a future reader doesn't go looking for
    # subdirectory-discovery logic in the wrong file.) Without this entry,
    # an OCR extraction succeeds and then `chunk_doc` raises "Unknown
    # extractor" -- a defect a review caught once already on this plan.
    "mineru-ocr": MinerUReader,
    "opendataloader": ODLReader,
    "python-docx": DocxReader,
}


def chunk_doc(
    *,
    extractor_output_path: Path | str,
    doc_meta: DocMeta,
    output_dir: Path | str | None = None,
    stamper: EntityStamper | None = None,
    source_pdf: Path | str | None = None,
) -> list[Chunk]:
    """Read one doc's extractor output, build chunks, stamp, optionally write.

    `source_pdf` (spec §3.2) lets the MinerU reader rebuild agency
    operating tables from the PDF text layer. It is used only for the two
    in-scope doc types (`OPERATING_TABLE_DOC_TYPES`) and only when the
    given path is a `.pdf` — a DOCX source or an out-of-scope doc type
    reads exactly as before, and `MinerUReader` never opens the file.
    """
    if not doc_meta.extractor:
        raise ValueError(
            "doc_meta.extractor is required (one of: "
            f"{sorted(_READER_REGISTRY.keys())})"
        )
    reader_cls = _READER_REGISTRY.get(doc_meta.extractor)
    if reader_cls is None:
        raise ValueError(
            f"Unknown extractor: {doc_meta.extractor!r} "
            f"(known: {sorted(_READER_REGISTRY.keys())})"
        )

    pdf = Path(source_pdf) if source_pdf is not None else None
    # WHY `reader_cls is MinerUReader` rather than `doc_meta.extractor in
    # (...)`: 'mineru' and 'mineru-ocr' both map to MinerUReader in
    # _READER_REGISTRY (same class object), so this one check covers both
    # rungs without hardcoding their names here too.
    if (
        pdf is not None
        and reader_cls is MinerUReader
        and doc_meta.doc_type in OPERATING_TABLE_DOC_TYPES
        and pdf.suffix.lower() == ".pdf"
    ):
        reader = MinerUReader(source_pdf=pdf)
    else:
        reader = reader_cls()
    doc = reader.read(Path(extractor_output_path))

    # Build chunks. Tables first (PDFs), then narrative; or section-per-chunk
    # for DOCX. The orchestrator owns the chunk-index sequence so all chunks
    # in one doc share a dense zero-padded numbering regardless of which
    # builder emitted them.
    chunks: list[Chunk] = []

    if doc.sections:
        # DOCX path
        chunks.extend(_build_docx_chunks(doc, doc_meta))
    else:
        # PDF path: tables first, then narrative
        next_idx = 0
        for table in doc.tables:
            chunks.append(
                build_table_chunk(table, doc, doc_meta, chunk_index=next_idx)
            )
            next_idx += 1
        narrative = build_narrative_chunks(doc, doc_meta, start_index=next_idx)
        chunks.extend(narrative)

    # Stamp every chunk via the entity stamper
    if stamper is None:
        stamper = EntityStamper.from_default_paths()
    chunks = [stamper.stamp(c, source_url=doc_meta.source_url) for c in chunks]

    # Optionally persist as NDJSON
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{doc_meta.doc_id}.json"
        with out_path.open("w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(chunk.model_dump_json() + "\n")

    return chunks


def _build_docx_chunks(doc: ExtractedDocument, doc_meta: DocMeta) -> list[Chunk]:
    """One chunk per Section. Heading + body text concatenated; provenance
    points at the heading paragraph_id.

    Sections with empty heading_paragraph_id (e.g. the synthetic 'preamble'
    section that catches body text appearing before any heading) emit a
    chunk anchored to their first body block's paragraph_id.
    """
    out: list[Chunk] = []
    for idx, section in enumerate(doc.sections):
        text = _docx_section_text(section)
        if not text.strip():
            continue
        paragraph_id = section.heading_paragraph_id or _first_body_para_id(section)
        if not paragraph_id:
            log.warning(
                "section %r (style=%s) has no usable paragraph_id; skipping",
                section.heading_text[:60],
                section.style,
            )
            continue
        out.append(
            Chunk(
                chunk_id=f"{doc_meta.doc_id}-{idx:04d}",
                doc_id=doc_meta.doc_id,
                text=text,
                section_path=[section.heading_text] if section.heading_text else [section.style],
                is_table=False,
                table_html=None,
                provenance=ChunkProvenance(paragraph_id=paragraph_id),
                fiscal_year=doc_meta.fiscal_year,
                doc_type=doc_meta.doc_type,
                publisher=doc_meta.publisher,
                token_count=count_tokens(text),
            )
        )
    return out


def _docx_section_text(section: Section) -> str:
    parts: list[str] = []
    if section.heading_text:
        parts.append(f"[{section.style}] {section.heading_text}")
    for body in section.body_blocks:
        if isinstance(body, DocxParagraph):
            if body.text.strip():
                parts.append(body.text)
        elif isinstance(body, DocxTableCell):
            if body.text.strip():
                parts.append(f"[{body.table_cell_id}] {body.text}")
    return "\n\n".join(parts)


def _first_body_para_id(section: Section) -> str | None:
    for body in section.body_blocks:
        if isinstance(body, DocxParagraph) and body.paragraph_id:
            return body.paragraph_id
        if isinstance(body, DocxTableCell) and body.table_cell_id:
            # Table cells aren't paragraph_ids per spec §6, but we accept them
            # as a last-resort provenance — the alternative is dropping the
            # whole section.
            return body.table_cell_id
    return None
