"""Local ONNX embedding facade (spec S4) — same shape as VoyageEmbedder
(db/embeddings.py) so retrieval code swaps without caring which is
behind it: embed_one(text, input_type=...) and
embed_batch(texts, input_type=...).

input_type mapping: "document" -> passage_embed, "query" -> query_embed.
Be aware that for the default model these two fastembed methods are
plain aliases of embed() — BAAI/bge-small-en-v1.5 resolves to
OnnxTextEmbedding, which overrides neither (both are `yield from
self.embed(...)`), and fastembed 0.8.0 has no prefix machinery at all;
only multitask models (jina-v3 and friends) specialize them. The
input_type branch therefore does NOT by itself change what the model
sees — QUERY_INSTRUCTION_PREFIXES is what makes it behavioral, by
prepending the model's documented query instruction ourselves.

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

# Per-model QUERY-side instruction prefix, keyed by fastembed model name.
#
# WHY: these models were trained asymmetrically — the query side carries a
# natural-language instruction, the passage side is embedded bare. fastembed
# 0.8.0 applies no prefix at all (query_embed IS embed for these models), so
# without this table our queries land off the manifold the model was tuned
# on. Measured on the 34-query eval corpus at Task 11: adding the BGE
# instruction moved the full-corpus dense rank of six known-hard chunks up
# 20-35% each (e.g. q-014 1360 -> 884, q-008 1621 -> 1115). Query-side ONLY —
# BGE's model card is explicit that passages must stay unprefixed, and
# prefixing them would also invalidate every vector already in LanceDB.
#
# Exact strings come from each model's card; do not paraphrase them (the
# trailing space is part of the instruction).
QUERY_INSTRUCTION_PREFIXES: dict[str, str] = {
    # BAAI BGE v1.5 English family — https://huggingface.co/BAAI/bge-small-en-v1.5
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
    # Snowflake arctic-embed reuses the same instruction (its model card sets
    # query_prefix to this string); listed explicitly so switching the
    # embedder to candidate #2 doesn't silently drop the prefix.
    "snowflake/snowflake-arctic-embed-xs": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-s": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-m": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-m-long": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-l": "Represent this sentence for searching relevant passages: ",
}


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
        # Resolved once here rather than looked up per call: embed_batch is on
        # the hot path for both the migration (7.7k chunks) and every query.
        self.query_prefix = QUERY_INSTRUCTION_PREFIXES.get(model_name, "")
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

        Query-side texts get this model's instruction prefix prepended (see
        QUERY_INSTRUCTION_PREFIXES); passages never do.
        """
        if not texts:
            return []
        if input_type == INPUT_TYPE_QUERY:
            if self.query_prefix:
                texts = [self.query_prefix + t for t in texts]
            it = self._model.query_embed(texts)
        else:
            it = self._model.passage_embed(texts)
        return [[float(x) for x in v] for v in it]
