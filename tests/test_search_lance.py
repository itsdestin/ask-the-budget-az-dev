"""bm25_query_lance / dense_query_lance over a real tmp LanceDB.
Vectors are hand-made; no models involved."""
import pytest

from retrieval.search_lance import bm25_query_lance, dense_query_lance
from retrieval.types import RetrievalFilters
from store.chunk_store import ChunkStore


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(root=tmp_path, dim=4)
    s.upsert_chunks("budget_chunks", [
        dict(chunk_id="c1", doc_id="d1", text="ahcccs provider rates",
             section_path=["S"], page=1, bbox=None,
             source_anchor='{"page": 1}', agency_canonical_ids=["ahcccs"],
             fund_canonical_id=None, fund_mentions=[], fiscal_year=2026,
             doc_type="baseline-per-agency", is_table=False,
             table_html=None, token_count=5, publisher="jlbc",
             vector=[1, 0, 0, 0]),
        dict(chunk_id="c2", doc_id="d2", text="child safety caseworkers",
             section_path=[], page=2, bbox=[1, 2, 3, 4],
             source_anchor=None, agency_canonical_ids=["dcs"],
             fund_canonical_id=None, fund_mentions=["general-fund"],
             fiscal_year=2025, doc_type="afr", is_table=True,
             table_html="<table/>", token_count=7, publisher="agao",
             vector=[0, 1, 0, 0]),
    ])
    s.build_fts_index("budget_chunks")
    return s


def test_dense_returns_retrieved_chunks_with_decoded_anchor(store):
    hits = dense_query_lance(
        [1, 0, 0, 0], store=store, corpus="budget_chunks",
        top_k=1, filters=RetrievalFilters(),
    )
    c = hits[0]
    assert c.chunk_id == "c1"
    assert c.source_anchor == {"page": 1}       # JSON decoded
    assert c.publisher == "jlbc"


def test_bm25_respects_filters(store):
    hits = bm25_query_lance(
        "caseworkers OR ahcccs", store=store, corpus="budget_chunks",
        top_k=10, filters=RetrievalFilters(publisher=["agao"]),
    )
    assert [c.chunk_id for c in hits] == ["c2"]
    assert hits[0].is_table is True and hits[0].bbox == [1.0, 2.0, 3.0, 4.0]


def test_bm25_sanitizes_special_chars(store):
    # Apostrophes/specials crashed tantivy before (#47) — must not raise.
    hits = bm25_query_lance(
        "governor's office", store=store, corpus="budget_chunks",
        top_k=5, filters=RetrievalFilters(),
    )
    assert isinstance(hits, list)


def test_dense_missing_anchor_stays_none(store):
    """source_anchor is nullable in the table; the decoder must not choke on
    NULL (json.loads(None) raises TypeError)."""
    hits = dense_query_lance(
        [0, 1, 0, 0], store=store, corpus="budget_chunks",
        top_k=1, filters=RetrievalFilters(),
    )
    assert hits[0].chunk_id == "c2" and hits[0].source_anchor is None


def test_bm25_of_only_specials_returns_empty(store):
    """A query that sanitizes down to nothing must short-circuit rather than
    hand an empty string to the FTS parser."""
    assert bm25_query_lance(
        "?*[]", store=store, corpus="budget_chunks", top_k=5,
        filters=RetrievalFilters(),
    ) == []
