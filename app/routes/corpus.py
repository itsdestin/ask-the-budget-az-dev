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
    fiscal_year, the source URL the row links to, and the search `terms` the
    filter box matches on. The page filters, groups and searches this
    client-side, so there is exactly one request on mount and none per
    keystroke.

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

    from app.search_terms import load_agency_catalog_by_slug, search_terms

    # Read the agency catalog ONCE for this whole listing, not once per row.
    # This does NOT cache a FAILURE across requests — a failed read is never
    # memoized (see load_agency_catalog_by_slug), so the next request retries.
    # It only stops one request re-reading it 5,330 times, which in the
    # degraded case also meant 5,330 stderr lines and 1.33 MB for a single
    # page load against the live corpus (2026-08-11 review).
    catalog = load_agency_catalog_by_slug()

    def _terms_for(doc_id: str, meta: dict) -> list[str]:
        """`search_terms`, skipped (not called) when `doc_type`/`fiscal_year`
        aren't the types it's typed to accept.

        Reproduced against this branch before this guard existed:
        `fiscal_year="2027"` (a string) raises TypeError from `>=` against an
        int in `_type_terms`; `fiscal_year=2027.0` (a float) raises ValueError
        formatting `:02d`; `doc_type=["baseline-per-agency"]` (a list) raises
        TypeError being hashed as a dict key. Any one of those 500'd the
        WHOLE listing, not just its own row.

        Same posture as the `isinstance(meta, dict)` guard two lines below —
        this module already treats a hand-edited sidecar's wrong shape as
        data ("can hold anything"), not a bug, and that guard skips the row
        WHOLESALE rather than salvaging whatever fields happen to parse.
        Mirrored here: a wrong-typed `doc_type` or `fiscal_year` skips the
        whole `terms` computation for the row (including the doc_id-derived
        agency terms `search_terms` would otherwise still find), rather than
        passing through only the one field that's still well-typed. A
        document whose sidecar entry is this damaged has nothing in it
        trustworthy enough to search on.

        `app/search_terms.py`'s contract is typed (`doc_type: str | None,
        fiscal_year: int | None`) and its own 2026-08-11 fix deliberately
        narrowed what it swallows internally, so honouring that contract is
        this caller's job, not something to catch after the fact.
        """
        doc_type = meta.get("doc_type")
        fiscal_year = meta.get("fiscal_year")
        if not (doc_type is None or isinstance(doc_type, str)):
            return []
        # `isinstance(x, int)` alone admits two nonsense inputs a hand-edited
        # sidecar can hold (2026-08-11 review finding 6): `bool` is an int
        # subclass, so `fiscal_year: true` passes as `1`; and a five-digit
        # typo like `20260` passes too, then silently becomes the term
        # "60br" via `_type_terms`'s `fiscal_year % 100`. Bounding to a
        # plausible four-digit year rejects both in the same check that was
        # already here — no user-visible harm today (no fixture has ever
        # carried either shape), so this stays a bound wide enough to need
        # no import from retrieval's MIN/MAX_PLAUSIBLE_YEAR, not a coupling
        # to that exact window.
        if not (
            fiscal_year is None
            or (isinstance(fiscal_year, int) and 1000 <= fiscal_year <= 9999)
        ):
            return []
        return search_terms(doc_id, doc_type, fiscal_year, catalog)

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
            # Extra strings the filter box matches by EXACT token
            # equality — the agency's JLBC slug and reviewed aliases,
            # plus this report type's shorthand ("26ar"). Computed here
            # rather than in the browser so JLBC's convention has exactly
            # one implementation; see app/search_terms.py for the
            # measurement that motivated it ("dema" matched 0 of 5,330
            # documents before this). Uses `_terms_for`, not
            # `search_terms` directly, so a wrong-typed
            # doc_type/fiscal_year can't 500 the whole listing — see that
            # helper's docstring for the three reproduced exceptions.
            "terms": _terms_for(doc_id, meta),
        }
        for doc_id, meta in docs.items()
        # A hand-edited sidecar can hold anything; a non-dict entry has
        # no metadata to list and would raise on .get. Skip it, same
        # posture as store.documents.document_record.
        if isinstance(meta, dict)
        # Budget corpus only — a sidecar entry with no chunks in
        # budget_chunks is a fiscal note (or was never ingested), and
        # neither belongs on the Budget Documents page.
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
