# Handoff: Budget Documents — browse/browse-search page (design approved; implement)

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, venv at
`.venv`). This is a **webapp frontend** task — no ingest, no retrieval, no eval.

## The job

Rebuild the **Budget Documents** page (currently `webapp/src/pages/Search.tsx`,
route `/search`) as a **browse-first directory** that mirrors the Fiscal Notes
layout, instead of today's "type a search to see anything" results page.

The design is **already settled and Destin-approved** in a self-contained,
interactive HTML/CSS mockup. Your first job is to *port that mockup faithfully*
(port, don't redesign — same posture as spec S12). Your second job is to wire
it to live data, which requires **one new backend listing endpoint** that does
not exist yet.

## Read first (in order)

1. **`mockups/budget-documents-browse.html`** — the approved design. Open it in
   a browser and click everything: filter the rail, search "ahcccs", expand a
   prior year. Every behavior described below is implemented in throwaway JS in
   this file. Its inline CSS reuses the app's real class recipes and design
   tokens, and its header comment records the design history. **This file is
   the source of truth for look and interaction.**
2. **`webapp/src/pages/FiscalNotes.tsx`** — the layout template being mirrored
   (sticky `.fnside` rail + `.fnmain` cards). Its long header comment documents
   the port conventions (CSS-only → React state, `.on` classes, honest counts).
3. **`webapp/src/components/ResultCard.tsx` + `reportFamilies.ts`** — the
   report-family `.grp` card and the family vocabulary (`familyOf`,
   `familyTitle`, `reportFormats`, `FILTER_BUCKETS`) that the browse page's
   cards are built from.
4. **`webapp/src/components/FilterBar.tsx`** — the existing dropdown recipe the
   rail's two selects imitate, and the canonical publisher labels.

## Core design decisions (all Destin-approved in the mockup; do not relitigate)

- **Two-region layout.** Sticky left rail (search pill + two named multi-select
  dropdowns) beside a results column, like Fiscal Notes.
- **Rail filters = "Document Type" and "Fiscal Year" only.** Each is a
  multi-select dropdown defaulting to **"Any type" / "Any year"** (trigger shows
  the single pick, "N selected" for several, tints gold while active — the
  search page's `.fbtn.has`). **No Publisher filter** — publisher only appears
  as a chip on each row.
- **Publisher vocabulary changed.** `governor` → **OSPB**, `agao` → **GAO**,
  and the separate `legislature` publisher is **folded into JLBC** (budget bills
  are JLBC products). Three chips: JLBC · OSPB · GAO. ⚠ This is a **data +
  label migration**, not just a relabel: `data/ingest-plan.yaml` publisher codes
  and `FilterBar.tsx`'s `PUBLISHERS` still say the old words. Decide whether to
  re-tag at ingest or map at display, and keep `publisherLabel()` honest either
  way. All chips render in **one color** (copper) — no per-publisher color.
- **Auto-loads with content.** Empty search box shows the corpus grouped by
  fiscal year — no "type to begin" dead end.
- **Report-family grouping, same as existing search.** Results group into one
  card per report family (Baseline / Appropriations Report / Executive Budget /
  Annual Financial Report / Budget Bill). **There is only ever ONE Baseline
  card per year**, one Approps card, etc.
- **Two card states per family:**
  - **Idle (empty search):** a *bare report card* — the top-level row IS the
    report ("FY 2027 Baseline", book glyph, "Open →"), with a dashed
    "N documents in this report / Browse documents" tray and a "Full report"
    button (only where `reportFormats` has a hand-verified URL).
  - **Searching:** the matched single-agency page is promoted to the card's
    top level, with "Part of the FY 2027 Baseline" framing and the other
    matches behind "N more matches" — the existing search page's own behavior.
- **Unified results on search.** Typing collapses the year sections into ONE
  "Results" card holding every matching family card across in-scope years
  (newest year first). Clearing the box returns to the year browse.
- **Latest FY expanded, prior years collapsed.** On browse, the newest in-scope
  year card is open; every earlier year is a collapsed header the user expands
  by clicking. Toggle state persists across filter/search round-trips.
- **Single-document families (AFR, Exec Budget) get no dashed tray** — the
  report row already links the one document.
- **Removed elements (deliberate):** the per-card "Sort A→Z" menu (fixed
  title-A→Z order instead), the square `.doc-ic` icon tile on rows (publisher
  chip leads the row), the "N documents" sub-line under each report title, and
  the per-type divider headers.

## What you'll need to build

1. **A corpus listing endpoint.** Today there is *no* way to enumerate all
   documents. `GET /api/corpus/counts` returns counts only; `/api/search` needs
   a query. The page needs a **`GET /api/documents`** (budget corpus) returning
   every document's `doc_id, title, publisher, doc_type, fiscal_year, doc_url`.
   Source it from `store/documents.py`'s `load_documents()` (the sidecar
   reader — already cached, mtime-stamped, degrades safely). Use
   `title_for(doc_id)` for display titles so migration-era entries humanize
   correctly. Keep it un-gated like `/api/corpus/counts`. ⚠ Do **not** confuse
   this with the existing `app/routes/documents.py`, which is AI Mode's
   `create_document` download-token route (`/api/documents/{token}`) — a
   different thing; pick a non-colliding path (e.g. `/api/corpus/documents`).
2. **The page.** A new `webapp/src/pages/` component (or a rebuild of
   `Search.tsx`) implementing the mockup. Reuse `reportFamilies.ts` for
   grouping and `FilterBar`'s dropdown idiom for the rail. Client-side
   filter/search/sort over the listing payload (the corpus is a few hundred
   docs — no server round-trip per keystroke).
3. **The publisher migration** (OSPB/GAO/JLBC) — see above.
4. **Tests.** Follow `FiscalNotes.test.tsx` / `Search.test.tsx`: intercept the
   API with `vi.spyOn`, assert filtered rows are *removed* (not `display:none`),
   pin the two card states, the latest-year-expanded default, and the
   unified-results collapse. Mechanism in pytest; no LanceDB/ONNX in the suite.

## Constraints

- **Port, don't redesign.** The mockup's class recipes come from the app's own
  stylesheet; keep class names so existing CSS applies. New elements (the
  publisher chip, the collapsible year card) must reuse existing tokens — the
  mockup's header comment documents which recipes were borrowed.
- **Honesty invariants.** No result without a real `doc_url` renders a dead
  link; counts are what's actually shown; "Full report" only where a
  hand-verified URL exists.
- **Don't break the route's other consumers.** Home's hero and Ai.tsx navigate
  to `/search?q=…`. If the page changes shape, keep that hand-off working (a
  `?q=` arriving on the page should land in the unified search state).
- **Work in a worktree off master.** Commit the eval results files alongside
  code only if you touch retrieval — this task shouldn't. Never `uv run` in a
  worktree; use `.venv/bin/`.

## Done looks like

The Budget Documents tab auto-loads the browsable, year-grouped directory; the
rail filters and search behave exactly as the mockup demonstrates; tests pass;
`cd webapp && npm run build` is green; and the publisher chips read JLBC · OSPB
· GAO throughout the app.
