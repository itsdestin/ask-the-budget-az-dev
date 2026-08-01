"""Pure unit tests for retrieval/types.py.

RetrievalFilters.is_empty and the RetrievedChunk row adapter — both
still live on the LanceDB path (search_lance.py builds RetrievedChunk
from Lance result dicts, which carry the same column names the old
psycopg rows did, which is why the adapter survived the store swap).

The build_filter_clauses half of this file went with retrieval/sql.py
in Plan 5 Track 4; ChunkStore.filter_expr is its LanceDB successor.
"""
from __future__ import annotations

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
