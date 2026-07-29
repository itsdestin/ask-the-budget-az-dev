"""Search seam: the app depends on this Protocol, not on the retrieval stack.

Keeps the app server importable (and testable) with no Postgres/Voyage
services running. The real provider (LanceSearchProvider) arrives in Task 12;
until then StubSearchProvider serves fixtures and /health reports "stub".
"""
from __future__ import annotations

from typing import Any, Protocol

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
            out.append(dict(row))
        return out[:top_k]
