"""Local cross-encoder rerank (spec S4), replacing Voyage rerank-2.5.

Mirrors the rerank_chunks contract (retrieval/rerank.py): takes the
RRF-fused candidates, returns top_k RetrievedChunk re-scored by the
cross-encoder, descending. Score semantics change vs Voyage (raw
logits, roughly -10..10, NOT 0..1) — the refusal threshold is
re-calibrated in a later task and consumers must not assume 0..1.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from retrieval.types import RetrievedChunk

DEFAULT_LOCAL_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class LocalReranker:
    """Thin facade over fastembed's TextCrossEncoder.

    Tests pass a preconstructed fake through `model=` so the unit suite
    never downloads the ONNX weights.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LOCAL_RERANK_MODEL,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        if model is not None:
            self._model = model
        else:
            # Lazy import for the same reason as LocalEmbedder: importing
            # this module must not trigger a model download.
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Re-score candidates with the cross-encoder and return the best
        top_k, descending.

        Unlike Voyage (which returns results already sorted with an index
        back into the input list), fastembed returns one score per input
        in input order — so we zip, then sort ourselves. chunk_id is the
        tiebreaker so equal scores produce a deterministic order.
        """
        if not chunks:
            return []
        scores = list(self._model.rerank(query, [c.text for c in chunks]))
        rescored = [
            replace(c, score=float(s)) for c, s in zip(chunks, scores)
        ]
        rescored.sort(key=lambda c: (-c.score, c.chunk_id))
        return rescored[:top_k]
