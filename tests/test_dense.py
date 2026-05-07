"""Dense retrieval integration tests against the live ParadeDB stack.

Two tiers:
- Free integration tests — use a stub embedder that returns a real chunk's
  pre-computed embedding from the DB. These exercise the SQL + filtering
  paths end-to-end without spending Voyage API budget. The "chunk finds
  itself" property is the cheapest possible self-test.
- Live Voyage tests — gated on VOYAGE_API_KEY. Real query embedding,
  real semantic recall checks.

All tests skip cleanly without a loaded corpus.
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from db.connection import close_pool, get_connection
from db.embeddings import VoyageEmbedder
from retrieval.dense import dense_query
from retrieval.types import RetrievalFilters

MIN_CHUNKS_FOR_RETRIEVAL = 50


def _has_database() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


def _has_embedded_corpus() -> bool:
    """Stronger than _has_loaded_corpus: also requires embeddings populated."""
    if not _has_database():
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()
            return bool(row and row[0] >= MIN_CHUNKS_FOR_RETRIEVAL)
    except Exception:
        return False


needs_embedded_corpus = pytest.mark.skipif(
    not _has_embedded_corpus(),
    reason=(
        f"Fewer than {MIN_CHUNKS_FOR_RETRIEVAL} embedded chunks in DB. "
        "Run scripts/load_slice.py + scripts/embed_corpus.py first."
    ),
)
needs_voyage_key = pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="VOYAGE_API_KEY not set",
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Stub embedder — returns a precomputed vector without calling Voyage.
# ---------------------------------------------------------------------------


class _FixedVecEmbedder:
    """Returns the same vector regardless of input text. Used to exercise
    the dense_query SQL path without spending Voyage budget. Mimics the
    VoyageEmbedder.embed_one signature.
    """

    def __init__(self, vector: list[float]):
        self.vector = vector

    def embed_one(self, text: str, *, input_type: str = "query") -> list[float]:
        return list(self.vector)


def _fetch_one_embedded_chunk(conn) -> tuple[str, list[float]]:
    """Pull one chunk_id + its embedding from the DB. Used as the 'self-search' anchor."""
    row = conn.execute(
        "SELECT chunk_id, embedding FROM chunks "
        "WHERE embedding IS NOT NULL ORDER BY chunk_id LIMIT 1"
    ).fetchone()
    assert row is not None, "no embedded chunks in DB"
    # pgvector returns a numpy array; convert to plain list for psycopg roundtrip.
    return row["chunk_id"], list(row["embedding"])


# ---------------------------------------------------------------------------
# Edge cases (no DB hit)
# ---------------------------------------------------------------------------


def test_dense_empty_query_returns_empty_list():
    """Whitespace-only query short-circuits before embedding or SQL."""
    # Embedder isn't called because we return early.
    embedder = _FixedVecEmbedder([0.0] * 1024)
    assert dense_query("", embedder=embedder) == []
    assert dense_query("   ", embedder=embedder) == []


# ---------------------------------------------------------------------------
# Free integration tests — stub embedder, real DB.
# ---------------------------------------------------------------------------


@needs_embedded_corpus
def test_dense_chunk_finds_itself_at_top():
    """Use a chunk's own embedding as the 'query' vector — that chunk should
    rank #1 against the cosine similarity over its own corpus."""
    with get_connection() as conn:
        chunk_id, vec = _fetch_one_embedded_chunk(conn)

    results = dense_query(
        "any text — bypassed because embedder is stubbed",
        top_k=5,
        embedder=_FixedVecEmbedder(vec),
    )
    assert results
    assert results[0].chunk_id == chunk_id, (
        f"chunk's own embedding should rank itself #1; "
        f"got {[r.chunk_id for r in results[:3]]}"
    )
    # Similarity to self should be ~1.0 (cosine of identical vectors).
    assert results[0].score > 0.99


@needs_embedded_corpus
def test_dense_descending_score_order():
    with get_connection() as conn:
        _, vec = _fetch_one_embedded_chunk(conn)

    results = dense_query(
        "ignored", top_k=10, embedder=_FixedVecEmbedder(vec)
    )
    if len(results) < 2:
        pytest.skip("not enough results to verify ordering")
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@needs_embedded_corpus
def test_dense_filter_by_publisher():
    with get_connection() as conn:
        _, vec = _fetch_one_embedded_chunk(conn)

    results = dense_query(
        "ignored",
        top_k=10,
        filters=RetrievalFilters(publisher=["legislature"]),
        embedder=_FixedVecEmbedder(vec),
    )
    if not results:
        pytest.skip("no legislature chunks in current corpus state")
    assert all(r.publisher == "legislature" for r in results)


@needs_embedded_corpus
def test_dense_filter_by_fiscal_year():
    with get_connection() as conn:
        _, vec = _fetch_one_embedded_chunk(conn)

    results = dense_query(
        "ignored",
        top_k=10,
        filters=RetrievalFilters(fiscal_year=[2026]),
        embedder=_FixedVecEmbedder(vec),
    )
    if not results:
        pytest.skip("no FY2026 chunks in current corpus state")
    assert all(r.fiscal_year == 2026 for r in results)


@needs_embedded_corpus
def test_dense_filter_by_agency_uses_gin_overlap():
    with get_connection() as conn:
        _, vec = _fetch_one_embedded_chunk(conn)
        agency_row = conn.execute(
            "SELECT agency_canonical_ids[1] AS aid FROM chunks "
            "WHERE array_length(agency_canonical_ids, 1) > 0 LIMIT 1"
        ).fetchone()
    assert agency_row is not None
    test_agency = agency_row["aid"]

    results = dense_query(
        "ignored",
        top_k=10,
        filters=RetrievalFilters(agency_canonical_id=[test_agency]),
        embedder=_FixedVecEmbedder(vec),
    )
    if not results:
        pytest.skip(f"no chunks for agency={test_agency}")
    assert all(test_agency in r.agency_canonical_ids for r in results)


@needs_embedded_corpus
def test_dense_top_k_is_respected():
    with get_connection() as conn:
        _, vec = _fetch_one_embedded_chunk(conn)
    results = dense_query(
        "ignored", top_k=3, embedder=_FixedVecEmbedder(vec)
    )
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# Live Voyage tests — semantic recall checks.
# ---------------------------------------------------------------------------


@needs_embedded_corpus
@needs_voyage_key
def test_dense_live_paraphrase_recall():
    """Plan §WS5 Step 1: a query phrased differently from the chunk text
    should still surface a chunk stamped with ADC. Tests that the dense
    leg bridges paraphrase gaps that BM25 lexical search would miss."""
    embedder = VoyageEmbedder()
    results = dense_query(
        "how much money did the prison system receive",
        top_k=20,
        embedder=embedder,
    )
    assert results, "dense returned 0 hits for a real-shaped query"
    # At least ONE of the top-20 should be agency:adc-stamped.
    has_adc = any(
        "agency:adc" in r.agency_canonical_ids for r in results
    )
    assert has_adc, (
        "expected at least one ADC-stamped chunk in dense top-20 for "
        "'prison system' paraphrase; got "
        + ", ".join(f"{r.chunk_id}={r.agency_canonical_ids}" for r in results[:5])
    )
