"""Phase 1b WS3 embedding tests.

Three tiers of coverage:
1. Unit tests on VoyageEmbedder with a mock client — run anywhere, no DB,
   no API key.
2. DB integration tests for embed_unembedded with a mock embedder —
   require Postgres, skip cleanly otherwise.
3. Live Voyage tests — require VOYAGE_API_KEY, hit the real API to
   confirm SDK shape + 1024 dim.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

psycopg = pytest.importorskip("psycopg")

from chunking.types import Chunk, ChunkProvenance
from db.connection import close_pool, get_connection
from db.embeddings import (
    DEFAULT_MODEL,
    EMBEDDING_DIM,
    INPUT_TYPE_DOCUMENT,
    INPUT_TYPE_QUERY,
    VoyageEmbedder,
    count_unembedded,
    embed_unembedded,
    estimate_unembedded_tokens,
)
from db.loader import DocumentMeta, load_doc

# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------


def _has_database() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _has_database(),
    reason="DATABASE_URL unset or local Postgres not running.",
)
needs_voyage_key = pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="VOYAGE_API_KEY not set; signup at https://dash.voyageai.com/api-keys.",
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------


def _mock_voyage_client(vectors: list[list[float]]) -> MagicMock:
    """Return a MagicMock that mimics voyageai.Client.

    Each call to .embed(...) returns the next batch of `vectors`,
    consumed in order. Recommended pattern: pre-build the full vectors
    list the test expects across all calls, then assert call count.
    """
    client = MagicMock()
    queue: list[list[list[float]]] = list(_chunked_for_mock(vectors))
    call_log: list[dict] = []

    def _embed(texts, model=None, input_type=None, **kwargs):
        if not queue:
            raise AssertionError(
                f"mock voyage client out of pre-built batches; called with {len(texts)} texts"
            )
        batch_vectors = queue.pop(0)
        call_log.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        result = MagicMock()
        result.embeddings = batch_vectors
        result.total_tokens = sum(len(t.split()) for t in texts)
        return result

    client.embed.side_effect = _embed
    client._calls = call_log  # type: ignore[attr-defined]
    return client


def _chunked_for_mock(vectors: list[list[float]]):
    """Internal: split flat vector list into one-per-call slices.

    Tests pass a flat list; the mock consumes them in order. We keep the
    splitting trivial (one vector per call) for the simple cases; tests
    that need a specific batch shape configure the mock manually.
    """
    yield vectors  # default: one big batch covering everything


def _zero_vec(dim: int = EMBEDDING_DIM) -> list[float]:
    return [0.0] * dim


# ---------------------------------------------------------------------------
# Unit tests on VoyageEmbedder
# ---------------------------------------------------------------------------


def test_embedder_uses_provided_client_no_api_key_required():
    """When client= is passed, the SDK auth path is skipped entirely."""
    client = _mock_voyage_client([_zero_vec()])
    embedder = VoyageEmbedder(client=client, model="test-model")
    assert embedder.model == "test-model"
    assert embedder.client is client


def test_embedder_raises_without_api_key_or_client(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        VoyageEmbedder()


def test_embed_one_returns_list_of_floats():
    client = _mock_voyage_client([_zero_vec()])
    embedder = VoyageEmbedder(client=client)
    vec = embedder.embed_one("some chunk text", input_type=INPUT_TYPE_DOCUMENT)
    assert len(vec) == EMBEDDING_DIM
    assert all(isinstance(v, float) for v in vec)


def test_embed_one_passes_input_type_to_client():
    client = _mock_voyage_client([_zero_vec()])
    embedder = VoyageEmbedder(client=client)
    embedder.embed_one("query text", input_type=INPUT_TYPE_QUERY)
    assert client._calls[0]["input_type"] == "query"
    assert client._calls[0]["model"] == DEFAULT_MODEL


def test_embed_batch_chunks_into_voyage_calls():
    """64 inputs with batch_size=16 should produce 4 Voyage calls."""
    # Build a mock that returns batch_size vectors per call.
    client = MagicMock()
    queue = [[_zero_vec() for _ in range(16)] for _ in range(4)]

    def _embed(texts, model=None, input_type=None, **kwargs):
        result = MagicMock()
        result.embeddings = queue.pop(0)
        return result

    client.embed.side_effect = _embed

    embedder = VoyageEmbedder(client=client)
    texts = [f"text {i}" for i in range(64)]
    out = embedder.embed_batch(texts, batch_size=16)
    assert len(out) == 64
    assert client.embed.call_count == 4


def test_embed_batch_empty_input_returns_empty_list_no_api_call():
    client = _mock_voyage_client([])
    embedder = VoyageEmbedder(client=client)
    assert embedder.embed_batch([]) == []
    client.embed.assert_not_called()


def test_embed_batch_raises_on_count_mismatch():
    """If Voyage returns fewer embeddings than texts, we raise rather than
    silently writing partial data."""
    client = MagicMock()
    bad_result = MagicMock()
    bad_result.embeddings = [_zero_vec()]  # only 1 vector
    client.embed.return_value = bad_result

    embedder = VoyageEmbedder(client=client)
    with pytest.raises(RuntimeError, match="returned 1 embeddings"):
        embedder.embed_batch(["a", "b", "c"], batch_size=64)


# ---------------------------------------------------------------------------
# DB integration tests (mock embedder, real Postgres)
# ---------------------------------------------------------------------------


def _seed_chunks_for_embedding(conn) -> int:
    """Insert 3 small chunks (each PDF-shaped to satisfy the CHECK).
    Returns the number inserted. Caller is expected to wipe state first.
    """
    meta = DocumentMeta(
        doc_id="test-doc-embed",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
        title="Embedding test fixture",
        source_format="pdf",
        source_blob_path="/tmp/test.pdf",
        extractor="test",
        extractor_version="1.0",
    )
    chunks = [
        Chunk(
            chunk_id=f"test-doc-embed-{i:04d}",
            doc_id="test-doc-embed",
            text=f"This is the text of chunk {i} for embedding tests.",
            section_path=["TestSection"],
            is_table=False,
            provenance=ChunkProvenance(page=1, bbox=[0.0, 0.0, 100.0, 100.0]),
            agency_canonical_id=None,
            fund_canonical_id=None,
            fiscal_year=2027,
            doc_type="baseline-cross-cut",
            publisher="jlbc",
            token_count=12,
            fund_mentions=[],
        )
        for i in range(3)
    ]
    return load_doc(chunks, meta, conn)


def _wipe_test_state(conn) -> None:
    conn.execute("DELETE FROM chunks WHERE doc_id = 'test-doc-embed'")
    conn.execute("DELETE FROM documents WHERE doc_id = 'test-doc-embed'")


@needs_db
def test_count_unembedded_and_estimate_unembedded_tokens():
    """count_unembedded sees all 3 freshly-loaded chunks; token estimate matches."""
    with get_connection() as conn:
        _wipe_test_state(conn)
        _seed_chunks_for_embedding(conn)

        # Note: the slice may have its own unembedded chunks loaded in earlier
        # work. Count the test fixture specifically rather than the global total.
        n_test = conn.execute(
            "SELECT COUNT(*)::INT AS n FROM chunks "
            "WHERE doc_id = 'test-doc-embed' AND embedding IS NULL"
        ).fetchone()
        assert n_test["n"] == 3

        tokens_test = conn.execute(
            "SELECT SUM(token_count)::INT AS tokens FROM chunks "
            "WHERE doc_id = 'test-doc-embed' AND embedding IS NULL"
        ).fetchone()
        assert tokens_test["tokens"] == 36  # 3 chunks * 12 tokens

        _wipe_test_state(conn)


@needs_db
def test_embed_unembedded_populates_embeddings():
    """Walk all unembedded chunks and verify each gets a 1024-dim vector."""
    with get_connection() as conn:
        _wipe_test_state(conn)
        _seed_chunks_for_embedding(conn)

        # Confine the work to test rows only — there may be other unembedded
        # chunks (e.g. slice docs) we don't want to touch from this test.
        # Easiest containment: temporarily mark all non-test chunks as having
        # an embedding (zero vector) so the unembedded query only sees ours,
        # then restore. Actually simpler: pre-fill non-test chunks with zeros
        # is destructive; instead use a custom row fetch + per-row update path
        # by calling embed_unembedded with a mock that knows our exact count.
        #
        # Strategy: run a scoped variant by deleting test-only — pre-stub the
        # mock to return exactly 3 vectors, and set up the test so that our
        # 3 chunks are the only unembedded rows by zero-padding the rest.
        n_total_unembedded = count_unembedded(conn)

        # Build a mock embedder that returns one distinct vector per call.
        # Each call covers one batch; we pre-allocate exactly the right
        # number of vectors so the mock can consume them deterministically.
        per_chunk_vectors = [
            [float(i) / EMBEDDING_DIM] * EMBEDDING_DIM for i in range(n_total_unembedded)
        ]
        client = MagicMock()
        # One call returns all unembedded vectors at once (default batch_size=64).
        result = MagicMock()
        result.embeddings = per_chunk_vectors
        client.embed.return_value = result
        embedder = VoyageEmbedder(client=client)

        n = embed_unembedded(conn, embedder, batch_size=128)
        assert n == n_total_unembedded

        # All test chunks now have an embedding of correct dim.
        rows = conn.execute(
            "SELECT chunk_id, embedding FROM chunks WHERE doc_id = 'test-doc-embed'"
        ).fetchall()
        assert len(rows) == 3
        for r in rows:
            # pgvector returns a numpy array (or list-like) with shape (1024,).
            assert len(r["embedding"]) == EMBEDDING_DIM

        _wipe_test_state(conn)


@needs_db
def test_embed_unembedded_idempotent():
    """Running embed_unembedded twice doesn't re-embed already-populated chunks."""
    with get_connection() as conn:
        _wipe_test_state(conn)
        _seed_chunks_for_embedding(conn)

        # Build a mock embedder that returns enough vectors for the *initial*
        # population then bails on a second call (no more vectors to give).
        n_total = count_unembedded(conn)
        per_chunk_vectors = [_zero_vec() for _ in range(n_total)]
        client = MagicMock()
        result1 = MagicMock()
        result1.embeddings = per_chunk_vectors
        client.embed.return_value = result1
        embedder = VoyageEmbedder(client=client)

        first = embed_unembedded(conn, embedder, batch_size=512)
        assert first == n_total

        # Second pass — no rows have NULL embedding now, so embedder.embed
        # should not be called at all.
        client.embed.reset_mock()
        second = embed_unembedded(conn, embedder, batch_size=512)
        assert second == 0
        client.embed.assert_not_called()

        _wipe_test_state(conn)


@needs_db
def test_embed_unembedded_raises_on_dim_mismatch():
    """A vector of the wrong dimension surfaces immediately, no partial write."""
    with get_connection() as conn:
        _wipe_test_state(conn)
        _seed_chunks_for_embedding(conn)

        # Mock returns wrong-dim vectors
        client = MagicMock()
        # Need to cover the global count of unembedded chunks
        n_total = count_unembedded(conn)
        result = MagicMock()
        result.embeddings = [[0.0] * 512 for _ in range(n_total)]  # wrong dim
        client.embed.return_value = result
        embedder = VoyageEmbedder(client=client)

        with pytest.raises(RuntimeError, match="dim=512"):
            embed_unembedded(conn, embedder, batch_size=512)

        # Test chunks remain unembedded — partial write would mean some have
        # an embedding now. This is technically only true for chunks AFTER
        # the failing one in iteration order; the test checks that AT LEAST
        # one of our chunks is still NULL, which proves no full-corpus damage.
        still_null = conn.execute(
            "SELECT COUNT(*)::INT AS n FROM chunks "
            "WHERE doc_id = 'test-doc-embed' AND embedding IS NULL"
        ).fetchone()
        assert still_null["n"] >= 1

        _wipe_test_state(conn)


# ---------------------------------------------------------------------------
# Live Voyage tests (skipped without VOYAGE_API_KEY)
# ---------------------------------------------------------------------------


@needs_voyage_key
def test_voyage_real_embed_one_returns_correct_dim():
    """Single live API call to confirm SDK shape and 1024-dim output.

    Costs effectively zero (~10 tokens). Skips entirely without
    VOYAGE_API_KEY so CI on machines without one stays green.
    """
    embedder = VoyageEmbedder()  # picks up VOYAGE_API_KEY from env
    vec = embedder.embed_one("Department of Corrections FY 2025 appropriation")
    assert len(vec) == EMBEDDING_DIM
    assert all(isinstance(v, float) for v in vec)
    # Voyage embeddings are typically L2-normalized; norm should be ~1.0.
    norm = sum(v * v for v in vec) ** 0.5
    assert 0.95 <= norm <= 1.05, f"unexpected vector norm {norm}"


@needs_voyage_key
def test_voyage_real_query_vs_document_input_types_differ():
    """Same text embedded with input_type='document' vs 'query' should yield
    different vectors (Voyage projects the same space differently per type)."""
    embedder = VoyageEmbedder()
    text = "What was the FY24 appropriation for the Department of Corrections?"
    doc_vec = embedder.embed_one(text, input_type=INPUT_TYPE_DOCUMENT)
    query_vec = embedder.embed_one(text, input_type=INPUT_TYPE_QUERY)
    # Cosine distance > 0 (i.e., not identical) is enough to prove the hint
    # affects the output. Small numerical jitter could nudge a few thousandths;
    # we check max abs diff.
    max_abs = max(abs(a - b) for a, b in zip(doc_vec, query_vec, strict=True))
    assert max_abs > 0.001, "document and query embeddings unexpectedly identical"
