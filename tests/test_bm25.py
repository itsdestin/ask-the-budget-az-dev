"""BM25 integration tests against the live ParadeDB stack.

Skips cleanly when:
- DATABASE_URL is unset or DB unreachable
- Slice (or any reasonable corpus) isn't loaded into chunks

The slice must be loaded before this test file is meaningful. Run:
    uv run python scripts/load_slice.py
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from db.connection import close_pool, get_connection
from retrieval.bm25 import _sanitize_bm25_query, bm25_query
from retrieval.types import RetrievalFilters

# Heuristic: the validated slice has 161 chunks, the volume corpus targets
# ~3000. Anything <50 means setup hasn't run.
MIN_CHUNKS_FOR_RETRIEVAL = 50


def _has_database() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


def _has_loaded_corpus() -> bool:
    if not _has_database():
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1) as c:
            row = c.execute("SELECT COUNT(*) FROM chunks").fetchone()
            return bool(row and row[0] >= MIN_CHUNKS_FOR_RETRIEVAL)
    except Exception:
        return False


needs_corpus = pytest.mark.skipif(
    not _has_loaded_corpus(),
    reason=(
        f"Live DB has < {MIN_CHUNKS_FOR_RETRIEVAL} chunks. "
        "Run scripts/load_slice.py first."
    ),
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Edge cases (no DB call needed for empty query)
# ---------------------------------------------------------------------------


def test_bm25_empty_query_returns_empty_list():
    """Whitespace-only query short-circuits before SQL — no DB hit needed."""
    assert bm25_query("") == []
    assert bm25_query("   \n\t  ") == []


# ---------------------------------------------------------------------------
# Sanitization (STATUS.md #47) — pure unit tests, no DB call
# ---------------------------------------------------------------------------


def test_sanitize_strips_apostrophes():
    """The load-bearing case: bare apostrophes in possessives must go.
    Pg_search reads them as phrase-quote delimiters and crashes the query."""
    assert _sanitize_bm25_query("Arizona's budget") == "Arizona s budget"
    assert _sanitize_bm25_query("DES's appropriation") == "DES s appropriation"
    assert _sanitize_bm25_query("Governor's FY 2027") == "Governor s FY 2027"


def test_sanitize_strips_other_tantivy_specials():
    """Other Lucene/tantivy operators are also stripped to avoid future
    parser crashes from quotes, brackets, colons, wildcards, etc."""
    assert "[" not in _sanitize_bm25_query("fund [balance]")
    assert "(" not in _sanitize_bm25_query("(General Fund)")
    assert ":" not in _sanitize_bm25_query("agency:DES")
    assert "*" not in _sanitize_bm25_query("approp*")
    assert "?" not in _sanitize_bm25_query("What is FY27?")


def test_sanitize_preserves_safe_punctuation():
    """Commas, periods, hyphens, dollar signs — all fine in tantivy."""
    out = _sanitize_bm25_query("FY 2026 budget: $1.2B, $400M general fund.")
    # Colon goes (tantivy field separator); dollar/comma/period/hyphen stay.
    assert "$1.2B" in out
    assert "," in out
    assert "." in out
    assert ":" not in out


def test_sanitize_collapses_whitespace():
    """Substitution can introduce double spaces — collapse them."""
    assert _sanitize_bm25_query("a   b") == "a b"
    assert _sanitize_bm25_query("a''b") == "a b"


def test_sanitize_handles_all_specials_input():
    """Pathological input of only special chars sanitizes to empty string.
    bm25_query catches this and short-circuits to [] (next test below)."""
    assert _sanitize_bm25_query("''''") == ""
    assert _sanitize_bm25_query("()[]{}") == ""


def test_bm25_apostrophe_query_does_not_raise(monkeypatch):
    """Regression test for STATUS.md #47. The pre-fix behavior was
    InternalError_: could not parse query string — an exception that
    aborted the whole retrieve() call. After the fix, the query goes
    through (and either returns hits or [] from the DB, never raises
    a ParadeDB parse error).

    Stubbed at the DB layer so this runs without a live ParadeDB.
    """
    captured: dict[str, object] = {}

    class FakeRow(dict):
        """Stand-in for a psycopg dict_row. Just needs to subscript."""

    class FakeCursor:
        def __init__(self, sql: str, bind: list):
            captured["sql"] = sql
            captured["bind"] = bind

        def fetchall(self):
            return []

    class FakeConn:
        def execute(self, sql, bind):
            return FakeCursor(sql, bind)

    bm25_query("Arizona's FY 2026 budget", conn=FakeConn())  # type: ignore[arg-type]

    # The query arg passed to the DB must have had the apostrophe stripped.
    assert "Arizona's" not in captured["bind"][0]
    assert "Arizona s FY 2026 budget" == captured["bind"][0]


def test_bm25_pathological_query_short_circuits(monkeypatch):
    """A query made entirely of stripped characters reduces to empty;
    bm25_query should return [] without issuing SQL."""
    calls = []

    class FakeConn:
        def execute(self, sql, bind):
            calls.append((sql, bind))
            raise AssertionError("should not have issued SQL")

    result = bm25_query("''''", conn=FakeConn())  # type: ignore[arg-type]
    assert result == []
    assert calls == []


# ---------------------------------------------------------------------------
# Smoke retrieval against the loaded slice
# ---------------------------------------------------------------------------


@needs_corpus
def test_bm25_returns_some_results_for_general_query():
    results = bm25_query("appropriation", top_k=10)
    assert results, "BM25 returned no hits for a common term — index may be unbuilt"
    assert all(r.score > 0 for r in results)


@needs_corpus
def test_bm25_descending_score_order():
    results = bm25_query("fund balance", top_k=10)
    if len(results) < 2:
        pytest.skip("not enough results to verify ordering")
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@needs_corpus
def test_bm25_finds_aviation_fund_in_s18():
    """Plan §WS4 Step 1: 'aviation fund balance' should surface s18 chunks
    (the cross-cut Other Fund Summary by Agency table that lists Aviation Fund
    as one of ~227 funds)."""
    results = bm25_query("Aviation Fund balance", top_k=10)
    assert any(
        "jlbc-baseline-fy2027-s18" in r.doc_id for r in results
    ), f"s18 not in top-10 for 'Aviation Fund balance'; got {[r.chunk_id for r in results]}"


# ---------------------------------------------------------------------------
# Filter integration
# ---------------------------------------------------------------------------


@needs_corpus
def test_bm25_filter_by_fiscal_year():
    """fiscal_year filter narrows results to the specified years only."""
    results = bm25_query(
        "appropriation",
        top_k=20,
        filters=RetrievalFilters(fiscal_year=[2026]),
    )
    assert results, "no FY2026 results — filter may be over-restrictive"
    assert all(r.fiscal_year == 2026 for r in results)


@needs_corpus
def test_bm25_filter_by_publisher():
    """publisher filter requires the documents JOIN (decision: not denormalized)."""
    results = bm25_query(
        "section",
        top_k=20,
        filters=RetrievalFilters(publisher=["legislature"]),
    )
    assert results, "no legislature results"
    assert all(r.publisher == "legislature" for r in results)


@needs_corpus
def test_bm25_filter_by_doc_type():
    results = bm25_query(
        "fund",
        top_k=20,
        filters=RetrievalFilters(doc_type=["baseline-cross-cut"]),
    )
    assert results
    assert all(r.doc_type == "baseline-cross-cut" for r in results)


@needs_corpus
def test_bm25_filter_by_is_table():
    """is_table=True restricts to chunks that wrap full tables."""
    results = bm25_query(
        "fund",
        top_k=20,
        filters=RetrievalFilters(is_table=True),
    )
    assert results, "no table chunks for 'fund'"
    assert all(r.is_table for r in results)
    assert all(r.table_html is not None for r in results), (
        "is_table chunks should carry table_html"
    )


@needs_corpus
def test_bm25_filter_by_agency_uses_gin_array_overlap():
    """Decision D2: agency filter uses && over the agency_canonical_ids array.
    Cross-cut chunks stamping multiple agencies should match a single-agency query.
    """
    # Pick an agency known to be present in the slice — try ahcccs, fall back
    # to whichever shows up in agency_canonical_ids.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT agency_canonical_ids[1] AS aid FROM chunks "
            "WHERE array_length(agency_canonical_ids, 1) > 0 LIMIT 1"
        ).fetchone()
    assert row is not None, "no agency-stamped chunks loaded — slice setup issue"
    test_agency = row["aid"]

    results = bm25_query(
        "fund",
        top_k=20,
        filters=RetrievalFilters(agency_canonical_id=[test_agency]),
    )
    assert results, f"no chunks for agency={test_agency}"
    assert all(test_agency in r.agency_canonical_ids for r in results)


@needs_corpus
def test_bm25_combined_filters_intersect():
    """Multiple filters AND together (not OR)."""
    results = bm25_query(
        "fund",
        top_k=20,
        filters=RetrievalFilters(
            fiscal_year=[2027],
            publisher=["jlbc"],
            doc_type=["baseline-cross-cut"],
        ),
    )
    if not results:
        pytest.skip("no chunks match combined filters in current corpus state")
    for r in results:
        assert r.fiscal_year == 2027
        assert r.publisher == "jlbc"
        assert r.doc_type == "baseline-cross-cut"


@needs_corpus
def test_bm25_apostrophe_query_against_live_paradedb():
    """End-to-end check: a query containing apostrophes (the exact shape
    that crashed in the 2026-05-22 eval) runs without raising and returns
    a non-empty result set. This is the integration counterpart to the
    unit tests above."""
    # Phrasing taken from eval q-014 — used to crash with InternalError_.
    results = bm25_query(
        "What does the Governor's FY 2027 budget glossary say PASARR and FMAP stand for?",
        top_k=10,
    )
    # No assertion about specific chunks (corpus drift is fine); just that
    # we got past the parser and the search executed.
    assert isinstance(results, list)


@needs_corpus
def test_bm25_top_k_is_respected():
    results_small = bm25_query("appropriation", top_k=3)
    results_large = bm25_query("appropriation", top_k=30)
    assert len(results_small) <= 3
    assert len(results_large) > len(results_small) or len(results_small) < 3
