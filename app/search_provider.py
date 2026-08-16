"""Search seam: the app depends on this Protocol, not on the retrieval stack.

Two providers behind one Protocol: StubSearchProvider (fixtures — dev, CI,
any machine without a migrated corpus) and LanceSearchProvider (the real
Plan 1 pipeline: LanceDB hybrid retrieval + local rerank). app/main.py's
_default_provider picks at startup by probing whether a corpus exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Plan 1's public retrieval API. Importing it does NOT load the ONNX models —
# that happens lazily inside retrieve() — so the app stays importable and the
# stub path stays instant on machines without model weights.
from retrieval import FUSED_TOP_K, RetrievalRequest, retrieve

from app.book_sections import section_of
from app.fixtures.search_fixtures import FISCAL_NOTE_FIXTURE_ROWS, FIXTURE_ROWS
from identity.resolve import resolve_title
from store.documents import (
    humanize_doc_id,
    load_documents,
    sidecar_stamp as _sidecar_stamp,
)


@dataclass(frozen=True)
class SearchOutcome:
    """What one search produced: the rows, plus what the pipeline INFERRED
    from the analyst's words before it ran (spec F15).

    WHY this type exists at all, rather than `search()` returning rows:
    `retrieve()` has always reported its guesses, and this seam has always
    thrown them away — a list of rows has nowhere to put a fact about the
    QUERY. The live consequence is silent and one-directional: a question
    naming a year is hard-filtered by session (verified: "FY 2027 revenue
    impact of a sales tax exemption" applies `inferred_fiscal_years=[2027]`,
    widened a year either side) while the page's own control still reads "Any
    session". The page said one thing; the search did another.

    The year guess is worth more care than the doc-type guess because it has
    no safety net: when a doc-type guess empties the result set the pipeline
    drops it and reports `dropped_filters`, but the year guess is never
    dropped, so a wrong or merely narrow one just returns less, confidently,
    forever.

    Empty lists mean "inferred nothing", never "did not look" — a provider
    that does no query parsing says so explicitly (see StubSearchProvider).
    """

    rows: list[dict[str, Any]]
    inferred_fiscal_years: list[int] = field(default_factory=list)
    inferred_doc_types: list[str] = field(default_factory=list)
    dropped_filters: list[str] = field(default_factory=list)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> SearchOutcome: ...


class StubSearchProvider:
    """Fixture-backed provider used while Plan 1 lands (parallel-execution
    contract). Applies filters faithfully so the filter UI is testable."""

    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        # Deliberately ignores `query`: there is no ranking or text matching
        # here, so every search returns the same fixture rows in the same order.
        #
        # It does NOT ignore `corpus` (fixed 2026-08-13). It used to, and the
        # consequence was visible on a FRESH INSTALL — the probe in
        # `_default_provider` falls back to this stub when `budget_chunks` is
        # empty, so a brand-new user searching note text on the Fiscal Notes
        # page was answered with five BUDGET documents dressed as note matches.
        # Nothing caught it while fiscal-note search was a small box in the
        # rail; the browse rebuild made it the page's headline feature.
        rows_for_corpus = (
            FISCAL_NOTE_FIXTURE_ROWS if corpus == "fiscal_notes" else FIXTURE_ROWS
        )
        # Filters (and top_k) are the only inputs that change the output —
        # they are what the Plan 2 filter UI needs to exercise. Real relevance
        # arrives with LanceSearchProvider in Task 12.
        out = []
        for row in rows_for_corpus:
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
            #
            # `corpus` is popped: it is this file's routing marker, not a field
            # of the /api/search row contract, and shipping it would make the
            # stub's response shape differ from the real provider's — the exact
            # class of drift tests/test_search_route.py's contract test exists
            # to catch.
            out.append({k: v for k, v in row.items() if k != "corpus"}
                       | {"agencies": list(row["agencies"])})
        # Empty inference lists, stated rather than omitted (spec F15). This
        # provider does no query parsing at all — it ignores `query` entirely
        # — so "inferred nothing" is the honest answer, and it is a DIFFERENT
        # shape from "the key is missing". The filter UI is tested against
        # this provider, so a stub that silently omitted the keys would make
        # F15 untestable in the suite most likely to catch a regression.
        return SearchOutcome(rows=out[:top_k])


# `_title_from_doc_id` is the humanizer fallback for the one case
# `identity.resolve_title` can't reach: a retrieved chunk whose doc_id isn't
# a key in documents.json at all (`_info`'s own default return, below, is
# what produces that gap — never observed live, but defended anyway).
#
# WHY there is no more `_ingest_title` / `require_ingested=True` gate here
# (2026-08-16): it existed only to keep migration-era junk titles from
# beating the mockup index. Now that the mockup index is no longer the
# title source (see `_info` below), `identity.resolve_title` is the single
# ladder and it already carries its own fallback — a second, page-local gate
# would just be a second copy of the same decision. See spec I12.
_title_from_doc_id = humanize_doc_id


# The vendored website mockup's own document index (webapp/reference/…/
# index-lite.js, `window.JLBC_DOCS=[…];`). It supplies this page's
# "category · doc_type · FY" meta line and the URL join that lets a result
# row link back to its source PDF. It is NO LONGER the title source (see
# `_info` below) — Destin's original ask was that search titles match the
# mockup's, but the mockup is a scrape of JLBC's own index page and is the
# supplier of 218 wrong names (`05app/bar.pdf`, the Board of Barbers, records
# as "Agriculture, Arizona Department of"). Joined to our corpus by exact
# source URL (case-insensitive), never fuzzily: the sidecar records the URL
# each doc was ingested FROM, and 373/382 corpus docs match a mockup index
# entry exactly.
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

        `title` comes from `identity.resolve_title` — the one ladder every
        surface shares (spec I12). The mockup index still supplies the
        "category · doc_type · FY" meta line and the sidecar supplies the
        link target; docs the mockup never indexed (9 of 382) get a null
        meta but still get a real title."""
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
                        # WHY the harvest is no longer rung 1 (2026-08-16):
                        # `index-lite.js` is a scrape of JLBC's index page and
                        # is the SUPPLIER of the 218 wrong names — it records
                        # `05app/bar.pdf` as "Agriculture, Arizona Department
                        # of" for the Board of Barbers. It won unconditionally
                        # here, so repairing the corpus changed nothing on this
                        # page while the audit script read documents.json and
                        # reported zero errors. The harvest still supplies the
                        # meta line, which was never wrong.
                        "title": resolve_title(did),
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
        wanted = filters.get("section_family")
        # The family filter runs AFTER ranking (below), so a family-filtered
        # search can starve below the caller's requested top_k unless it asks
        # retrieve() for a bigger pool to filter from. Measured 2026-08-11
        # against the real corpus (5 queries x doc_type=[detailed-list-pdf,
        # topic-pdf], top_k=20 each):
        #   Baseline:              (20,4) (20,10) (20,0) (20,5) (20,10)
        #   Appropriations Report: (20,16) (20,10) (20,20) (20,15) (20,10)
        # Worst case is 0/20 (Baseline, "detailed list of changes" -- every
        # top-20 hit for that query was an Approps section), so a
        # ceil(top_k / worst_case_yield) formula divides by zero. There is no
        # need to compute one: `retrieval/pipeline.py`'s reranker always
        # scores the WHOLE fused pool regardless of the requested top_k
        # (`rerank(req.query, fused, top_k=len(fused))`) -- `top_k` only
        # slices the already-computed output. So asking for FUSED_TOP_K (the
        # pipeline's own ceiling, 20) instead of the caller's top_k costs
        # nothing extra IN THE RETRIEVAL PIPELINE -- it is automatically
        # "capped at the pipeline's own limits" by construction, and gives the
        # family filter the largest pool retrieve() can ever produce. (It is
        # NOT free below: row-building runs self._info() + section_of() over
        # up to FUSED_TOP_K rows instead of the caller's top_k -- a small,
        # bounded cost, not the "nothing extra" claim above, which is scoped
        # to the pipeline only.) Re-sliced to the caller's top_k after
        # filtering, below.
        req = RetrievalRequest(
            query=query,
            top_k=FUSED_TOP_K if wanted else top_k,
            corpus=self._CORPUS_TABLE[corpus],
            fiscal_year=filters.get("fiscal_year"),
            publisher=filters.get("publisher"),
            doc_type=filters.get("doc_type"),
            agency_canonical_id=filters.get("agency"),
        )
        result = retrieve(req)
        rows = [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                # `identity.resolve_title`, via `_info`'s cached join (spec
                # I12). The `or _title_from_doc_id(...)` fallback is for a
                # chunk whose doc_id isn't in documents.json at all — `_info`
                # then can't call resolve_title and returns title=None.
                "doc_title": (info := self._info(c.doc_id))["title"]
                or _title_from_doc_id(c.doc_id),
                "snippet": c.text[:280],
                # The FULL passage. The browser chooses the preview window and
                # marks the query's words in one place, in one language (spec
                # H8) — a server-chosen window plus browser-chosen marks can
                # disagree, and its failure is silent: a window obviously
                # picked BECAUSE of the match, with nothing marked in it.
                # Measured cost ~18KB per search (chunk text median 789 chars,
                # max 2,117, twenty results). Safe to ship as text: 0 of 4,000
                # sampled chunk `text` values contain markup — table markup
                # lives in the separate `table_html` column, not shipped here.
                "text": c.text,
                # The heading trail this passage sits under, innermost last
                # ("JLBC Fiscal Note" > "Estimated Impact"). Additive
                # 2026-08-13: the fiscal-note result card prints the innermost
                # heading as the excerpt's legend, and until now the only
                # section-ish field on a row was `doc_meta` — the mockup
                # index's CATEGORY line, which on this corpus reads
                # "Fiscal Notes · Fiscal Notes · FY 2026".
                "section_path": list(c.section_path),
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
                # Which JLBC book this passage's document is a section of, or
                # null. Same derivation the browse listing uses.
                "section_of": section_of(c.doc_type, info["url"]),
            }
            for c in result.chunks
        ]

        if wanted:
            # `detailed-list-pdf` belongs to BOTH books (255 approps / 45
            # baseline), so a doc_type filter alone cannot express "Baseline
            # sections" and would leak up to 269 documents. Dropping here
            # removes only what the reader explicitly filtered out -- that is
            # honouring a filter, not losing a match. Applied ONLY when the
            # filter is present, so an unfiltered search never loses a row.
            rows = [r for r in rows if r["section_of"] in (None, wanted)]
            # The retrieve() call above asked for FUSED_TOP_K, not the
            # caller's top_k, so it can return MORE rows than promised once
            # filtered back down. Re-slice to what was asked for. This
            # statement only runs inside `if wanted:` -- when unfiltered,
            # req.top_k was already the caller's top_k and this line never
            # executes at all, so there is no "no-op" case to describe here.
            rows = rows[:top_k]
        # Pass the pipeline's own guesses through untouched (spec F15). These
        # describe the QUERY, not the rows, which is why they ride alongside
        # `rows` rather than being stamped onto each one — every row in a
        # response shares them, and duplicating them 20 times would invite a
        # reader to think a row could disagree with its siblings.
        return SearchOutcome(
            rows=rows,
            inferred_fiscal_years=list(result.inferred_fiscal_years),
            inferred_doc_types=list(result.inferred_doc_types),
            dropped_filters=list(result.dropped_filters),
        )
