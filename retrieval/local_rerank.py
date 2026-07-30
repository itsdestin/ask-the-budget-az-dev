"""Local cross-encoder rerank (spec S4), replacing Voyage rerank-2.5.

Mirrors the rerank_chunks contract (retrieval/rerank.py): takes the
RRF-fused candidates, returns top_k RetrievedChunk re-scored by the
cross-encoder, descending. Score semantics change vs Voyage (raw
logits, roughly -10..10, NOT 0..1) — the refusal threshold is
re-calibrated in a later task and consumers must not assume 0..1.

512-token ceiling: this cross-encoder's tokenizer truncates the
(query, passage) pair at 512 WordPiece tokens ('longest_first',
direction right), so only roughly the first ~500 tokens of each chunk
influence its score. Our chunker targets 512 *cl100k* tokens and allows
up to 1024 (chunking/builders/narrative_chunk.py), and WordPiece runs
hotter than cl100k on this corpus (spot-measured 1.05-1.35x on
numeral-dense JLBC prose — dollar figures fragment into many subword
pieces), so long chunks are judged on their openings alone. Voyage
rerank-2.5 read the whole passage, so this is a real behavioral delta:
a diagnostic worth checking if the G1 eval gate misses.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from retrieval.types import RetrievedChunk

# WHY L-12 over L-6: the 2026-07-30 reranker sweep showed L-12 is the ONLY
# fastembed cross-encoder that clears the amended G1 gate (recall@15 >= 90%
# on the arctic candidate pool); L-6 and jina-turbo both land at 89.66%.
# L-12 costs ~2x L-6 per candidate (measured 4.9s at a 50-candidate pool,
# 2.7s mean / 3.1s max at 20), which is why the fused pool default dropped
# to 20 (see retrieval/pipeline.py FUSED_TOP_K).
DEFAULT_LOCAL_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-12-v2"


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
        if top_k <= 0:
            # A negative top_k would silently slice as chunks[:-1] and drop a
            # result; zero would return nothing. Both are caller bugs, and a
            # quietly short candidate list would corrupt Task 12's threshold
            # calibration, so fail loudly instead.
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        scores = list(self._model.rerank(query, [c.text for c in chunks]))
        rescored = [
            # strict=True: a short score iterable would otherwise silently
            # drop candidates off the end with no downstream backstop.
            replace(c, score=float(s)) for c, s in zip(chunks, scores, strict=True)
        ]
        rescored.sort(key=lambda c: (-c.score, c.chunk_id))
        return rescored[:top_k]
