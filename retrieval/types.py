"""Shared dataclasses for Phase 1b retrieval (WS4 BM25, WS5 dense, WS6 hybrid).

Kept minimal so the dependency graph stays one-way: types is imported
by sql, bm25, dense; nothing here imports retrieval submodules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalFilters:
    """Optional filters narrowing a retrieval to a slice of the corpus.

    Every field is None / empty by default = "no filter on this dimension".
    Lists are AND-of-OR semantics: e.g. fiscal_year=[2026, 2027] AND
    publisher=['jlbc'] returns chunks where (fy=2026 OR fy=2027) AND
    publisher='jlbc'. Match the spec §11 retrieval contract.

    Agency filter uses array-overlap on chunks.agency_canonical_ids
    (decision D2). All other list filters use ANY() against scalar
    columns.
    """

    fiscal_year: list[int] | None = None
    doc_type: list[str] | None = None
    publisher: list[str] | None = None  # JOIN to documents
    agency_canonical_id: list[str] | None = None
    fund_canonical_id: list[str] | None = None
    fund_mentions: list[str] | None = None
    is_table: bool | None = None

    def is_empty(self) -> bool:
        """True when no filter is set. Skips the JOIN/WHERE assembly."""
        return (
            not self.fiscal_year
            and not self.doc_type
            and not self.publisher
            and not self.agency_canonical_id
            and not self.fund_canonical_id
            and not self.fund_mentions
            and self.is_table is None
        )


@dataclass(frozen=True)
class RetrievedChunk:
    """One row returned by a retrieval helper.

    Score semantics depend on the producer:
    - BM25: ParadeDB BM25 score (positive, unbounded; higher = better)
    - Dense: cosine similarity (1 - cosine distance), 0..1 range
    - Reranker: raw local cross-encoder logit (roughly -10..10, NOT 0..1)

    Downstream RRF (WS6) compares ranks across retrievers, not raw scores,
    so the score field is only used by the producer's own consumers
    (logging, debugging, threshold checks).
    """

    chunk_id: str
    doc_id: str
    text: str
    score: float
    section_path: list[str]
    page: int | None
    bbox: list[float] | None
    source_anchor: dict[str, Any] | None
    agency_canonical_ids: list[str]
    fund_canonical_id: str | None
    fund_mentions: list[str]
    fiscal_year: int | None
    doc_type: str
    is_table: bool
    table_html: str | None
    token_count: int
    publisher: str  # denormalized via JOIN at query time

    @classmethod
    def from_row(cls, row: dict[str, Any], score: float) -> "RetrievedChunk":
        """Build from a psycopg dict_row + an externally-derived score.

        The score is passed in (rather than read from the row) because the
        scoring expression varies per producer: BM25 uses paradedb.score,
        dense uses 1 - (embedding <=> query), reranker uses Voyage's API
        response. Callers compute the score expression in SQL and pass it
        through.
        """
        bbox = row.get("bbox")
        if bbox is not None:
            bbox = [float(x) for x in bbox]
        return cls(
            chunk_id=row["chunk_id"],
            doc_id=row["doc_id"],
            text=row["text"],
            score=float(score),
            section_path=list(row.get("section_path") or []),
            page=row.get("page"),
            bbox=bbox,
            source_anchor=row.get("source_anchor"),
            agency_canonical_ids=list(row.get("agency_canonical_ids") or []),
            fund_canonical_id=row.get("fund_canonical_id"),
            fund_mentions=list(row.get("fund_mentions") or []),
            fiscal_year=row.get("fiscal_year"),
            doc_type=row["doc_type"],
            is_table=bool(row["is_table"]),
            table_html=row.get("table_html"),
            token_count=int(row["token_count"]),
            publisher=row["publisher"],
        )
