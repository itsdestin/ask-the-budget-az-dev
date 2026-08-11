# Budget Documents — query highlighting and book sections

**Date:** 2026-08-11
**Status:** designed, approved by Destin. Not yet implemented.
**Supersedes:** the two open issues in
`docs/superpowers/handoffs/2026-08-11-highlighting-and-raw-doc-types.md`
**Branch:** `budget-docs-highlighting-sections`, off `f6f98bf`

Two defects on the Budget Documents page (`/search`), both found by looking at
the running app after 2,999 tests passed. They ship together because they are
one reader's complaint about one page, but their file sets are nearly disjoint
and the plan may run them as parallel tracks.

Every number below was measured against the live corpus on 2026-08-11 (7,434
documents, 77,574 budget chunks) using ten realistic natural-language
questions and their top-20 results — 200 to 240 cards depending on the round.
The scratch scripts are not committed; each measurement is reproducible from
the description given with it.

---

## A note on how these decisions were reached

Three times in one design session, a measurement that counted **how often a
rule produces an answer** disagreed with **how often the answer is right**:

| what was counted | reading | what was actually true |
|---|---|---|
| a match-centred window shows more query terms on 32% of cards | "the window is the fix" | those windows are usually WORSE — they drop the heading and the dollar figure |
| the doc_id yields a parent book for 647 of 647 sections | "doc_id is the parent" | it is WRONG on 21 of them |
| citation linking's 92.9% coverage (historical) | "the linker works" | 34.2% of links pointed at the wrong document |

The rule this repo already knows — gate on the error rate, not the production
rate — is restated here because it caught two live design errors in one
sitting. **Any acceptance criterion below that counts productions is wrong and
should be replaced before it is used.**

---

## Part 1 — Query highlighting

### The defect

`webapp/src/search/contentSearch.ts::highlight()` searches the snippet for the
**entire query as a single literal substring**. Marks appear only when every
word of the question appears consecutively and in order.

**Measured: 0 of 200 cards produce a single `<mark>`.** Not "rarely" — never,
for any of the ten questions. Content mode is exactly where this matters,
because the page only escalates to it when title matching found nothing.

### The decisions

**H1. Mark every word the analyst typed. No stopword list, no length rule, no
vocabulary of any kind.**

Four candidate rules were measured, all with word-boundary matching, counting
marks inside one rendered card:

| rule | marks per card | cards with no mark |
|---|---|---|
| every typed word | 6.0 | 2.9% |
| hand-maintained stopword list | 5.2 | 2.9% |
| length ≥ 4 chars | 4.8 | 2.9% |
| length ≥ 4 **or** typed in caps | 4.9 | 2.9% |

**The blank rate is identical across all four.** Dropping function words
rescues no card; it only moves mark density by about one mark in a window of
roughly 45 words. So this is a cosmetic preference, not a functional one —
which is a demotion from how the handoff framed it, and the reason the cheap
answer wins.

A length rule was rejected on evidence, not taste: `≥ 4 chars` silently drops
`aid` (as in *basic state aid*) and `des`, which are exactly the terms this
domain is about. "Or typed in caps" only rescues them when the analyst shifts,
which they mostly will not.

A stopword list was rejected because it buys about one mark per card in
exchange for a hand-maintained list, in a repo that has twice shipped the
two-lists-that-drift bug. "We underline the words you typed" is also a sentence
a non-developer maintainer can hold, and every mark on screen is
self-justifying because the reader put it there.

**Do not borrow `_LOGICAL_KEY_STOPWORDS` from `retrieval/query_agency.py`.** It
exists for agency-catalog dedup and was measured for that. Reusing a list for a
purpose it was never measured against is the same drift trap wearing a
different hat.

**H2. Match on word boundaries, not substrings.** This is the change that
actually matters for noise. Naive substring matching runs 8.3 marks per card
and peaks at 31, because short words match inside longer ones. Boundaries take
that to 6.0 and cap it at 14.

**H3. The preview stays the LEADING text of the passage. A match-centred
window is a fallback, never the default.**

This reverses the obvious fix, on evidence. JLBC front-loads these documents by
construction: every chunk opens with a section heading, then "The Baseline
includes $X for Y", then background prose. The leading characters *are* the
summary — which is also why the median first query-word match sits at
character 5 and only 3.5% of cards lose their mark to truncation.

Reading the windows rather than counting terms in them:

```
QUERY: how many prison beds are funded

leading   "Florence Replacement Beds
           The Baseline includes an increase of $22,500,000 from the General
           Fund in FY 2023 for the second-year costs of new private prison…"

centred   "for the second-year costs of new private prison beds to replace
           beds removed from service in the partial Florence prison closure.
           (See the Florence Prison section.) Background – This line item…"
```

The centred window scores higher on term count and throws away both the heading
and the dollar figure. A second case shifted the window ten characters to gain
one term and chopped "Enrollment Changes" into " Changes". Optimising for terms
visible rewards drifting into dense prose and away from the headline.

**H4. Fall back to a match-centred window only when the leading text contains
no typed word at all** — 3.5% of cards. The reader is otherwise shown a passage
with no visible reason for being there. Falling back is explainable in one
sentence; defaulting to it is not.

**H5. The window snaps to word boundaries and carries a leading ellipsis when
it does not start at the beginning of the passage**, so a slid window never
impersonates the start of the document.

**H6. Nothing is invented for the no-match case.** About 3% of cards contain
none of the analyst's words anywhere in the chunk — they ranked on the dense
leg alone. Those render with no marks. An honest absence beats a guess.

**H7. Do NOT derive "which terms matched" from the backend.** BM25 knows its
own matched terms, but ranking is BM25 + dense + RRF + rerank and a passage can
reach the top of the page on the dense leg with no lexical overlap. It would be
silent precisely when the reader most wants to know why a passage is there.

A related idea was measured and is decisively dead: **"only mark terms that are
rare across the twenty results" collapses to 0.4 marks per card and 70% blank
cards**, because it drops `ahcccs`, `child`, `subsidy`, `wildfire`, `prison` —
every word that made the passages rank. Retrieval has already filtered to
passages that share the topic, so within a result set the most relevant terms
are the most common ones. **Any "let the data decide which words matter" scheme
fails for this reason.**

### Where the work happens

**H8. `SearchResult` gains the full chunk text as an additive field. The
browser picks the window AND paints the marks.**

The alternative — server picks the window, browser paints the marks — puts
"which words count" in two languages, and its failure is silent: a snippet
obviously chosen *because* of the match, with nothing marked in it, no test
red. Returning server-computed mark offsets was also rejected: it makes the
browser dumb, so any later UI change needs a server round-trip, and it adds
offset-arithmetic contract surface of exactly the kind the citation work spent
a month getting wrong.

Cost is about 18KB per search (chunk text median 789 chars, mean 907, max
2,117; twenty results). Verified safe to ship as text: **0 of 4,000 sampled
chunk `text` values contain any HTML markup** — table markup lives in the
separate `table_html` column, which is not shipped. 41% of chunks are tables,
and their `text` is tab-delimited plain text, so a table previews as columns of
tabs rather than as a grid. It is public-record budget text with no confidentiality dimension.

It also buys expand-in-place for free.

**H9. The card expands in place to the full passage, marks and all.** No second
fetch. This is where the 3% of no-mark passages land honestly — the reader can
see for themselves that the match was semantic.

**H10. Runs, not markup.** `highlight()` keeps returning `{text, hit}[]` and
the component renders real elements. `dangerouslySetInnerHTML` stays out of
this codebase; the snippet is corpus text, not trusted markup.

**H11. The Fiscal Notes page is unchanged.** `LanceSearchProvider.search()` is
the single snippet producer and serves both corpora, so this is a deliberate
carve-out, not an oversight: that page does no highlighting today and giving it
some is a separate decision. Recorded as a follow-up.

---

## Part 2 — 647 documents under raw machine slugs

### The defect

The year cards show "FY 2027 s-pdf", "FY 2027 detailed-list-pdf" and three
others as if they were report families beside "FY 2027 Baseline".

Counts reproduce the handoff exactly: `detailed-list-pdf` 300, `s-pdf` 187,
`bd-pdf` 112, `bh-pdf` 28, `topic-pdf` 20 — **647 documents**.

### These were never document types

The doc_id stems are literally `bd1…bd10`, `bh11`, `s1`, and the mangled
table-of-contents titles carry the matching page references:

```
"Summary of Total Spending Authority … BD-10"
"General Fund Budget 4-Year Analysis … BH-11"
"Statement of General Fund Revenues and Expenditures … S-1"
```

**They are JLBC's own printed page-number prefixes.** BD-x and BH-x are page
ranges in the Appropriations Report; S-x is the Baseline's summary section.
`ingest/lance_writer.py` already says as much in a comment — the `-pdf` suffix
is "a corpus-internal marker for which JLBC index page a document came off, not
something an analyst should ever read."

`topic-pdf` is the exception and is genuinely topical: `capitaloutlay`, `crr`
(Consolidated Retirement Report), `appropveto`, `fy06brbs`.

### The decisions

**B1. Fold them into their parent book. Do not name them.**

Every one is a chapter of a book already on the page, and **all 38 distinct
parent book+year pairs exist as real books in the corpus** — folding orphans
nothing.

**B2. The parent comes from `source_url`, not from `doc_id` and not from the
title.**

| candidate | parses | correct |
|---|---|---|
| `doc_id` prefix | 647/647 | **wrong on 21** |
| title suffix | 603/647 | agrees with source_url on all 603 |
| **`source_url` book directory** | **647/647** | **0 conflicts with the title** |

The 21 failures are the `make_doc_id` family-collision class STATUS.md already
documents — Baseline sections minted with an approps doc_id.
`jlbc-approps-fy2022-497` is titled *"General Fund Revenue — FY 2022 Baseline"*
and lives at `azjlbc.gov/22baseline/497.pdf`. STATUS.md names four of them
(`jlbc-approps-fy2027-{502,507,517,522}`); there are 21.

`source_url` is the only independent evidence — the URL JLBC actually published
the section at. The title corroborates it on every document that has a
parseable one, and the doc_id is the lone outlier. Resulting split:
**Appropriations Report 389, Baseline 258.**

**Neither the doc_ids nor the 21 collisions are repaired here.** Repairing them
means re-minting doc_ids, which re-points chunk_ids and eval ground truth. This
change reads around the defect and records it; the repair is its own work with
its own re-ingest question.

**B3. `familyOf` cannot stay a pure `doc_type → family` map.**
`detailed-list-pdf` splits 255 approps / 45 baseline and `topic-pdf` splits
14 / 6, so the family depends on the document, not on its type. The listing
carries what is needed; the derivation belongs on the server, next to the data
that defines it and beside `app/search_terms.py`, which already made this
choice for the same reason.

**B4. A book shows two groups: agency pages and summary sections.** Books gain
20–24 sections against the 112–150 agency pages they already carry. Twenty
topical sections dropped into a list of a hundred and fifty agency entries are
buried, and "Capital Outlay" and "General Fund Revenue" are exactly the
cross-cutting pages an analyst hunts by name. It also mirrors how the book is
printed: the BD/BH/S pages are a front section, not agency entries.

**B5. Content-mode filtering stays exact, by filtering in the provider.**

Browse mode is client-side over the full listing, so its filtering is exact for
free. Content mode sends `doc_type` slugs to `/api/search`, and a Baseline
filter would send `detailed-list-pdf` — pulling in up to 269 approps sections.

`app/search_provider.py` already reads the documents sidecar per result
(`self._info(c.doc_id)`), so it can compute the exact family and drop
cross-family leakage there. This is `app/`, not `retrieval/` — **no eval gate,
no ranking change.** Dropping here removes only results the reader explicitly
filtered out, which is honouring a filter, not losing a match.

The pool shrinks after filtering, so the provider must over-fetch when a family
filter narrows to an ambiguous slug. **The over-fetch factor must be measured,
not guessed** — a fixed multiplier chosen by eye is how a page quietly returns
twelve results where it promised twenty.

**B6. Nothing may stop being findable.** The 647 are reachable today by title
in the filter box and by content search. Both must still reach them after
folding — this was the original branch's hardest constraint and it is unchanged.

**B7. The page's counts stay derived from what renders.** An earlier bug
computed them separately and they disagreed. Folding changes the top-level
report counts by construction; no second count is introduced to "fix" that.

**B8. `familyOf`'s unknown-slug contract survives.** A doc_type nobody has
named still returns itself and still renders, rather than being dropped. That
behaviour was itself a bug fix — documents were counted but never displayed —
and folding these five must not quietly re-delete the next new type.

---

## Testing

Mechanism in pytest and vitest; quality by looking at the page.

- `highlight()` gets exhaustive unit coverage: word boundaries, casing
  preserved from the source, multi-word queries, the no-match case, the
  fallback window, the ellipsis.
- A regression test pins that **no vocabulary list exists** — the rule marks
  every typed word — so a future "small stopword list" cannot arrive unnoticed.
- A test pins that the run-based return shape survives, i.e. that no
  `dangerouslySetInnerHTML` appears in this path.
- The parent-book derivation is tested against the **21 known collisions by
  name**, asserting they resolve to Baseline. That is the case a doc_id-based
  implementation passes every other test while failing.
- A test pins that all five raw slugs disappear from the type rail and that
  their documents are still counted and still rendered.
- `search_terms` / filter-box matching keeps its existing coverage; B6 needs a
  test that each of the five slugs is still reachable by title.

**No eval run is required.** Nothing under `retrieval/`, `ingest/`,
`chunking/`, `citation/` or `harness/system-prompt.md` changes. `app/` and
`webapp/` are outside that rule. If implementation finds a reason to touch
`retrieval/`, the eval gate applies and the results are committed with the diff.

**Neither issue was caught by 2,999 passing tests.** Acceptance requires
opening the page.

---

## Not in scope

- Repairing the 21 mis-minted doc_ids, or the `make_doc_id` family collision
  behind them.
- Highlighting on the Fiscal Notes page (H11).
- Renaming `bd-pdf` / `bh-pdf` / `s-pdf` at ingest. They are page prefixes;
  folding makes them invisible to readers, which is the whole point.
- Title quality for these sections. Several are mangled table-of-contents
  extractions (`'JLBC FY2026 — •  Summary of Rent Charges'`, dot-leader runs,
  one unbalanced parenthesis, one `'FY 2012 Baseline — FY 2012 Baseline'`).
  Worth its own pass; folding does not depend on it.
- A `family` filter dimension in `retrieval/`. B5 avoids needing one.

---

## Open questions

None blocking. Two things the implementation must decide with a measurement
rather than by eye:

1. **The content-mode over-fetch factor (B5).** Measure the post-filter yield
   on a family-filtered search; do not pick a multiplier by eye.
2. **The expand-in-place affordance (H9)** has no visual design yet. It is
   behaviourally specified; the presentation is a build-time detail.
