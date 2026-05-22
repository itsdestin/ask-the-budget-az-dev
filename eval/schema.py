"""Pydantic models for the eval harness.

Two surfaces:
  * `EvalQuery` (and its children QueryDimensions, ExpectedChunk) — the
    YAML shape stored at `eval/queries.yaml`. Hybrid ground truth:
    chunk_id (tight, brittle to re-chunking) + dimensions (loose,
    durable) + anchor_text (deterministic recovery target for the
    refresh tool).
  * `EvalResult` (with EvalSummary, PerQueryResult) — the JSON shape
    written per run to `eval/results/<UTC-ISO>-<git-sha>.json`.

Models are frozen-ish (Pydantic v2 default = frozen=False, but we don't
mutate them after construction in the runner — they're built once and
serialized).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class QueryDimensions(BaseModel):
    """Loose-but-durable expected-chunk constraint. A returned chunk
    satisfies the dimensions when ALL non-None fields match."""

    publisher: str  # jlbc | agao | governor | legislature
    doc_type: str  # baseline-per-agency | approps-cross-cut | budget-bill | ...
    fiscal_year: int
    # Optional because some chunks (e.g. topic-level cross-cuts) don't
    # stamp to a single agency. When None, agency is not part of the
    # constraint (any chunk satisfying the other three fields passes).
    agency: Optional[str] = None


class ExpectedChunk(BaseModel):
    """One expected-chunk entry on an EvalQuery.

    The hybrid:
      * chunk_id — primary, exact. Used for tight scoring while
        chunk boundaries are stable.
      * dimensions — fallback. Used when chunk_id is no longer in the
        corpus (post-reingest). Survives re-chunking.
      * anchor_text — short distinctive substring from the seed chunk.
        Used by `refresh_chunk_ids.py` to find the successor chunk
        deterministically.
    """

    chunk_id: str
    dimensions: QueryDimensions
    anchor_text: Optional[str] = None


class EvalQuery(BaseModel):
    """A single eval query: question + ground truth + provenance."""

    id: str
    query: str
    type: Literal["lookup", "comparison", "refusal"]
    expected_chunks: list[ExpectedChunk] = Field(default_factory=list)
    expected_refusal: bool = False
    synthesized_by: Optional[str] = None
    synthesized_at: Optional[str] = None


class PerQueryResult(BaseModel):
    """One row of `eval/results/<file>.json::per_query`."""

    id: str
    type: str
    status: Literal["pass", "fail"]
    # `chunk_id` when an expected chunk's chunk_id was in top K.
    # `dimensions_fallback` when chunk_id was missing but a returned
    # chunk satisfied the dimensions.
    # None on fail.
    matched_via: Optional[Literal["chunk_id", "dimensions_fallback"]] = None
    rank: Optional[int] = None  # 1-based rank of the matching chunk
    latency_ms: int
    top_score: float
    top_chunk_ids: list[str] = Field(default_factory=list)


class EvalSummary(BaseModel):
    """Aggregate metrics across all queries in a run."""

    recall_at_5: float
    recall_at_20: float
    fallback_rate: float  # share of passes that used dimensions fallback
    latency_p50_ms: int
    latency_p95_ms: int
    refusal_precision: float  # of would-refuse, how many were correct?
    refusal_recall: float  # of expected-refuse, how many actually did?
    # by_type carries per-type breakdowns. Shape varies (lookup +
    # comparison have recall_at_K; refusal has precision). Keeping as
    # dict for shape flexibility — readers index by string keys.
    by_type: dict


class EvalResult(BaseModel):
    """The full JSON written per run to eval/results/."""

    git_sha: str
    timestamp: str  # UTC ISO 8601
    summary: EvalSummary
    per_query: list[PerQueryResult]
