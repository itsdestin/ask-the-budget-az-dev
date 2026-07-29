"""GET /api/fiscal-notes — serves the committed snapshot (Plan 2).
Plan 3 swaps the data source to the live corpus + refresh scraper
behind this same contract."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "fiscal-notes-snapshot.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    # Cached: the snapshot is ~460KB of frozen, committed JSON, so re-parsing it
    # per request would burn CPU for an identical result. Callers must treat the
    # returned dict as read-only — it is the single shared cached instance, and
    # mutating it would corrupt every later response.
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    # Normalize ordering here rather than trusting the exporter, so the
    # newest-first contract holds even if Plan 3's live source emits any order.
    # list.sort is stable, so sessions sharing a year keep their source order.
    data["sessions"].sort(key=lambda s: -s["year"])
    return data


@router.get("/api/fiscal-notes")
def fiscal_notes():
    return _load()
