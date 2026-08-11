# Budget Documents page — what this branch changes

Branch `budget-docs-browse-page` vs. master. Three pieces of work, in order:
the browse-first rewrite, then an audit of what it broke, then putting back
the two things it dropped.

Specs: `docs/superpowers/specs/2026-08-10-budget-documents-content-search-design.md`
and `2026-08-11-title-filter-shorthand-design.md`.

## Where it started

A retrieval-backed **results page**: a large centered search bar, Publisher /
Type / Fiscal Year filter chips, and a "type something to see anything" blank
state. You had to know what to type before the page showed you anything.

## What it is now

A **browse-first directory** that also searches, on the same URL (`/search`)
and the same nav pill.

- **Auto-loads.** Opening the tab shows every budget document, grouped by
  fiscal year, newest expanded. No dead end.
- **Sticky left rail** — a search box plus Document Type and Fiscal Year
  multi-selects. No Publisher filter; publisher is a chip on each row
  (JLBC · OSPB · GAO).
- **One card per report family per year.** The top-level row IS the report;
  its agency sections sit behind a "Browse sections" tray. Single-document
  families (the AFR) get no tray.
- **"Full report"** on each report row. Where Arizona published both shapes,
  it opens a chooser — one single-file PDF, or the linked table of contents.
  Where only one exists it goes straight there. Where neither does, the row
  renders unlinked, never a dead link.

### One search box, two modes

- **Title mode** filters the loaded listing client-side — no server call per
  keystroke.
- **Content mode** calls the existing `POST /api/search`. It escalates on its
  own two seconds after the box goes quiet with zero title hits, and the
  moment it arms, the page says so — spinner and all — rather than showing a
  no-results message it is about to replace.
- A toggle is always visible, both directions, and declining an escalation
  does not re-fire it.
- Content results are **one card per document**, headed by the best-matching
  passage quoted rather than the document's title. Clicking a passage opens
  the PDF drawer at that page.

### The filter box understands analyst shorthand

`dema` matched **0** of 5,330 documents before this; it now matches 38.
`26ar dema` finds exactly the FY 2026 DEMA Appropriations Report.

Every whitespace-separated word must match — the title by substring (so
`ahccc` still works), the publisher by substring or stored code (so
`governor` works, not just `OSPB`), or one of the document's search terms
exactly. Terms are the agency's JLBC slug and reviewed aliases plus the
report type's shorthand, computed server-side from `samples/entity-catalog.yaml`
so JLBC's convention has one implementation rather than two.

Shorthand forms: `ar`, `baseline` (JLBC's own, from `azjlbc.gov/26AR/`), plus
`br`, `afr`, `exec` (ours). No budget-bill form. Bare and year-prefixed both
work (`br`, `26br`).

## Four regressions the audit found and fixed

1. **Fiscal notes leaked in.** One sidecar serves both corpora and records no
   corpus, so the listing handed fiscal notes to the budget page. Membership
   now reads from `budget_chunks` — the fact, not a doc_type guess.
2. **Empty states blamed filters that weren't set.** "Try clearing one" now
   appears only when a filter is set; an empty listing names no cause,
   because the route cannot tell an un-ingested corpus from an unreadable one.
3. **Counts disagreed with the screen.** They counted agency sections as
   documents and were computed independently of what rendered. They now count
   top-level **reports**, derived from the render.
4. **Unknown doc_types vanished** — counted but never displayed. They now
   render under their raw slug after the curated families.

## Backend

- `GET /api/corpus/documents` — the listing. Now carries `terms` per row and
  is restricted to the budget corpus.
- `app/search_terms.py` — new. Computes a document's search terms; owns the
  suppression maths reused from `retrieval/query_agency.py`.
- `retrieval/query_year.py` — `SHORTHAND_DOC_TYPE` gained `br`/`afr`/`exec`
  and became public. **This is the only eval-gated change**; the eval was run
  and recall held (recall@5 0.88095, unchanged; @15 and @20 at 1.0).

Nothing else moved: `/search`, the nav, Fiscal Notes, AI Mode, Upload,
ingest, chunking and citation are untouched.

## Known, accepted

`26 exec` parses as the FY 2026 Executive Budget and hard-filters the query —
including in prose like "page 26 exec summary". Accepted knowingly
(Destin, 2026-08-11); the reasoning and the declined narrowing are recorded
under D9 of the shorthand spec.

647 documents render under raw doc_type slugs (`s-pdf`, `bd-pdf`,
`detailed-list-pdf`, `topic-pdf`, `bh-pdf`) because nobody has given those
types display names. Visible rather than silently dropped, which is the
improvement — but "FY 2027 s-pdf" is not a phrase to show a student.
