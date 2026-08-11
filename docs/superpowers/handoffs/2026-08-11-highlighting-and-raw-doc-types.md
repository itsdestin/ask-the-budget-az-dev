# Handoff — two open issues on the Budget Documents page

**Date:** 2026-08-11
**Status:** open, undecided. Nothing here has been designed yet.
**Landed as:** `f6f98bf` on master (branch `budget-docs-browse-page`, since deleted)

---

## How to use this document

Paste the section below into a new session, or point a session at this file.

> I have two open issues on the Budget Documents page of ask-the-budget-az.
> Read `docs/superpowers/handoffs/2026-08-11-highlighting-and-raw-doc-types.md`
> for the background — the facts in it were measured, not guessed.
>
> **Work through them with me before building anything.** Both are design
> questions with real forks, and issue 2 in particular may not be the problem
> it first looks like. Ask me one question at a time, propose approaches with
> tradeoffs, and get my approval on a design before writing a plan or code.
> Verify the claims in the handoff against the actual code rather than taking
> them on trust — some were measured a session ago and the corpus moves.
>
> Start with issue 1; it is smaller and independent.

---

## Background you need either way

The Budget Documents page (`/search`) is a browse-first directory of the whole
budget corpus, with one search box that works in two modes:

- **Title mode** filters the loaded listing client-side (title substring,
  publisher, and per-document shorthand terms, all-words matching).
- **Content mode** calls `POST /api/search` — real retrieval — and renders one
  card per document, headed by that document's best-matching passage quoted.

Both shipped 2026-08-11. Specs:
- `docs/superpowers/specs/2026-08-10-budget-documents-content-search-design.md`
- `docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md`

Repo conventions that bind any fix here (see `CLAUDE.md`):
- The owner is a **non-developer** and relies on WHY comments. A comment that
  contradicts the code is treated as a defect.
- **Never `dangerouslySetInnerHTML`** — snippets are corpus text, not trusted
  markup.
- Mechanism goes in pytest, quality in eval. **Any change under `retrieval/`,
  `ingest/`, `chunking/`, `citation/` or `harness/system-prompt.md` requires an
  eval run** (`uv run python -m eval.run_eval`, ~60s, needs `JLBC_DATA_DIR`,
  results committed with the diff).
- This repo distrusts hand-maintained lists that duplicate existing data. It
  has been bitten by two-lists-that-drift more than once.

---

## Issue 1 — query highlighting almost never fires

### What happens

Content-mode results quote a passage and are supposed to mark the query terms
inside it. In practice **nothing highlights** for any realistic question. A
search for "child care subsidy waiting list" returns twenty passages with zero
`<mark>` elements.

### Why

`webapp/src/search/contentSearch.ts::highlight(text, query)` searches for the
**entire query as one literal substring**:

```ts
const needle = query.trim().toLowerCase();
...
const at = haystack.indexOf(needle, i);
```

So it only marks anything when all the query's words appear consecutively, in
order, in the snippet. That is common for a one-word query and essentially
never true for a natural-language question — which is precisely the case
content search exists to serve, since the page only escalates to it when
*title* matching found nothing.

This is a defect in the original spec, not in anyone's implementation of it.

### Where the pieces are

| File | Role |
|---|---|
| `webapp/src/search/contentSearch.ts` | `highlight()` — returns `{text, hit}[]` runs |
| `webapp/src/search/contentSearch.test.ts` | its unit tests |
| `webapp/src/components/PassageCard.tsx` | `Quote` renders the runs as `<mark>`/`<span>` elements |

The runs-not-markup shape is deliberate and must stay: it is what keeps
`dangerouslySetInnerHTML` out of the codebase.

### What is genuinely undecided

**Splitting on whitespace is the obvious fix and it is not obviously right.**
If every word highlights independently, then "the", "of", "in", "for" light up
all over every passage and the marking becomes noise — arguably worse than
nothing, because it stops meaning "here is your answer".

Options worth weighing, none chosen:

- **Highlight every word.** Simplest, no new vocabulary. Accepts stopword noise.
- **Skip short/common words.** Needs a stopword list — a new hand-maintained
  list, which this repo has good reasons to distrust. Where would it live?
- **Ask the backend which terms matched.** BM25 already knows. `SearchResult`
  (`webapp/src/api.ts`) currently carries no match information — adding spans or
  matched terms would be an additive contract change, and touching `retrieval/`
  triggers the eval gate. More honest, more expensive.
- **Highlight the longest matching phrase**, falling back to words. Splits the
  difference; more code.

Also unresolved: should highlighting reflect what *retrieval actually matched*
(which may include stemmed or expanded terms the reader never typed), or only
what the reader literally typed? Those are different products.

### How to see it

Run the app (`cd webapp && npm run build`, then
`uv run uvicorn app.main:create_app --factory --port 9300` with `JLBC_DATA_DIR`
set), go to `/search`, and search something no document title contains — e.g.
`how much did child care subsidy cost`. It escalates to content search after a
two-second pause. Look at the passages.

---

## Issue 2 — 647 documents render under raw machine slugs

### What happens

The year cards show entries like **"FY 2027 s-pdf"**, "FY 2027 detailed-list-pdf",
"FY 2027 topic-pdf" as if they were report families alongside "FY 2027 Baseline"
and "FY 2027 Executive Budget".

### The counts (measured 2026-08-11 against the live corpus)

| doc_type | documents |
|---|---|
| `detailed-list-pdf` | 300 |
| `s-pdf` | 187 |
| `bd-pdf` | 112 |
| `bh-pdf` | 28 |
| `topic-pdf` | 20 |
| **total** | **647** |

### Why they show at all

`webapp/src/reportFamilies.ts` maps doc_types to display families. These five
have no entry, and `familyOf()`'s documented contract is that an unknown
doc_type **returns itself** rather than being dropped. `orderFamilies()` then
sorts them after the five curated families.

That behaviour is deliberate and was itself a bug fix on this branch: these
documents used to be **counted but never displayed**, so the page's counts
disagreed with what was on screen. Showing them honestly is the improvement.
Showing them as `s-pdf` is the leftover.

### The reframe — check this first

**These are probably not report families at all.** Their titles already say what
they belong to:

```
detailed-list-pdf  "Capital Outlay — FY 2005 Appropriations Report"
                   "Summary of Rent Charges — FY 2005 Appropriations Report"
bd-pdf             "Summary of Additional Operating Appropriations — FY 2005 Appropriations Report"
bh-pdf             "FY 1997 - FY 2007 'Then and Now' Comparisons — FY 2007 Appropriations Report"
topic-pdf          "FY 2006 Budget Reconciliation Bills — FY 2006 Appropriations Report"
s-pdf              "General Fund - Detailed List of FY 2012 Changes — FY 2012 Baseline"
```

Every one is a **section of the Baseline or the Appropriations Report** — the
same books the page already renders as top-level reports with their agency
sections in a tray. JLBC publishes them as separate PDFs (hence separate
doc_types at ingest), but to a reader they are chapters of a book that is
already on the page.

So the question may not be "what do we call `s-pdf`" but **"should these be
folded into the Baseline and Appropriations Report cards as sections?"**

Verify before designing:
- Does every one of the 647 map cleanly to exactly one book+year? The titles
  suggest yes; confirm it, and find the exceptions.
- What does `doc_type` mean at ingest for these — is the distinction between
  `bd-pdf` and `bh-pdf` load-bearing anywhere else (retrieval filters, the
  `SearchResult.doc_meta` line, the doc-type registry)?
- `SearchResult` carries a `doc_meta` field described as the mockup index's
  meta line ("Agency Budget Detail · Appropriations Report · FY 2025"). Does
  that already contain a human name for these? It may be the display source
  nobody has used.

### What is genuinely undecided

- **Fold vs. name.** Folding them into the parent book is more honest to what
  they are, but changes the page's report counts (FY 2027 would show fewer
  top-level reports and larger section trays) and touches grouping logic that
  was carefully fixed on this branch. Naming them is smaller but leaves five
  odd families on the page forever.
- **If folding: which tray?** Baseline and Appropriations Report cards already
  have a "Browse sections" tray holding per-agency pages. Do these join it, or
  does a book need two groups (agency pages vs. topic sections)?
- **If naming: what are they?** Nobody in the project currently knows what
  `bd`, `bh` and `s` stand for. That is a research question against JLBC's site
  before it is a code question.
- **What about search?** These 647 are findable today by title. Whatever
  changes, they must stay findable — the branch's hardest constraint was that
  nothing may remove a match that works.

---

## Things not to redo

- The counts on this page are **reports**, derived from what renders. An
  earlier bug had them computed separately and disagreeing; do not reintroduce
  a second count.
- Empty states must name only conditions that are true. "Try clearing a filter"
  appears only when a filter is set.
- Both of these issues were found *after* review and merge, by looking at the
  running app rather than at tests. 2,999 tests pass and neither issue trips
  one. Look at the app.
