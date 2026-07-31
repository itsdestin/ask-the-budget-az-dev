"""GET /api/fiscal-notes — the bill/session directory, plus refresh control.

Data source, in order: the live directory the refresh scraper writes to the
shared data dir, else the committed snapshot. That fallback is what makes a
fresh install useful on day one — 28 sessions of history are already there,
and the first refresh only adds what's new.

The response contract is Plan 2's, unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Request

from ingest.fiscal_notes_refresh import directory_path
from ingest.jobs import new_job, save

router = APIRouter()
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "fiscal-notes-snapshot.json"

# Parsed-directory cache, keyed on (path, mtime, size). Plan 2 used lru_cache,
# which was right for a frozen committed file and wrong the moment the file
# became live: a refresh would update the directory and every reader would keep
# serving the pre-refresh copy until the process restarted. Re-parsing 460 KB
# per request is real CPU, so the cache stays — it just checks the file's
# signature first. Callers must treat the returned dict as read-only; it is the
# single shared cached instance.
_cache: tuple[tuple, dict] | None = None
_cache_lock = Lock()


def _source() -> Path:
    live = directory_path()
    return live if live.is_file() else SNAPSHOT


def _load() -> dict:
    global _cache
    path = _source()
    stat = path.stat()
    signature = (str(path), stat.st_mtime_ns, stat.st_size)

    with _cache_lock:
        if _cache is not None and _cache[0] == signature:
            return _cache[1]

    data = json.loads(path.read_text(encoding="utf-8"))
    # Normalize ordering here rather than trusting the writer, so the
    # newest-first contract holds whichever source served it. list.sort is
    # stable, so sessions sharing a year keep their source order.
    data.setdefault("sessions", []).sort(key=lambda s: -s["year"])

    with _cache_lock:
        _cache = (signature, data)
    return data


@router.get("/api/fiscal-notes")
def fiscal_notes():
    return _load()


@router.get("/api/fiscal-notes/status")
def fiscal_notes_status():
    """How much of the fiscal-note corpus is actually searchable.

    The page's semantic-search box stays disabled until this is non-zero:
    offering a search that can only ever return nothing is worse than saying
    it isn't ready yet.
    """
    try:
        from store.chunk_store import ChunkStore

        chunks = ChunkStore().count("fiscal_note_chunks")
    except Exception:
        # An unreachable share means the search can't work anyway — report
        # zero and let the rail stay disabled rather than 500 the page.
        chunks = 0
    return {"chunks": chunks}


@router.post("/api/fiscal-notes/refresh", status_code=202)
def refresh(request: Request):
    """Queue a scrape of the newest sessions from azjlbc.gov.

    Runs as a queue job so it serializes behind the same single-writer lock
    and corpus backup as any other write, and so its progress and failures
    show up in the one place users already look.
    """
    job = new_job(
        doc_id="fiscal-notes-refresh",
        title="Fiscal notes — check azjlbc.gov for new notes",
        corpus="fiscal_notes",
        source_path="",
        source_sha256="",
        publisher="legislature",
        doc_type="fiscal-note",
        fiscal_year=0,
        kind="refresh",
    )
    save(job)
    worker = getattr(request.app.state, "ingest_worker", None)
    if worker is not None:
        worker.start()
    return {"job_id": job.job_id}
