# Table section paths: read the heading, stop searching for it

**Status:** approved 2026-08-26 (Destin). Decisions D1–D3 below are his and
are not to be re-litigated.

Every chunk carries a `section_path` — the breadcrumb of headings it sits
under. It is load-bearing in four places:

1. it is **line 0 of the chunk's embedded text**, so it feeds both BM25 and
   the dense vector (`table_chunk._build_text`, `narrative_chunk._flush_…`);
2. the **entity stamper reads it** when resolving agency and fund
   (`chunking/entity_stamper.py` Rule 3 scans `section_path + text`);
3. it is the **breadcrumb an analyst reads** in AI Mode
   (`RetrieveView.tsx` renders `section_path[last]`) and on a fiscal note
   (`FiscalNoteResult.tsx`);
4. it is where a units statement — *"(expressed in thousands)"* — reaches
   the reader of a figure.

A wrong `section_path` is therefore not cosmetic. It degrades retrieval,
degrades agency labelling, and can put a false unit on a citable number.

---

## 1. The defect, as measured 2026-08-26

There are two producers of `section_path` and they use different rules.

**Narrative chunks read the answer.** `build_narrative_chunks` walks the
outline tree and takes each node's own `body_blocks` — so a paragraph's
breadcrumb is the heading it physically sits beneath, by construction
(`narrative_chunk.py::visit`).

**Table chunks search for it.** `table_chunk._resolve_section_path` takes
cell text from the table's first three rows and calls
`ExtractedDocument.outline_path(q)`, which returns the deepest node whose
heading **or any body block anywhere in the document** contains that string.
On a tie it keeps the first found, and the walk runs in document order — so
**the earliest, shallowest node containing the string wins**, wherever it is
in the document.

Nothing in that rule refers to where the table is.

### 1.1 How far off it lands

Measured against the live cached extractor output, not inferred:

| | |
|---|---|
| `agao-afr-fy2024` — median distance between a table and the heading it was given | **93 pages** |
| — share of its tables labelled with a heading >5 pages away | **96.4%** (407 of 422) |
| `governor-governors-budget-fy2026` — tables labelled `Table of Contents` | **1,079 of 1,246** |
| — tables whose label differs from the heading they sit under | **1,196 of 1,246 (95.8%)** |

The Governor's Budget case shows the mechanism at its clearest: the contents
page lists every agency name in the book, so a table whose first cell reads
*"Acupuncture Examiners, Board of"* finds that string in the contents node's
body; the contents node is early and shallow, so it wins. **86% of a 661-page
book is filed under its own table of contents.**

### 1.2 Corpus scope

Sample: **234 documents across all ten `doc_type`s** (30 per type, seeded),
**3,078 tables**. Read with the reader named by each page file's own
`extractor` field; a `mineru/` or `mineru-ocr/` re-read subdirectory
supersedes the root output.

| doc_type | tables | differ from the heading they sit under |
|---|---|---|
| governors-budget | 1,250 | 95.8% |
| afr | 909 | 10.6% (plus 53.6% with no owning heading at all) |
| detailed-list-pdf | 209 | 20.1% |
| baseline-per-agency | 194 | 24.2% |
| s-pdf | 137 | 1.5% |
| bh-pdf | 103 | 4.9% |
| topic-pdf | 94 | 28.7% |
| approps-per-agency | 92 | 13.0% |
| bd-pdf | 71 | 5.6% |
| fiscal-note | 19 | 5.3% |
| **sample total** | **3,078** | **46.6%** |

The sample deliberately over-weights the two giant books (30-per-type on
types with only 2 and 4 members). Weighting each type's rate by its real
document count and mean tables/document gives **≈26,000 table chunks
corpus-wide, of which ≈5,500 (about one in five) carry a heading they do not
sit under.** The corpus holds ~24,000 table chunks, so the estimate is sound
to within ~8%.

**That is the mislabelled count, not the size of the write** — the orphan
case in §1.3 changes too. See §3.5 for the ≈10,200 rows this repair
actually rewrites.

### 1.3 The orphan case is the worst of it

**673 of 3,078 sampled tables (21.9%) sit under no heading at all** — 520
appear before the document's first heading, 85 are in documents where the
extractor found no heading anywhere. `_build_outline` attaches a block to
`stack[-1]` only when the stack is non-empty, so these blocks belong to no
node.

**539 of those 673 (80%) are given a label anyway** by the text search. Worked
example, read from the live data: a table on **page 3** of `agao-afr-fy2021`
— a financial statement — is labelled
`Note 1. – Summary of Significant Accounting Policies > Note 3. – State…`,
headings that appear roughly a hundred pages later.

That is invention, and it renders identically to a correct breadcrumb.

---

## 2. The fix

**The correct answer is already in the data and was never used.** The
readers' `_build_outline` appends every non-`Heading` block — tables
included — to the innermost open heading's `body_blocks`. That list is the
haystack `outline_path` searches. The haystack already records the answer.

### D1 — `section_path` for a table is the node that owns it

`_resolve_section_path` is deleted. A table's `section_path` is the
breadcrumb of the outline node whose `body_blocks` contains **that table
object**, plus its ancestors — identity, not text.

This is byte-for-byte the rule narrative chunks already use, so after this
change **two chunks on the same page can no longer disagree about which
section they are in.**

`ExtractedDocument.outline_path` has exactly one production caller
(`grep -rn outline_path` — verified). With that caller gone it is dead, and
it is deleted with its test rather than left as a second way to answer the
same question.

`body_blocks` stays. It is what both builders read, and its docstring
(`readers/types.py:161`, which credits `outline_path`) is corrected to say
so.

### D2 — a table with no owning heading gets an empty `section_path`

Not a guess, not the document title, not the next heading (only 68 of the
673 orphans have a heading later on their own page — measured; a
look-forward rule would cover 10% of the case and add a rule).

**There is already a precedent in this repo and this follows it.** The
orphaned-paragraph recovery in `narrative_chunk.py` handles the identical
situation — prose appearing before the first heading — and emits
`section_path=[]`, with a comment recording that `RetrieveView` checks
`section_path.length > 0` before rendering and `table_chunk._build_text`
checks `if section_path:`. Both consumers already degrade correctly. Tables
adopting it is consistency, not a new behaviour.

Consequence, stated plainly: **~22% of table chunks will render no
breadcrumb** where today ~4% do. That is the honest state (Invariant 3), and
539 of those labels are currently invented.

#### D2 is where this change is most likely to cost something, and it was read, not assumed

The orphan case is NOT uniform, and the small-document half of it deserves
its own paragraph because it is the largest single block of rows this repair
touches (≈3,400 of ≈10,200 — the two JLBC per-agency types).

Sampled 120 JLBC per-agency documents; of their orphan tables that carry a
label today, **89 of 107 (83%) got it from a heading within one page.** On a
7-page agency document a nearby heading is not the absurdity it is in a
191-page AFR, so today's rule is mostly *harmless* here rather than
*correct*.

The other 18 are one recognisable shape, and it is the important table on
the page: the **page-1 operating-budget summary**
(`| FY 2023 ACTUAL | FY2024 ESTIMATE | FY 2025 BASELINE`), labelled with
whatever minor heading the search reached — observed live:
`Overtime and Compensation Time` (heading on p3),
`New Footnotes` (p3), `Bed Surplus/Shortfall` (p6),
`College and Career Goal Arizona` (p4).

**Two consequences follow, and they point in opposite directions:**

1. On screen, blanking costs the reader nothing. `RetrieveView` groups
   results **by document** and names the document above the breadcrumb, so
   a page-1 summary table under
   *"Corrections, Department of — FY 2025 Baseline"* with no breadcrumb
   reads correctly. The breadcrumb was never carrying that information.
2. **In search, blanking removes a keyword.** `section_path` is line 0 of
   the embedded text. A summary table whose line 0 currently reads
   `Operating Budget` will start at its first data row. Where the label was
   wrong this is a precision gain; where it happened to be a useful word it
   is a recall loss.

This is the most likely source of movement in G-T2 and the reason that gate
is a per-query status check rather than an aggregate. **If Layer 1 moves,
this paragraph is the first place to look** — not the relabelled 5,500.

### D3 — nothing else changes in this pass

Two adjacent defects were measured and are **deliberately out of scope**;
both are recorded in §5.

No distance bound is applied. It was evaluated and rejected on evidence —
see §4.1.

---

## 3. The corpus repair

Destin, 2026-08-26: fix the code **and** repair the existing corpus. The
catastrophic documents are already ingested; a code-only fix would change
nothing an analyst can see today.

### 3.1 A surgical rewrite, NOT a re-ingest

**A re-ingest would undo part of the August identity repair, and this was
verified rather than assumed.** `identity/merge_agencies.py` merged nine
duplicate agency ids out of the corpus on 2026-08-16. The corpus is still
clean — a live scan returns **0 chunks** for `agency:cs`, `agency:wif`,
`agency:rev`. But `samples/entity-catalog.yaml` **still contains all nine**,
and the stamper run live today mints them:

```
Child Safety, Department of            -> agency:cs     (merged away in August)
Water Infrastructure Finance Authority -> agency:wif    (merged away in August)
```

So re-chunking any document re-derives the split ids. (This is a standing
bug with a wider blast radius than this work — see §5.3.)

The repair is therefore modelled on the three passes this project has
already run safely — `identity/relabel.py`, `identity/merge_agencies.py`,
`funds/unstamp.py` — and reuses that shape:

> dry run (no lock, no write) → **ingest lock** → snapshot + CRC verify →
> scan → recompute → batched write of changed rows only → verify every
> changed row plus a sample of untouched ones → tmp+rename reversal record
> → **rebuild the full-text index and `optimize()`**

The final step is not optional. `funds/unstamp.py` learned it: rows
re-added by `upsert_chunks` are invisible to BM25 until the FTS index is
rebuilt. (`identity/relabel.py` does not do this and is a separate
follow-up, already noted in STATUS.)

### 3.2 Mapping a stored chunk back to its table

`chunk_doc` emits table chunks **first**, in `doc.tables` order, so table
*n* is `{doc_id}-{n:04d}`. Changing `section_path` changes neither the
ordering nor the count, so **every `chunk_id` is preserved** and eval ground
truth, saved transcripts and citation annotations are untouched.

That mapping is a hypothesis per document, so it is **gated, not trusted**:
before any row of a document is written, the rebuilt table text must match
the stored chunk's text **ignoring line 0**. A document that fails is
skipped and named in the report. This is what catches a document whose
extractor output on disk no longer corresponds to what was ingested.

### 3.3 What is written, and what is not

Written: `section_path`, the chunk's `text`, and the recomputed `vector` —
for changed rows only.

`text` changes **only in its heading line**, and there are two cases, which
the implementation must handle separately because they are not the same
edit:

- **relabel** — line 0 is replaced with the new `" > ".join(section_path)`;
- **to blank** — line 0 is **removed entirely**, because
  `_build_text` opens with `if section_path:` and emits no heading line at
  all for an empty path. A blank first line would not match what a fresh
  `chunk_doc` run produces, and the repair must be a no-op against a
  re-chunk (see G-T6).

Every other line of `text` is byte-identical, and that is asserted per row
before the write.

**Not written:** `chunk_id`, `agency_canonical_id`, `agency_canonical_ids`,
`fund_mentions`, `doc_type`, `fiscal_year`, `publisher`, `page`, `bbox`,
`source_anchor`, `table_html`. The August agency and fund repairs survive
untouched, and so do the citation-highlight anchors shipped 2026-08-18.

**The stamper is not re-run.** A consequence worth naming: the Governor's
Budget tables that gain an agency name in `section_path` do **not** gain the
agency *tag* that name would have produced, because tagging is not
re-derived here. That is a deliberate deferral, not an oversight — see
§5.3.

### 3.4 Coverage

Documents with no cached extractor output are skipped and listed. ~400 of
7,574 documents are in that state (the migration-era entries; the same set
`chunking`'s orphan repair could not reach on 2026-08-12).

### 3.5 How many rows this actually rewrites

Measured directly (old path vs new path per table, same 234-document
sample), then weighted by each type's real document count and mean
tables/document:

| doc_type | tables/doc | rows changed | corpus docs | est. tables | est. changed |
|---|---|---|---|---|---|
| baseline-per-agency | 6.47 | 37.6% | 1,659 | 10,728 | 4,037 |
| approps-per-agency | 3.07 | 40.2% | 2,794 | 8,568 | 3,446 |
| governors-budget | 625.00 | 95.8% | 2 | 1,250 | 1,197 |
| afr | 227.25 | 61.9% | 4 | 909 | 563 |
| detailed-list-pdf | 6.97 | 25.8% | 280 | 1,951 | 504 |
| fiscal-note | 0.63 | 26.3% | 2,104 | 1,333 | 351 |
| topic-pdf | 4.95 | 33.0% | 19 | 94 | 31 |
| bd-pdf | 2.37 | 7.0% | 112 | 265 | 19 |
| s-pdf | 4.57 | 1.5% | 172 | 785 | 11 |
| bh-pdf | 3.55 | 4.9% | 29 | 103 | 5 |
| **total** | | **39.1%** | **7,175** | **25,986** | **≈10,200** |

In the sample, 1,972 of 3,078 tables change: **1,433 relabelled, 539 to
blank, 0 gaining a path they did not have.** (Zero gains is expected — the
text search almost always finds *something*.)

So the write is **≈10,200 rows re-embedded, ~12% of the 83,016-chunk
corpus.** The earlier "≈5,500" figure in §1.2 counts only mislabelled
tables and understates the write; both numbers are kept because they answer
different questions — 5,500 is how many labels are *wrong*, 10,200 is how
many rows are *touched*.

---

## 4. Rejected alternatives, with the measurement that rejected them

### 4.1 A distance bound ("a heading stops applying after N pages")

**Rejected.** A bounded version of the outline walk was already built,
calibrated and shipped for this on 2026-08-16, measured inert, and reverted
(`1292030`) — it bounded a mechanism no table chunk reads. This spec's
proposal is different (it changes the rule table chunks actually use), so
the bound was re-evaluated on its own merits at the table level and still
loses.

Table → its own heading, page distance, n=3,078:

| distance | share | cumulative |
|---|---|---|
| 0 | 17.0% | 17.0% |
| 1 | 12.7% | 29.8% |
| 2–3 | 17.5% | 47.3% |
| 4–5 | 6.2% | 53.5% |
| 6–10 | 6.0% | 59.6% |
| 11–20 | 2.8% | 62.4% |
| >20 | 15.8% | 78.1% |
| *no owning heading* | *21.9%* | — |

A 5-page bound would blank **~25% of all table chunks** on top of the 22%
that have no heading — pushing ~46% of tables to no breadcrumb.

**And reading the examples shows distance does not separate right from
wrong**, which counting them cannot show:

- Governor's Budget, a table **131 pages** after `Capital Projects`, first
  rows *"Superior Courts / General Fund 257.8 21,775.0"* — the label is
  **coarse but correct**; it really is inside that section, it has merely
  lost its own agency sub-heading.
- FY2024 AFR, a table **0 pages** from its heading, where the "heading" is
  `PENDITURES: \$15,208,607,391FY24 TOTAL OTHER FUND EXPENDITURES: \$24,363,969,795`
  — **a row of numbers the extractor mistook for a heading.**

Distance is a proxy for extractor quality, and it is a poor one.

### 4.2 A units rule ("a scale claim does not travel")

**Evaluated, and declined by Destin, 2026-08-26.** Recorded with its numbers
because it is the obvious next thing anyone will propose.

A heading stating units is an assertion about specific figures, not a topic
label, and such headings are vanishingly rare — **3 of 3,584 headings in the
sample, in 2 of 200 documents** — so a rule about them would cost nothing
elsewhere. On `agao-afr-fy2024`, tables carrying a units claim:

| | tables claiming "expressed in thousands" |
|---|---|
| today (text search) | **121** |
| D1 alone (this spec) | **51** |
| D1 + strip a units phrase inherited past 5 pages | **5** |

Destin's call was to keep this change to one rule. **The residual is real
and is named in §5.1.**

---

## 5. Explicitly not fixed

### 5.1 51 passages in `agao-afr-fy2024` still claim "expressed in thousands" over whole-dollar figures

Down from 121, but a 1,000× error on citable numbers is being knowingly
carried. Distance breakdown of the 51 under D1: 2 at 0–1pp, 3 at 2–5pp, 20
at 6–20pp, 26 at >20pp. §4.2 records the fix that would close it.

### 5.2 Garbage strings are still accepted as headings

Reading the heading faithfully means faithfully reading a letterhead
(`OFFICE OF THE DIRECTOR 100 NORTH FIFTEENTH AVENUE ∙ SUITE 302 …`) or a
fused row of figures (§4.1). `identity/validator.py` — built for the corpus
identity work to answer *"is this string a name?"* — is the right precedent
for a heading-plausibility filter. Separate defect, separate spec.

### 5.3 🔴 The catalog still holds the nine merged-away agency ids

Found while scoping this work; **not caused by it and wider than it.**
`identity/merge_agencies.py` rewrote corpus rows; `samples/entity-catalog.yaml`
was never deduped and `chunking/entity_stamper.py` still resolves to the
merged-away ids (verified live, §3.1). **Every document uploaded since
2026-08-16 re-splits those agencies**, silently. The corpus happens to be
clean only because nothing has been ingested since.

This is why §3.1 is surgical. It also means the Governor's Budget's new
agency names cannot be turned into agency *tags* until the catalog is fixed
— do that first, then re-stamp deliberately, as its own change with its own
eval.

---

## 6. Gates

**G-T1 — the two producers agree.** A test that reads one real document and
asserts every table's `section_path` is derivable by the same rule the
narrative builder uses. This is the check that was missing: every existing
test asks *"is this chunk's label right?"*, and nothing asked *"do our two
labellers agree?"* (CLAUDE.md: *a per-item check cannot find a cross-item
defect*).

**G-T2 — Layer 1 eval, control run immediately before the write.** Not a
remembered baseline: unmodified code, same machine, same 47-query set,
minutes before. `section_path` is line 0 of chunk text, so BM25 and vector
both change and the numbers **may legitimately move**. The gate is that
**no query changes status**; a rank change with an unchanged verdict is
reported, not failed. Both result files committed.

**G-T3 — nothing but the intended columns moved.** Every changed row
verified in full; a 200-row sample of untouched rows per table verified;
`agency_canonical_ids` and `fund_mentions` byte-identical corpus-wide
before and after.

**G-T4 — read the documents, do not count them.** `governor-governors-budget-fy2026`:
no table labelled `Table of Contents`; a sample read by eye carries the
agency it is about. `agao-afr-fy2021`: the page-3 statements no longer
labelled with Note 1/Note 3. `agao-afr-fy2024`: the units count is 51, as
predicted here — a different number means the model of the defect is wrong
and the write should stop.

**G-T5 — a dry run precedes every write**, and the dry-run and apply row
counts must be identical (the discipline `funds/unstamp.py` used).

**G-T6 — the repair equals a re-chunk, on at least one real document of
each shape.** Run the NEW `chunk_doc` end-to-end over cached extractor
output and assert every table chunk it produces is byte-identical to what
the repair pass wrote — `section_path` and `text`. This is the gate the
2026-08-16 attempt did not have: that fix was measured against
`OutlineNode.body_blocks`, a mechanism no chunk reads, passed twelve specs
and five of six mutations, and changed **zero** chunks in production.
**Mutation testing proves a test observes the code; it cannot prove the code
observes anything.** One end-to-end `chunk_doc` run is free, offline, and
about sixty seconds. Required shapes: one JLBC per-agency page (the
to-blank case), the Governor's Budget (the relabel case), one AFR (the
no-heading case).

---

## 7. Risks

| risk | mitigation |
|---|---|
| **Recall falls on JLBC agency summary tables** — ≈3,400 rows lose a keyword from line 0 (§D2) | The single most likely source of movement; G-T2 is a per-query status gate and this is the first place to look if it fires |
| Retrieval moves generally — line 0 of ≈10,200 chunks changes | G-T2 with a same-hour control on unmodified code, same 47-query set |
| The chunk↔table mapping is wrong for some document | §3.2 gate: every line but line 0 must match, or the document is skipped and named |
| The repair and a future re-chunk disagree, so the next re-ingest silently reverts a document | G-T6: the repair's output must be byte-identical to a real `chunk_doc` run on three document shapes |
| A partial write leaves the corpus inconsistent | CRC-verified snapshot taken under the lock; reversal record carries the full old `section_path` and `text` per row |
| Losing breadcrumbs looks like a regression to a reader | ~22% of tables, and `RetrieveView` names the document above the breadcrumb (§D2); G-T4 reads examples; stated in STATUS |
| Re-embedding is slow | ≈10,200 changed table rows, not the 83,016-chunk corpus |
| A reader assumes the ≈5,500 and ≈10,200 figures are the same number | §3.5 states which question each answers |
