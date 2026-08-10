# Budget Documents — content search, the format chooser, and the browse-page regression fixes

**Date:** 2026-08-10
**Status:** Approved 2026-08-10 — no open decisions. Regression fixes R1–R4 are BUILT and passing on branch `budget-docs-browse-page`; F1 and F2 are designed and mocked, not built.
**Branch:** `budget-docs-browse-page`
**Amends:** `2026-07-29-standalone-consolidation-design.md` decision **S12**, whose 2026-07-30 amendment froze the search RESULTS presentation. This spec supersedes that amendment for the Budget Documents page only; Fiscal Notes and AI Mode are untouched.

## Why

The 2026-08-03 browse-first rebuild of the Budget Documents page replaced a
retrieval-backed results page with a client-side title filter. That was the
right call for browsing — the old page's "type something to see anything"
blank state was a dead end — but it silently dropped things nobody asked it to
drop, and a review on 2026-08-09 found nine of them.

Four were correctness bugs with no design content; they are fixed. Two were
features: full-text search over document CONTENTS, and the Linked Table of
Contents vs Single File PDF chooser. This spec covers rebuilding both on top
of the browse page rather than reverting to the old one.

The North Star applies directly. **Retrieval with auditable provenance** is
what this system is for; a Budget Documents page that cannot search inside a
document, and cannot show you the page a sentence came from, is not doing the
job. Core Invariant 1 — every claim auditable, citations linking to the exact
PDF page — is the reason F1 ends at a rendered page with a highlight and not
at a snippet.

## What was already lost, and what this spec restores

| # | Regression | Status |
|---|---|---|
| R1 | Empty state blamed filters that were never set | **Fixed** |
| R2 | Counts included silently-dropped documents | **Fixed** |
| R3 | Fiscal notes leaked into the budget document listing | **Fixed** |
| R4 | 259 lines of dead CSS + 3 orphaned modules | **Fixed** |
| F1 | Full-text / retrieval search, passages, and the in-app PDF viewer | **This spec** |
| F2 | Linked TOC vs Single File PDF chooser | **This spec** |
| O1 | `?q=` no longer written — searches unlinkable, back button dead | **This spec (D11)** |
| O2 | Publisher filter removed | **Deferred** — Destin called it deliberate; revisit if "Governor" not finding OSPB documents becomes a real complaint |
| O3 | Home's "searched full text" card copy | **Closed** — Destin, 2026-08-10: leave it |

---

## Part 0 — the regression fixes (built)

Recorded here because F1 and F2 build on them, and because two of them changed
user-visible vocabulary that the rest of this spec assumes.

**R1 · Honest empty states.** Three distinct facts now get three distinct
lines. "Try clearing one" appears only when a filter is actually set. An empty
listing says *"No budget documents are available."* and deliberately names **no
cause**: `/api/corpus/documents` degrades a missing sidecar AND an unreadable
chunk table to the same empty list and cannot tell them apart, so any "nothing
has been ingested yet" would be a guess. `app/health.py` is the surface that
distinguishes empty from broken — this is the module's own documented posture,
carried over from `chunk_counts`.

**R2 · The page counts REPORTS, not sections.** A Baseline book is one report
ingested as ~100 per-agency documents. `5 reports · 419 documents` was counting
the agency pages. Every count is now the number of top-level reports — one per
report family per fiscal year — and is **derived from what actually renders**,
not recomputed from the raw list. Two consequences:

- The old count was computed independently of the render and could disagree
  with it. It did: `groupCorpus` dropped any family outside the curated five
  while the status line still counted its documents. Unknown families now
  render (after the five, alphabetically) and appear in the Document Type
  filter, which also makes `familyOf`'s documented contract true again.
- **Vocabulary:** the things inside a report are **sections**, not documents.
  "N sections in this report", "Browse sections" / "Hide sections". Calling
  them documents contradicted every count above it.

**R3 · Corpus filter on the listing.** `documents.json` is ONE sidecar for both
corpora — `ingest/lance_writer.py::_merge_document_entry` writes the same file
for a Baseline book and a fiscal note (worker.py's single `write_doc` call
serves both tables), and the record carries no `corpus` field. `/api/corpus/documents`
now reads membership from `budget_chunks` via a one-column projection scan.

Chosen over a `doc_type == "fiscal-note"` denylist deliberately: a denylist is
only as good as the list, and `/api/upload` accepts any registered doc_type
against either corpus, so a note filed under another type walks straight
through. Cost is one scan per page load — `ChunkStore.scan`'s docstring
measures the full budget corpus at ~60ms with six columns.

**R4 · Deleted.** `components/FilterBar.tsx`, `components/ResultCard.tsx`,
`FILTER_BUCKETS`, and 259 lines of `.page-search` CSS (the page block, the
filter dropdown rail, the report-format chooser modal). Every selector was
scoped under a class no component had rendered since the rewrite.
`publisherLabel` moved to `webapp/src/publishers.ts` — a display vocabulary is
not a component. **`pdf/SourcePanel.tsx` was deliberately kept**: F1 re-wires it.

---

## Part 1 — F1, content search

### The shape

One search box, two modes, and an escalation between them.

**Title mode** (default). Instant, local, no server call: case-insensitive
substring against document title or publisher display label, exactly as today.

**Content mode.** `POST /api/search` against the budget corpus — the existing
retrieval pipeline, untouched. Returns matched passages with page numbers and
chunk ids.

**Escalation, two paths:**

- **Automatic** — when the title filter returns **exactly zero** and the user
  has stopped typing for **2000ms**, content search fires on its own. The reasoning:
  a natural-language question essentially never substring-matches a title,
  while an agency name almost always does, so "zero title hits" is an honest
  proxy for "this was a content question." The escalation reads as intelligent
  rather than as a fallback.
- **Manual** — a gold pill below the results, always present once the box has
  text, matching Fiscal Notes' "Search all legislative sessions" control
  (`.allbar`/`.allbtn`, already in `app.css`).

### Decisions

**D1 · Content results REPLACE title results.** Not appended. The toggle's two
faces are `Search document contents` and `↩ Back to title matches`, the same
label swap Fiscal Notes uses (`.all-off`/`.all-on`). Append was rejected
because it mixes two kinds of row with different meanings in one card, and
because the auto-escalation path has no title matches to append to — it would
produce two different-looking outcomes for one feature.

**D2 · The toggle is ALWAYS shown once the box has text**, including on both
empty states. Toggling back to titles on a query with no title matches shows
the empty state *with the toggle still there*. It is never a dead end.

**Exception:** the toggle is hidden while content search is in flight. There
is nothing to toggle to while the answer is pending, and offering it invites a
click that cancels work the user did not ask to start.

**D3 · The header names the mode.** `Results (searching document titles)` /
`Results (searching document contents)`. Without it there is no way to tell
which search produced the list on screen.

**D4 · The rail's filters constrain retrieval, passed to the BACKEND.** Not
applied to its answer. Applied afterward, retrieval would find its best 20
passages corpus-wide and the filters would discard 18, leaving two weak results
instead of the best two *in scope*. Requires a family-name → doc_type-slug map
(the inverse of `FAMILY_OF_DOC_TYPE`); `fiscal_year` passes through as-is.

**D5 · The result card is passage-first, one card per DOCUMENT.** Two
documents from the same report in the same year (AHCCCS FY2027 Baseline and
Health Services FY2027 Baseline) are two cards. One document never gets two
cards.

- **Headline row:** the best matching passage, quoted, query term highlighted
  with the gold wash, publisher chip left, page number as a right-hand
  `.doc-pill`.
- **Dashed block:** publisher chip, document title, and exactly ONE action —
  **More from this document**. No "Open document", no "Full report". No book
  glyph before the title.
- **Expanded passages:** white tiles, gapped, **no divider line** above the
  first one — the identity row and the tiles are one continuous surface.

Rejected alternatives, and why, from `mockups/retrieval-results-variants.html`
and `mockups/retrieval-expanded-passage-stylings.html`: nested-tray (the thing
you searched for hides one click deep), best-passage-inline (draws two equal
passages differently), split reader (half the width empty until you click),
and for the tiles: numbered (implies a ranking the numbers don't mean),
page-headed (page numbers stop scanning down a fixed column), banded (~1%
luminance difference, near-invisible), ruled (an accent that looks like it
encodes something and doesn't).

**D6 · Clicking a passage opens the source in-app.** `SourcePanel` →
`SourceView` → the rendered PDF page with the passage highlighted, plus the
always-visible cited-text panel. This is Core Invariant 1's verification
surface and it already exists and already runs in AI Mode; F1 re-wires it, it
does not rebuild it. The DOCX/no-page-image case (budget bills) is already
handled by `SourceView`'s `pdfUnavailable` branch and must not be re-invented.

**D7 · The clickability cue is the arrow pill (A1).** The `p. 142` pill gains
a chevron and lights gold on row hover, matching the browse rows' "Open" pill.
**Ships with a keyboard path** — the row must be focusable and open on Enter.
The old page had exactly that and the rewrite deleted it along with its test;
provenance is the one path that must not require a pointing device.

### Spacing (settled by eye, 2026-08-10)

```css
/* .page-docs — retrieval result card, expanded passages */
.page-docs .ctx-row{padding-bottom:10px;}
/* `.open` is load-bearing: the base `.tray.open{display:block}` outranks a
   plain `.tray` selector, and block layout SILENTLY IGNORES gap. */
.page-docs .ctx .tray.open{padding:0 14px 12px;
  display:flex;flex-direction:column;gap:5px;}
.page-docs .ctx .tray .doc{background:#fff;border:1px solid var(--line);
  border-radius:var(--r-sm);padding:10px 14px;box-shadow:var(--shadow-sm);}
.page-docs .ctx .tray .doc:hover{border-color:var(--az-gold);background:#fff;}
```

The gap above the first tile is the identity row's own `padding-bottom`, not a
tray `padding-top` — one number instead of two that have to agree, and the
collapsed state stays correct with no tray to pad.

### Loading state

Replaces the empty-state line the moment the title filter hits zero: a spinner,
**"Searching document contents"** with a rolling-and-resetting ellipsis, and a
sub-line saying why it is slow ("reading inside every ingested PDF"). Honors
`prefers-reduced-motion`.

### Empty states

| Situation | Copy |
|---|---|
| No title matches, no filters | No document titles match "q". |
| No title matches, filters set | No document titles match "q" with those filters — try clearing one. |
| No content matches, no filters | No passages inside the ingested documents mention "q". |
| No content matches, filters set | …same, + "Try clearing a filter." |

Each names **what was searched**, so an empty result never reads as "the corpus
says nothing about this" when only titles were checked.

---

## Part 2 — F2, the report format chooser

JLBC publishes an annual report two ways: a **Linked Table of Contents** index
page whose every agency/section opens its own smaller PDF, and the complete
**Single File PDF**. The rewrite kept the gold "Full report" button but wired
it straight to `singleFile`, making `linkedToc` unreachable data.

**Scope: browse and title-search cards only.** The retrieval card (D5) traded
both buttons for "More from this document" and stays that way.

**D8 · "Full report" replaces the top-line "Open" pill**, gold-filled. The
top-line row IS the report, so its action is the report. The duplicate button
is removed from the dashed block, which keeps only "Browse sections".

**D9 · The rule, unchanged from master:**

| Formats available | Behaviour |
|---|---|
| Both | Offer a choice |
| Exactly one | Link straight to it — a one-option chooser is pointless |
| Neither | No pill; the row renders unlinked, never a dead href |

**How thin the data is:** only THREE families have a verified `linkedToc` —
FY27 Baseline, FY26 Baseline, FY25 Appropriations Report. Hand-verified,
exact-match, no fuzzy matching, because a wrong PDF behind an "open the report"
button violates the auditability invariant. **The one-format path is the common
case**, and both presentations must be judged on how they behave when the
chooser does *not* fire.

**D10 · Presentation — the MODAL (M1).** Destin, 2026-08-10. Both candidates
are in `mockups/report-format-chooser.html`; the modal won because it refuses
to pick a default and has room for the copy that actually matters — most
readers do not know what a "Linked Table of Contents" PDF is, and "best for
jumping straight to one agency without downloading the whole report" has
nowhere to live in a pill.

**What the modal costs, and must therefore be built:** a **focus trap** and
**Escape** handling, since it is the only modal on a page where every other
control is inline. One structural consequence: on a both-formats card the
top-line row cannot stay an `<a>` — an interactive pill nested inside a link is
invalid markup — so it renders as a `<button>` with UA resets, visually
identical to the links beside it.

**REJECTED — M2 · Inline row.** Top-line "Full report" goes straight to the
single file; the dashed block grows an "Also available" row offering the TOC
with one line of explanation. Cheaper (no dialog, no focus trap, row stays a
link) but it picks a default on the user's behalf and shrinks the explanation
to one line. Kept in the mockup as the rejected alternative.

**Implementation trap, already hit once:** every `.report-modal` rule is scoped
under the page class. A `position:fixed` overlay mounted OUTSIDE
`<main className="page-docs">` gets no styling and paints as an unstyled block.
The old `Search.tsx` rendered `SourcePanel` inside `<main>` for this reason.

---

## Part 3 — D11, URL state

Today the query lives only in component state. Consequences, all real:

- Searches cannot be linked, shared, or bookmarked.
- The back button does not walk through searches.
- A concrete dead end: arrive from Home with `?q=medicaid`, clear the box, go
  Home, search "medicaid" again → `urlQuery` is unchanged, the sync effect does
  not re-fire, and you land on the browse view with an empty box. Master had an
  `attempt` counter specifically to kill this bug class; the rewrite removed it.

**DECIDED — write both the query and the mode.** `?q=medicaid&in=contents`,
with `in=titles` as the default and therefore omitted from the URL.

Destin, 2026-08-10: "idc about the url" — taken as delegated, not dropped, and
recorded here so the reasoning is auditable rather than assumed. Two reasons
not to simply skip it:

1. **The dead end is a bug regardless of whether anyone shares links.** Arrive
   from Home with `?q=medicaid`, clear the box, go Home, search "medicaid"
   again → empty box, browse view. Fixing that needs either URL state or a
   restored `attempt` counter; doing the URL properly gets both.
2. **The mode costs nothing extra once `q` is there**, and a link that reopens
   a *title* filter when the sender meant a passage list is a silent wrong
   answer — the failure mode this codebase exists to avoid.

Build it into the Stage 2 plumbing; it is awkward to retrofit through a
debounce and a two-mode toggle.

---

## Implementation staging

Each stage leaves the app working and independently verifiable.

**Stage 0 — commit the regression fixes.** Built, green, self-contained, no
dependency on anything below.

**Stage 1 — F2, the format chooser.** A small change confined to `Search.tsx`
plus the recovered CSS and a modal component. Smallest piece, closes the
regression Destin flagged first, and touches no code F1 needs.

**Stage 2 — F1 plumbing.** Re-wire `api.search`, the family→slug filter map,
the debounce, the escalation trigger, URL state (D11). No new UI; verifiable by
tests alone.

**Stage 3 — F1 result card.** The passage-first card, tiles, toggle, mode
label, both empty states, the loading state.

**Stage 4 — F1 source drawer.** Re-wire `SourcePanel`, the arrow pill, the
keyboard path. Mostly restoring deleted wiring, including a test deleted with
it (`pdf/__tests__/search-source-panel.test.tsx`).

## Testing

Per CLAUDE.md: **mechanism in pytest, quality in the eval.** F1 changes no
retrieval code, so **no eval run is required** — `retrieval/`, `ingest/`,
`chunking/`, `citation/` and the system prompt are all untouched. If that
stops being true, the eval gate applies.

Guards worth having, one per decision that could silently rot:

- Escalation fires only at zero title hits, and only after the debounce
- The toggle is present on both empty states and absent while in flight
- Filters reach `api.search` as doc_type slugs, not family names
- A passage click opens the drawer **from the keyboard**
- The chooser modal traps focus and closes on Escape (D10's stated cost —
  the one guard that keeps "we'll add the focus trap later" from shipping)
- A both-formats card's top-line row is a `<button>`, not an `<a>`
- `?q=` round-trips, and re-running an identical query still fires (D11)
- `budget_doc_ids` excludes fiscal notes *(done)*
- Counts equal rendered reports *(done)*

## Non-goals

- Changing retrieval ranking, chunking, or the citation pipeline
- Touching Fiscal Notes, AI Mode, Upload, or the admin surfaces
- The publisher filter (O2) and Home's card copy (O3)
- A format chooser on the retrieval card (explicitly deferred)

## Mockups

All in `mockups/`, self-contained, opened directly in a browser. The
`.page-docs` CSS in each is copied verbatim from `app.css` so the cards render
exactly as the app renders them.

| File | What it settled |
|---|---|
| `retrieval-results-variants.html` | Passage-first over three alternatives |
| `retrieval-passage-first-stylings.html` | S1's quote + S2's identity row |
| `retrieval-expanded-passage-stylings.html` | Tiles over four alternatives |
| `retrieval-result-card.html` | The spacing, dialled in on live sliders |
| `retrieval-source-drawer.html` | The drawer + the A1 affordance |
| `retrieval-states-and-toggle.html` | All five states, the toggle, the mode label |
| `report-format-chooser.html` | F2 — the modal (M1) won; M2 kept as the rejected alternative |
