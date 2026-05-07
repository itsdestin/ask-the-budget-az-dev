"""Top-level retrieval pipeline: BM25 + dense -> RRF -> Voyage rerank -> top-K.

Phase 1b WS6 Task 6.3. Composes `bm25_query`, `dense_query`, `rrf_fuse`,
and `rerank_chunks` into a single `retrieve(RetrievalRequest)` ->
`RetrievalResult` API. Phase 1c's Budget MCP server wraps this; the
Phase 1b WS8 eval harness calls it directly (single-shot, deterministic
per-query measurement).

Top-K defaults match spec §3.4:
- BM25: top 200 lexical candidates
- Dense: top 100 ANN candidates
- Fused: top 50 after RRF (caller can shrink to fewer for cheaper
  rerank, but quality drops if less than ~20)
- Reranked: top 20 returned to caller (`req.top_k` default)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import psycopg

from db.embeddings import VoyageEmbedder
from retrieval.bm25 import bm25_query
from retrieval.dense import dense_query
from retrieval.rerank import rerank_chunks
from retrieval.rrf import RankedList, rrf_fuse
from retrieval.types import RetrievalFilters, RetrievedChunk

# Default top-K caps at each stage (see spec §3.4).
BM25_TOP_K = 200
DENSE_TOP_K = 100
FUSED_TOP_K = 50
DEFAULT_PIPELINE_TOP_K = 20


@dataclass(frozen=True)
class RetrievalRequest:
    """Public input shape — what Phase 1c's Budget MCP server `retrieve()`
    tool will accept (after JSON deserialization). Matches the filter
    dimensions on `RetrievalFilters` plus `query` and `top_k`.
    """

    query: str
    fiscal_year: list[int] | None = None
    doc_type: list[str] | None = None
    publisher: list[str] | None = None
    agency_canonical_id: list[str] | None = None
    fund_canonical_id: list[str] | None = None
    fund_mentions: list[str] | None = None
    is_table: bool | None = None
    top_k: int = DEFAULT_PIPELINE_TOP_K

    def to_filters(self) -> RetrievalFilters:
        return RetrievalFilters(
            fiscal_year=self.fiscal_year,
            doc_type=self.doc_type,
            publisher=self.publisher,
            agency_canonical_id=self.agency_canonical_id,
            fund_canonical_id=self.fund_canonical_id,
            fund_mentions=self.fund_mentions,
            is_table=self.is_table,
        )


@dataclass(frozen=True)
class RetrievalResult:
    """Public output shape. `chunks` is the final reranked top-K; `top_score`
    is the reranker score of the highest-ranked chunk (drives the spec §11
    refusal threshold check at the MCP-tool boundary in Phase 1c).

    `bm25_count` / `dense_count` / `fused_count` are diagnostics — they
    let the eval harness and the audit log capture how many candidates
    each stage produced before rerank.
    """

    chunks: list[RetrievedChunk] = field(default_factory=list)
    top_score: float = 0.0
    reranker_scores: list[float] = field(default_factory=list)
    bm25_count: int = 0
    dense_count: int = 0
    fused_count: int = 0


def retrieve(
    req: RetrievalRequest,
    *,
    conn: psycopg.Connection[Any] | None = None,
    embedder: VoyageEmbedder | None = None,
    rerank_client: Any | None = None,
    bm25_top_k: int = BM25_TOP_K,
    dense_top_k: int = DENSE_TOP_K,
    fused_top_k: int = FUSED_TOP_K,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> RetrievalResult:
    """Run the full hybrid retrieval pipeline for one query.

    Stages:
    1. Lexical: ParadeDB BM25 over chunk text (filtered).
    2. Dense:   pgvector cosine ANN over Voyage embeddings (same filters).
    3. Fuse:    RRF combines the two ranked lists, optional per-list weights.
    4. Rerank:  Voyage rerank-2.5 reorders fused top-50 to final top-K.

    Empty / whitespace-only queries return an empty result without
    making any API calls.

    `embedder` and `rerank_client` are optional: by default both are
    constructed from VOYAGE_API_KEY. Tests inject mocks. When `embedder`
    is provided and `rerank_client` is None, the rerank step reuses
    `embedder.client` (one Voyage SDK Client serves both endpoints).

    `conn` is optional: when None, the BM25 + dense helpers each grab
    a pooled connection. Pass an explicit conn to share one for the
    whole pipeline (e.g. tests that want to wrap retrieval in a
    transaction).
    """
    if not req.query.strip():
        return RetrievalResult()

    filters = req.to_filters()

    if embedder is None:
        embedder = VoyageEmbedder()

    bm25_hits = bm25_query(
        req.query, top_k=bm25_top_k, filters=filters, conn=conn
    )
    dense_hits = dense_query(
        req.query,
        top_k=dense_top_k,
        filters=filters,
        conn=conn,
        embedder=embedder,
    )

    fused = rrf_fuse(
        [
            RankedList(chunks=bm25_hits, weight=bm25_weight),
            RankedList(chunks=dense_hits, weight=dense_weight),
        ],
        k=rrf_k,
        top_k=fused_top_k,
    )

    if not fused:
        return RetrievalResult(
            bm25_count=len(bm25_hits),
            dense_count=len(dense_hits),
            fused_count=0,
        )

    # Reuse the embedder's Voyage client when the caller hasn't passed
    # a separate rerank client — saves one client construction.
    rerank_client_arg = rerank_client or getattr(embedder, "client", None)

    reranked = rerank_chunks(
        req.query,
        fused,
        top_k=req.top_k,
        client=rerank_client_arg,
    )

    return RetrievalResult(
        chunks=reranked,
        top_score=reranked[0].score if reranked else 0.0,
        reranker_scores=[c.score for c in reranked],
        bm25_count=len(bm25_hits),
        dense_count=len(dense_hits),
        fused_count=len(fused),
    )
