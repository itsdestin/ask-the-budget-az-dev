"""Search seam: the app depends on this Protocol, not on the retrieval stack.

Two providers behind one Protocol: StubSearchProvider (fixtures — dev, CI,
any machine without a migrated corpus) and LanceSearchProvider (the real
Plan 1 pipeline: LanceDB hybrid retrieval + local rerank). app/main.py's
_default_provider picks at startup by probing whether a corpus exists.
"""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any, Protocol

# Plan 1's public retrieval API. Importing it does NOT load the ONNX models —
# that happens lazily inside retrieve() — so the app stays importable and the
# stub path stays instant on machines without model weights.
from retrieval import RetrievalRequest, retrieve

from app.fixtures.search_fixtures import FIXTURE_ROWS
from store.documents import (
    humanize_doc_id,
    load_documents,
    sidecar_stamp as _sidecar_stamp,
    sidecar_title,
)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> list[dict[str, Any]]: ...


class StubSearchProvider:
    """Fixture-backed provider used while Plan 1 lands (parallel-execution
    contract). Applies filters faithfully so the filter UI is testable."""

    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        # Deliberately ignores `query` and `corpus`: there is no ranking or
        # text matching here, so every search returns the same fixture rows.
        # Filters (and top_k) are the only inputs that change the output —
        # they are what the Plan 2 filter UI needs to exercise. Real relevance
        # arrives with LanceSearchProvider in Task 12.
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
            # Copy the row AND its `agencies` list: a plain dict(row) shares the
            # same list object, so a caller mutating result["agencies"] would
            # corrupt FIXTURE_ROWS for the whole process.
            out.append({**row, "agencies": list(row["agencies"])})
        return out[:top_k]


# Title precedence on this page is: mockup index → the sidecar's own title
# → the doc-id humanizer. The middle step is GATED on `ingested_at`
# (`require_ingested=True`), which is what keeps the migration's doc-id
# derived junk ("AGAO FY2025 fy2025") from beating the humanizer on the 9
# documents the mockup index never matched.
#
# That gate is this page's rule, NOT a global one — see
# `store.documents.title_for` for why the harness must not adopt it.
# Both the gate and the humanizer moved to `store/documents.py` in Plan 5
# Task 19; these aliases keep the call sites below reading the same.
_ingest_title = partial(sidecar_title, require_ingested=True)
_title_from_doc_id = humanize_doc_id


# The vendored website mockup's own document index (webapp/reference/…/
# index-lite.js, `window.JLBC_DOCS=[…];`). It is the source of the mockup's
# display titles ("Corrections, State Department of — FY 2025 Appropriations
# Report") and meta lines — Destin: search result titles must be THE SAME as
# the mockup's. Joined to our corpus by exact source URL (case-insensitive),
# never fuzzily: the sidecar records the URL each doc was ingested FROM, and
# 373/382 corpus docs match a mockup index entry exactly.
MOCKUP_INDEX_PATH = (
    Path(__file__).resolve().parent.parent
    / "webapp" / "reference" / "assets" / "search" / "index-lite.js"
)


class LanceSearchProvider:
    """Real retrieval (Plan 1 stack) behind the frozen /api/search contract."""

    name = "lance"

    def __init__(self) -> None:
        # doc_id -> {url, title, meta}: the sidecar JOINED to the vendored
        # mockup index. This cache is the JOIN, not the sidecar — reading and
        # parsing documents.json is `store.documents`' job as of Plan 5 Task
        # 19, and it has its own mtime cache. What stays here is the URL join
        # and the mockup's meta-line recipe, which nothing else wants.
        # None until first use; {} if the sidecar is missing (rows then carry
        # doc_url=None + humanized titles — degraded, not broken).
        self._doc_info: dict[str, dict] | None = None
        # Stamp of the sidecar the JOIN was built from. Plan 3's ingest
        # rewrites that file whenever a document goes live, and this provider
        # is a process-lifetime singleton — without a staleness check every
        # document ingested during a session would keep the doc-id humanizer's
        # title until the app restarted.
        self._doc_info_sig: tuple | None = None

    @staticmethod
    def _load_mockup_index() -> dict[str, dict]:
        """lowercase url -> mockup index entry. {} when unreadable."""
        raw = MOCKUP_INDEX_PATH.read_text(encoding="utf-8")
        # The file is `window.JLBC_DOCS=[…];` — everything after the first
        # `=` (minus the trailing semicolon) is plain JSON.
        payload = raw.split("=", 1)[1].strip().rstrip(";")
        entries = json.loads(payload)
        return {e["url"].lower(): e for e in entries if e.get("url")}

    def _info(self, doc_id: str) -> dict:
        """{url, title, meta} for a doc — url/title/meta None when unknown.

        The join is what makes result rows read EXACTLY like the website
        mockup's: its index entry supplies the display title and the
        "category · doc_type · FY" meta line, and the sidecar supplies the
        link target. Docs the mockup never indexed (9 of 382) fall back to
        the slug humanizer and a null meta."""
        if self._doc_info is None or self._sidecar_changed():
            try:
                self._doc_info_sig = _sidecar_stamp()
                sidecar = load_documents()
                index = self._load_mockup_index()
                info: dict[str, dict] = {}
                for did, meta in sidecar.items():
                    url = meta.get("source_url")
                    entry = index.get(url.lower()) if url else None
                    fy = entry.get("fiscal_year") if entry else None
                    info[did] = {
                        "url": url,
                        "title": (
                            entry.get("title") if entry
                            else _ingest_title(meta)
                        ),
                        # The mockup docRow's own meta recipe:
                        # [category, doc_type, 'FY '+fy], joined with ·
                        "meta": " · ".join(
                            p for p in (
                                entry.get("category"),
                                entry.get("doc_type"),
                                f"FY {fy}" if fy else None,
                            ) if p
                        ) if entry else None,
                    }
                self._doc_info = info
            except Exception as e:
                # Missing/corrupt sidecar or index degrades to humanized
                # titles + unlinked rows; search keeps working. Say WHY on
                # stderr (same posture as _default_provider's note).
                import sys

                print(
                    f"jlbc-insight: document metadata unavailable "
                    f"({type(e).__name__}: {e}) — search rows fall back to "
                    "generated titles without source links.",
                    file=sys.stderr,
                )
                self._doc_info = {}
                self._doc_info_sig = None
        return self._doc_info.get(doc_id) or {"url": None, "title": None, "meta": None}

    def _sidecar_changed(self) -> bool:
        """Has documents.json been rewritten since the JOIN was built?

        Cheap (one stat) and checked per lookup, because the alternative is a
        colleague uploading a document, seeing it appear in search under a
        machine-generated title, and having no way to know a restart fixes it.
        """
        stamp = _sidecar_stamp()
        if stamp is None:
            # Sidecar gone or share unreachable — keep the last good map.
            # (Different from store.documents' policy on purpose: this map is
            # display metadata, so serving slightly stale titles beats a page
            # of unlinked rows during a brief share hiccup.)
            return False
        return self._doc_info_sig != stamp

    # /api/search's corpus values -> LanceDB table names (store/chunk_store.py's
    # CORPUS_TABLES). The route's pydantic pattern only admits these two.
    _CORPUS_TABLE = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}

    def search(self, query, *, top_k, corpus, filters):
        req = RetrievalRequest(
            query=query,
            top_k=top_k,
            corpus=self._CORPUS_TABLE[corpus],
            fiscal_year=filters.get("fiscal_year"),
            publisher=filters.get("publisher"),
            doc_type=filters.get("doc_type"),
            agency_canonical_id=filters.get("agency"),
        )
        result = retrieve(req)
        return [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                # The mockup index's own display title when the URL join has
                # one; the slug humanizer only as fallback (9 of 382 docs).
                "doc_title": (info := self._info(c.doc_id))["title"]
                or _title_from_doc_id(c.doc_id),
                "snippet": c.text[:280],
                "page": c.page,
                # Raw cross-encoder logit (roughly -10..10, negatives normal) —
                # NOT 0..1. The contract types this as float and makes no scale
                # claim; the UI clamps for its bar and prints the number as-is.
                "score": c.score,
                "doc_type": c.doc_type,
                "fiscal_year": c.fiscal_year,
                "publisher": c.publisher,
                "agencies": list(c.agency_canonical_ids),
                # Additive contract field (2026-07-30): the document's own
                # source URL, so result rows can link to the individual agency
                # narrative PDF like the mockup's rows did. None when the
                # sidecar has no record.
                "doc_url": info["url"],
                # Additive (2026-07-30): the mockup's meta line for its rows
                # ("Agency Budget Detail · Appropriations Report · FY 2025").
                # None when the doc isn't in the mockup index.
                "doc_meta": info["meta"],
            }
            for c in result.chunks
        ]
