"""Dense retrieval via pgvector ANN over Voyage-3-large embeddings.

Phase 1b WS5. Mirror of `retrieval.bm25` for the dense leg of the hybrid
pipeline. Top-k default = 100 per spec §3.4 (dense top 100 + BM25 top 200
-> RRF fusion). Query embeddings are generated on-the-fly via
`db.embeddings.VoyageEmbedder.embed_one(text, input_type='query')` --
Voyage's two-mode encoder yields a different projection for queries vs.
documents, so re-using the document encoder would degrade recall.

The HNSW index on chunks.embedding is declared in 0002_indexes.sql with
cosine_ops; we score via `1 - (embedding <=> query)` so higher = better
(matches BM25 polarity for downstream RRF).
"""
from __future__ import annotations

from typing import Any

import psycopg

from db.embeddings import INPUT_TYPE_QUERY, VoyageEmbedder
from retrieval.sql import PROJECTION_COLUMNS, build_filter_clauses
from retrieval.types import RetrievalFilters, RetrievedChunk

DEFAULT_TOP_K = 100


def dense_query(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    filters: RetrievalFilters | None = None,
    conn: psycopg.Connection[Any] | None = None,
    embedder: VoyageEmbedder | None = None,
) -> list[RetrievedChunk]:
    """Run a pgvector cosine ANN over chunks.embedding and return top-k hits.

    `embedder` is optional: when None, a fresh VoyageEmbedder is built from
    the VOYAGE_API_KEY env var. Tests pass a mock embedder to avoid hitting
    the real API.

    `filters` apply pre-ANN as a WHERE clause; HNSW with filters is still
    fast at our chunk count. Empty filters skip the WHERE assembly.

    Returns chunks in descending similarity order (higher = closer to the
    query in vector space).
    """
    if not query.strip():
        return []

    if embedder is None:
        embedder = VoyageEmbedder()

    query_vec = embedder.embed_one(query, input_type=INPUT_TYPE_QUERY)

    where_clauses, params, _ = build_filter_clauses(filters or RetrievalFilters())
    where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

    # Cast the query vector to pgvector's vector type explicitly so the HNSW
    # index is used. The index also requires the row's embedding to be NOT
    # NULL -- we filter that out so unembedded chunks (e.g. mid-WS3 ingest)
    # don't crash the cosine operator.
    sql = f"""
        SELECT
            {", ".join(PROJECTION_COLUMNS)},
            1 - (c.embedding <=> %s::vector) AS dense_score
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE c.embedding IS NOT NULL
        {where_sql}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    bind = [query_vec, *params, query_vec, top_k]

    if conn is None:
        from db.connection import get_connection

        with get_connection() as owned_conn:
            rows = owned_conn.execute(sql, bind).fetchall()
    else:
        rows = conn.execute(sql, bind).fetchall()

    return [RetrievedChunk.from_row(r, score=r["dense_score"]) for r in rows]
