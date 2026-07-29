"""Unit tests mock fastembed (no model download); one opt-in
integration test hits the real model."""
import numpy as np
import pytest

from retrieval.local_embedder import LocalEmbedder


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


def test_injected_fake_keeps_declared_dim():
    # The fake has no fastembed registry entry, so an explicit dim is the
    # only way to state one — and it must not be second-guessed.
    assert LocalEmbedder(model=FakeModel(), dim=2).dim == 2
    assert LocalEmbedder(model=FakeModel()).dim is None


def test_dim_mismatch_raises_before_any_download():
    # bge-base emits 768. Passing the small model's 384 must fail fast —
    # this test would take minutes if the guard ran after model construction.
    with pytest.raises(ValueError, match="768"):
        LocalEmbedder(model_name="BAAI/bge-base-en-v1.5", dim=384)


@pytest.mark.slow
def test_real_model_dim():
    emb = LocalEmbedder()
    vec = emb.embed_one("arizona state budget", input_type="query")
    assert len(vec) == emb.dim == 384
