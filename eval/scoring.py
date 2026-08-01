"""Pure scoring logic for the eval harness.

Functions here take simple dicts (from `retrieve()`) and Pydantic
models (from `eval/queries.yaml`) and return tuples or summary objects.
No DB, no I/O — trivially testable.

The matching algorithm:
  1. chunk_id exact match → "chunk_id" (tight)
  2. dimensions all match → "dimensions_fallback" (loose, and now the
     ONLY thing standing between a re-ingest and a scoring collapse —
     the refresh tool that used to re-bind stale chunk_ids was deleted
     with the Postgres tooling; see eval/schema.py)
  3. neither → None (this chunk doesn't satisfy this expected)

Lookup: pass if ANY expected_chunk has a match in top K.
Comparison: pass if ALL expected_chunks have a match in top K.
Refusal: pass if top_score < threshold (retrieval correctly declined).
"""
from __future__ import annotations

from typing import Literal, Optional

from eval.schema import (
    EvalQuery,
    EvalSummary,
    ExpectedChunk,
    PerQueryResult,
)

MatchKind = Optional[Literal["chunk_id", "dimensions_fallback"]]


def chunk_matches_expected(
    retrieved: dict, expected: ExpectedChunk
) -> MatchKind:
    """Return the match kind, or None when this chunk doesn't satisfy
    this expected. The retrieved chunk is expected to carry the shape
    `retrieve()` returns: chunk_id, publisher, doc_type, fiscal_year,
    agency_canonical_ids (a list)."""
    if retrieved.get("chunk_id") == expected.chunk_id:
        return "chunk_id"

    dims = expected.dimensions
    if retrieved.get("publisher") != dims.publisher:
        return None
    if retrieved.get("doc_type") != dims.doc_type:
        return None
    if retrieved.get("fiscal_year") != dims.fiscal_year:
        return None
    # agency is the only nullable dimension. When None on the expected
    # side it's not part of the constraint.
    if dims.agency is not None:
        agency_ids = retrieved.get("agency_canonical_ids") or []
        if dims.agency not in agency_ids:
            return None
    return "dimensions_fallback"


def score_lookup(
    query: EvalQuery, retrieved: list[dict], k: int
) -> tuple[Literal["pass", "fail"], MatchKind, Optional[int]]:
    """Lookup passes if ANY expected_chunk has a match in top K.
    Returns (status, matched_via, 1-based-rank). When status is "fail"
    matched_via and rank are None."""
    for rank, chunk in enumerate(retrieved[:k], start=1):
        for expected in query.expected_chunks:
            match = chunk_matches_expected(chunk, expected)
            if match is not None:
                return "pass", match, rank
    return "fail", None, None


def score_comparison(
    query: EvalQuery, retrieved: list[dict], k: int
) -> tuple[Literal["pass", "fail"], MatchKind, Optional[int]]:
    """Comparison passes if ALL expected_chunks have a match in top K.
    `matched_via` is "dimensions_fallback" when ANY of the matches used
    fallback (the eval reports degraded ground-truth), "chunk_id" only
    when all matched exactly. `rank` is the MAX rank across the
    matches (the "worst" position needed)."""
    ranks: list[int] = []
    any_fallback = False
    for expected in query.expected_chunks:
        found = False
        for rank, chunk in enumerate(retrieved[:k], start=1):
            match = chunk_matches_expected(chunk, expected)
            if match is not None:
                ranks.append(rank)
                if match == "dimensions_fallback":
                    any_fallback = True
                found = True
                break
        if not found:
            return "fail", None, None
    # Worst rank — comparison passes only when ALL expected chunks are
    # in top K, so the bottleneck is the worst-positioned one. This
    # makes recall@5 for a comparison query mean "both chunks within
    # top 5," not "either chunk within top 5."
    return (
        "pass",
        "dimensions_fallback" if any_fallback else "chunk_id",
        max(ranks),
    )


def score_refusal(
    query: EvalQuery, top_score: float, threshold: float
) -> Literal["pass", "fail"]:
    """Refusal passes when top_score is below the refusal threshold —
    retrieval correctly declined to surface low-confidence chunks."""
    return "pass" if top_score < threshold else "fail"


def aggregate_metrics(
    per_query: list[PerQueryResult],
) -> EvalSummary:
    """Compute the EvalSummary from per-query results.

    The runner always scores at K=20. To keep this simple, it sends ONE
    PerQueryResult per query (scored at K=20) and we recompute the shallower
    cutoffs here by checking each pass's rank against them.

    K=15 is the gating cutoff (spec gate G1, amended 2026-07-30 to
    "recall@15 >= 90% and recall@20 >= 95%") because it is exactly what
    retrieve() returns — DEFAULT_PIPELINE_TOP_K in retrieval/pipeline.py. K=5
    stays reported but no longer gates: it measures the local cross-encoder's
    ordering polish, which the Task 11 sweep showed is capped at 62-69%
    regardless of candidate quality.
    """
    retrieval_queries = [p for p in per_query if p.type != "refusal"]
    refusal_queries = [p for p in per_query if p.type == "refusal"]

    # Recall@5: pass AND rank <= 5.
    passes_at_5 = sum(
        1
        for p in retrieval_queries
        if p.status == "pass" and p.rank is not None and p.rank <= 5
    )
    passes_at_15 = sum(
        1
        for p in retrieval_queries
        if p.status == "pass" and p.rank is not None and p.rank <= 15
    )
    passes_at_20 = sum(
        1 for p in retrieval_queries if p.status == "pass"
    )

    # Fallback rate: of all passes, how many used the dimensions
    # fallback?
    total_passes = sum(
        1 for p in retrieval_queries if p.status == "pass"
    )
    fallback_passes = sum(
        1
        for p in retrieval_queries
        if p.status == "pass" and p.matched_via == "dimensions_fallback"
    )
    fallback_rate = (
        fallback_passes / total_passes if total_passes else 0.0
    )

    # Refusal precision: of refusal-type queries that passed (retrieval
    # correctly declined), what share were expected to refuse? Today
    # every refusal-type query IS expected to refuse, so precision
    # equals pass rate.
    refusal_passes = sum(
        1 for p in refusal_queries if p.status == "pass"
    )
    refusal_precision = (
        refusal_passes / len(refusal_queries) if refusal_queries else 0.0
    )
    # Refusal recall: same as precision for v1 (we don't currently
    # detect "queries we should have refused on but didn't" because
    # that requires the eval to KNOW which retrieval queries the model
    # should have refused but answered — out of scope until Layer 2).
    refusal_recall = refusal_precision

    # Latency percentiles across ALL queries.
    # Nearest-rank percentile (no interpolation). int((n-1) * q) maps
    # q=0.50 to the lower-median, q=0.95 to the 95th-percentile
    # nearest-rank — matches numpy.percentile(..., method="lower"). The
    # naive `int(n * q)` overshoots by 1 for n=20 / n=100.
    latencies = sorted(p.latency_ms for p in per_query)
    p50 = latencies[int((len(latencies) - 1) * 0.50)] if latencies else 0
    p95 = latencies[int((len(latencies) - 1) * 0.95)] if latencies else 0

    # Per-type breakdown.
    by_type: dict = {}
    for type_name in ("lookup", "comparison"):
        bucket = [p for p in retrieval_queries if p.type == type_name]
        if not bucket:
            continue
        passes_5 = sum(
            1
            for p in bucket
            if p.status == "pass" and p.rank is not None and p.rank <= 5
        )
        passes_15 = sum(
            1
            for p in bucket
            if p.status == "pass" and p.rank is not None and p.rank <= 15
        )
        passes_20 = sum(1 for p in bucket if p.status == "pass")
        by_type[type_name] = {
            "recall_at_5": passes_5 / len(bucket),
            "recall_at_15": passes_15 / len(bucket),
            "recall_at_20": passes_20 / len(bucket),
            "count": len(bucket),
        }
    if refusal_queries:
        by_type["refusal"] = {
            "precision": refusal_precision,
            "count": len(refusal_queries),
        }

    total_retrieval = len(retrieval_queries)
    return EvalSummary(
        recall_at_5=passes_at_5 / total_retrieval if total_retrieval else 0.0,
        recall_at_15=passes_at_15 / total_retrieval if total_retrieval else 0.0,
        recall_at_20=passes_at_20 / total_retrieval
        if total_retrieval
        else 0.0,
        fallback_rate=fallback_rate,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        refusal_precision=refusal_precision,
        refusal_recall=refusal_recall,
        by_type=by_type,
    )
