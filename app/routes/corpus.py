"""Corpus size, for everyone (Plan 5 Task 19).

One endpoint. It exists so the footer can state a TRUE corpus size again:
it used to say "382 docs", Plan 3's upload queue falsified that the first
time anyone uploaded, and the honest interim fix was to remove the number
entirely rather than let it rot unnoticed.

**Not admin-gated.** Corpus size is not sensitive and this feeds a footer
every analyst sees; `/api/admin/corpus` is the gated, much richer view
(bytes on disk, dead versions, queue state).
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
