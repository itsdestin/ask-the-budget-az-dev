"""BM25 retrieval via ParadeDB pg_search.

Phase 1b WS4. Wraps the `chunks_bm25` index (declared in 0002_indexes.sql)
into a Python helper that returns scored, filtered candidates ready for
RRF fusion in WS6.

Top-k default = 200 per spec §3.4: BM25 contributes the lexical leg of
the hybrid pipeline (BM25 top 200 + dense top 100 -> RRF -> rerank).
"""
from __future__ import annotations

from typing import Any

import psycopg

from retrieval.sql import PROJECTION_COLUMNS, build_filter_clauses
from retrieval.types import RetrievalFilters, RetrievedChunk

DEFAULT_TOP_K = 200


def bm25_query(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    filters: RetrievalFilters | None = None,
    conn: psycopg.Connection[Any] | None = None,
) -> list[RetrievedChunk]:
    """Run a ParadeDB BM25 search over chunks.text and return the top-k hits.

    `filters` is applied as additional WHERE clauses against the chunks +
    documents tables; see `RetrievalFilters` for the supported set. Empty
    filters skip the WHERE assembly.

    `conn` is optional: when None, the helper grabs a pooled connection
    from `db.connection`. Tests can pass an explicit `conn` to compose
    multiple queries in one transaction (or to reuse a non-pooled connection).

    Returns chunks in descending BM25 score order. Callers that need
    deterministic ties can post-sort by chunk_id.
    """
    if not query.strip():
        return []

    where_clauses, params, _ = build_filter_clauses(filters or RetrievalFilters())

    # ParadeDB pg_search syntax (v0.23+):
    # `c.text @@@ %s` runs BM25 against the configured field; combined with
    # `paradedb.score(c.chunk_id)` to expose the per-row score.
    where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

    sql = f"""
        SELECT
            {", ".join(PROJECTION_COLUMNS)},
            paradedb.score(c.chunk_id) AS bm25_score
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE c.text @@@ %s
        {where_sql}
        ORDER BY bm25_score DESC
        LIMIT %s
    """
    bind = [query, *params, top_k]

    if conn is None:
        from db.connection import get_connection

        with get_connection() as owned_conn:
            rows = owned_conn.execute(sql, bind).fetchall()
    else:
        rows = conn.execute(sql, bind).fetchall()

    return [RetrievedChunk.from_row(r, score=r["bm25_score"]) for r in rows]
