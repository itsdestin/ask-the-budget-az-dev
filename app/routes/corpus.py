"""Corpus size and the document listing, for everyone (Plan 5 Task 19 + the
Budget Documents browse page).

Two endpoints. `/api/corpus/counts` exists so the footer can state a TRUE
corpus size again: it used to say "382 docs", Plan 3's upload queue
falsified that the first time anyone uploaded, and the honest interim fix
was to remove the number entirely rather than let it rot unnoticed.
`/api/corpus/documents` is what the browse-first Budget Documents page
loads on mount — the whole corpus as one flat listing.

**Not admin-gated.** Neither corpus size nor the catalog of what's been
ingested is sensitive, and both feed surfaces every analyst sees;
`/api/admin/corpus` is the gated, much richer view (bytes on disk, dead
versions, queue state).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

CORPUS_TABLES = ("budget_chunks", "fiscal_note_chunks")


def chunk_counts() -> dict[str, int]:
    """Row counts per corpus table, zero on anything unopenable.

    A missing or unreadable table reads as 0 — the same number a genuinely
    empty corpus produces. That ambiguity is deliberate: the health ladder
    (`app/health.py`) is what distinguishes "empty" from "broken", with a
    plain sentence for each. This function's job is the numbers, and it
    must not be the thing that takes a page down.
    """
    counts = {name: 0 for name in CORPUS_TABLES}
    try:
        from store.chunk_store import ChunkStore

        store = ChunkStore()
        for name in counts:
            try:
                counts[name] = store.count(name)
            except Exception:  # noqa: BLE001 — missing table, bad schema…
                continue
    except Exception:  # noqa: BLE001 — LanceDB itself unavailable
        pass
    return counts


def document_count() -> int:
    """How many documents the sidecar knows about.

    Goes through `store.documents`, which degrades a missing or corrupt
    file to `{}` and says why on stderr. Zero is then the honest answer,
    and the footer showing "0 documents" is a visible symptom — far better
    than a 500 inside a footer fetch.
    """
    from store.documents import load_documents

    return len(load_documents())


@router.get("/api/corpus/counts")
def corpus_counts() -> dict:
    return {"documents": document_count(), **chunk_counts()}


def document_listing() -> list[dict]:
    """Every document the sidecar knows about, as the browse page renders it.

    One flat row per document: id, display title, publisher, doc_type,
    fiscal_year and the source URL the row links to. The page filters,
    groups and searches this client-side, so there is exactly one request
    on mount and none per keystroke.

    Titles come from `store.documents.title_for` with its DEFAULT gate —
    not the search page's `require_ingested=True`. The gate exists because
    the search page has the vendored mockup index as a better title source
    to fall back to; this listing has no third source, so gating would
    replace ~378 real migration-era titles ("JLBC FY2025 — African-American
    Affairs, Arizona Commission of") with humanized doc-id slugs. See
    `title_for`'s own docstring — it names this exact case.
    """
    from store.documents import load_documents, title_for

    docs = load_documents()
    rows = [
        {
            "doc_id": doc_id,
            "title": title_for(doc_id),
            "publisher": meta.get("publisher"),
            "doc_type": meta.get("doc_type"),
            "fiscal_year": meta.get("fiscal_year"),
            "doc_url": meta.get("source_url"),
        }
        for doc_id, meta in docs.items()
        # A hand-edited sidecar can hold anything; a non-dict entry has no
        # metadata to list and would raise on .get. Skip it, same posture as
        # store.documents.document_record.
        if isinstance(meta, dict)
    ]
    # Deterministic order for a payload the page diffs across reloads:
    # doc_id sorts year and publisher together naturally.
    rows.sort(key=lambda r: r["doc_id"])
    return rows


@router.get("/api/corpus/documents")
def corpus_documents() -> dict:
    """The budget corpus as a browsable listing. Missing or corrupt sidecar
    degrades to an empty list (load_documents' own rule) — the page shows
    "no documents yet" instead of a 500."""
    return {"documents": document_listing()}
