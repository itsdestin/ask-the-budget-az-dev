"""Pure unit tests for retrieval/sql.py + retrieval/types.py.

No database required. Verifies the filter-clause builder emits the
right SQL fragments + parameter shapes, and the RetrievedChunk
dataclass round-trips correctly from a psycopg dict-row.
"""
from __future__ import annotations

from retrieval.sql import build_filter_clauses
from retrieval.types import RetrievalFilters, RetrievedChunk


# ---------------------------------------------------------------------------
# RetrievalFilters.is_empty
# ---------------------------------------------------------------------------


def test_filters_is_empty_default():
    assert RetrievalFilters().is_empty()


def test_filters_is_empty_only_if_all_unset():
    assert not RetrievalFilters(fiscal_year=[2026]).is_empty()
    assert not RetrievalFilters(publisher=["jlbc"]).is_empty()
    assert not RetrievalFilters(is_table=True).is_empty()
    assert not RetrievalFilters(is_table=False).is_empty()  # False is a real filter, not "no filter"


# ---------------------------------------------------------------------------
# build_filter_clauses
# ---------------------------------------------------------------------------


def test_empty_filters_emit_nothing():
    clauses, params, needs_join = build_filter_clauses(RetrievalFilters())
    assert clauses == []
    assert params == []
    assert needs_join is False


def test_fiscal_year_filter():
    clauses, params, needs_join = build_filter_clauses(
        RetrievalFilters(fiscal_year=[2026, 2027])
    )
    assert clauses == ["c.fiscal_year = ANY(%s)"]
    assert params == [[2026, 2027]]
    assert needs_join is False


def test_publisher_filter_requires_documents_join():
    clauses, params, needs_join = build_filter_clauses(
        RetrievalFilters(publisher=["jlbc", "legislature"])
    )
    assert clauses == ["d.publisher = ANY(%s)"]
    assert params == [["jlbc", "legislature"]]
    assert needs_join is True


def test_agency_filter_uses_array_overlap():
    """Decision D2: agency filter is && over agency_canonical_ids[], not ANY()."""
    clauses, params, _ = build_filter_clauses(
        RetrievalFilters(agency_canonical_id=["agency:adc", "agency:ahcccs"])
    )
    assert clauses == ["c.agency_canonical_ids && %s::text[]"]
    assert params == [["agency:adc", "agency:ahcccs"]]


def test_fund_canonical_id_filter_uses_any():
    """fund_canonical_id is scalar on chunks, so ANY() not && ."""
    clauses, params, _ = build_filter_clauses(
        RetrievalFilters(fund_canonical_id=["fund:ahcccs"])
    )
    assert clauses == ["c.fund_canonical_id = ANY(%s)"]
    assert params == [["fund:ahcccs"]]


def test_fund_mentions_filter_uses_array_overlap():
    """fund_mentions is array, parallel to agency_canonical_ids."""
    clauses, params, _ = build_filter_clauses(
        RetrievalFilters(fund_mentions=["fund:general"])
    )
    assert clauses == ["c.fund_mentions && %s::text[]"]
    assert params == [["fund:general"]]


def test_is_table_filter_passes_bool():
    clauses, params, _ = build_filter_clauses(RetrievalFilters(is_table=True))
    assert clauses == ["c.is_table = %s"]
    assert params == [True]


def test_combined_filters_compose():
    clauses, params, needs_join = build_filter_clauses(
        RetrievalFilters(
            fiscal_year=[2027],
            publisher=["jlbc"],
            agency_canonical_id=["agency:adc"],
            is_table=False,
        )
    )
    # Order matches the field order in build_filter_clauses
    assert clauses == [
        "c.fiscal_year = ANY(%s)",
        "d.publisher = ANY(%s)",
        "c.agency_canonical_ids && %s::text[]",
        "c.is_table = %s",
    ]
    assert params == [[2027], ["jlbc"], ["agency:adc"], False]
    assert needs_join is True


# ---------------------------------------------------------------------------
# RetrievedChunk.from_row
# ---------------------------------------------------------------------------


def _row(**overrides):
    """Build a complete dict_row from chunks + documents JOIN."""
    base = {
        "chunk_id": "jlbc-baseline-fy2027-s18-0001",
        "doc_id": "jlbc-baseline-fy2027-s18",
        "text": "Department of Corrections General Fund: $1.74B",
        "section_path": ["Department of Corrections", "Operating Lump Sum"],
        "page": 3,
        "bbox": [72.0, 100.0, 540.0, 200.0],
        "source_anchor": None,
        "agency_canonical_ids": ["agency:adc"],
        "fund_canonical_id": "fund:general",
        "fund_mentions": ["fund:general"],
        "fiscal_year": 2027,
        "doc_type": "baseline-cross-cut",
        "is_table": False,
        "table_html": None,
        "token_count": 42,
        "publisher": "jlbc",
    }
    base.update(overrides)
    return base


def test_from_row_pdf_chunk():
    chunk = RetrievedChunk.from_row(_row(), score=12.5)
    assert chunk.chunk_id == "jlbc-baseline-fy2027-s18-0001"
    assert chunk.doc_id == "jlbc-baseline-fy2027-s18"
    assert chunk.score == 12.5
    assert chunk.page == 3
    assert chunk.bbox == [72.0, 100.0, 540.0, 200.0]
    assert chunk.source_anchor is None
    assert chunk.agency_canonical_ids == ["agency:adc"]
    assert chunk.fund_canonical_id == "fund:general"
    assert chunk.publisher == "jlbc"
    assert chunk.is_table is False


def test_from_row_docx_chunk_uses_source_anchor():
    chunk = RetrievedChunk.from_row(
        _row(
            page=None,
            bbox=None,
            source_anchor={"paragraph_id": "p47", "table_cell_id": "tbl3.r5.c2"},
            doc_type="budget-bill",
            publisher="legislature",
        ),
        score=8.1,
    )
    assert chunk.page is None
    assert chunk.bbox is None
    assert chunk.source_anchor == {"paragraph_id": "p47", "table_cell_id": "tbl3.r5.c2"}
    assert chunk.publisher == "legislature"


def test_from_row_handles_null_arrays_as_empty_lists():
    """Postgres TEXT[] with no entries can come back as None or []; either becomes []."""
    chunk = RetrievedChunk.from_row(
        _row(agency_canonical_ids=None, fund_mentions=None, section_path=None),
        score=1.0,
    )
    assert chunk.agency_canonical_ids == []
    assert chunk.fund_mentions == []
    assert chunk.section_path == []


def test_from_row_score_coerced_to_float():
    """psycopg may return Decimal for paradedb.score; the dataclass holds float."""
    from decimal import Decimal

    chunk = RetrievedChunk.from_row(_row(), score=Decimal("4.7"))
    assert chunk.score == 4.7
    assert isinstance(chunk.score, float)


def test_from_row_table_chunk_carries_table_html():
    chunk = RetrievedChunk.from_row(
        _row(
            is_table=True,
            table_html="<table><tr><td>X</td></tr></table>",
        ),
        score=10.0,
    )
    assert chunk.is_table is True
    assert chunk.table_html == "<table><tr><td>X</td></tr></table>"
