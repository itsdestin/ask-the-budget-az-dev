"""Top-level retrieval pipeline: BM25 + dense -> RRF -> rerank -> top-K.

Composes the LanceDB search legs (`bm25_query_lance`, `dense_query_lance`),
`rrf_fuse`, and the local cross-encoder reranker into a single
`retrieve(RetrievalRequest)` -> `RetrievalResult` API. Phase 1c's Budget
MCP server wraps this; the eval harness calls it directly (single-shot,
deterministic per-query measurement).

Plan 1 swapped the substrate underneath this module — Postgres
(ParadeDB BM25 + pgvector ANN) and Voyage (embeddings + rerank-2.5) are
gone, replaced by an embedded LanceDB store and local ONNX models. The
public shapes (`RetrievalRequest`, `RetrievalResult`) are unchanged; the
`conn` and `rerank_client` parameters are gone because there is no
server and no external API to point them at. One score-semantics change
leaks through: reranker scores are raw cross-encoder logits (roughly
-10..10), not Voyage's 0..1, so refusal thresholds must be calibrated
against this distribution.

Top-K defaults match spec §3.4:
- BM25: top 200 lexical candidates
- Dense: top 100 ANN candidates
- Fused: top 50 after RRF (caller can shrink to fewer for cheaper
  rerank, but quality drops if less than ~20)
- Reranked: top `req.top_k` returned to caller (default
  DEFAULT_PIPELINE_TOP_K = 15; lowered from 20 on 2026-05-19 after
  dogfood showed context spillover)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.rrf import RankedList, rrf_fuse
from retrieval.search_lance import bm25_query_lance, dense_query_lance
from retrieval.types import RetrievalFilters, RetrievedChunk
from store.chunk_store import ChunkStore

# Default top-K caps at each stage (see spec §3.4).
BM25_TOP_K = 200
DENSE_TOP_K = 100
FUSED_TOP_K = 50
# Lowered from 20 to 15 (2026-05-20, Decision Q2 — dogfood hardening).
# Sized so a default retrieve() response stays comfortably under Claude
# Code's 25K-token per-tool-result budget; eliminates the spillover-to-
# disk + redundant Read pattern that 31 dogfood sessions exhibited at
# top_k=20. See scripts/measure_retrieve_size.py for the supporting
# measurement.
DEFAULT_PIPELINE_TOP_K = 15
# The corpus a request targets when it doesn't say. One LanceDB table per
# corpus (store.chunk_store.CORPUS_TABLES); budget documents are the
# default because every caller today is asking about the budget.
DEFAULT_CORPUS = "budget_chunks"

# Process-wide lazily-built collaborators. WHY singletons: constructing
# LocalEmbedder / LocalReranker loads ONNX weights (~3.6s cold for the
# pair) and holds them in memory, so building them per call would make
# every query pay a model load.
_default_store: ChunkStore | None = None
_default_embedder: LocalEmbedder | None = None
_default_reranker: LocalReranker | None = None
# WHY a lock: FastAPI runs sync endpoints in a threadpool, so two
# concurrent first requests would otherwise each build a full model stack
# — double the cold start and double the resident memory, with one copy
# then orphaned. ORT sessions are thread-safe to USE; only construction
# races.
_defaults_lock = threading.Lock()


def _get_store() -> ChunkStore:
    global _default_store
    with _defaults_lock:
        if _default_store is None:
            _default_store = ChunkStore()
        return _default_store


def _get_embedder() -> LocalEmbedder:
    global _default_embedder
    with _defaults_lock:
        if _default_embedder is None:
            _default_embedder = LocalEmbedder()
        return _default_embedder


def _get_reranker() -> LocalReranker:
    global _default_reranker
    with _defaults_lock:
        if _default_reranker is None:
            _default_reranker = LocalReranker()
        return _default_reranker


@dataclass(frozen=True)
class RetrievalRequest:
    """Public input shape — what Phase 1c's Budget MCP server `retrieve()`
    tool will accept (after JSON deserialization). Matches the filter
    dimensions on `RetrievalFilters` plus `query`, `top_k`, and `corpus`.
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
    corpus: str = DEFAULT_CORPUS

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

    NOTE post-Plan-1: those scores are raw cross-encoder logits (roughly
    -10..10, negatives are normal), not Voyage's 0..1 — any threshold
    compared against `top_score` has to be calibrated for this scale.

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
    store: ChunkStore | None = None,
    embedder: LocalEmbedder | None = None,
    reranker: LocalReranker | None = None,
    bm25_top_k: int = BM25_TOP_K,
    dense_top_k: int = DENSE_TOP_K,
    fused_top_k: int = FUSED_TOP_K,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> RetrievalResult:
    """Run the full hybrid retrieval pipeline for one query.

    Stages:
    1. Lexical: LanceDB FTS (BM25) over chunk text (filtered).
    2. Dense:   LanceDB cosine ANN over local ONNX embeddings (same filters).
    3. Fuse:    RRF combines the two ranked lists, optional per-list weights.
    4. Rerank:  local cross-encoder reorders fused top-50 to final top-K.

    Empty / whitespace-only queries return an empty result without opening
    the store or loading a model.

    `store`, `embedder`, and `reranker` are optional: each defaults to a
    process-wide singleton built on first use. Only the ones actually
    needed get built — a caller that injects a store and an embedder never
    pays for a model it won't use, and a query with no candidates never
    builds the reranker at all. Tests inject fakes for all three.

    Score semantics: the returned chunks carry raw cross-encoder logits
    (not 0..1). See the module docstring.
    """
    if not req.query.strip():
        return RetrievalResult()

    if store is None:
        store = _get_store()
    if embedder is None:
        embedder = _get_embedder()

    filters = req.to_filters()

    bm25_hits = bm25_query_lance(
        req.query,
        store=store,
        corpus=req.corpus,
        top_k=bm25_top_k,
        filters=filters,
    )
    # The dense leg doesn't own a model — the caller embeds the query and
    # passes the vector in, so the store stays model-agnostic.
    qvec = embedder.embed_one(req.query, input_type="query")
    dense_hits = dense_query_lance(
        qvec,
        store=store,
        corpus=req.corpus,
        top_k=dense_top_k,
        filters=filters,
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
        # Return before touching the reranker: it is the expensive stage,
        # and there is nothing for it to score.
        return RetrievalResult(
            bm25_count=len(bm25_hits),
            dense_count=len(dense_hits),
            fused_count=0,
        )

    if reranker is None:
        reranker = _get_reranker()

    reranked = reranker.rerank(req.query, fused, top_k=req.top_k)

    return RetrievalResult(
        chunks=reranked,
        top_score=reranked[0].score if reranked else 0.0,
        reranker_scores=[c.score for c in reranked],
        bm25_count=len(bm25_hits),
        dense_count=len(dense_hits),
        fused_count=len(fused),
    )
