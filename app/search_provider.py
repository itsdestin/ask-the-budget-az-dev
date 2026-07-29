"""Search seam: the app depends on this Protocol, not on the retrieval stack.

Keeps the app server importable (and testable) with no Postgres/Voyage
services running. The real provider arrives in Task 4/12; StubSearchProvider
is what /health reports as "stub".
"""
from __future__ import annotations

from typing import Any, Protocol


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> list[dict[str, Any]]: ...


class StubSearchProvider:
    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        return []
