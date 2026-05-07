"""Shared SQL helpers for Phase 1b retrieval queries.

Both BM25 (WS4) and dense (WS5) helpers project the same row shape
back to the caller and accept the same filter set. The clause builder
here is the single source of truth for that mapping; `bm25.py` and
`dense.py` consume it.
"""
from __future__ import annotations

from typing import Any

from retrieval.types import RetrievalFilters

# All chunks columns we project, plus publisher from documents.
# Caller's SELECT prefix should match this list (the order matters because
# `RetrievedChunk.from_row` reads by name, but consistency aids debugging).
PROJECTION_COLUMNS = (
    "c.chunk_id",
    "c.doc_id",
    "c.text",
    "c.section_path",
    "c.page",
    "c.bbox",
    "c.source_anchor",
    "c.agency_canonical_ids",
    "c.fund_canonical_id",
    "c.fund_mentions",
    "c.fiscal_year",
    "c.doc_type",
    "c.is_table",
    "c.table_html",
    "c.token_count",
    "d.publisher",
)


def build_filter_clauses(
    filters: RetrievalFilters,
) -> tuple[list[str], list[Any], bool]:
    """Convert a RetrievalFilters into psycopg-parameterized WHERE clauses.

    Returns
    -------
    clauses : list[str]
        Each entry is one fragment to AND together (e.g. "c.fiscal_year = ANY(%s)").
        Caller assembles via " AND ".join(clauses).
    params : list[Any]
        Positional params, in the same order as the clauses.
    needs_documents_join : bool
        True when any filter requires the documents table (only `publisher`
        does today). Caller adds the JOIN unconditionally if it's already
        joining for the projection's `d.publisher` column.

    The agency filter uses the `&&` array-overlap operator (decision D2,
    backed by `chunks_agency_ids_gin`); fund_mentions uses the same pattern.
    All other list filters use `= ANY(%s)` against scalar columns.
    """
    clauses: list[str] = []
    params: list[Any] = []
    needs_doc_join = False

    if filters.fiscal_year:
        clauses.append("c.fiscal_year = ANY(%s)")
        params.append(list(filters.fiscal_year))
    if filters.doc_type:
        clauses.append("c.doc_type = ANY(%s)")
        params.append(list(filters.doc_type))
    if filters.publisher:
        needs_doc_join = True
        clauses.append("d.publisher = ANY(%s)")
        params.append(list(filters.publisher))
    if filters.agency_canonical_id:
        clauses.append("c.agency_canonical_ids && %s::text[]")
        params.append(list(filters.agency_canonical_id))
    if filters.fund_canonical_id:
        clauses.append("c.fund_canonical_id = ANY(%s)")
        params.append(list(filters.fund_canonical_id))
    if filters.fund_mentions:
        clauses.append("c.fund_mentions && %s::text[]")
        params.append(list(filters.fund_mentions))
    if filters.is_table is not None:
        clauses.append("c.is_table = %s")
        params.append(bool(filters.is_table))

    return clauses, params, needs_doc_join
