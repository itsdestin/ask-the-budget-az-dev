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
from typing import Any

from retrieval.agency_boost import apply_match_penalty
from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.query_agency import parse_query_agencies
from retrieval.query_doc_type import parse_query_doc_types
from retrieval.query_match import is_filterable
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

    `inferred_agencies` and `inferred_doc_types` report what was parsed out
    of the query and applied — but they are applied DIFFERENTLY, and a UI
    must not describe them the same way.

    `inferred_doc_types` is a hard FILTER: those document types are the only
    ones searched. Empty when the caller passed its own `doc_type`, when the
    match was too weak to filter on, or when the filter matched nothing and
    had to be dropped (see `dropped_filters`).

    `inferred_agencies` is only a ranking PREFERENCE — measured to beat a
    hard filter by ~5 points of recall at every cutoff, because the corpus
    is stamped incompletely and a correct reading of the question can still
    exclude the answer. Nothing is removed from the results, so an analyst
    seeing "preferring Corrections" still gets everything else below it.
    Empty only when the caller passed its own `agency_canonical_id`. The
    reasoning and the measurement are at the inference site in `retrieve`.

    `dropped_filters` (spec Q3) names the dimensions whose INFERRED filter
    returned nothing and was therefore abandoned for a second, unfiltered
    search. In practice that is only ever `["doc_type"]`, since agency no
    longer filters and so can never empty the page. It exists so the UI can say
    "showing all documents — no Corrections results matched" rather than
    silently pretending no filter was ever guessed. A filter that is
    invisibly not applied is the kind of thing that makes a tool feel
    haunted.
    """

    chunks: list[RetrievedChunk] = field(default_factory=list)
    top_score: float = NO_RESULTS_TOP_SCORE
    reranker_scores: list[float] = field(default_factory=list)
    bm25_count: int = 0
    dense_count: int = 0
    fused_count: int = 0
    inferred_fiscal_years: list[int] = field(default_factory=list)
    inferred_agencies: list[str] = field(default_factory=list)
    inferred_doc_types: list[str] = field(default_factory=list)
    dropped_filters: list[str] = field(default_factory=list)
    # Spec N5, `retrieve_spread` only — empty on the default path. One entry
    # per REQUESTED group, in request order:
    # `{"value": <year|doc_id>, "top_score": float|None, "count": int}`.
    # A group that matched nothing appears with count 0 rather than being
    # dropped: "FY2020 holds nothing" and "FY2020 was never searched" are
    # different answers, and only one of them is honest.
    spread_groups: list[dict[str, Any]] = field(default_factory=list)


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

    # Spec Q2: the same "the analyst typed it, so filter on it" idea as the
    # year parser above, extended to agency and document type — the two
    # dimensions an analyst actually names ("doc baseline", "dema ar").
    #
    # WHY confidence decides filter-versus-boost: a year token is
    # unambiguous, an agency acronym is not. `doc`, `ar` and `pp` are
    # ordinary words, so is_filterable() only lets a match through when
    # EVERY match is exact. Anything weaker is kept aside and handed to the
    # post-rerank penalty below, which competes with reranker scores instead
    # of overriding them.
    # AGENCY IS A RANKING PREFERENCE, NEVER A HARD FILTER — a deliberate
    # deviation from spec Q2, which specified a hard filter for an exact match.
    # Measured on the 47-query eval set, agency-filter ON vs OFF, everything
    # else identical:
    #
    #                       recall@5   recall@15   recall@20   failed lookups
    #     hard filter         83.33%      95.24%      95.24%     q-009, q-022
    #     preference only     88.10%     100.00%     100.00%     none
    #
    # WHY the filter loses, and it is not a tuning accident: the corpus is
    # stamped incompletely, so a CORRECT reading of the question can still
    # exclude the answer. q-009 names "the DOR Unclaimed Property Fund" and the
    # AFR passage answering it is stamped only agency:sba; q-022 names the
    # Secretary of State and its answer sits in a House document. In both the
    # parser is right and the filter still deletes the answer — and it deletes
    # it SILENTLY, because the agency has other chunks so the empty-result
    # fallback never fires.
    #
    # The cost is one slot on one navigational query (dema ar) out of six.
    # That is a good trade for 4.8 points of recall at every cutoff.
    #
    # Re-open this only with a measurement, and re-run it after any re-ingest
    # that improves agency stamping — the trade could genuinely reverse once
    # the corpus side has the aliases the query side now has.
    inferred_agencies: list[str] = []
    weak_agencies: list[str] = []
    if not req.agency_canonical_id:
        weak_agencies = [m.value for m in parse_query_agencies(req.query)]
        inferred_agencies = list(weak_agencies)

    inferred_doc_types: list[str] = []
    weak_doc_types: list[str] = []
    if not req.doc_type:
        type_matches = parse_query_doc_types(req.query)
        if is_filterable(type_matches):
            inferred_doc_types = [m.value for m in type_matches]
            filters = dataclass_replace(filters, doc_type=inferred_doc_types)
        else:
            weak_doc_types = [m.value for m in type_matches]

    # The query vector does not depend on the filters, so a retry below must
    # not pay to embed twice — embedding is the second-most expensive stage
    # after rerank.
    qvec_cache: list[list[float]] = []

    def _search(active: RetrievalFilters):
        bm25_hits = bm25_query_lance(
            req.query,
            store=store,
            corpus=req.corpus,
            top_k=bm25_top_k,
            filters=active,
        )
        # The dense leg doesn't own a model — the caller embeds the query and
        # passes the vector in, so the store stays model-agnostic.
        if not qvec_cache:
            qvec_cache.append(embedder.embed_one(req.query, input_type="query"))
        dense_hits = dense_query_lance(
            qvec_cache[0],
            store=store,
            corpus=req.corpus,
            top_k=dense_top_k,
            filters=active,
        )
        fused = rrf_fuse(
            [
                RankedList(chunks=bm25_hits, weight=bm25_weight),
                RankedList(chunks=dense_hits, weight=dense_weight),
            ],
            k=rrf_k,
            top_k=fused_top_k,
        )
        return bm25_hits, dense_hits, fused

    bm25_hits, dense_hits, fused = _search(filters)

    # Spec Q3, non-negotiable: an inferred filter is a GUESS, and a wrong
    # guess must cost the analyst ranking quality, never the whole page.
    # When one empties the result set we search again without it and report
    # what was let go, so the UI can say "showing all documents — no
    # Corrections results matched" instead of leaving them to wonder where
    # everything went.
    #
    # Only filters THIS pipeline inferred are droppable. A caller's explicit
    # filter was an instruction, not a guess; discarding it would answer a
    # different question than the one asked. The inferred YEAR filter is also
    # left alone — that is shipped S21 behaviour and changing it here would
    # alter refusal semantics as a side effect.
    # Only DOC TYPE can be dropped, because only doc type is ever applied as a
    # filter — agency is a ranking preference and so can never empty the page.
    dropped_filters: list[str] = []
    if not fused and inferred_doc_types:
        dropped_filters.append("doc_type")
        filters = dataclass_replace(filters, doc_type=req.doc_type)
        # The guess no longer describes what was applied, and `inferred_*`
        # means "inferred AND applied" — see RetrievalResult. It becomes a weak
        # signal instead, so the penalty below can still prefer the right
        # document type inside the unfiltered set.
        weak_doc_types = weak_doc_types or inferred_doc_types
        inferred_doc_types = []
        bm25_hits, dense_hits, fused = _search(filters)

    if not fused:
        # Return before touching the reranker: it is the expensive stage,
        # and there is nothing for it to score. top_score is left at the
        # NO_RESULTS_TOP_SCORE default — see that constant for why it isn't 0.
        return RetrievalResult(
            bm25_count=len(bm25_hits),
            dense_count=len(dense_hits),
            fused_count=0,
            inferred_fiscal_years=inferred_fiscal_years,
            inferred_agencies=inferred_agencies,
            inferred_doc_types=inferred_doc_types,
            dropped_filters=dropped_filters,
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

    # Spec Q4: the low-confidence half of query understanding. A match too
    # weak to hard-filter on ("doc baseline") still says something, so it
    # penalises chunks that do NOT match instead of being thrown away.
    #
    # Applied at the same seam as the recency boost, and penalty-shaped for
    # the same reason: `top_score` is what REFUSAL_THRESHOLD is compared
    # against, so an adjustment that RAISED a score would silently weaken
    # refusal. Ships at weight 0.0 until calibrated — see agency_boost.py.
    if weak_agencies or weak_doc_types:
        reranked = apply_match_penalty(
            reranked, agency_ids=weak_agencies, doc_types=weak_doc_types
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
        inferred_agencies=inferred_agencies,
        inferred_doc_types=inferred_doc_types,
        dropped_filters=dropped_filters,
    )


@dataclass(frozen=True)
class SpreadSpec:
    """One structured multi-group search (spec N4).

    `by` names the axis, `groups` the values in the order the caller wants
    them back, `per_group` how many passages each group keeps. The tool
    boundary (`harness/tools.py`) enforces the caps — this dataclass is the
    already-validated shape, so the pipeline never has to guess what a
    model meant.
    """

    by: str                      # "fiscal_year" | "doc_id"
    groups: tuple = ()           # tuple[int, ...] | tuple[str, ...]
    per_group: int = 3


def retrieve_spread(
    req: RetrievalRequest,
    spread: SpreadSpec,
    *,
    store: ChunkStore | None = None,
    embedder: LocalEmbedder | None = None,
    reranker: LocalReranker | None = None,
    bm25_top_k: int = BM25_TOP_K,
    dense_top_k: int = DENSE_TOP_K,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> RetrievalResult:
    """One query, searched once per group, reranked as ONE batch (spec N5).

    The structural fix for edition monoculture: "ahcccs appropriations report"
    can never surface FY2026 on the default path, because ~2,000 near-identical
    AHCCCS chunks span FY2005-2026 and the fused pool is capped at 20 — one
    edition's near-duplicates fill it before rerank starts. Measured: raising
    RECENCY_BOOST_PER_YEAR to 4.0 does not help, because the right edition is
    not in the pool to be boosted. No ranking constant can fix a pool
    COMPOSITION problem. FY2026 cannot be crowded out of the pool when FY2026
    IS its own pool.

    Three deliberate differences from `retrieve()`, each load-bearing:

    * **No query-understanding inference.** The groups ARE the instruction, so
      neither the S21 year filter nor the Q2 doc-type filter runs — inferring
      a year here would fight the caller's own grouping, and an inferred
      doc-type filter would silently shrink a group the model asked for. Weak
      agency / doc-type parsing still runs, but only to feed the penalty.
    * **No recency, on either axis.** This is the existing skip rule extended,
      not a new idea: the default path already skips recency whenever a year
      filter is active, and every `by=fiscal_year` group IS a year filter.
      More important, per-group `top_score`s are compared ACROSS groups by the
      model, and an anchor-relative recency pass (~0.85/yr x 16 yr = ~13.6
      logits, larger than the whole +/-10 logit range) would report "FY2010
      has nothing" where FY2010 holds a perfect hit. Refusal interaction,
      stated so nobody rediscovers it: recency is a PENALTY, so skipping it
      can only RAISE `top_score` — spread refuses no more than the default
      path and possibly less, exactly as an explicit year-filtered retrieve
      already does.
    * **The agency penalty runs over the FULL candidate set BEFORE the
      per-group trim.** Same lesson as the rerank-then-trim comment in
      `retrieve()`: an adjustment can only reorder chunks it can see, so
      penalising after the trim would mean a matching chunk at position
      per_group+1 could never be promoted into its group's results.

    Nothing here adds a score BONUS, so the penalty-only invariant on
    `top_score` holds and the three coupled ranking constants are untouched.
    """
    if not req.query.strip() or not spread.groups:
        return RetrievalResult()

    if store is None:
        store = _get_store()
    if embedder is None:
        embedder = _get_embedder()

    base = req.to_filters()
    # Once, for every group: the embedding does not depend on the filters, and
    # it is the second-most expensive stage after rerank.
    qvec = embedder.embed_one(req.query, input_type="query")
    # Small overfetch per group so the penalty has something to reorder — the
    # trim happens after it, not here. Floor of 6 so a per_group of 1 still
    # gives the penalty and the reranker a real choice.
    overfetch = max(2 * spread.per_group, 6)

    candidates_by_group: dict[Any, list[RetrievedChunk]] = {}
    for value in spread.groups:
        if spread.by == "fiscal_year":
            # EXACT, deliberately not the default path's +/-1 adjacent-year
            # window: the model named this group, and widening it would blur
            # the cross-group comparison the whole feature exists to make.
            active = dataclass_replace(base, fiscal_year=[int(value)])
        else:
            active = dataclass_replace(base, doc_id=[str(value)])
        bm25_hits = bm25_query_lance(
            req.query, store=store, corpus=req.corpus,
            top_k=bm25_top_k, filters=active,
        )
        dense_hits = dense_query_lance(
            qvec, store=store, corpus=req.corpus,
            top_k=dense_top_k, filters=active,
        )
        candidates_by_group[value] = rrf_fuse(
            [
                RankedList(chunks=bm25_hits, weight=bm25_weight),
                RankedList(chunks=dense_hits, weight=dense_weight),
            ],
            k=rrf_k,
            top_k=overfetch,
        )

    # No cross-group dedup is needed and none is done: a chunk has exactly one
    # fiscal_year and exactly one doc_id, so on either axis the groups are
    # disjoint by construction. If a third axis is ever added, that assumption
    # must be re-checked before this line is copied.
    all_candidates = [c for group in candidates_by_group.values() for c in group]
    empty_summary = [
        {"value": v, "top_score": None, "count": 0} for v in spread.groups
    ]
    if not all_candidates:
        return RetrievalResult(spread_groups=empty_summary)

    if reranker is None:
        reranker = _get_reranker()
    # ONE batch over every group's candidates, and `top_k` covers the whole
    # list so the penalty below can still see everything (see the docstring).
    reranked = reranker.rerank(req.query, all_candidates, top_k=len(all_candidates))

    # Spec Q4's low-confidence half, same seam and same penalty shape as the
    # default path. Only weak matches reach it: anything the caller passed
    # explicitly is already a filter, and nothing here is ever promoted to one.
    weak_agencies = (
        [m.value for m in parse_query_agencies(req.query)]
        if not req.agency_canonical_id else []
    )
    weak_doc_types = (
        [m.value for m in parse_query_doc_types(req.query)]
        if not req.doc_type else []
    )
    if weak_agencies or weak_doc_types:
        reranked = apply_match_penalty(
            reranked, agency_ids=weak_agencies, doc_types=weak_doc_types
        )

    # Partition the RERANKED (and penalised) chunks by the axis attribute, so
    # the trim below sorts on the final score rather than the leg's.
    by_value: dict[Any, list[RetrievedChunk]] = {v: [] for v in spread.groups}
    for chunk in reranked:
        key = chunk.fiscal_year if spread.by == "fiscal_year" else chunk.doc_id
        if key in by_value:
            by_value[key].append(chunk)

    chunks: list[RetrievedChunk] = []
    groups_summary: list[dict[str, Any]] = []
    for value in spread.groups:
        kept = sorted(by_value[value], key=lambda c: -c.score)[: spread.per_group]
        chunks.extend(kept)
        groups_summary.append({
            "value": value,
            "top_score": kept[0].score if kept else None,
            "count": len(kept),
        })

    return RetrievalResult(
        chunks=chunks,
        top_score=max((c.score for c in chunks), default=NO_RESULTS_TOP_SCORE),
        reranker_scores=[c.score for c in chunks],
        fused_count=len(all_candidates),
        spread_groups=groups_summary,
    )
