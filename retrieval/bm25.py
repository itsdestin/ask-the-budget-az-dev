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

# ParadeDB / tantivy query-parser special characters that, when present
# bare inside the query string, cause `could not parse query string`
# errors. The apostrophe is the load-bearing case (STATUS.md #47):
# `Arizona's budget` is interpreted as an unterminated phrase delimiter
# (`'s budget` opens a quote that never closes). Bare double-quotes,
# brackets, braces, parens, colons, carets, tildes, slashes, and
# wildcards have analogous failure modes — none of them appear in
# natural-language analyst questions in a useful way, so we strip the
# whole set to a single space rather than try to preserve them.
#
# We intentionally do NOT strip `+ - !` because (a) `+` and `-` are
# common in numeric tokens like "$1.2M+" and (b) tantivy only treats
# them as operators when they prefix a term, and even then the failure
# mode is a parser warning, not a crash.
_BM25_SPECIAL_CHARS = set("'\"()[]{}^~:/\\?*")


def _sanitize_bm25_query(query: str) -> str:
    """Replace tantivy/Lucene parser special chars with spaces.

    Pragmatic fix for STATUS.md #47. The pg_search query parser inherits
    Lucene-style semantics: bare apostrophes are read as phrase-quote
    delimiters and crash the whole retrieve() call. Stripping them is
    lossy (`Arizona's` -> `Arizona s`) but the BM25 tokenizer drops
    the orphaned single `s`, and the dense+rerank legs of the hybrid
    pipeline are unaffected — they see the original query string and
    do the heavy lifting on possessives.

    Returns the cleaned string with consecutive spaces collapsed.
    """
    out = "".join(" " if ch in _BM25_SPECIAL_CHARS else ch for ch in query)
    # Collapse runs of whitespace introduced by the substitution.
    return " ".join(out.split())


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

    # Strip apostrophes + other tantivy specials before handing to pg_search.
    # See `_sanitize_bm25_query` docstring and STATUS.md #47.
    cleaned_query = _sanitize_bm25_query(query)
    if not cleaned_query:
        # If sanitation reduced the query to nothing (pathological input
        # of only special chars), there's nothing meaningful to search.
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
    bind = [cleaned_query, *params, top_k]

    if conn is None:
        from db.connection import get_connection

        with get_connection() as owned_conn:
            rows = owned_conn.execute(sql, bind).fetchall()
    else:
        rows = conn.execute(sql, bind).fetchall()

    return [RetrievedChunk.from_row(r, score=r["bm25_score"]) for r in rows]
