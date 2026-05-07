"""Reciprocal Rank Fusion (RRF) — pure function, no IO.

Phase 1b WS6 Task 6.1. The standard rank-based fusion for hybrid
retrieval: takes N ranked candidate lists and merges them into one
list ordered by sum-of-reciprocal-ranks.

For each chunk d appearing in any input list,
    rrf_score(d) = sum_i  weight_i / (k + rank_i(d))
where rank_i is 1-indexed and chunks absent from list i contribute 0.
The standard k = 60 (Cormack et al. 2009) — small enough that top-rank
contributions dominate, large enough that mid-rank contributions still
matter when a chunk shows up in multiple lists.

Per-list weights default to 1.0. Spec §3.4 hints at "slight weight
toward BM25 for lookup-type sub-queries" — implement here as an
optional knob; the agent-pattern caller (Phase 1c) decides when to
flex it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

from retrieval.types import RetrievedChunk

DEFAULT_K = 60  # Cormack et al. 2009


@dataclass(frozen=True)
class RankedList:
    """One ranked candidate list + an optional fusion weight."""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    weight: float = 1.0


def rrf_fuse(
    ranked_lists: Iterable[RankedList | list[RetrievedChunk]],
    *,
    k: int = DEFAULT_K,
    top_k: int = 50,
) -> list[RetrievedChunk]:
    """Fuse N ranked candidate lists by Reciprocal Rank Fusion.

    Inputs may be `RankedList` instances (with explicit weight) or raw
    `list[RetrievedChunk]` (treated as weight=1.0). Each input list is
    assumed already sorted descending by its own scoring metric.

    The returned chunks carry the RRF score in their `score` field
    (replacing the original BM25/dense score, which is rank-only data
    after fusion). Identity is by `chunk_id`; the first occurrence's
    metadata is preserved if a chunk appears in multiple lists.

    Returns the top `top_k` chunks ordered by RRF score descending,
    breaking ties by chunk_id for determinism.
    """
    fused_scores: dict[str, float] = {}
    first_seen: dict[str, RetrievedChunk] = {}

    for entry in ranked_lists:
        if isinstance(entry, RankedList):
            chunks, weight = entry.chunks, entry.weight
        else:
            chunks, weight = entry, 1.0

        for rank, chunk in enumerate(chunks, start=1):
            cid = chunk.chunk_id
            fused_scores[cid] = fused_scores.get(cid, 0.0) + weight / (k + rank)
            if cid not in first_seen:
                first_seen[cid] = chunk

    if not fused_scores:
        return []

    # Stable sort by (-score, chunk_id) — chunk_id tiebreaker is deterministic
    # across identical scores so retries return the same order.
    sorted_ids = sorted(
        fused_scores.keys(),
        key=lambda cid: (-fused_scores[cid], cid),
    )[:top_k]

    return [
        replace(first_seen[cid], score=fused_scores[cid]) for cid in sorted_ids
    ]
