"""Search seam: the app depends on this Protocol, not on the retrieval stack.

Two providers behind one Protocol: StubSearchProvider (fixtures — dev, CI,
any machine without a migrated corpus) and LanceSearchProvider (the real
Plan 1 pipeline: LanceDB hybrid retrieval + local rerank). app/main.py's
_default_provider picks at startup by probing whether a corpus exists.
"""
from __future__ import annotations

from typing import Any, Protocol

# Plan 1's public retrieval API. Importing it does NOT load the ONNX models —
# that happens lazily inside retrieve() — so the app stays importable and the
# stub path stays instant on machines without model weights.
from retrieval import RetrievalRequest, retrieve

from app.fixtures.search_fixtures import FIXTURE_ROWS


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> list[dict[str, Any]]: ...


class StubSearchProvider:
    """Fixture-backed provider used while Plan 1 lands (parallel-execution
    contract). Applies filters faithfully so the filter UI is testable."""

    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        # Deliberately ignores `query` and `corpus`: there is no ranking or
        # text matching here, so every search returns the same fixture rows.
        # Filters (and top_k) are the only inputs that change the output —
        # they are what the Plan 2 filter UI needs to exercise. Real relevance
        # arrives with LanceSearchProvider in Task 12.
        out = []
        for row in FIXTURE_ROWS:
            if filters.get("publisher") and row["publisher"] not in filters["publisher"]:
                continue
            if filters.get("fiscal_year") and row["fiscal_year"] not in filters["fiscal_year"]:
                continue
            if filters.get("doc_type") and row["doc_type"] not in filters["doc_type"]:
                continue
            if filters.get("agency") and not set(row["agencies"]) & set(filters["agency"]):
                continue
            # Copy the row AND its `agencies` list: a plain dict(row) shares the
            # same list object, so a caller mutating result["agencies"] would
            # corrupt FIXTURE_ROWS for the whole process.
            out.append({**row, "agencies": list(row["agencies"])})
        return out[:top_k]


def _title_from_doc_id(doc_id: str) -> str:
    """Best-effort humanization of doc_id slugs
    ('jlbc-baseline-fy2027-ahcccs' -> 'JLBC Baseline FY 2027 Ahcccs').

    Plan 1's documents.json sidecar DOES exist (store/config.py), but its
    migration-era titles are rougher than this ('AGAO FY2025 fy2025'), so the
    slug stays the better source until Plan 3's ingest writes real titles —
    switch this to the sidecar then."""
    parts = doc_id.split("-")
    out = []
    for p in parts:
        if p.startswith("fy") and p[2:].isdigit():
            out.append(f"FY {p[2:]}")
        elif p in ("jlbc", "agao", "afr", "sad"):
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return " ".join(out)


class LanceSearchProvider:
    """Real retrieval (Plan 1 stack) behind the frozen /api/search contract."""

    name = "lance"

    # /api/search's corpus values -> LanceDB table names (store/chunk_store.py's
    # CORPUS_TABLES). The route's pydantic pattern only admits these two.
    _CORPUS_TABLE = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}

    def search(self, query, *, top_k, corpus, filters):
        req = RetrievalRequest(
            query=query,
            top_k=top_k,
            corpus=self._CORPUS_TABLE[corpus],
            fiscal_year=filters.get("fiscal_year"),
            publisher=filters.get("publisher"),
            doc_type=filters.get("doc_type"),
            agency_canonical_id=filters.get("agency"),
        )
        result = retrieve(req)
        return [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "doc_title": _title_from_doc_id(c.doc_id),
                "snippet": c.text[:280],
                "page": c.page,
                # Raw cross-encoder logit (roughly -10..10, negatives normal) —
                # NOT 0..1. The contract types this as float and makes no scale
                # claim; the UI clamps for its bar and prints the number as-is.
                "score": c.score,
                "doc_type": c.doc_type,
                "fiscal_year": c.fiscal_year,
                "publisher": c.publisher,
                "agencies": list(c.agency_canonical_ids),
            }
            for c in result.chunks
        ]
