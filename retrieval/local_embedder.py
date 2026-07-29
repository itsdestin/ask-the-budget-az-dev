"""Local ONNX embedding facade (spec S4) — same shape as VoyageEmbedder
(db/embeddings.py) so retrieval code swaps without caring which is
behind it: embed_one(text, input_type=...) and
embed_batch(texts, input_type=...).

input_type mapping: fastembed's query_embed/passage_embed apply the
model-appropriate prefixes (bge models want a query instruction
prefix); "document" -> passage_embed, "query" -> query_embed.
"""
from __future__ import annotations

from typing import Any

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
LOCAL_EMBEDDING_DIM = 384

INPUT_TYPE_DOCUMENT = "document"
INPUT_TYPE_QUERY = "query"


class LocalEmbedder:
    """Thin facade over fastembed's TextEmbedding.

    Tests pass a preconstructed fake through `model=` so the unit suite
    never downloads the ~67MB ONNX weights.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LOCAL_MODEL,
        dim: int = LOCAL_EMBEDDING_DIM,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.dim = dim
        if model is not None:
            self._model = model
        else:
            # Lazy import: keeps `import retrieval` cheap and lets tests
            # run without fastembed's model download.
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name)

    def embed_one(self, text: str, *, input_type: str = INPUT_TYPE_DOCUMENT) -> list[float]:
        """Single-text helper. Unlike Voyage there's no per-call network
        cost, but batching still amortizes ONNX session overhead — prefer
        embed_batch for many texts."""
        return self.embed_batch([text], input_type=input_type)[0]

    def embed_batch(
        self,
        texts: list[str],
        *,
        input_type: str = INPUT_TYPE_DOCUMENT,
    ) -> list[list[float]]:
        """Embed many texts locally. fastembed returns a generator of
        numpy arrays; we materialize plain float lists so callers (LanceDB
        writes, JSON responses) don't have to know about numpy."""
        if not texts:
            return []
        if input_type == INPUT_TYPE_QUERY:
            it = self._model.query_embed(texts)
        else:
            it = self._model.passage_embed(texts)
        return [[float(x) for x in v] for v in it]
