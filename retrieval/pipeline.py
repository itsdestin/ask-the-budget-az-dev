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
against this distribution. That change also forced the no-results
sentinel to move — `top_score` used to be 0.0 when nothing was found,
which sat below every threshold on Voyage's 0..1 scale but now outranks
a genuinely-bad hit. See NO_RESULTS_TOP_SCORE.

Top-K caps at each stage (spec §3.4 for the first three; the reranked
default was deliberately lowered below the spec's 20):
- BM25: top 200 lexical candidates
- Dense: top 100 ANN candidates
- Fused: top 20 after RRF (lowered from the spec's 50 on 2026-07-30 —
  the local cross-encoder's per-candidate cost makes 50 unaffordable;
  see the FUSED_TOP_K comment)
- Reranked: top `req.top_k` returned to caller (default
  DEFAULT_PIPELINE_TOP_K = 15; lowered from the spec's 20 on 2026-05-20
  after dogfood showed context spillover)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace as dataclass_replace

from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.query_year import fiscal_year_filter, parse_query_years
from retrieval.recency import anchor_fiscal_year, apply_recency_boost
from retrieval.rrf import RankedList, rrf_fuse
from retrieval.search_lance import bm25_query_lance, dense_query_lance
from retrieval.types import RetrievalFilters, RetrievedChunk
from store.chunk_store import ChunkStore

# Default top-K caps at each stage (see spec §3.4).
BM25_TOP_K = 200
DENSE_TOP_K = 100
# Lowered from the spec's 50 on 2026-07-30 with the L-12 reranker swap:
# the local cross-encoder pays ~130-250ms PER candidate on an i5 CPU, so a
# 50-candidate pool costs ~4.9s of rerank per query — over the ~3s
# interactive-search budget. 20 candidates measured 2.7s mean / 3.1s max,
# and the fused-20 pool still passes the amended G1 gate (recall@15/@20 —
# see eval/results/ for the run this was decided on).
FUSED_TOP_K = 20
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

# `top_score` when the pipeline found nothing. Deliberately NOT 0.0.
#
# WHY: reranker scores are raw cross-encoder logits, and 0.0 sits ABOVE a
# genuinely-irrelevant hit. Measured on the migrated corpus: real hits score
# +2.27..+7.72, a pure-gibberish query scores -11.12. With 0.0 as the
# sentinel, "found nothing" would outrank "found garbage", so a threshold
# calibrated at or below 0 (Task 12) would read an empty result as a
# confident one. That is not a corner case — it is reachable by ordinary
# over-filtering (fiscal_year=[1999]) and by any query against the
# legitimately-empty fiscal_note_chunks table.
#
# WHY a finite floor instead of float("-inf"): api.py returns this field to
# clients. Measured on pydantic 2.13.3 / fastapi 0.136.1 — a pydantic
# response model serializes -inf to JSON `null`, which reaches the MCP
# server as a non-number and breaks its `top_score < threshold` comparison;
# and handing -inf to FastAPI's JSONResponse directly raises ValueError
# outright, because that renderer sets allow_nan=False. -1e9 is an ordinary
# float everywhere, JSON-legal, and ~1e8 below any reachable logit.
NO_RESULTS_TOP_SCORE = -1e9

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


def reset_default_collaborators() -> None:
    """Drop the process-wide store/embedder/reranker so the next call rebuilds.

    Public because tests (and the sidecar's lifespan hooks, if it ever needs
    to swap models without a restart) must not have to reach into private
    globals to get a clean slate. Takes the same lock as the getters so a
    concurrent first request can't observe a half-cleared set.
    """
    global _default_store, _default_embedder, _default_reranker
    with _defaults_lock:
        _default_store = None
        _default_embedder = None
        _default_reranker = None


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
    compared against `top_score` has to be calibrated for this scale. When
    there are no results at all, `top_score` is NO_RESULTS_TOP_SCORE
    (-1e9), which is below every real logit; it is NOT 0.0, because 0.0
    would rank an empty result above a bad one.

    `bm25_count` / `dense_count` / `fused_count` are diagnostics — they
    let the eval harness and the audit log capture how many candidates
    each stage produced before rerank.

    `inferred_fiscal_years` (S21 layer 1) reports fiscal years the
    pipeline parsed out of the query text and APPLIED as a hard filter —
    empty when the query named none, and also empty when the caller
    passed its own `fiscal_year` (the caller's filter wins, so nothing
    was inferred). It exists so a UI or tool response can say "filtered
    to FY 2019" instead of leaving the analyst wondering where the other
    years went.
    """

    chunks: list[RetrievedChunk] = field(default_factory=list)
    top_score: float = NO_RESULTS_TOP_SCORE
    reranker_scores: list[float] = field(default_factory=list)
    bm25_count: int = 0
    dense_count: int = 0
    fused_count: int = 0
    inferred_fiscal_years: list[int] = field(default_factory=list)


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

    # S21 layer 1: a fiscal year the analyst typed ("fy2019 DES funding")
    # becomes a hard filter. WHY a hard filter and not a boost: after the
    # S20 backfill the corpus holds ~20 near-identical editions of every
    # per-agency page, so a soft preference for FY2019 still returns
    # fifteen other years' worth of the same page. WHY only when the
    # caller passed none: an explicit `fiscal_year` argument is a
    # deliberate instruction from a tool call or the UI, and a parser
    # quietly overriding it would make that argument untrustworthy.
    #
    # The filter is WIDER than what is echoed back: `inferred_fiscal_years`
    # reports the years the analyst named, while the filter also admits
    # their immediate neighbours, because a passage about FY N often lives
    # in a document stamped FY N±1. See ADJACENT_YEAR_WINDOW.
    inferred_fiscal_years: list[int] = []
    if not req.fiscal_year:
        inferred_fiscal_years = parse_query_years(req.query)
        if inferred_fiscal_years:
            filters = dataclass_replace(
                filters, fiscal_year=fiscal_year_filter(inferred_fiscal_years)
            )

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
        # and there is nothing for it to score. top_score is left at the
        # NO_RESULTS_TOP_SCORE default — see that constant for why it isn't 0.
        return RetrievalResult(
            bm25_count=len(bm25_hits),
            dense_count=len(dense_hits),
            fused_count=0,
            inferred_fiscal_years=inferred_fiscal_years,
        )

    if reranker is None:
        reranker = _get_reranker()

    # Rerank the WHOLE fused pool, then trim after the recency pass.
    #
    # WHY not `top_k=req.top_k` here: the recency bonus below can only
    # reorder chunks it can see. If the reranker has already dropped the
    # newest edition out of the top-K — which is the exact failure S21
    # exists to fix, twenty near-identical editions competing and the
    # cross-encoder picking an arbitrary one — no weight can bring it
    # back. Costs nothing: the reranker already scored every fused
    # candidate, `top_k` only sliced its sorted output.
    reranked = reranker.rerank(req.query, fused, top_k=len(fused))

    # S21 layer 3: with no year named, prefer newer editions. Skipped on
    # the fiscal-note corpus (triage wants similar notes at any age) and
    # skipped whenever a year filter is active — inside a set the analyst
    # already narrowed to FY 2019, preferring "newer" is fighting the
    # instruction. Ships at weight 0.0, i.e. a no-op, until
    # eval/calibrate_recency.py recommends a weight against a backfilled
    # corpus; see retrieval/recency.py for why that ordering matters.
    if req.corpus == DEFAULT_CORPUS and not filters.fiscal_year:
        reranked = apply_recency_boost(
            reranked, anchor_fy=anchor_fiscal_year(reranked)
        )

    reranked = reranked[: req.top_k]

    return RetrievalResult(
        chunks=reranked,
        # `reranked` can only be empty if the reranker dropped everything;
        # that is still "no results", so it gets the same sentinel.
        top_score=reranked[0].score if reranked else NO_RESULTS_TOP_SCORE,
        reranker_scores=[c.score for c in reranked],
        bm25_count=len(bm25_hits),
        dense_count=len(dense_hits),
        fused_count=len(fused),
        inferred_fiscal_years=inferred_fiscal_years,
    )
