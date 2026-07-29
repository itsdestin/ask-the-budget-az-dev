"""Local ONNX embedding facade (spec S4) — same shape as VoyageEmbedder
(db/embeddings.py) so retrieval code swaps without caring which is
behind it: embed_one(text, input_type=...) and
embed_batch(texts, input_type=...).

input_type mapping: "document" -> passage_embed, "query" -> query_embed.
Be aware that for the default model these two fastembed methods are
plain aliases of embed() — BAAI/bge-small-en-v1.5 resolves to
OnnxTextEmbedding, which overrides neither (both are `yield from
self.embed(...)`), and fastembed 0.8.0 has no prefix machinery at all;
only multitask models (jina-v3 and friends) specialize them. So the
branch here is forward-compat structure, NOT a behavior difference
today. In particular BGE's query instruction ("Represent this sentence
for searching relevant passages:") is NOT applied — prepending it
manually to queries is an untried retrieval-quality lever to reach for
if the G1 eval gate comes in short.

512-token ceiling: this model's tokenizer truncates at 512 WordPiece
tokens ('longest_first', direction right), so anything past that is
silently dropped from the vector. Our chunker targets 512 *cl100k*
tokens and allows up to 1024 (chunking/builders/narrative_chunk.py),
and WordPiece runs hotter than cl100k on this corpus — spot-measured
1.05-1.35x on numeral-dense JLBC prose, because dollar figures and long
numerals fragment into many subword pieces. Long chunks therefore lose
their tails. Voyage-3-large had a 32K context and never truncated, so
this is a real behavioral delta: check it first if G1 recall misses.
"""
from __future__ import annotations

from typing import Any

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
# Expected dim for DEFAULT_LOCAL_MODEL. The real dim is resolved from
# fastembed's registry at construction time (see __init__); this constant
# is the documented expectation, not the source of truth.
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
        dim: int | None = None,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        if model is not None:
            # Injected fake (tests only): there's no registry entry to
            # resolve a dim from, so dim stays whatever the caller declared
            # — None when unstated.
            self._model = model
            self.dim = dim
            return

        # Lazy import: keeps `import retrieval` cheap and lets tests
        # run without fastembed's model download.
        from fastembed import TextEmbedding

        # Resolve dim from fastembed's model registry instead of trusting a
        # hardcoded default. Why: LocalEmbedder(model_name="BAAI/bge-base-en-v1.5")
        # would otherwise keep dim=384 while emitting 768-wide vectors, and the
        # corpus migration then dies ~7 minutes in with an unreadable pyarrow
        # list-size error. get_embedding_size reads bundled metadata only — no
        # download — so this stays cheap.
        resolved = TextEmbedding.get_embedding_size(model_name)
        if dim is not None and dim != resolved:
            # Validated BEFORE constructing the model so a caller's stale dim
            # fails instantly instead of after a multi-minute weight download.
            raise ValueError(
                f"dim={dim} was passed for model {model_name!r}, but that model "
                f"emits {resolved}-wide vectors. Drop the explicit dim (it is "
                f"resolved automatically) or fix the LanceDB schema to match."
            )
        self.dim = resolved
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
        writes, JSON responses) don't have to know about numpy.

        Note the 512-WordPiece-token truncation described in the module
        docstring — long chunks are embedded from their opening tokens only.
        """
        if not texts:
            return []
        if input_type == INPUT_TYPE_QUERY:
            it = self._model.query_embed(texts)
        else:
            it = self._model.passage_embed(texts)
        return [[float(x) for x in v] for v in it]
