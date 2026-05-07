"""Phase 1a chunk JSON -> Postgres row loader.

Phase 1b WS2, Task 2.1. Reads NDJSON chunk files (one Pydantic-validated
`Chunk` per line, as written by Phase 1a's slice orchestrator) and upserts
them into the `documents` + `chunks` tables.

Two responsibilities the loader carries that the chunker does not:

1. **Document-level metadata** — the chunker only stamps each chunk with
   `publisher`, `doc_type`, `fiscal_year`, `doc_id`. The `documents` table
   needs more (title, source_url, source_blob_path, extractor +
   extractor_version, ingested_at, page_count). Caller passes a
   `DocumentMeta` instance so the loader stays declarative.

2. **Polymorphic provenance** -> SQL columns. PDF chunks (page + bbox)
   land in dedicated columns; DOCX chunks (paragraph_id [+ table_cell_id])
   land in `source_anchor JSONB`. The `chunks` CHECK constraint enforces
   one shape or the other.

3. **Scalar -> array agency promotion (decision D2).** Phase 1a chunks
   carry `agency_canonical_id: str | None` (singular). The schema stores
   `agency_canonical_ids TEXT[]`. The loader does the promotion. When
   the chunker is updated to emit arrays natively (cross-cut chunks
   stamping all 25 agencies in s18, not just the alphabetical first),
   this code keeps working unchanged because it normalizes both shapes.

All inserts use `ON CONFLICT DO UPDATE`, so re-running the loader on the
same chunks is idempotent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from chunking.types import Chunk

# ---------------------------------------------------------------------------
# DocumentMeta -- what the chunker doesn't carry but the documents table needs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentMeta:
    """Document-level metadata supplied by the caller of `load_chunk_file`.

    The chunker carries `publisher`, `doc_type`, `fiscal_year` denormalized
    on each chunk; the loader cross-checks those against the meta to catch
    chunker/orchestrator drift. Everything else (title, source_url, etc.)
    lives only here.
    """

    doc_id: str
    publisher: str               # 'jlbc' | 'agao' | 'governor' | 'legislature'
    doc_type: str                # 'baseline-cross-cut' | 'approps-cross-cut' | 'budget-bill' | ...
    fiscal_year: int
    title: str
    source_format: str           # 'pdf' | 'docx'
    source_blob_path: str
    extractor: str               # 'mineru-2.5' | 'opendataloader-2.4.1' | 'python-docx' | 'sonnet-vision'
    extractor_version: str
    source_url: str | None = None
    page_count: int | None = None
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# chunk_to_row -- pure mapping. Tested without a database.
# ---------------------------------------------------------------------------


def chunk_to_row(chunk: Chunk, doc_id: str) -> dict[str, Any]:
    """Map a Pydantic `Chunk` into a parameter dict suitable for the
    `INSERT INTO chunks (...)` statement built by `load_doc`.

    PDF chunks (provenance.page is not None) populate `page` + `bbox`
    columns and leave `source_anchor` NULL. DOCX chunks (paragraph_id is
    not None) flip the polarity. The CHECK constraint in 0001 enforces
    that one of those shapes is satisfied.

    `agency_canonical_id` (scalar on the chunk) is promoted to a 1-element
    array when present, empty array when absent (decision D2).
    """
    p = chunk.provenance
    is_pdf = p.page is not None

    if is_pdf:
        page = p.page
        # Postgres NUMERIC[] accepts a Python list of floats via psycopg's
        # default adapter. None bbox on a PDF chunk would fail the CHECK
        # constraint at INSERT time -- caller's chunker is expected to
        # stamp bbox on every PDF chunk; loader doesn't repair.
        bbox = p.bbox
        source_anchor = None
    else:
        page = None
        bbox = None
        anchor: dict[str, Any] = {"paragraph_id": p.paragraph_id}
        if p.table_cell_id:
            anchor["table_cell_id"] = p.table_cell_id
        # Wrap in psycopg's Jsonb adapter so the dict is serialized as JSONB
        # rather than the default Postgres composite-record encoding.
        source_anchor = Jsonb(anchor)

    agency_ids: list[str] = (
        [chunk.agency_canonical_id] if chunk.agency_canonical_id else []
    )

    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": doc_id,
        "text": chunk.text,
        "page": page,
        "bbox": bbox,
        "source_anchor": source_anchor,
        "section_path": list(chunk.section_path),
        "agency_canonical_ids": agency_ids,
        "fund_canonical_id": chunk.fund_canonical_id,
        "fund_mentions": list(chunk.fund_mentions),
        "fiscal_year": chunk.fiscal_year,
        "doc_type": chunk.doc_type,
        "is_table": chunk.is_table,
        "table_html": chunk.table_html,
        "token_count": chunk.token_count,
    }


# ---------------------------------------------------------------------------
# load_doc -- single-document round-trip.
# ---------------------------------------------------------------------------

_DOC_UPSERT = """
INSERT INTO documents (
    doc_id, publisher, doc_type, fiscal_year, title, source_url,
    source_format, source_blob_path, page_count, ingested_at,
    extractor, extractor_version
) VALUES (
    %(doc_id)s, %(publisher)s, %(doc_type)s, %(fiscal_year)s,
    %(title)s, %(source_url)s, %(source_format)s, %(source_blob_path)s,
    %(page_count)s, %(ingested_at)s, %(extractor)s, %(extractor_version)s
)
ON CONFLICT (doc_id) DO UPDATE SET
    publisher = EXCLUDED.publisher,
    doc_type = EXCLUDED.doc_type,
    fiscal_year = EXCLUDED.fiscal_year,
    title = EXCLUDED.title,
    source_url = EXCLUDED.source_url,
    source_format = EXCLUDED.source_format,
    source_blob_path = EXCLUDED.source_blob_path,
    page_count = EXCLUDED.page_count,
    ingested_at = EXCLUDED.ingested_at,
    extractor = EXCLUDED.extractor,
    extractor_version = EXCLUDED.extractor_version
"""

_CHUNK_UPSERT = """
INSERT INTO chunks (
    chunk_id, doc_id, text, page, bbox, source_anchor,
    section_path, agency_canonical_ids, fund_canonical_id,
    fund_mentions, fiscal_year, doc_type, is_table, table_html, token_count
) VALUES (
    %(chunk_id)s, %(doc_id)s, %(text)s, %(page)s, %(bbox)s, %(source_anchor)s,
    %(section_path)s, %(agency_canonical_ids)s, %(fund_canonical_id)s,
    %(fund_mentions)s, %(fiscal_year)s, %(doc_type)s, %(is_table)s,
    %(table_html)s, %(token_count)s
)
ON CONFLICT (chunk_id) DO UPDATE SET
    text = EXCLUDED.text,
    page = EXCLUDED.page,
    bbox = EXCLUDED.bbox,
    source_anchor = EXCLUDED.source_anchor,
    section_path = EXCLUDED.section_path,
    agency_canonical_ids = EXCLUDED.agency_canonical_ids,
    fund_canonical_id = EXCLUDED.fund_canonical_id,
    fund_mentions = EXCLUDED.fund_mentions,
    fiscal_year = EXCLUDED.fiscal_year,
    doc_type = EXCLUDED.doc_type,
    is_table = EXCLUDED.is_table,
    table_html = EXCLUDED.table_html,
    token_count = EXCLUDED.token_count
"""


def load_doc(
    chunks: list[Chunk],
    doc_meta: DocumentMeta,
    conn: psycopg.Connection[Any],
) -> int:
    """Upsert one document and all its chunks in a single transaction.

    Returns the number of chunk rows written. Raises ValueError if any
    chunk's denormalized publisher/doc_type/fiscal_year/doc_id disagrees
    with `doc_meta` (caller-side chunker drift).
    """
    if not chunks:
        # Still upsert the document row so a doc with zero chunks is
        # discoverable (e.g. parse failure recorded). Caller can then
        # decide whether to retry the chunker.
        conn.execute(_DOC_UPSERT, asdict(doc_meta))
        return 0

    # Cross-check chunk denormalization against doc_meta.
    for c in chunks:
        if c.doc_id != doc_meta.doc_id:
            raise ValueError(
                f"chunk {c.chunk_id}: doc_id={c.doc_id!r} != meta.doc_id={doc_meta.doc_id!r}"
            )
        if c.publisher != doc_meta.publisher:
            raise ValueError(
                f"chunk {c.chunk_id}: publisher={c.publisher!r} != meta.publisher={doc_meta.publisher!r}"
            )
        if c.doc_type != doc_meta.doc_type:
            raise ValueError(
                f"chunk {c.chunk_id}: doc_type={c.doc_type!r} != meta.doc_type={doc_meta.doc_type!r}"
            )
        if c.fiscal_year != doc_meta.fiscal_year:
            raise ValueError(
                f"chunk {c.chunk_id}: fiscal_year={c.fiscal_year} != meta.fiscal_year={doc_meta.fiscal_year}"
            )

    conn.execute(_DOC_UPSERT, asdict(doc_meta))

    rows = [chunk_to_row(c, doc_meta.doc_id) for c in chunks]
    with conn.cursor() as cur:
        cur.executemany(_CHUNK_UPSERT, rows)

    return len(rows)


# ---------------------------------------------------------------------------
# Convenience wrappers -- file IO + bulk runs.
# ---------------------------------------------------------------------------


def parse_chunk_ndjson(path: Path) -> list[Chunk]:
    """Read an NDJSON file (one chunk per line) and return validated Chunks."""
    chunks: list[Chunk] = []
    text = path.read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            chunks.append(Chunk.model_validate_json(raw))
        except Exception as e:  # pragma: no cover -- diagnostic re-raise
            raise ValueError(
                f"{path}:{lineno}: invalid Chunk JSON: {e}"
            ) from e
    return chunks


def load_chunk_file(
    path: Path,
    doc_meta: DocumentMeta,
    conn: psycopg.Connection[Any],
) -> int:
    """Parse one NDJSON file and run `load_doc` against the result."""
    return load_doc(parse_chunk_ndjson(path), doc_meta, conn)


def load_chunk_files(
    files_with_meta: Iterable[tuple[Path, DocumentMeta]],
    conn: psycopg.Connection[Any],
) -> dict[str, int]:
    """Bulk-load. Returns a doc_id -> chunks-loaded dict for the caller's report."""
    counts: dict[str, int] = {}
    for path, meta in files_with_meta:
        counts[meta.doc_id] = load_chunk_file(path, meta, conn)
    return counts
