"""LanceDB-backed lexical + dense retrieval stages.

Replaces retrieval/bm25.py (ParadeDB) and retrieval/dense.py
(pgvector). Returns list[RetrievedChunk] so rrf_fuse and the rerankers
work unchanged. Reuses the #47 sanitizer idea: the FTS query parser
chokes on Lucene-ish specials, so strip them before querying.
"""
from __future__ import annotations

import json
from typing import Any

from retrieval.types import RetrievalFilters, RetrievedChunk
from store.chunk_store import ChunkStore

# Characters the full-text query parser treats as syntax. This set is
# copied verbatim from bm25.py's _BM25_SPECIAL_CHARS (the STATUS.md #47
# fix) so the two stages sanitize identically during the cutover.
#
# WHY `+ - !` are NOT stripped, unlike a naive "strip all Lucene specials"
# set: they are load-bearing inside real analyst queries ("$1.2M+",
# "FY2026-27"), and the parser only reads them as operators when they
# prefix a term — where the failure mode is a parse warning, not a crash.
# The apostrophe is the one that actually crashed (`Arizona's` opens a
# phrase quote that never closes).
_BM25_SPECIAL_CHARS = set("'\"()[]{}^~:/\\?*")


def _sanitize(query: str) -> str:
    """Replace FTS parser special chars with spaces; collapse whitespace."""
    out = "".join(" " if ch in _BM25_SPECIAL_CHARS else ch for ch in query)
    return " ".join(out.split())


def _where(store: ChunkStore, filters: RetrievalFilters) -> str | None:
    if filters.is_empty():
        return None
    return store.filter_expr(
        fiscal_year=filters.fiscal_year,
        doc_type=filters.doc_type,
        publisher=filters.publisher,
        agency_canonical_id=filters.agency_canonical_id,
        fund_canonical_id=filters.fund_canonical_id,
        fund_mentions=filters.fund_mentions,
        is_table=filters.is_table,
    )


def row_to_chunk(row: dict[str, Any], score: float) -> RetrievedChunk:
    """LanceDB dict -> RetrievedChunk. source_anchor is JSON-encoded in
    the table (Arrow has no dict column); decode it here so downstream
    consumers see the same shape psycopg rows had."""
    # Copy first: the caller's dict is the store's own result row, and
    # mutating source_anchor in place would corrupt it for anyone else
    # holding a reference (e.g. a debug log of the raw hits).
    row = dict(row)
    anchor = row.get("source_anchor")
    # Falsy-not-None check covers both NULL (nullable column) and the
    # empty string; json.loads would raise TypeError/ValueError on those.
    row["source_anchor"] = json.loads(anchor) if anchor else None
    return RetrievedChunk.from_row(row, score)


def bm25_query_lance(
    query: str, *, store: ChunkStore, corpus: str, top_k: int,
    filters: RetrievalFilters,
) -> list[RetrievedChunk]:
    """Lexical (BM25) leg of the hybrid pipeline, over the Lance FTS index."""
    q = _sanitize(query)
    if not q:
        # Pathological input of only special chars — an empty query string
        # is not something to hand the FTS parser.
        return []
    rows = store.fts_search(corpus, q, top_k=top_k, where=_where(store, filters))
    return [row_to_chunk(r, r["_score"]) for r in rows]


def dense_query_lance(
    query_vector: list[float], *, store: ChunkStore, corpus: str,
    top_k: int, filters: RetrievalFilters,
) -> list[RetrievedChunk]:
    """Dense (cosine) leg of the hybrid pipeline. The caller embeds the
    query; this stage only searches, so it needs no model."""
    rows = store.vector_search(
        corpus, query_vector, top_k=top_k, where=_where(store, filters)
    )
    return [row_to_chunk(r, r["_score"]) for r in rows]
