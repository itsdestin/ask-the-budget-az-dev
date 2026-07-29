"""bm25_query_lance / dense_query_lance over a real tmp LanceDB.
Vectors are hand-made; no models involved."""
import pytest

from retrieval.search_lance import (
    _sanitize,
    _where,
    bm25_query_lance,
    dense_query_lance,
    row_to_chunk,
)
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
    # NOTE: on Lance this passes even without _sanitize (apostrophes are
    # harmless there); test_bm25_quoted_phrase_does_not_crash below is the
    # one that actually pins the sanitizer. Kept because it is spec'd.
    hits = bm25_query_lance(
        "governor's office", store=store, corpus="budget_chunks",
        top_k=5, filters=RetrievalFilters(),
    )
    assert isinstance(hits, list)


def test_bm25_quoted_phrase_does_not_crash(store):
    """THE reason _sanitize exists on Lance. Without it this raises
    `RuntimeError: position is not found but required for phrase queries`
    — an all-quoted query parses as a phrase query, and build_fts_index
    creates the index without token positions. An LLM caller emits quoted
    phrases constantly, so this is the common path, not an edge case."""
    hits = bm25_query_lance('"ahcccs provider rates"', store=store,
                            corpus="budget_chunks", top_k=5,
                            filters=RetrievalFilters())
    assert [c.chunk_id for c in hits] == ["c1"]


def test_sanitize_strips_the_bm25_char_set():
    """Pins the exact char set, so a future edit cannot silently narrow it.
    Apostrophes still go (kept identical to bm25.py's #47 set for cutover
    comparability), while `+ - !` deliberately survive for tokens like
    "$1.2M+" and "FY2026-27"."""
    assert _sanitize("governor's office") == "governor s office"
    assert _sanitize('"provider rates"') == "provider rates"
    assert _sanitize("$1.2M+ FY2026-27 !x") == "$1.2M+ FY2026-27 !x"
    assert _sanitize("a(b)c[d]e{f}g^h~i:j/k?l*m") == "a b c d e f g h i j k l m"
    assert _sanitize("   ") == ""


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


def test_dense_respects_filters(store):
    """Filtering the dense leg goes through a different LanceDB code path
    (prefiltered ANN vs prefiltered FTS) even though _where is shared, so
    it needs its own coverage. The query vector points AT c1; the filter
    must still exclude it."""
    hits = dense_query_lance(
        [1, 0, 0, 0], store=store, corpus="budget_chunks",
        top_k=10, filters=RetrievalFilters(fiscal_year=[2025], is_table=True),
    )
    assert [c.chunk_id for c in hits] == ["c2"]


def test_empty_filters_produce_no_where_clause(store):
    """An unfiltered query must pass where=None, not a vacuous 'TRUE'-ish
    expression — filter_expr returns None for no filters and the search
    methods branch on falsiness."""
    assert _where(store, RetrievalFilters()) is None
    assert _where(store, RetrievalFilters(publisher=["agao"])) == \
        "publisher IN ('agao')"


def test_malformed_source_anchor_names_the_chunk():
    """A bare JSONDecodeError ("Expecting value: line 1 column 1") cannot be
    traced to a row among ~100k chunks; the error must name the chunk and
    the fix."""
    row = dict(
        chunk_id="c9", doc_id="d9", text="t", section_path=[], page=None,
        bbox=None, source_anchor="{'page': 1}",  # str() of a dict, not JSON
        agency_canonical_ids=[], fund_canonical_id=None, fund_mentions=[],
        fiscal_year=None, doc_type="afr", is_table=False, table_html=None,
        token_count=1, publisher="jlbc",
    )
    with pytest.raises(ValueError, match=r"chunk 'c9' has a malformed source_anchor"):
        row_to_chunk(row, 1.0)
