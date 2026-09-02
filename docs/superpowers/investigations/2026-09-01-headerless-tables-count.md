---
status: shipped
---
# Headerless table chunks outside the operating-table scope (spec §5 rule 5)

**⚠ 2026-09-01 revision.** The first version of this memo claimed "zero" of
30+ hand-read headerless chunks were true continuations, and dropped rule
5 on that basis. **That claim was false.** A reviewer ran an adjacency +
column-width probe the first version did not attempt, hand-read the
flagged set, and found unambiguous true continuations concentrated in the
Governor's budget's multi-year fund tables. This revision adds that probe
to the script, hand-reads a stratified sample of what it flags, and
re-argues the decision on the corrected numbers. The false "zero" claim
below is struck through, not deleted, so nobody re-derives it.

**What this measures, in plain words.** Spec §3.1/§5 rule 5 asks: when a
table chunk has no year header (`FY 2024 / FY 2025 / …` across the top), is
that because it is the SECOND PIECE of a bigger table whose header sits in
an earlier chunk — in which case a "continuation-header borrow" could go
fetch that earlier chunk's header at answer time — or is it a table that
never had a year header to begin with, in which case there is nothing to
borrow and the mechanism would cost a live database read on every search
for no benefit? Phase A only covers the two agency-operating-table document
types (`approps-per-agency`, `baseline-per-agency`) and only the chunks that
carry a ladder word (`FUND SOURCES`, `AGENCY TOTAL`, etc.) — this measures
every table chunk OUTSIDE that scope.

**Population covered.** Every row in the live corpus's `budget_chunks`
table (`JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data`)
where `is_table = true` — **22,889 of 83,197 budget chunks**. This is a
full scan, not a sample: `ChunkStore.scan()` with no `limit` returns every
matching row. `fiscal_note_chunks` (14,161 rows) was **not** scanned —
operating tables and the ladder vocabulary in `chunking/table_text.py` are
a budget-document phenomenon; fiscal notes carry no `approps-per-agency` /
`baseline-per-agency` chunks and the spec discusses this rule only in the
budget-corpus context.

## Run

Command: `JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data uv run python -m scripts.count_headerless_tables`

(See "Deviation from the sketch" below for why `-m scripts.count_headerless_tables`
rather than the brief's `python scripts/count_headerless_tables.py`.)

```
table chunks: 22889  in-scope: 4875  out-of-scope: 18014
out-of-scope with tab rows and NO header: 7411
  approps-per-agency       2323
  baseline-per-agency      1650
  detailed-list-pdf        1083
  afr                      1012
  governors-budget         972
  s-pdf                    132
  bd-pdf                   102
  bh-pdf                   87
  topic-pdf                50

...of those, predecessor chunk (idx-1, same doc_id) is a table WITH a header: 1634
  approps-per-agency       670
  baseline-per-agency      607
  governors-budget         199
  detailed-list-pdf        128
  topic-pdf                13
  bd-pdf                   10
  s-pdf                    5
  bh-pdf                   2

...of those, current chunk's row width matches the predecessor's header-row width: 359
  baseline-per-agency      153
  approps-per-agency       106
  governors-budget         67
  detailed-list-pdf        23
  topic-pdf                4
  bd-pdf                   3
  s-pdf                    2
```

(`width-matched chunk_ids, for hand-reading:` — 359 ids — is printed after
this but not pasted here; it is what fed the sample below.)

## What the 7,411 chunks actually ARE

**Two questions, not one.** "Does this chunk have no header?" (7,411 —
unchanged from the first pass) and "is that BECAUSE it is a continuation
of a table whose header sits in the chunk before it?" (a separate
question this revision actually answers, instead of assuming).

**The adjacency probe answers the second question directly.** For each of
the 7,411, does `f"{doc_id}-{idx-1:04d}"` (the ingest-minted chunk_id one
index lower, in the same document) exist as a table chunk that DOES carry
a detected header? **1,634 of 7,411 (22%) do** — concentrated in
`approps-per-agency` (670), `baseline-per-agency` (607) and
`governors-budget` (199). This alone does not prove a continuation — two
UNRELATED tables can sit back to back, one with a real multi-year header
and the next without one purely by coincidence — so a second, narrower
filter was added: does the current chunk's typical row width (the most
common cell-count among its own tab-split rows) match the WIDTH of the
predecessor's header row? That narrows 1,634 down to **359** — still not
proof, but a set worth reading by hand, and small enough to actually read.

### Hand-read: 24 of the 359, drawn across every doc type

Random sample (seed fixed for reproducibility), stratified by doc type in
rough proportion to each type's share of the 359: 6 `governors-budget`,
6 `baseline-per-agency`, 6 `approps-per-agency`, 3 `detailed-list-pdf`,
1 each of `topic-pdf` / `bd-pdf` / `s-pdf`. Each was read alongside its
predecessor's FULL text (not just the last/first few hundred characters)
to judge whether the current chunk's rows genuinely belong under the
predecessor's header, or whether it is a different, complete table that
happens to be the same width.

| chunk_id | doc type | verdict | why |
|---|---|---|---|
| `governor-governors-budget-fy2026-0510` | governors-budget | **TRUE** | SLI fund list splits mid-alphabet, same 4-year `BY APPROPRIATED FUND` header, same agency running-heading |
| `governor-governors-budget-fy2027-0776` | governors-budget | **TRUE** | same shape, Secretary of State |
| `governor-governors-budget-fy2027-0865` | governors-budget | **TRUE** | same shape, a university |
| `governor-governors-budget-fy2026-0508` | governors-budget | **TRUE** | same shape, Health Services fund list |
| `governor-governors-budget-fy2026-1056` | governors-budget | **TRUE** | same shape, Water Resources SLI list |
| `governor-governors-budget-fy2026-0950` | governors-budget | **TRUE** | same shape, Transportation non-appropriated fund list |
| `jlbc-baseline-fy2024-liq-0002` | baseline-per-agency | **TRUE** | `SUMMARY OF FUNDS FY2022/FY2023` header, current chunk is exactly its `Funds Expended` / `Year-End Fund Balance` rows |
| `jlbc-baseline-fy2026-sba-0003` | baseline-per-agency | **TRUE** | same `SUMMARY OF FUNDS` shape |
| `jlbc-baseline-fy2023-des-0025` | baseline-per-agency | **TRUE** | same shape, Federal TANF Block Grant |
| `jlbc-baseline-fy2013-msl-0006` | baseline-per-agency | **TRUE** | same shape, Medical Student Loan Fund |
| `jlbc-baseline-fy2027-s80-0001` | s-pdf | **TRUE** | same `PREVIOUSLY ENACTED APPROPRIATIONS FY 2027 and BEYOND` title reprinted verbatim as a running header, list continues straight through to `GENERAL FUND TOTAL` |
| `jlbc-baseline-fy2015-deq-0009` | baseline-per-agency | **plausible** | predecessor's `SUMMARY OF FUNDS FY2013/FY2014` header names a DIFFERENT fund ("Extension of Underground Storage Tank Tax") than the current chunk's own heading ("WQARF Priority Site Remediation") — likely two funds' identical-format summaries back to back in the same document, so the YEARS are probably still right even though the specific fund heading is not the immediately preceding one |
| `jlbc-approps-fy2019-469-0009` | detailed-list-pdf | **plausible** | the current chunk reprints the SAME running title (`CROSSWALK OF FY 2019 GENERAL APPROPRIATION ACT...`) as the predecessor and continues its agency rows — looks like one document-wide matrix table split across many chunks, but the "header" both carry is a single-year column-caption row, not a genuine multi-year ladder, so what a borrow would supply is less clearly a "year" |
| `jlbc-approps-fy2011-bd3-0001` | bd-pdf | **plausible** | predecessor is cut off MID-WORD (`SUBTOTAL APPROPRIATIO…`) — a genuine chunk-boundary truncation — and current continues the same statute-cite/description/FY2011/FY2012 row shape for a new subsection of the same appropriations-bill summary |
| `jlbc-baseline-fy2020-axs-0029` | baseline-per-agency | **FALSE — distinct table** | predecessor is a DSH-distribution table; current opens with its OWN heading ("Prescription Drug Rebate Fund", "Table 5") and its own (single-year) subject |
| `jlbc-approps-fy2008-agr-0003` | approps-per-agency | **FALSE — distinct table** | same agency heading and same fund NAMES as predecessor, but wildly different dollar amounts (change/adjustment figures, not the base totals) — a different sub-table under a repeated agency heading, not a continuation |
| `jlbc-approps-fy2010-hea-0003` | approps-per-agency | **FALSE — distinct table** | predecessor ("Lump Sum Reduction") ends cleanly on one complete row; current opens with a DIFFERENT heading ("Operating Budget") and different values for the same fund |
| `jlbc-approps-fy2020-ade-0007` | approps-per-agency | **FALSE — distinct table** | current opens with its own name and number: "Table 6 DAA Suspensions & Restorations", unrelated subject to predecessor's K-12 endowment table |
| `jlbc-approps-fy2006-adegs-0002` | approps-per-agency | **FALSE — distinct table** | current opens with "Achievement Testing / Table 1 / Achievement Testing Appropriation (FY 2006)", its own complete 1-year table |
| `jlbc-approps-fy2006-unibor-0006` | approps-per-agency | **FALSE — distinct table, but instructive** | current chunk IS its own complete table with its own 2-year header (`FY 2005` / `FY 2006c)`) — `find_header` missed it only because a footnote marker fused onto "2006c)" broke the `\b` word boundary the year regex needs. Not a continuation; a header-detection miss on a self-contained table |
| `jlbc-approps-fy2017-axs-0015` | approps-per-agency | **FALSE — distinct table** | current opens with "Table 9 Total Medicaid Population Increase", a population-count table, unrelated to predecessor's dollar-figure table |
| `jlbc-approps-fy2012-284-0010` | detailed-list-pdf | **FALSE — distinct table** | current is its own "Description of Provision / FY 12 / FY 13 / … / FY18" table — has a real header, missed because it uses 2-digit years (`FY 12`), which the 4-digit year regex can't see |
| `jlbc-approps-fy2017-462-0005` | detailed-list-pdf | **FALSE — distinct table** | current opens with "Table 5 / Reasons for Change in the Employer Contribution Rate", a different named table with years as ROW labels rather than column headers |
| `jlbc-baseline-fy2025-capitaloutlay-0005` | topic-pdf | **FALSE — distinct table** | current is its OWN complete D1-shaped ladder table (`AGENCY TOTAL` / `FUND SOURCES` / `TOTAL - ALL SOURCES`), single year, under a new heading ("Rent Adjustments") — correctly excluded from D1 by document type, not a lost continuation |

**Count: 11 unambiguous TRUE, 3 plausible, 10 distinct-table false
positives**, out of 24 read (24 = 6+6+6+3+1+1+1).

**The rate is not uniform — it is exactly the shape the reviewer named.**
`governors-budget` came back **6 of 6 true**, every one the same pattern:
a `BY APPROPRIATED FUND` or `SLI` (Special Line Item) fund-by-fund list,
one fund per row, four year columns, that MinerU/the text-layer split
mid-list with no repeated header — a structurally homogeneous shape, which
is why the hit rate there is so much higher than the pooled 15–25% the
reviewer measured across the WHOLE 359. `baseline-per-agency` came back
**4 true + 1 plausible of 6**, essentially all the same `SUMMARY OF
FUNDS`-then-`Funds Expended`/`Year-End Fund Balance` two-line shape (this
is the SAME shape as the D1-in-scope `paz-0001→0002` example the reviewer
found — see the phase B note below). `approps-per-agency` came back
**0 of 6 true** — every sampled chunk there opens its own named table
("Table 1", "Table 6", "Table 9") or repeats an agency heading over a
DIFFERENT sub-table (adjustment figures under the same fund names), so its
670/106 predecessor-headed/width-matched counts are dominated by
coincidence, not by continuations.

**A weighted estimate from these doc-type-specific rates, applied to the
full 359 width-matched population:**

| doc type | width-matched | sampled hit rate | estimated true |
|---|---|---|---|
| governors-budget | 67 | 6/6 (100%) | ~67 |
| baseline-per-agency | 153 | 4/6 true + 1/6 half-credit (67–83%) | ~102–128 |
| approps-per-agency | 106 | 0/6 (0%) | ~0 |
| detailed-list-pdf | 23 | 0/3 true + 1/3 half-credit (17%) | ~4 |
| topic-pdf | 4 | 0/1 (0%) | ~0 |
| bd-pdf | 3 | 1/1 plausible, half-credit | ~1–3 |
| s-pdf | 2 | 1/1 (100%) | ~2 |
| **total** | **359** | | **~175–205** |

**Estimated true-continuation population: roughly 150–220, point estimate
~180 — about 0.2%–0.3% of the 83,197-row budget corpus, or 0.8%–1.0% of
the 22,889 table chunks.** This is somewhat HIGHER than the reviewer's own
50–150 / "under 0.2%" estimate (which pooled the 15–25% hit rate evenly
across doc types), because a stratified read shows the rate is not even —
it is close to 100% in `governors-budget` and close to 0% in
`approps-per-agency`, and `governors-budget` alone (67 width-matched, all
6 sampled true) accounts for roughly a third of the estimate. Both
estimates agree on the shape and the order of magnitude: **real, non-zero,
concentrated in a few patterns, and a small minority — well under 1% of
the corpus.** The N=24 sample (N=6 for the two largest buckets) leaves real
uncertainty in the exact count; nobody should treat "~180" as more precise
than "on the order of a few hundred, mostly Governor's-budget fund lists."

**\~~Struck-through, false, kept for the record~~: the first version of
this memo said "None of the more than 30 chunks read... is a truncated
fragment of a table whose header lives in a chunk before it." That
sentence was written from an UNSTRATIFIED, adjacency-blind sample — every
example in the first pass happened to land on a distinct-table case
(footnote breakdowns, named `Table N` tables, AFR pie charts). It never
tested the one shape (the Governor's-budget SLI/fund-list split) that
turns out to be the dominant true-continuation pattern, because the
vocabulary probe it used (`Personal Services` / `ERE` / `FTE Positions`)
is D1's own line-item vocabulary and has nothing to do with how the
Governor's budget formats its fund lists — structurally blind to the
shape that mattered, exactly as the review said.**

**What the doc types are, corrected for `governors-budget`:** the earlier
descriptions of `approps-per-agency`/`baseline-per-agency` (county
property-tax tables, community-college tables, one-year fund-breakdown
footnotes), `detailed-list-pdf` (rate schedules, revenue forecasts, and —
now confirmed — one continuing statewide crosswalk table), `afr` (pie-chart
summary pages), `s-pdf`/`bd-pdf` (statewide summary lists, some of which
genuinely continue across chunks), `bh-pdf` (revenue/spending pie charts)
and `topic-pdf` (cross-agency topical tables, including self-contained
ladder-shaped ones outside D1's doc-type scope) all still hold. **What was
wrong is `governors-budget`**, which the first pass described only as:

> "the Governor's budget 'Table of Contents' funding-by-issue lines:
> `Funding FY 2027 / General Fund 0.0 / Issue Total 0.0` — one year, one
> number."

That is the MAJORITY shape (roughly 972 − 199 ≈ 773 of the 972 headerless
`governors-budget` chunks have no headed predecessor at all, and are
genuinely single-year, single-number "Issue Total" lines with nothing to
borrow). But **a real minority — the 199 with a headed predecessor, of
which 67 width-match and all 6 sampled read as genuine continuations — are
long, multi-year `BY APPROPRIATED FUND` / `SLI` (Special Line Item)
fund-by-fund tables** (four year columns: Actual / Appropriation / Net
Change / Executive Budget) that get split mid-list across chunk
boundaries with no repeated header, the same way D1's own operating
tables do. `governors-budget` is not one shape; it is two, and only the
second one is where rule 5 would ever matter.

## Decision

**The brief's two branches don't literally fit, and forcing one would
misstate the evidence either way.** "Under 1,000 and no year columns
anyway" is false — the raw headerless count is 7,411, and a real
(if small) fraction of it genuinely lacks a year column only because that
column sits in the chunk before it. "Dominated by continuations in one
doc type" is also false — the estimated true-continuation population
(~150–220) is a small minority of the 7,411 headerless chunks (~2–3%) and
of the 22,889 table chunks (~0.8–1.0%), even though it IS concentrated,
mostly in `governors-budget` with a real slice of `baseline-per-agency`.

**DROP rule 5 — but as a cost/benefit judgement, not because no cases
exist.** They do exist, and they are not rare in an absolute sense (~150–220
chunks is not "one or two"). Three things together argue against building
the borrow mechanism anyway:

1. **The population is small relative to the corpus** — under 0.3% of
   budget chunks, so most searches would never touch the new code path at
   all, which cuts both ways: the live-store-read COST is rarely paid, but
   so is the BENEFIT.
2. **The discrimination method needed to trust a borrow is not reliable
   enough to build on.** Adjacency + column-width match — the strongest
   simple heuristic tried here — still returns roughly 40–55% FALSE
   POSITIVES on hand-reading (10 of 24, plus 3 genuinely ambiguous). A
   mechanism that attaches the wrong header to a table it should have left
   alone is worse than one that renders no header at all: a wrong year
   label reads as a confident, verifiable-looking fact, and Invariant 1
   treats an unlabelled figure as safer than a mislabelled one. Getting the
   false-positive rate down further would need a materially smarter
   check than the brief's simple adjacency test — real work, on a rule that
   only ever fires for a fraction of a percent of the corpus.
3. **The recovered value is narrow.** The dominant true-continuation
   pattern (Governor's-budget SLI/fund-by-fund line items) is legislative
   line-item detail, not the agency-level totals D1 already renders — a
   real but modest gain in exchange for a new failure mode on every
   search.

Those chunks fall to today's plain text, unchanged — same outcome as the
first pass's conclusion, arrived at for a defensible reason this time.

**Follow-up, if this is ever revisited.** The concentrated pattern is
`governors-budget`'s `BY APPROPRIATED FUND` / `SLI` tables — four-year
fund-by-fund lists that split mid-alphabet across chunk boundaries.
Confirmed true-continuation examples, for whoever picks this up:
`governor-governors-budget-fy2026-0509→0510`,
`governor-governors-budget-fy2027-0775→0776`,
`governor-governors-budget-fy2027-0864→0865`,
`governor-governors-budget-fy2026-0507→0508`,
`governor-governors-budget-fy2026-1055→1056`,
`governor-governors-budget-fy2026-0949→0950`. If a borrow mechanism is
ever built, scoping it to JUST this pattern (a homogeneous, near-100%-hit
shape) rather than to every width-matched headerless chunk corpus-wide
would avoid most of the false-positive risk described above — that is a
narrower, cheaper rule than "borrow from any adjacent headed table," and
was not tested here because it is out of this task's scope.

**A separate, phase B question: the `paz-0001→0002` shape.** Several of
the TRUE and plausible baseline-per-agency examples above
(`liq-0002`, `sba-0003`, `des-0025`, `msl-0006`, and the `paz` example the
reviewer originally found) are `SUMMARY OF FUNDS` two-year tables inside
the two D1-SCOPED doc types (`baseline-per-agency` / `approps-per-agency`)
— they are outside THIS measurement's scope only because they lack a
ladder marker (`FUND SOURCES` / `AGENCY TOTAL` / etc.), not because their
doc type is wrong. Whether phase B's text-layer rebuild (which covers D1's
ladder tables) also needs to cover this DIFFERENT, non-ladder,
two-year-summary shape is a question for phase B's own spec work, not
this rule-5 measurement — flagging it here so it isn't lost.

## Deviation from the sketch

The brief's run command (`uv run python scripts/count_headerless_tables.py`)
fails: `python <path>` puts the SCRIPT's own directory on `sys.path`, not
the repo root, so `from chunking.table_text import …` raises
`ModuleNotFoundError`. Verified there is no `.pth` file or path shim
making the bare-path form work in this repo. The working invocation is
`uv run python -m scripts.count_headerless_tables` (module form, which
puts the current working directory — the repo root — on `sys.path`). The
script's core counting logic is unchanged from the sketch; the adjacency
and width-match extensions (2026-09-01 revision, in response to review)
are new, read-only, and reuse the same `ChunkStore`/`find_header` calls —
no new store access pattern, just a lookup dict built from the rows
already scanned.
