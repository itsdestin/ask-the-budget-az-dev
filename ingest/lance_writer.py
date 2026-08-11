"""Chunk → LanceDB writer: the last stage of every ingest job.

Three jobs live here:

1. `chunk_to_lance_row` — the Phase-1a `Chunk` model into the Arrow row the
   corpus tables actually store. This is the same mapping the Postgres
   loader did (`db/loader.py::chunk_to_row`) followed by the migration's
   Postgres→Lance conversion (`scripts/migrate_to_lancedb.py::pg_row_to_lance`),
   collapsed into one step now that Postgres is out of the ingest path.
2. `write_doc` — replace one document's chunks, rebuild the FTS index, and
   merge the document's metadata into `documents.json`.
3. `build_title` — real display titles for new ingests, replacing the
   doc-id-derived strings ("GOVERNOR FY2027 fy2027") the migration inherited.

`write_doc` mutates the shared corpus. **Callers must hold the ingest lock**
(`ingest.lock.IngestLock`) and should snapshot first (`store.backup.snapshot`);
the ingest worker's write phase does both.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence

from chunking.types import Chunk, DocMeta
from store.chunk_store import ChunkStore
from store.config import DOCS_FIELDS, write_documents_sidecar
from store.documents import load_documents

# Document-metadata fields ingest adds on top of the migration's set. They
# answer the two questions the migration never had to: "have we seen this
# file before?" (dedup, Task 10) and "who put it here?" (Invariant 8
# accountability — the corpus is public-record-only and uploads are attributed).
INGEST_DOCS_FIELDS = ("source_sha256", "ingested_at", "uploaded_by")

# doc_type → display pattern. `{y}` is the fiscal year; `{agency}` is appended
# by the caller-facing builder when the document is a per-agency page.
_TITLE_PATTERNS: dict[str, str] = {
    "baseline-per-agency": "FY {y} Baseline",
    "approps-per-agency": "FY {y} Appropriations Report",
    "afr": "FY {y} Annual Financial Report",
    "governors-budget": "FY {y} Executive Budget",
    "budget-bill": "FY {y} Budget Bill",
    "fiscal-note": "FY {y} Fiscal Note",
}

# doc_types whose title carries an agency name when one was resolved.
_PER_AGENCY_DOC_TYPES = frozenset({"baseline-per-agency", "approps-per-agency"})


def chunk_to_lance_row(
    chunk: Chunk,
    *,
    vector: Sequence[float],
    agency_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Map one `Chunk` + its embedding onto a `store.schema.chunk_schema` row.

    Four conversions the Arrow schema forces and a plain `model_dump()`
    would get wrong:

    * `provenance` is a nested model; Lance stores flat `page` / `bbox`
      columns plus a JSON `source_anchor` string. bbox floats are cast
      explicitly — pyarrow refuses Decimals into a float32 list.
    * `source_anchor` must be `json.dumps`'d. A `str()` repr would emit
      single-quoted pseudo-JSON that `json.loads` rejects at *query* time,
      long after ingest reported success.
    * `agency_canonical_id` is scalar on the chunk but the column is a list
      (decision D2 — a table chunk can name many agencies). `agency_ids`
      overrides it for the multi-agency path.
    * The list columns are non-nullable, so `or []` is load-bearing: one
      None fails the entire add() batch, not just its row.

    `alias_chain` is deliberately dropped — it's stamper-debugging sidecar
    data with no column and no consumer.

    Unlike the Postgres loader, `source_anchor` carries `page` for PDF
    chunks too instead of being NULL. It's additive: readers locate PDF
    chunks through the `page`/`bbox` columns, and having every locator in
    one place makes the anchor self-describing for the DOCX viewer work.
    """
    p = chunk.provenance
    anchor = {
        key: value
        for key, value in (
            ("page", p.page),
            ("paragraph_id", p.paragraph_id),
            ("table_cell_id", p.table_cell_id),
        )
        if value is not None
    }
    if agency_ids is None:
        agency_ids = [chunk.agency_canonical_id] if chunk.agency_canonical_id else []

    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "text": chunk.text,
        "section_path": list(chunk.section_path or []),
        "page": p.page,
        "bbox": [float(x) for x in p.bbox] if p.bbox else None,
        "source_anchor": json.dumps(anchor) if anchor else None,
        "agency_canonical_ids": list(agency_ids),
        "fund_canonical_id": chunk.fund_canonical_id,
        "fund_mentions": list(chunk.fund_mentions or []),
        "fiscal_year": chunk.fiscal_year,
        "doc_type": chunk.doc_type,
        "is_table": bool(chunk.is_table),
        "table_html": chunk.table_html,
        "token_count": chunk.token_count,
        "publisher": chunk.publisher,
        "vector": list(vector),
    }


def write_doc(
    store: ChunkStore,
    table: str,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    doc_meta: DocMeta,
    *,
    title: str,
    source_sha256: str,
    source_blob_path: str | None,
    source_url: str | None,
    source_format: str,
    uploaded_by: str,
    agency_ids_by_chunk: dict[str, list[str]] | None = None,
) -> None:
    """Replace one document in the corpus and record its metadata.

    Fixed sequence, and every step matters:

      delete_doc → upsert_chunks → build_fts_index → optimize → documents.json

    `delete_doc` first is what makes re-ingest idempotent — a second run's
    chunk_ids need not match the first's, so keying the replacement on
    chunk_id alone would leave orphans behind.

    `build_fts_index` is NOT optional. New rows are invisible to BM25 until
    the inverted index is rebuilt, which surfaces as the worst possible bug:
    the document looks ingested, semantic search finds it, and keyword search
    silently doesn't.

    documents.json is written LAST, so a crash mid-write leaves a document
    the sidecar doesn't advertise rather than an advertised document with no
    chunks. The merge preserves every other document's entry.

    **The caller holds the ingest lock and has already snapshotted.**
    """
    if len(chunks) != len(vectors):
        raise ValueError(
            f"write_doc got {len(chunks)} chunks but {len(vectors)} vectors — "
            "they must be positionally paired."
        )

    store.ensure_tables()
    store.delete_doc(table, doc_meta.doc_id)
    rows = [
        chunk_to_lance_row(
            chunk,
            vector=vector,
            agency_ids=(agency_ids_by_chunk or {}).get(chunk.chunk_id),
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    store.upsert_chunks(table, rows)
    store.build_fts_index(table)
    store.optimize(table)

    _merge_document_entry(
        doc_meta,
        title=title,
        source_sha256=source_sha256,
        source_blob_path=source_blob_path,
        source_url=source_url,
        source_format=source_format,
        uploaded_by=uploaded_by,
        page_count=_page_count(chunks),
    )


def build_title(
    *,
    publisher: str,
    doc_type: str,
    fiscal_year: int,
    user_title: str,
    agency_name: str | None,
    stage: str | None = None,
) -> str:
    """The document's display title, as the search page renders it.

    A title the uploader typed wins verbatim — they know what the document
    is and we don't. Otherwise the doc_type decides the shape, with the
    agency name appended for per-agency pages (an FY 2027 Baseline is 110
    separate documents; without the agency they'd be indistinguishable).

    Unknown doc_types get a humanized slug rather than a raw one, because
    the alternative is what the migration produced from doc_ids —
    "GOVERNOR FY2027 fy2027" — which is worse than useless in a results list.

    `publisher` is accepted but unused: doc_type already determines the
    shape (only AGAO publishes AFRs, only the Governor an Executive Budget),
    and the parameter keeps the signature honest about what identifies a
    document if that stops being true.

    WHY `stage` is appended even over a user-typed title: `doc_title` rides
    on every retrieved chunk and is the ONLY place a document's stage
    (Introduced/Engrossed) is visible to AI Mode — there is deliberately no
    new chunk column for it (Plan A Task 5; a corpus-wide migration was
    explicitly out of scope). The system prompt's "Engrossed supersedes
    Introduced" rule can only ever fire by reading this suffix, so it must
    survive regardless of which branch decided the base title.
    """
    if user_title and user_title.strip():
        base = user_title.strip()
    else:
        pattern = _TITLE_PATTERNS.get(doc_type)
        base = (
            pattern.format(y=fiscal_year)
            if pattern
            else f"FY {fiscal_year} {_humanize_doc_type(doc_type)}"
        )
        if agency_name and doc_type in _PER_AGENCY_DOC_TYPES:
            base = f"{base} — {agency_name}"

    if stage and stage.strip():
        # Capitalized the way a person reads it ("Engrossed"), not the
        # lowercase wire value the upload route normalizes to.
        base = f"{base} ({stage.strip().capitalize()})"
    return base


# --- internals --------------------------------------------------------------


def _humanize_doc_type(doc_type: str) -> str:
    """'detailed-list-pdf' → 'Detailed List'.

    The '-pdf' suffix is a corpus-internal marker for which JLBC index page a
    document came off, not something an analyst should ever read.
    """
    words = [w for w in doc_type.split("-") if w and w != "pdf"]
    return " ".join(w.capitalize() for w in words) or doc_type


def _page_count(chunks: Sequence[Chunk]) -> int | None:
    """Highest page any chunk cites — None for DOCX (no pages at all)."""
    pages = [c.provenance.page for c in chunks if c.provenance.page is not None]
    return max(pages) if pages else None


def _merge_document_entry(
    doc_meta: DocMeta,
    *,
    title: str,
    source_sha256: str,
    source_blob_path: str | None,
    source_url: str | None,
    source_format: str,
    uploaded_by: str,
    page_count: int | None,
) -> None:
    """Update this document's entry in documents.json, preserving the rest.

    Read-modify-write of a whole-file JSON is safe here only because the
    caller holds the ingest lock — it's the same single-writer assumption
    the corpus tables run under.
    """
    entry = {
        "title": title,
        "publisher": doc_meta.publisher,
        "doc_type": doc_meta.doc_type,
        "fiscal_year": doc_meta.fiscal_year,
        "source_format": source_format,
        "source_blob_path": source_blob_path,
        "source_url": source_url,
        "page_count": page_count,
        "source_sha256": source_sha256,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": uploaded_by,
    }
    # Pin the key set against the sidecar's declared fields so a typo here
    # can't quietly produce an entry the /docs endpoint won't read.
    expected = set(DOCS_FIELDS) | set(INGEST_DOCS_FIELDS)
    assert set(entry) == expected, f"documents.json field drift: {set(entry) ^ expected}"

    docs = _read_documents()
    docs[doc_meta.doc_id] = entry
    write_documents_sidecar(docs)


def _read_documents() -> dict[str, dict[str, Any]]:
    """The sidecar, read the WRITE path's way (Plan 5 Task 19).

    `strict=True` is load-bearing, not a style choice. Every other reader
    degrades a corrupt documents.json to `{}` so search keeps working. Here
    that would be a data-loss bug: this is a read-modify-write, so an empty
    read means the merge writes a sidecar containing ONE document and
    silently orphans every PDF in the viewer. The corrupt bytes are the
    only remaining record of where those files live.

    `strict` also re-validates instead of trusting the mtime cache, which
    matters here for the same reason — a good read earlier in the process
    must not license writing over a file that has since been damaged.
    """
    return load_documents(strict=True)
