"""LanceDB-backed lexical + dense retrieval stages.

Replaces retrieval/bm25.py (ParadeDB) and retrieval/dense.py
(pgvector). Returns list[RetrievedChunk] so rrf_fuse and the rerankers
work unchanged.

The lexical leg still sanitizes the query before handing it to the FTS
index, but for a DIFFERENT reason than the ParadeDB stage did — see
_BM25_SPECIAL_CHARS. On Lance the load-bearing character is the double
quote, not the apostrophe. The sanitizer is NOT dead ParadeDB baggage;
removing it makes quoted queries raise.
"""
from __future__ import annotations

import json
from typing import Any

from retrieval.types import RetrievalFilters, RetrievedChunk
from store.chunk_store import ChunkStore

# Characters stripped from the query before it reaches the Lance FTS
# index. The set is kept CHARACTER-FOR-CHARACTER IDENTICAL to bm25.py's
# _BM25_SPECIAL_CHARS (the STATUS.md #47 fix) so that during the cutover
# a Lance result set can be compared against the ParadeDB one without
# sanitizer differences confounding the diff. Its *justification* on
# Lance is different, and narrower:
#
# The double quote is the only load-bearing character (measured against
# lancedb 0.36, index built by build_fts_index() with a default FTS()
# config, i.e. WITHOUT token positions):
#
#   - A query whose terms are ALL double-quoted parses as a phrase
#     query and raises `RuntimeError: lance error: Invalid user input:
#     position is not found but required for phrase queries`. This fires
#     for a single quoted word ('"provider"') just as it does for
#     '"provider rates"'. A query mixing quoted and bare terms
#     ('"provider rates" extra') falls back to bag-of-words and is fine,
#     so the crash is real but not universal.
#   - This matters because the caller is an LLM (the MCP `retrieve`
#     tool): Claude emits quoted phrases constantly and unprompted, so
#     the crash path is the common case, not an edge case.
#
# The rest of the set is retained purely for that cutover parity — on
# Lance they are harmless either way. Verified: apostrophes do NOT crash
# ("governor's office" returns hits — the tokenizer is bag-of-words with
# no phrase-quote state to leave unterminated, which was the entire #47
# mechanism on tantivy), and `+ - ! ^ ~ : ( ) [ ] { } \ * ? /` are NOT
# operators here — the tokenizer treats them as word boundaries and
# splits on them ("alpha^beta" matches a doc containing "alpha beta").
#
# `+ - !` stay out of the set to match bm25.py, but on Lance it makes no
# difference to matching either way: "FY2026-27" tokenizes to
# fy2026 + 27 whether or not the sanitizer strips the hyphen.
#
# The alternative to sanitizing is rebuilding the index with positions
# (FTS(with_position=True) in store/chunk_store.py), which would make
# phrase queries actually work instead of being flattened. That is a
# store-side index-size tradeoff, out of scope for this stage; until
# someone takes it, quoted phrases degrade to unordered term matching.
_BM25_SPECIAL_CHARS = set("'\"()[]{}^~:/\\?*")


def _sanitize(query: str) -> str:
    """Replace FTS parser special chars with spaces; collapse whitespace.

    Load-bearing for `"` (phrase-query crash); see _BM25_SPECIAL_CHARS.
    """
    out = "".join(" " if ch in _BM25_SPECIAL_CHARS else ch for ch in query)
    return " ".join(out.split())


def _where(store: ChunkStore, filters: RetrievalFilters) -> str | None:
    if filters.is_empty():
        return None
    return store.filter_expr(
        fiscal_year=filters.fiscal_year,
        doc_type=filters.doc_type,
        doc_id=filters.doc_id,
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
    if anchor:
        try:
            row["source_anchor"] = json.loads(anchor)
        except json.JSONDecodeError as e:
            # WHY re-raise with the chunk_id: the bare decoder error says
            # only "Expecting value: line 1 column 1", which is useless
            # for finding the offending row among ~100k chunks. The cause
            # is always a writer that stored a str() instead of a
            # json.dumps(), so name the row and the fix.
            raise ValueError(
                f"chunk {row.get('chunk_id')!r} has a malformed "
                f"source_anchor: expected JSON, got {anchor!r}. "
                "The writer must json.dumps it."
            ) from e
    else:
        row["source_anchor"] = None
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
