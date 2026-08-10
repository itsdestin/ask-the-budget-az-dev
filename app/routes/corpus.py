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


def budget_doc_ids() -> set[str]:
    """Every doc_id that has chunks in the BUDGET corpus table.

    WHY this exists: `documents.json` is ONE sidecar shared by both corpora.
    `ingest/lance_writer.py`'s `_merge_document_entry` writes the same file
    whether `write_doc` was handed `budget_chunks` or `fiscal_note_chunks`
    (worker.py:697 is the single call site for both), and the record it writes
    carries no `corpus` field — see its `entry` dict, pinned by an assert
    against DOCS_FIELDS + INGEST_DOCS_FIELDS, neither of which names one. So
    listing the sidecar unfiltered hands FISCAL NOTES to the Budget Documents
    page, which is what this filters out.

    Membership is read from the chunk table rather than guessed from doc_type
    (e.g. excluding "fiscal-note"): a doc_type denylist is only as good as the
    list, and `/api/upload` accepts any registered doc_type against either
    corpus, so a fiscal note filed under another type would slip straight
    through. A document is in the budget corpus exactly when budget_chunks
    holds chunks for it — that is the fact, not a proxy for it.

    Cost: a one-column projection scan. `ChunkStore.scan`'s own docstring
    measures the full budget corpus at ~60ms with SIX columns, and this route
    is hit once per page load (the browse page fetches on mount and filters
    client-side), never per keystroke.

    Failure posture: an unopenable or missing table reads as an EMPTY set, the
    same answer a genuinely empty corpus gives. That ambiguity is deliberate
    and is this module's existing documented rule — see `chunk_counts` above,
    which resolves the identical question the same way and points at
    `app/health.py` as the thing that distinguishes "empty" from "broken".
    Callers must not phrase an empty result as a claim about ingestion.
    """
    try:
        from store.chunk_store import ChunkStore

        rows = ChunkStore().scan("budget_chunks", ["doc_id"])
    except Exception:  # noqa: BLE001 — missing table, bad schema, no LanceDB
        return set()
    return {r["doc_id"] for r in rows if isinstance(r, dict) and r.get("doc_id")}


def document_listing() -> list[dict]:
    """Every BUDGET document the sidecar knows about, as the browse page
    renders it.

    One flat row per document: id, display title, publisher, doc_type,
    fiscal_year and the source URL the row links to. The page filters,
    groups and searches this client-side, so there is exactly one request
    on mount and none per keystroke.

    Restricted to the budget corpus via `budget_doc_ids()` — the sidecar
    itself cannot tell the two corpora apart. See that function for why.

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
    in_budget = budget_doc_ids()
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
        # Budget corpus only — a sidecar entry with no chunks in budget_chunks
        # is a fiscal note (or was never ingested), and neither belongs on the
        # Budget Documents page.
        and doc_id in in_budget
    ]
    # Deterministic order for a payload the page diffs across reloads:
    # doc_id sorts year and publisher together naturally.
    rows.sort(key=lambda r: r["doc_id"])
    return rows


@router.get("/api/corpus/documents")
def corpus_documents() -> dict:
    """The budget corpus as a browsable listing.

    A missing or corrupt sidecar degrades to an empty list (load_documents'
    own rule), as does an unreadable chunk table (see `budget_doc_ids`) —
    either way the page renders its empty state instead of a 500. That state
    must NOT name a cause: an empty list here means "nothing to show", and
    this route cannot tell an un-ingested corpus from a broken one."""
    return {"documents": document_listing()}
