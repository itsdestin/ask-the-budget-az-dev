"""Unit tests mock fastembed (no model download); one opt-in
integration test hits the real model."""
import numpy as np
import pytest

from retrieval.local_embedder import (
    DEFAULT_LOCAL_MODEL,
    LOCAL_EMBEDDING_DIM,
    QUERY_INSTRUCTION_PREFIXES,
    LocalEmbedder,
)

# Shared by BGE v1.5 and arctic-embed (verified against arctic-embed-m's
# config_sentence_transformers.json, which sets exactly this query prompt).
BGE_PREFIX = "Represent this sentence for searching relevant passages: "


class FakeModel:
    def __init__(self):
        self.calls = []

    def query_embed(self, texts):
        self.calls.append(("query", list(texts)))
        return iter([np.array([1.0, 0.0])])

    def passage_embed(self, texts):
        texts = list(texts)
        self.calls.append(("passage", texts))
        return iter([np.array([0.0, 1.0]) for _ in texts])


def test_embed_one_query_uses_query_path():
    fake = FakeModel()
    emb = LocalEmbedder(model=fake)
    vec = emb.embed_one("what is x", input_type="query")
    assert vec == [1.0, 0.0]
    assert fake.calls[0][0] == "query"


def test_embed_batch_documents_uses_passage_path():
    fake = FakeModel()
    emb = LocalEmbedder(model=fake)
    out = emb.embed_batch(["a", "b"], input_type="document")
    assert out == [[0.0, 1.0], [0.0, 1.0]]
    assert fake.calls[0] == ("passage", ["a", "b"])


def test_query_gets_bge_instruction_prefix_and_passages_do_not():
    # The asymmetry IS the point: BGE's card documents the instruction for
    # queries only, and prefixing passages would both hurt quality and
    # invalidate every vector already written to LanceDB.
    fake = FakeModel()
    emb = LocalEmbedder(model=fake, model_name=DEFAULT_LOCAL_MODEL)
    emb.embed_batch(["what is x"], input_type="query")
    emb.embed_batch(["a passage"], input_type="document")
    assert fake.calls == [
        ("query", [BGE_PREFIX + "what is x"]),
        ("passage", ["a passage"]),
    ]


def test_non_prefix_model_leaves_the_query_untouched():
    # Only models whose card documents an instruction are in the registry;
    # everyone else must pass through verbatim.
    fake = FakeModel()
    emb = LocalEmbedder(model=fake, model_name="sentence-transformers/all-MiniLM-L6-v2")
    assert emb.query_prefix == ""
    emb.embed_one("what is x", input_type="query")
    assert fake.calls == [("query", ["what is x"])]


def test_prefix_registry_entries_end_in_a_space():
    # The trailing space is part of the documented instruction — dropping it
    # glues the instruction onto the first query word.
    for name, prefix in QUERY_INSTRUCTION_PREFIXES.items():
        assert prefix.endswith(" "), name


def test_injected_fake_keeps_declared_dim():
    # The fake has no fastembed registry entry, so an explicit dim is the
    # only way to state one — and it must not be second-guessed.
    assert LocalEmbedder(model=FakeModel(), dim=2).dim == 2
    assert LocalEmbedder(model=FakeModel()).dim is None


def test_dim_mismatch_raises_before_any_download():
    # bge-small emits 384. Passing 768 (the current default's width) must
    # fail fast — this test would take minutes if the guard ran after model
    # construction.
    with pytest.raises(ValueError, match="384"):
        LocalEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=768)


def test_declared_dim_matches_the_store_default():
    # Pins the one drift that breaks retrieval silently at the seam: the
    # pipeline builds its store as a bare ChunkStore(), so if DEFAULT_DIM and
    # the default model's real width disagree, _check_dim refuses to open the
    # table the migration wrote — and the failure surfaces as "corpus is
    # empty," nowhere near the constant that caused it.
    from store.chunk_store import DEFAULT_DIM

    assert LOCAL_EMBEDDING_DIM == DEFAULT_DIM


@pytest.mark.slow
def test_real_model_dim():
    emb = LocalEmbedder()
    vec = emb.embed_one("arizona state budget", input_type="query")
    assert len(vec) == emb.dim == 768
