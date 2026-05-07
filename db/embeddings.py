"""Voyage embedding pipeline.

Phase 1b WS3, Tasks 3.1 + 3.2. Wraps the `voyageai.Client.embed` call
into one place and provides `embed_unembedded` to walk every chunk in
the database that doesn't yet have an embedding and populate it.

Voyage-3-large is the spec model — output dimension 1024, matching
`chunks.embedding vector(1024)` in 0001_initial_schema.sql. The SDK
returns Python lists of floats; pgvector's psycopg adapter accepts
those directly (no numpy conversion required).

`input_type` matters for retrieval quality: documents and queries get
embedded into the same vector space but Voyage internally re-projects
based on this hint. The chunk loader uses `input_type="document"`;
query-time retrieval (Phase 1b WS5+) uses `input_type="query"`.

Embedding is the only place in Phase 1b that costs real money.
Voyage-3-large pricing (2026): ~$0.18 per 1M document tokens, ~$0.06
per 1M query tokens. Slice corpus is ~30K-60K tokens (5 docs / 161
chunks); volume corpus targets ~1.8M tokens (~3000 chunks). One-time
cost for the slice: <$0.02. One-time cost for volume: ~$0.32.
`scripts/embed_corpus.py` prints an estimate before doing anything.
"""
from __future__ import annotations

import os
from typing import Any

import psycopg

# voyageai is imported lazily inside the embedder constructor so that
# `import db.embeddings` doesn't fail in environments where the SDK
# isn't installed (rare; covered by pyproject pinning) or doesn't yet
# have credentials (common during testing).

DEFAULT_MODEL = "voyage-3-large"
EMBEDDING_DIM = 1024  # MUST match the schema's vector(1024) column
DEFAULT_BATCH_SIZE = 64

# Allowed Voyage input_type values; the SDK doesn't pre-validate.
INPUT_TYPE_DOCUMENT = "document"
INPUT_TYPE_QUERY = "query"


class VoyageEmbedder:
    """Thin facade around `voyageai.Client.embed` so callers don't have
    to manage the client object directly. Holds one client per instance.

    Tests can pass a preconstructed mock client through the `client`
    parameter to avoid hitting the real API.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            import voyageai

            resolved_key = api_key or os.environ.get("VOYAGE_API_KEY")
            if not resolved_key:
                raise RuntimeError(
                    "VOYAGE_API_KEY not set. Either pass api_key=... or set the "
                    "env var (sign up at https://dash.voyageai.com/api-keys)."
                )
            self.client = voyageai.Client(api_key=resolved_key)
        self.model = model

    def embed_one(self, text: str, *, input_type: str = INPUT_TYPE_DOCUMENT) -> list[float]:
        """Single-text helper. Use embed_batch for >1 text — Voyage charges
        per call AND per token, but per-call overhead is real over WAN."""
        result = self.client.embed([text], model=self.model, input_type=input_type)
        embeddings = result.embeddings
        if not embeddings:
            raise RuntimeError(f"Voyage returned no embeddings for: {text[:80]!r}")
        return list(embeddings[0])

    def embed_batch(
        self,
        texts: list[str],
        *,
        input_type: str = INPUT_TYPE_DOCUMENT,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> list[list[float]]:
        """Embed many texts. Internally chunks into `batch_size`-sized
        Voyage requests; current Voyage limits are 1000 inputs / 320K
        tokens per call but smaller batches are friendlier to mid-run
        failures (a network blip resends fewer texts).
        """
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            result = self.client.embed(chunk, model=self.model, input_type=input_type)
            if len(result.embeddings) != len(chunk):
                raise RuntimeError(
                    f"Voyage returned {len(result.embeddings)} embeddings for batch of {len(chunk)} texts"
                )
            out.extend(list(v) for v in result.embeddings)
        return out


# ---------------------------------------------------------------------------
# DB-side: walk the chunks table, embed unembedded rows, persist.
# ---------------------------------------------------------------------------


def count_unembedded(conn: psycopg.Connection[Any]) -> int:
    """Return the number of chunks without an embedding."""
    row = conn.execute("SELECT COUNT(*)::INT AS n FROM chunks WHERE embedding IS NULL").fetchone()
    return int(row["n"]) if row else 0


def estimate_unembedded_tokens(conn: psycopg.Connection[Any]) -> int:
    """Sum token_count across unembedded chunks. Used for cost estimates."""
    row = conn.execute(
        "SELECT COALESCE(SUM(token_count), 0)::INT AS tokens FROM chunks WHERE embedding IS NULL"
    ).fetchone()
    return int(row["tokens"]) if row else 0


def embed_unembedded(
    conn: psycopg.Connection[Any],
    embedder: VoyageEmbedder,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Any = None,
) -> int:
    """Walk every chunk where `embedding IS NULL`, embed it via Voyage,
    and persist the result. Returns the number of chunks newly embedded.

    Idempotent: re-running picks up wherever the last call left off
    (because we filter on `embedding IS NULL`). Each batch is its own
    transaction by default — psycopg autocommits on the with-block exit
    in `db.connection.get_connection`.

    `progress` is an optional callable invoked as
    `progress(done, total, batch_size)` after each successful batch.
    Useful for the embed_corpus.py CLI to print a rolling line.
    """
    rows = conn.execute(
        "SELECT chunk_id, text FROM chunks WHERE embedding IS NULL ORDER BY chunk_id"
    ).fetchall()
    if not rows:
        return 0

    total = len(rows)
    embedded = 0

    for start in range(0, total, batch_size):
        batch = rows[start : start + batch_size]
        texts = [r["text"] for r in batch]
        ids = [r["chunk_id"] for r in batch]

        vectors = embedder.embed_batch(
            texts, input_type=INPUT_TYPE_DOCUMENT, batch_size=batch_size
        )
        for chunk_id, vector in zip(ids, vectors, strict=True):
            if len(vector) != EMBEDDING_DIM:
                raise RuntimeError(
                    f"Voyage returned dim={len(vector)} for chunk {chunk_id}; "
                    f"schema requires vector({EMBEDDING_DIM}). Wrong model?"
                )
            conn.execute(
                "UPDATE chunks SET embedding = %s WHERE chunk_id = %s",
                (vector, chunk_id),
            )

        embedded += len(batch)
        if progress is not None:
            progress(embedded, total, len(batch))

    return embedded


def reindex_hnsw(conn: psycopg.Connection[Any]) -> None:
    """Rebuild the HNSW index over chunks.embedding.

    pgvector docs recommend creating (or rebuilding) HNSW after data is
    loaded — index quality is materially better than incremental
    inserts. The migration creates the index unconditionally; rerunning
    REINDEX after a corpus-scale embed run is the official "make it
    fast" knob.
    """
    conn.execute("REINDEX INDEX chunks_embedding_hnsw")
