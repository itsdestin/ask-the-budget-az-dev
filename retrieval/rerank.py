"""Voyage rerank-2.5 wrapper.

Phase 1b WS6 Task 6.2. Takes a list of candidate chunks (typically the
RRF-fused top-50) plus the original query, and reorders by
cross-encoder relevance. Voyage rerank-2.5 returns scores in [0, 1];
higher = more relevant.

Reranking is the single highest-cost step in the retrieval pipeline
per query (~$0.05 / 1k requests, where one request = one query × up to
1k candidates), but it materially improves precision at top-K.
We rerank the top-50 fused candidates to top-20.

The Voyage reranker uses a separate model (rerank-2.5) from the
embedder (voyage-3-large), but both ship in the same `voyageai` SDK
and share a Client object. We reuse `VoyageEmbedder.client` when the
caller has one already, otherwise we build a fresh client from
VOYAGE_API_KEY.
"""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from retrieval.types import RetrievedChunk

DEFAULT_RERANK_MODEL = "rerank-2.5"
DEFAULT_RERANK_TOP_K = 20


def rerank_chunks(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_k: int = DEFAULT_RERANK_TOP_K,
    model: str = DEFAULT_RERANK_MODEL,
    client: Any | None = None,
) -> list[RetrievedChunk]:
    """Rerank candidates via Voyage rerank-2.5; return top-k by relevance.

    `client` is optional: when None, build a fresh `voyageai.Client`
    from VOYAGE_API_KEY. Tests pass a mock client to avoid hitting the
    real API.

    The returned chunks carry the reranker's `relevance_score` in their
    `score` field (replacing whatever upstream score was there). Empty
    inputs short-circuit before any API call. Empty query returns the
    candidates unchanged (truncated to top_k).
    """
    if not candidates:
        return []
    if not query.strip():
        return list(candidates[:top_k])

    if client is None:
        import voyageai

        api_key = os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY not set — pass client=... or set the env var "
                "(sign up at https://dash.voyageai.com/api-keys)."
            )
        client = voyageai.Client(api_key=api_key)

    response = client.rerank(
        query=query,
        documents=[c.text for c in candidates],
        model=model,
        top_k=top_k,
    )

    # Voyage's response.results carries `index` (into the original docs
    # list) and `relevance_score` per item. We map back to the original
    # chunks by index, replacing the score.
    return [
        replace(candidates[r.index], score=float(r.relevance_score))
        for r in response.results
    ]
