"""The ONE read-path title resolver (spec I12).

Every surface calls this. Three ladders existed before it — search results,
the browse listing, and AI Mode — and they disagreed on both of their upper
rungs, which is why the same document could be called one thing on the page
and another inside an answer with no test able to see it.

WHY the website index is not a rung here, when it was rung 1 of the search
page: it is a harvest of JLBC's own index page and it is the supplier that
produced the 218 wrong names (`05app/bar.pdf` → "Agriculture, Arizona
Department of", for the Board of Barbers). The corpus's own record is
repaired from the document's text; the harvest is not. Keeping the harvest
above it would have made the entire title repair invisible on the primary
path — measured, and the reason this module ships before any repair.

The harvest is still repaired in place (spec I6) so that a future re-ingest
cannot re-import a wrong name; it is simply no longer the authority at read
time.

WHY there is no `require_ingested` gate: it existed only as a tiebreak
against the harvest. With the harvest gone the sidecar is the sole source,
and gating it swaps 375 real agency names for doc-id slugs.
"""
from __future__ import annotations

from typing import Iterable

from store.documents import humanize_doc_id, sidecar_title
from store import documents as _docs


def resolve_title(doc_id: str) -> str:
    """Display title for one doc_id. Never empty."""
    meta = _docs._load_cached().get(doc_id)
    return sidecar_title(meta) or humanize_doc_id(doc_id)


def resolve_titles(doc_ids: Iterable[str]) -> dict[str, str]:
    """`resolve_title` over many ids with ONE sidecar read.

    Reads `_load_cached()` directly rather than calling `resolve_title` per
    id — that private accessor is the one-read-in-place view; going through
    the public `load_documents()` instead would deep-copy the whole sidecar
    (thousands of records) once per id on a ~20-row search page.
    """
    docs = _docs._load_cached()
    return {
        doc_id: sidecar_title(docs.get(doc_id)) or humanize_doc_id(doc_id)
        for doc_id in doc_ids
    }
