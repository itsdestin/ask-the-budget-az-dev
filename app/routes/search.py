"""POST /api/search — the frozen search contract Plans 3/4 build against.

Delegates to whatever SearchProvider is on app.state (stub fixtures now,
LanceSearchProvider in Task 12), so the route never imports the retrieval
stack directly. Response field names are frozen: do not rename.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class SearchFilters(BaseModel):
    fiscal_year: list[int] | None = None
    publisher: list[str] | None = None
    doc_type: list[str] | None = None
    agency: list[str] | None = None
    # Which BOOK's sections to keep when the doc_type list names a section
    # slug that belongs to both books (spec B5). Not a retrieval filter -- it
    # is applied by the provider after ranking, from the documents sidecar.
    section_family: str | None = None


class SearchBody(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=100)
    corpus: str = Field(default="budget", pattern="^(budget|fiscal_notes)$")
    filters: SearchFilters = Field(default_factory=SearchFilters)


@router.post("/api/search")
def search(body: SearchBody, request: Request):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    provider = request.app.state.provider
    try:
        outcome = provider.search(
            body.query, top_k=body.top_k, corpus=body.corpus,
            # exclude_none so providers can test `filters.get(k)` for "not set"
            # instead of having to distinguish None from an empty list.
            filters=body.filters.model_dump(exclude_none=True),
        )
    except Exception as e:
        # A provider failure mid-request (network share offline, model weights
        # missing, LanceDB lock) would otherwise escape as FastAPI's PLAIN-TEXT
        # "Internal Server Error" — which the web client can't parse, so the
        # user would see a bare "search failed: 500". A JSON 503 with the real
        # cause rides the client's existing `detail` plumbing instead.
        raise HTTPException(
            status_code=503,
            detail=f"Search backend failed: {type(e).__name__}: {e}",
        ) from e
    # Frozen-contract note: `total` is the count of rows actually returned,
    # AFTER top_k truncation — it is not a corpus-wide count of matches.
    #
    # The three `inferred_*` / `dropped_filters` keys are ADDITIVE (spec F15,
    # 2026-08-13): nothing above is renamed or removed, so every existing
    # caller keeps working and the contract stays frozen in the sense that
    # matters. They exist because the pipeline guesses filters from the
    # analyst's words — most consequentially a YEAR, which it applies as a
    # hard filter and never drops — and until now nothing carried that fact to
    # the browser, so the page could show "Any session" while the search had
    # quietly narrowed to three.
    return {
        "results": outcome.rows,
        "total": len(outcome.rows),
        "provider": provider.name,
        "inferred_fiscal_years": outcome.inferred_fiscal_years,
        "inferred_doc_types": outcome.inferred_doc_types,
        "dropped_filters": outcome.dropped_filters,
    }
