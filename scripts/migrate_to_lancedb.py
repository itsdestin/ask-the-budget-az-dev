"""One-time Postgres -> LanceDB migration (spec S5, gate G2 input).

Reads every chunk (+ documents.publisher via JOIN) from the Phase-1b
Postgres, re-embeds text with LocalEmbedder (passage mode), and writes
the budget_chunks LanceDB table, then builds the FTS index and compacts.
It also writes `<data_dir>/documents.json` — the per-document metadata
(title, source_format, source_blob_path, …) that has no home in the chunk
schema but that `/docs/{doc_id}` needs to point the PDF viewer at a file.

chunk_ids are preserved verbatim, so eval/queries.yaml ground truth
stays valid with no refresh_chunk_ids pass.

Usage:  uv run python scripts/migrate_to_lancedb.py [--batch 128]
        uv run python scripts/migrate_to_lancedb.py --docs-only
Env:    DATABASE_URL (source), JLBC_DATA_DIR (dest; default dev dir)
Runtime: ~7,755 chunks on an i5 CPU ~= 7-20 min (embedding-bound).
        --docs-only is ~1s.
Re-runnable: upsert semantics; safe to interrupt and restart.

NOTE the embeddings are NOT copied from Postgres: the old column holds
1024-dim voyage-3-large vectors, and this migration's whole point is to
replace them with 768-dim local arctic-embed-m vectors. Text is re-embedded,
is why the run is CPU-bound rather than IO-bound.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

# Repo root on sys.path so `retrieval.*` / `store.*` resolve when this is
# invoked as a plain script (`uv run python scripts/...`), which puts
# scripts/ — not the root — on the path. Same prologue as
# scripts/embed_corpus.py and friends.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retrieval.local_embedder import LocalEmbedder  # noqa: E402
from store.chunk_store import ChunkStore  # noqa: E402
from store.config import documents_path  # noqa: E402

# Column names verified against db/migrations/0001_initial_schema.sql
# (chunks.* + documents.publisher). ORDER BY chunk_id makes the run
# deterministic so an interrupted migration restarts over the same
# sequence — useful when comparing progress lines across attempts.
SELECT_SQL = """
    SELECT c.chunk_id, c.doc_id, c.text, c.section_path, c.page, c.bbox,
           c.source_anchor, c.agency_canonical_ids, c.fund_canonical_id,
           c.fund_mentions, c.fiscal_year, c.doc_type, c.is_table,
           c.table_html, c.token_count, d.publisher
    FROM chunks c
    JOIN documents d ON d.doc_id = c.doc_id
    ORDER BY c.chunk_id
"""


# Every column of `documents` that a consumer asks for, verified against
# db/migrations/0001_initial_schema.sql. `ingested_at` / `extractor` /
# `extractor_version` are deliberately left behind: nothing reads them, and
# ingested_at is a timestamptz that would need its own JSON encoding.
DOCS_SELECT_SQL = """
    SELECT doc_id, title, publisher, doc_type, fiscal_year,
           source_format, source_blob_path, source_url, page_count
    FROM documents
    ORDER BY doc_id
"""

# Keys written per document — the same names the sidecar's
# DocMetadataResponse uses, minus doc_id (which is the JSON key).
DOCS_FIELDS = (
    "title", "publisher", "doc_type", "fiscal_year",
    "source_format", "source_blob_path", "source_url", "page_count",
)


def pg_rows_to_documents(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map `documents` rows onto the doc_id-keyed sidecar shape.

    Pure so tests/test_migrate_rows.py can pin it. Only the declared field
    set is copied: passing psycopg rows straight through would drag along
    `ingested_at` (a datetime json.dumps refuses) the first time somebody
    adds it to the SELECT.
    """
    return {
        row["doc_id"]: {key: row.get(key) for key in DOCS_FIELDS}
        for row in rows
    }


def write_documents_sidecar(docs: dict[str, dict[str, Any]]) -> Path:
    """Write documents.json into the shared data dir; return its path.

    WHY the temp-file + replace: the retrieval sidecar reads this file live
    (on an mtime change), and on a network share a reader could otherwise
    catch a half-written file and log a JSON error. os.replace is atomic on
    both Windows and POSIX.
    """
    path = documents_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(docs, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def migrate_documents(dsn: str) -> int:
    """Pull the documents table into the JSON sidecar. Returns the count."""
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(DOCS_SELECT_SQL).fetchall()
    docs = pg_rows_to_documents(rows)
    path = write_documents_sidecar(docs)
    print(f"documents metadata: {len(docs)} entries -> {path}", flush=True)
    return len(docs)


def pg_row_to_lance(row: dict[str, Any], *, vector: list[float]) -> dict[str, Any]:
    """Map one psycopg dict row onto the Arrow schema in store/schema.py.

    Two conversions matter and are pinned by tests/test_migrate_rows.py:

    * source_anchor arrives as a Python dict (db/loader.py wrote it with
      psycopg's Jsonb(...) wrapper, so psycopg decodes it on the way
      back out) but the LanceDB column is a JSON *string*. It must be
      json.dumps'd — a str() repr would emit single-quoted pseudo-JSON
      that json.loads rejects at query time, i.e. the failure would only
      surface long after the migration reported success.
    * bbox is NUMERIC[] in Postgres, so psycopg yields Decimals, which
      pyarrow will not accept into a float32 list. Cast explicitly.

    Array columns are NOT NULL in Postgres but are normalized through
    `or []` anyway, because the Arrow schema declares them non-nullable
    and a None would fail the whole 128-row batch.
    """
    anchor = row.get("source_anchor")
    return {
        **{k: row.get(k) for k in (
            "chunk_id", "doc_id", "text", "page", "fund_canonical_id",
            "fiscal_year", "doc_type", "table_html", "token_count",
            "publisher",
        )},
        "section_path": list(row.get("section_path") or []),
        "bbox": [float(x) for x in row["bbox"]] if row.get("bbox") else None,
        "source_anchor": json.dumps(anchor) if anchor is not None else None,
        "agency_canonical_ids": list(row.get("agency_canonical_ids") or []),
        "fund_mentions": list(row.get("fund_mentions") or []),
        "is_table": bool(row.get("is_table")),
        "vector": vector,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument(
        "--docs-only",
        action="store_true",
        help=(
            "Write documents.json and stop — no chunk read, no embedding. "
            "Use this to refresh document metadata (titles, PDF paths) "
            "without re-running the full migration."
        ),
    )
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set — source Postgres required.", file=sys.stderr)
        return 1

    # WHY --docs-only exists: the chunk half of this migration costs ~16
    # minutes of CPU-bound embedding, and its output (the LanceDB table) is
    # already correct. Document metadata is a separate, cheap read that may
    # need to be refreshed on its own — after an ingest adds a document, or
    # (as happened 2026-07-29) when a consumer turns out to need a column
    # the first pass never carried across. Refreshing it must not cost a
    # re-embed, so this branch returns before LocalEmbedder is even built.
    if args.docs_only:
        return 0 if migrate_documents(dsn) else 3

    # dim is resolved by LocalEmbedder from fastembed's registry; passing it
    # to ChunkStore keeps the Arrow vector width and the model in lockstep.
    embedder = LocalEmbedder()
    store = ChunkStore(dim=embedder.dim)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(SELECT_SQL).fetchall()
    print(f"source chunks: {len(rows)}", flush=True)

    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        batch = rows[i : i + args.batch]
        vecs = embedder.embed_batch(
            [r["text"] for r in batch], input_type="document"
        )
        store.upsert_chunks(
            "budget_chunks",
            # strict=True: a short vector list would otherwise silently drop
            # the batch's tail chunks, leaving a count mismatch as the only
            # (much later) symptom.
            [pg_row_to_lance(r, vector=v) for r, v in zip(batch, vecs, strict=True)],
        )
        done = i + len(batch)
        rate = done / max(time.time() - t0, 1e-9)
        print(f"  {done}/{len(rows)}  ({rate:.0f} chunks/s)", flush=True)

    store.build_fts_index("budget_chunks")
    # WHY optimize after the load: each batch above commits its own data
    # file (~61 of them for the full corpus), and the fragmentation costs
    # measurable query latency (78ms -> 58ms once compacted). Runs after
    # the FTS index so the compaction covers it too.
    store.optimize("budget_chunks")

    n = store.count("budget_chunks")
    print(f"lancedb budget_chunks rows: {n}")
    if n != len(rows):
        print("COUNT MISMATCH — do not proceed to eval.", file=sys.stderr)
        return 2

    # Document metadata last: it is cheap, and putting it after the count
    # check means a failed chunk migration doesn't leave a fresh sidecar
    # implying the corpus is fine.
    migrate_documents(dsn)

    print(f"migration OK  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
