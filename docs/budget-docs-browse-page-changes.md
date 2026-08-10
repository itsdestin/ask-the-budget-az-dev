# Budget Documents browse page — what this branch changes

Branch `budget-docs-browse-page` (3 commits) vs. master.

## The old Budget Documents tab (what it used to be)

A retrieval-backed **results page**: a large centered search bar, Publisher /
Type / Fiscal Year filter chips, and a "type something to see anything"
blank state. Every keystroke + submit fired a `POST /api/search` query;
results came back as matched *passages* grouped into report-family cards,
with a "Part of the FY …" badge, expandable passage trays, and a click-through
to the PDF source panel.

## The new Budget Documents tab (what this branch ships)

A **browse-first directory** mirroring the Fiscal Notes layout. Same URL
(`/search`), same nav pill.

- **Auto-loads.** Opening the tab immediately shows every document in the
  corpus, grouped by fiscal year (newest first). No search required.
- **Sticky left rail** replaces the old centered search bar: a search box +
  two multi-select dropdowns (**Document Type**, **Fiscal Year**), each
  with honest counts and gold tinting when active.
- **Publisher filter removed.** Publisher survives as a copper chip on each
  row, in one color for everyone.
- **Collapsible year cards.** Newest year starts open; prior years start
  collapsed. Toggle state persists across search/filter round-trips.
- **One card per report family per year** (Baseline, Appropriations Report,
  AFR, Executive Budget, Budget Bill), each with two states:
  - *Idle:* the report IS the row ("FY 2027 Baseline"), with a dashed
    "Browse documents" tray for its contents and a "Full report" button
    where a hand-verified single-file URL exists.
  - *Searching:* the matched agency page is promoted to the top with
    "Part of the FY … " framing; other matches behind "N more matches".
- **Search collapses the year cards** into one unified "Results" card,
  newest year first. Clearing the box returns to the browse view.
- **Search is title/publisher matching, not retrieval.** The page loads one
  flat listing and filters it client-side — no server call per keystroke.
  Full-text passage search still lives in AI Mode. `?q=` from Home's hero
  still works and lands in the search state.
- **No passages, no source panel.** Rows link straight to the source PDF
  (or render unlinked when the URL is unknown — never a dead link).

## Publisher display migration

| Stored code (unchanged) | Old label | New label |
|---|---|---|
| `jlbc` | JLBC | JLBC |
| `governor` | Governor | **OSPB** |
| `agao` | AGAO | **GAO** |
| `legislature` | Legislature | **JLBC** (folded in) |

Display-layer only — `publisherLabel()` in `FilterBar.tsx`. Ingest, stored
sidecar codes, and `data/ingest-plan.yaml` are untouched.

## Backend

One new un-gated endpoint: `GET /api/corpus/documents` — every document's
`doc_id, title, publisher, doc_type, fiscal_year, doc_url`, sourced from
`store/documents.load_documents()`, titles via `title_for()`. Degrades to an
empty list on a missing/corrupt sidecar, never a 500. (Lives in the existing
`corpus.py` router alongside `/api/corpus/counts`.)

## Files touched

| File | Change |
|---|---|
| `app/routes/corpus.py` | + the listing endpoint |
| `tests/test_corpus_documents_route.py` | + 9 new tests |
| `webapp/src/api.ts` | + `corpusDocuments()` client |
| `webapp/src/pages/Search.tsx` | rewritten as the browse page |
| `webapp/src/pages/Search.test.tsx` | rewritten (15 tests) |
| `webapp/src/pages/Search.ai-mode.test.tsx` | updated |
| `webapp/src/styles/app.css` | + `.page-docs` block (+ spacing fix) |
| `webapp/src/components/FilterBar.tsx` | publisher labels only |
| `webapp/src/pdf/__tests__/search-source-panel.test.tsx` | deleted (old page's chunk drawer no longer exists) |

## Deliberately unchanged

The route `/search`, the nav pill, Fiscal Notes, AI Mode, Upload, ingest,
retrieval, eval — nothing outside the page itself.
