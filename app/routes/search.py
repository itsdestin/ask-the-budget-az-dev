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
    results = provider.search(
        body.query, top_k=body.top_k, corpus=body.corpus,
        # exclude_none so providers can test `filters.get(k)` for "not set"
        # instead of having to distinguish None from an empty list.
        filters=body.filters.model_dump(exclude_none=True),
    )
    # Frozen-contract note: `total` is the count of rows actually returned,
    # AFTER top_k truncation — it is not a corpus-wide count of matches.
    return {"results": results, "total": len(results), "provider": provider.name}
