---
status: active
---

# The operating-table rebuild, dry-run over the whole corpus (G-OT1)

Task 10 of `docs/superpowers/plans/2026-08-26-agency-table-rebuild-design.md`;
spec §6.1 and §6.3. This is the checkpoint document — the repair has been
planned over every in-scope table in the live corpus and **nothing has been
written**. The apply (`--apply`) has never been run.

**Headline: 4,656 of 4,875 operating tables (95.5%) can be rebuilt from the
PDF text layer and verified arithmetically. The worst fiscal year is 2009 at
83.7%. Both G-OT1 floors are cleared. Recommendation: GO to the rehearsal.**

> **This record is the SECOND full run**, made after the reader fix in
> "The `--` rule gap, fixed" below. The first run (95.4%, 4,653 rebuilt) is
> superseded; every number here comes from the run of 2026-09-02.

---

## The command, and the population it covered

```
JLBC_DATA_DIR=<share>/data/insight-data \
  uv run python -m chunking.repair_tables --report <plan>.json --pairs 20
```

Run 2026-09-01/02 from the `agency-tables` worktree against the live corpus
(read-only: `ChunkStore(create=False)` and `scan`; the CLI defaults to a dry
run and writes only with an explicit `--apply`).

| | |
|---|---|
| in-scope table chunks | **4,875** |
| documents they sit in | 4,771 |
| in-scope rule | `is_table` AND `doc_type in OPERATING_TABLE_DOC_TYPES` AND a ladder marker (spec D1) |
| source of the MinerU table | 4,533 cached extractor output / **342 stored-html fallback** |
| chunks whose document had cached output but could not use it | **0** |
| **`no source pdf`** | **0 of 4,875** |

### 🔴 THIS RESULT IS MACHINE-DEPENDENT, AND ON THE WRONG MACHINE THE GATE FAILS

**329 in-scope documents — 342 table chunks — record a repo-relative
`source_blob_path` of `data/cached-pdfs/<shard>/<sha>.pdf` and resolve ONLY
through `app.routes.pdf.REPO_ROOT / <relative>`.** They are not on the share
under either of `_resolve_blob`'s other two candidates. Those 342 chunks are
byte-identical to the 342 rows whose plan source is `html`.

A git worktree does not carry that gitignored download cache. Run from a
checkout without it, **the same pass over the same corpus reports 88.7%
overall, with FY2027 at 47.3%, FY2025 at 48.5% and FY2026 at 49.8% — it
FAILS G-OT1's 70% per-year floor**, on a corpus that is completely fine.
**327 of the tables this plan promises to rebuild would instead be refused as
`no source pdf`.**

This is a configuration fact every time, never a corpus fact, so the CLI now
refuses to report such a run as a measurement: a full run (no `--doc`) with
any `no source pdf` prints a banner naming the cause and **exits non-zero**.

This run was made after hard-linking the main checkout's `data/cached-pdfs/`
into the worktree (`cp -al`, 0 extra bytes). A symlink does **not** work:
`_resolve_blob` calls `.resolve()` and then requires containment in
`REPO_ROOT`, so a symlink out of the worktree is correctly rejected.

**Follow-up for its own item, not fixed here:** `_resolve_blob` is the same
resolver the PDF viewer uses (`app/routes/pdf.py`), so those 329 documents'
"Open source PDF" is probably broken on every office machine — the share has
no copy of the blob under any candidate path. That is a corpus-identity
defect affecting analysts today, independently of this pass.

**This agrees with the Task 6 reader-only probe to within one table.** That
probe ran the reader directly over the same 4,875 tables and reported 4,654
rebuilt, 140 arithmetic, 52 anchor, 12 two-figures, 10 no-header, 7
last-row, 0 retention. This run, through the whole plan (extractor-first
pairing, html fallback, per-chunk verdicts) gave **4,653 / 141 / 52 / 12 / 10
/ 7 / 0** on its FIRST run — one table apart from the probe. The plan's
pairing and fallback therefore do not differ materially from the reader
alone. The numbers throughout the rest of this document are from the SECOND
run, taken after the `--` reader fix: 4,656 / 143 / 47 / 12 / 10 / 7 / 0.

---

## Per fiscal year (G-OT1), verbatim

```
  year  tables  rebuilt  unverif   rate
  2005     140      136        4  97.1%
  2006     148      144        4  97.3%
  2007     146      136       10  93.2%
  2008     162      147       15  90.7%
  2009     153      128       25  83.7%
  2010     150      133       17  88.7%
  2011     142      132       10  93.0%
  2012     258      251        7  97.3%
  2013     251      243        8  96.8%
  2014     251      239       12  95.2%
  2015     251      240       11  95.6%
  2016     258      246       12  95.3%
  2017     257      248        9  96.5%
  2018     250      245        5  98.0%
  2019     231      230        1  99.6%
  2020     229      219       10  95.6%
  2021     228      220        8  96.5%
  2022     229      221        8  96.5%
  2023     230      219       11  95.2%
  2024     233      223       10  95.7%
  2025     227      221        6  97.4%
  2026     227      220        7  96.9%
  2027     224      215        9  96.0%
   all    4875     4656      219  95.5%
```

Spec §4.1 says to stop and investigate below 90% overall or below 70% in any
year. Overall is 95.5%; the worst year, 2009, is 83.7%. **Neither floor is
breached.** The refusals were still read, because a passing rate is not the
same as a understood one.

The weak band is FY2007–FY2011 (83.7–93.2%). That is the era of the
four-column Appropriations Report page and of the smallest agency pages, and
both shapes are over-represented in the refusals below.

---

## Reasons for the 222 refusals

```
     143  arithmetic
      47  anchor match <threshold>
      12  two figures in one column
      10  no header
       7  last row unmatched
       0  figure retention <threshold>
       0  refinement raised
       0  no source pdf
```

A refusal costs the chunk nothing: spec D3 keeps MinerU's stored text
untouched, so 219 tables stay exactly as they are today.

**Bucketed notes — why a chunk did not use its document's cached extractor
output: none.** Every one of the 4,875 chunks resolved to a reading. The 342
`html` rows are the ~398 documents that were never cached at all, which
carry no note by construction.

### `arithmetic` (143) — the PAGE, not the rule

Decisive corpus-wide measurement rather than an impression: run the same
gate over **MinerU's own stored table** for each of the 143.

| | |
|---|---|
| MinerU's stored table **also fails** the same gate | **141** |
| MinerU's stored table has no check row at all | 0 |
| MinerU's stored table **passes** where the rebuild fails | **2** |

**How to reproduce this**, because the plan JSON cannot answer it: a refused
chunk carries `new_text: None` by construction (spec D3 — it keeps what it
has), so the page-vs-rule classification comes from re-running the gate over
each chunk's `old_text`, not from reading the report. The script is six lines
around `chunking.repair_tables.table_rows` and `chunking.table_gate.reconcile`.

So for 141 of 143 the printed column does not foot in either reading. Ten
were read individually through the real plan path (region walk included).
Two shapes:

* **The book does not foot.** `jlbc-approps-fy2012-adc-0000`: the FY 2010
  column reconciles exactly (721,391,400), and the FY 2011 column's
  `OPERATING SUBTOTAL` is printed 847,628,700 against 849,628,700 for the
  sum of its own printed parts — off by $2.0M; its
  `SUBTOTAL - Other Appropriated Funds` is off by $500.
  `jlbc-baseline-fy2021-hla-0000` is off by $200 on a four-row table.
  This is the gate doing its job: refuse rather than store a table nobody
  can verify.
* **A span the gate cannot resolve**, where the nearest candidate boundary
  is empty and no boundary produces the printed total —
  `jlbc-approps-fy2010-axsadmn-0000` fails a `PROGRAM TOTAL = SUBTOTAL -
  APPROPRIATED FUNDS` cross-check in all three columns.

The **two** where MinerU passes and the rebuild does not are
`jlbc-baseline-fy2014-att-0000` and `jlbc-baseline-fy2019-dhs-0001`. Both
keep their stored text, so nothing is lost; the second is a two-page table
whose MinerU reading has the second page's header row spliced into the
middle of the fund list, which happens to reconcile.

**Verdict: page, not rule. No change recommended.**

### `anchor match <threshold>` (47) — MinerU's HEADER ROWS in the denominator

Ten were read with the matched/missed anchor list beside the printed page.
The pattern is uniform and is not about the threshold:

| missed anchor kind, across the 52 refusals of the first run | count |
|---|---|
| page **masthead** (`DIRECTOR: …`, `PRESIDENT: …`, `GOVERNOR: …`) | 35 |
| bare header text (`ACTUAL`, `ESTIMATE`, `FY 2009`) | 35 |
| a bare **figure** sitting in MinerU's label column | 24 |
| everything else (real body labels) | 60 |

Nine of the ten read misses the masthead and eight also miss a bare
`ACTUAL`. `jlbc-approps-fy2009-apc-0000` is the clearest: three distinct
anchors, of which one is `DIRECTOR: KIMBERLY O'CONNOR` — the page prints
`Director: Kimberly O'Connor JLBC Analyst: Jon McAvoy` as **one line**, so
the printed line is longer than the anchor and page→MinerU containment can
never match it. One structurally unmatchable anchor out of three is 67%.

`_region`'s own docstring already records that the first anchor is often an
unmatchable masthead and falls back rather than refusing. What this run adds
is that **the same anchors still sit in the denominator of the match rate**.
Excluding header-row and figure-as-label anchors from the denominator would
let **40 of the 52 clear 80%** — they would then still have to pass header
detection, `_rows`, figure retention and the arithmetic gate, so that is an
upper bound on recoveries, not a count of them. **That change is NOT made** —
see "What is deliberately not changed".

**Verdict: page/MinerU.** The one genuine rule defect among them was found,
fixed and re-measured — the next section.

### The small classes

`two figures in one column` (12), `no header` (10), `last row unmatched` (7)
are all cases where the reader could not establish the table's shape and
correctly declined. `figure retention` fired zero times, so no rebuild was
caught landing on a neighbouring table.

---

## The `--` rule gap, fixed (and what fixing it actually took)

The first run's anchor refusals contained one class that was genuinely the
**rule**, so under spec §4.1 it was fixed rather than counted.

JLBC prints a dash for "no value". `_label_text`'s docstring has always said
dash-zeros are stripped from a printed label — but it enumerated only the
ASCII hyphen (`w == "-"`). A page whose whole last column reads `--` therefore
kept its figures inside the label text, no anchor could match it, and the
table was refused for a low anchor rate **with every one of its labels printed
plainly on the page**. `jlbc-baseline-fy2013-irc-0000` scored 29%.

**Which dash spellings actually occur** was measured rather than assumed —
over 250 sampled in-scope pages of the live corpus, the standalone dash-only
tokens the text layer yields are:

| token | occurrences |
|---|---|
| `-` (U+002D) | 1,123 — already handled |
| **`—` (U+2014)** | **243** |
| `–` (U+2013) | 7 |
| `--` | 5 |

So the em dash, not the double hyphen, is the common unhandled spelling. The
fix is one predicate, `_is_dash_zero`, over the whole dash block.

### 🔴 Fixing `_label_text` alone would have made the corpus WORSE

The obvious one-line change strips the dash from the label and stops there.
Run against the real `jlbc-baseline-fy2013-irc-0000`, that rebuilds as:

```
Lump Sum Appropriation --	106,100	3,000,000
AGENCY TOTAL --	106,100	3,000,000
```

— the dash glued to the **label** and the FY 2013 column **empty**, which is
worse than MinerU's own reading, which at least has the `--` in the right
column. The cause is that the same unenumerated rule appears **twice**:
`_rows`' column assignment also said `w.text == "-"`, so a `--` was not
recognised as a figure-column value and fell through to the label. Both call
sites now use `_is_dash_zero`. Correct output:

```
Lump Sum Appropriation	106,100	3,000,000	--
AGENCY TOTAL	106,100	3,000,000	--
```

### What the fix moved, measured by diffing the two full runs

| | |
|---|---|
| refused → **rebuilt** | **3** |
| **rebuilt → refused** | **0** |
| refusal reason changed | 2 |
| rebuilt in both runs whose text changed | 1 |

**Recovered by the `--` fix:** `jlbc-baseline-fy2013-irc-0000` (was
`anchor match 29%`), `jlbc-baseline-fy2014-irc-0000` (`29%`),
`jlbc-baseline-fy2015-irc-0000` (`40%`).

**Two moved from an anchor refusal to an arithmetic one** —
`jlbc-approps-fy2007-doc-0000` (was 76%) and `jlbc-approps-fy2008-adc-0000`
(was 75%). They now locate their region and fail the gate instead, which is
why `arithmetic` went 141 → 143 while `anchor match` went 52 → 47.

**The one changed rebuild is the most valuable thing the fix caught.**
`jlbc-approps-fy2007-min-0000` was already `rebuilt` before the fix, and was
producing:

```
Aggregate Mining Reclamation Fund --	0	0
SUBTOTAL - Other Appropriated Funds --	0	0
```

That would have been **written to the corpus** with the dash on the label and
the last column empty. It now reads `… 0 0 --`. A latent wrong output on a
row nothing was flagging.

**A prediction that was wrong, recorded because it was:** a read-only
monkeypatch probe run before the fix predicted **4** recoveries, naming
`jlbc-baseline-fy2013-axs-0000` alongside the three `irc` chunks. It did not
recover — it was an `arithmetic` refusal before and still is. The probe
patched `_label_text` only, so it was measuring a fix that was never shipped.
The shipped number is 3.

---

## `ANCHOR_MIN_MATCH` — keep 0.8

`ANCHOR_MIN_MATCH = 0.8` was the spec's placeholder. The distribution now
exists, taken over all 4,875 tables, rebuilt and refused:

```
ALL 4875    : min 36%  p10 94%  p50 100%  p90 100%
rebuilt     : min 80%  p10 95%  p50 100%
refused (47): min 36%  p50 67%  max 78%
```

Rebuilt tables by match rate: 80–82% 10, 82–84% 6, 84–86% 13, 86–88% 25,
88–90% 15, 90–92% 43, 92–94% 239, 94–96% 296, 96–98% 182, **98–100% 3,827**.

**There is a real gap, and 0.8 sits in it.** No table anywhere in the corpus
scores between 78% and 80% — the highest refusal is **0.7778** and the lowest
rebuild is exactly **0.8000**. Any threshold in that interval gives
byte-identical behaviour, so this is a plateau, not a cliff edge.

Moving it either way was checked against the same distribution:

| threshold | effect |
|---|---|
| 0.75 | re-attempts 11 of the 47 refusals |
| **0.80 (keep)** | — |
| 0.85 | would refuse **16 tables that currently rebuild and pass the arithmetic gate** |

⚠ **The 0.85 figure is 16, not 29.** 29 is the number of rebuilds scoring
below **0.86**, and reading it as the cost of a 0.85 threshold is an
off-by-one-bucket error: the whole 0.84–0.86 bucket is 13 tables at exactly
**0.8571** (12/14), every one of which a 0.85 threshold *keeps*. The correct
count of rebuilds below 0.85 is 16.

**Real tables are not being cut by the threshold.** The 47 refusals are low
because their denominator contains anchors no printed line can match, not
because their regions are badly located — so lowering the number treats a
symptom and buys at most a handful of tables while weakening the one check
that says "I found the right region". Raising it costs 16 verified rebuilds
for nothing measured. 0.8 stays, and the conclusion rests on the
0.7778/0.8000 plateau rather than on the cost of moving.

---

## What the rebuild changes, in aggregate

| | |
|---|---|
| merged cells (two figures in one cell) **removed** by the rebuilds | **8,666** |
| merged cells that **stay wrong**, on 126 refused chunks | 490 |
| footnote markers separated from their figure | 10,706 |
| four-column rebuilds (the FY2005–FY2010 page shape) | 174 |
| rebuilds with the same row count as MinerU | 2,294 |
| rebuilds with fewer rows (un-fusing a split row) | 1,018 |
| rebuilds with more rows (un-fusing a merged row) | 1,344 |
| **rebuilds byte-identical to the stored text** | **66 of 4,656 (1.4%)** |

### The no-op share matters to Task 11

66 rebuilds (1.4%) produce text byte-identical to what is already stored.
The apply path rewrites four columns unconditionally (spec D4), so those 66
rows would be re-embedded and re-written for no change. At 1.4% this is not
worth special-casing — skipping them adds a branch to the write path to
save 66 rows of ~4,900 — but the number is recorded here so Task 11 decides
on evidence rather than guessing.

### Row growth, and prose

Only **2 of 4,656** rebuilds gained more than three rows:

* `jlbc-approps-fy2026-att-0000` (51 → 55) is a clean win. MinerU had
  `Federal Funds TOTAL - ALL SOURCES` and `9,178,500 212,501,700` fused into
  single cells; the rebuild separates them into
  `Federal Funds 9,178,500 22,135,500 9,712,700` and
  `TOTAL - ALL SOURCES 212,501,700 232,670,200 222,873,200`, and splits a
  fund name that wraps over two printed lines.
* `jlbc-baseline-fy2020-occ-0000` (17 → 22) pulls the page's
  `AGENCY DESCRIPTION`, `FOOTNOTES` and footnote body in as label-only rows.
  MinerU's stored table already contains the same prose (OCR-mangled as
  `AGENcY DEscRIPTioN`), so this reformats an existing defect.

**18 of 4,656 (0.39%)** pull at least one prose row in — 53 rows in total,
all of them label-only (no figure column is affected). **13 of the 18
already carried the same prose inside MinerU's own table.** The five that
newly introduce one add a single row each, and all five are named here:
the page masthead (`Executive Director: … JLBC Analyst: …`) on
`jlbc-approps-fy2005-nci-0000`, `jlbc-approps-fy2006-nci-0000` and
`jlbc-approps-fy2011-for-0000`; a rule of underscores on
`jlbc-baseline-fy2026-acc-0000`; and the agency description on
`jlbc-approps-fy2018-sdb-0000`, which MinerU's own table also carries but
OCR-mangled (`AGENcY DEscRIPTioN`), so the "already present" comparison
does not see it as the same string.

Note on reading this figure: the first version of this diagnostic counted
*any* bare label row and reported 4,650 of the first run's 4,653, which says
nothing — 89%
of bare label rows are `FUND SOURCES`, `OPERATING BUDGET`,
`Other Appropriated Funds` and `SPECIAL LINE ITEMS`, real JLBC section
headings, most of them ones MinerU had fused into the following row and the
rebuild correctly split out. The CLI now reports only rows the rebuild
introduced that read as prose.

---

## Digit disagreements (spec §6.1) — the text layer is right every time

**1,141 disagreements on 613 of the 4,656 rebuilt tables.** A disagreement
is a comma-grouped or decimal figure present in one reading and absent from
the other, after the arithmetic gate has passed.

Twenty examples were sampled and every individual figure in them (28 in
total) was checked against the printed page. **All 28 resolve in favour of
the text layer. MinerU is wrong in every one.**

| chunk | disagreement | who is right, and why |
|---|---|---|
| `jlbc-approps-fy2008-judcoa-0000` | `-147.51`, `+147.5` | **Text layer.** The PDF prints `147.51/` — an FTE count of 147.5 immediately followed by footnote marker `1/`. MinerU read the number **147.51**, *and put it on the `OPERATING BUDGET` heading row, leaving the `Full Time Equivalent Positions` row's column empty* — so the stored table has the wrong number in the wrong place. The page's own footnote says *"Of the 147.5 FTE Positions for FY 2008…"* |
| `jlbc-approps-fy2008-doafs-0001` | `-105.51` | **Text layer.** Same shape: printed `105.51/`, MinerU read `105.51`, the rebuild reads `105.5 [1/]` |
| `jlbc-approps-fy2007-dhspub-0000` | `+2,300,000 +248.1 +4,260,900 +518,000 +7,100,000 +768,000` | **Text layer.** All six are printed on the page and absent from MinerU's table |
| `jlbc-approps-fy2014-des-0000` | `+52,251,200 +56,060,000` | **Text layer.** Both printed; `56,060,000` is on **page 2** (`Workforce Investment Act Grant … 56,060,000 17/`) — the forward walk found it |
| `jlbc-approps-fy2025-uniasu-0000` | `-8,285.71`, `+(10,995,800)` | **Text layer.** `8,285.71` is not printed anywhere (an FTE + marker fusion); the accounting-negative `(10,995,800)` is printed and MinerU lost it |
| `jlbc-approps-fy2020-uninau-0000` | `+2,291,800` | **Text layer** — printed, absent from MinerU |
| `jlbc-approps-fy2006-ata-0000` | `+25,000` | **Text layer** — printed |
| `jlbc-approps-fy2026-dps-0000` | `+5,000,000` | **Text layer** — printed |
| `jlbc-approps-fy2016-spb-0000` | `+10,627,400` | **Text layer** — printed |
| `jlbc-approps-fy2019-ema-0000` | `+1,700,000` | **Text layer** — printed |
| `jlbc-baseline-fy2025-doa-sfd-0000` | `+77,898,600` | **Text layer** — printed |
| `jlbc-approps-fy2011-dhsash-0000` | `+748.9` | **Text layer** — printed |
| `jlbc-baseline-fy2016-dcs-0000` | `+2,784.9` | **Text layer** — printed |
| `jlbc-approps-fy2008-doafm-0000` | `+7,433,800` | **Text layer** — printed |
| `jlbc-approps-fy2013-rev-0000` | `+860.3` | **Text layer** — printed |
| `jlbc-baseline-fy2021-sfb-0000` | `+45,805,900` | **Text layer** — printed |
| `jlbc-approps-fy2022-pos-0000` | `-5.01` | **Text layer.** Not printed — an FTE+marker fusion MinerU invented |
| `jlbc-baseline-fy2020-ema-0000` | `-69.61` | **Text layer.** Not printed — same fusion |
| `jlbc-approps-fy2021-uniumain-0000` | `-6,021.31` | **Text layer.** Not printed — same fusion |
| `jlbc-approps-fy2016-azh-0000` | `-51.91` | **Text layer.** Not printed — same fusion |

The recurring `NN.N1` shape is the single most valuable thing this run
surfaced: MinerU silently multiplies an FTE count by roughly ten whenever a
footnote marker follows it without a space, and those figures are in the
corpus today, citable.

---

## Eval intersection (G-OT2) — 1 of 51, and it passes

```
Eval intersection (G-OT2): 1 of 51 ground-truth chunk ids in eval/queries.yaml
are in scope for this pass
       q-013 jlbc-approps-fy2025-unibor-0000          rebuilt    anchor_found=True
```

**Both numbers are printed deliberately.** The spec expected five in-scope
ground-truth ids; exactly one of the 51 in `eval/queries.yaml` is an
operating table this pass touches. The other four the spec names sit in
in-scope document types but are not operating tables and carry no ladder
marker (a Community Corrections expenditure table, a prison-closure budget
plan, an Auditor General "SUMMARY OF FUNDS" table and a COVID-19
expenditure table), so `in_scope` correctly never admits them.

G-OT2 passes on what it covers. What it covers is one chunk, and a bare
"all passing" line would read like five times more assurance than exists.

---

## A before/after pair, verbatim

`jlbc-baseline-fy2024-hom-0000` (extractor, 4 merged cells, anchor 100%),
from the run log. Four defects in six lines — a heading fused onto a data
row, a footnote digit fused onto a figure, a fund name split across two rows,
and two subtotal rows crushed into one:

```
--- before
Other Operating Expenditures AGENCY TOTAL	16,900	17,000	17,000 51,9001/
	46,200	51,900	
FUND SOURCES Other Appropriated Funds			
Board of Homeopathic and Integrated Medicine	46,200	51,900	51,900
Examiners' Fund			
SUBTOTAL - Other Appropriated Funds	46,200	51,900	51,900 51,900
SUBTOTAL - Appropriated Funds TOTAL - ALL SOURCES	46,200 46,200	51,900 51,900	51,900
--- after
Other Operating Expenditures	16,900	17,000	17,000
AGENCY TOTAL	46,200	51,900	51,900 [1/]
FUND SOURCES			
Other Appropriated Funds			
Board of Homeopathic and Integrated Medicine Examiners' Fund	46,200	51,900	51,900
SUBTOTAL - Other Appropriated Funds	46,200	51,900	51,900
SUBTOTAL - Appropriated Funds	46,200	51,900	51,900
TOTAL - ALL SOURCES	46,200	51,900	51,900
```

`51,9001/` is stored in the corpus today as this agency's FY 2024 total, on a
row whose label reads `Other Operating Expenditures AGENCY TOTAL`.

The other 19 pairs are reproduced by re-running the command at the top of
this document with `--pairs 20` (the sample is seeded, so the same 20 come
back).

Two more were verified by hand against the spec's own expectations:
`jlbc-approps-fy2026-axs-0000` rebuilds with `TOTAL - ALL SOURCES`
FY 2026 = `23,010,071,300`, `DES Eligibility` FY 2026 = `99,294,500 [3/]`,
and the two `SUBTOTAL` rows separate; `jlbc-approps-fy2006-col-0000`
rebuilds as a **four-column** table with `AGENCY TOTAL`
FY 2006 = `15,352,300 [1/]`.

---

## What is deliberately NOT changed here

One reader improvement was found, measured, and left alone: **excluding
MinerU header-row and figure-as-label anchors from the match-rate
denominator**, which would let 40 of the 52 first-run anchor refusals clear
80% (an upper bound on recoveries, not a count of them).

It changes `chunking/readers/text_layer_table.py`, which every one of the
4,875 tables goes through, so it would invalidate this dry run and could move
tables in both directions. It belongs in a follow-up with its own full dry
run and its own before/after comparison. The gate passes without it.

(The `--` gap found alongside it *was* fixed, because it was the rule rather
than the page — see "The `--` rule gap, fixed" above. The full dry run was
re-run afterwards and every number in this document is from that second run.)

**Also a follow-up, and larger than this pass:** `_resolve_blob` cannot find
the source PDF for 329 in-scope documents anywhere but a dev checkout, and it
is the same resolver the in-app PDF viewer uses. See the machine-dependence
section above.

---

## Recommendation: GO to the rehearsal

* Both G-OT1 floors are cleared with margin (95.5% overall against 90%;
  worst year 83.7% against 70%).
* Every refusal class was read and none is a rebuild defect that would put
  wrong figures in the corpus: 141 of 143 arithmetic refusals fail in
  MinerU's own reading too, and the anchor refusals are caused by anchors no
  printed line can match.
* The one refusal class that *was* the rule has been fixed and the whole run
  repeated: 3 tables recovered, **0 moved rebuilt → refused**, and one latent
  wrong rebuild corrected before it could be written.
* `figure retention` fired **zero** times, so no rebuild was caught landing
  on a neighbouring table — the failure mode that the arithmetic gate
  structurally cannot see.
* Every sampled digit disagreement resolves in favour of the text layer.
* The blast radius of the imperfect cases is small and bounded: 18 chunks
  (0.39%) gain a label-only prose row, 2 gain more than three rows, and 219
  chunks are left exactly as they are.

**Conditions on the rehearsal**, all of them things this dry run cannot
answer:

* 🔴 **Run the apply from a checkout where `data/cached-pdfs/` resolves**
  (this worktree, with the main checkout's cache hard-linked in), or **327
  tables this plan promises to rebuild will be refused as `no source pdf`**
  and FY2025/26/27 will come out at 47–50%. The CLI now exits non-zero on a
  full run in that state, but the apply is the run where it would cost
  something.
* Rehearse on a **copy** of the corpus, not the live one, and diff the
  written rows against this plan before touching the share.
* Re-run the dry run immediately before the apply. The plan is a hypothesis
  about rows as they are now; the apply's compare-and-swap will skip a row
  whose text moved, and a large skip count means the plan is stale.
* Confirm the reversal record lands on disk before the first row moves, and
  that the snapshot is CRC-verified.
* Watch the FTS index rebuild: re-added rows are invisible to BM25 until it
  runs.
* The 66 byte-identical rebuilds will be re-written and re-embedded. That is
  accepted, not overlooked.

---

# The rehearsal on a COPY (Task 11) — applied, verified, and measured

Everything below happened on **2026-09-02**, on a **copy** of the corpus.
**The live corpus was not written to and is byte-identical to what it was
before this session.** The only thing this task did to the live store was
*read* it twice: once for the G-OT2 control eval, once to confirm the copy
was current.

The copy lives in this session's scratchpad and is not committed. It was
made from the live data dir after the section-path repair had been applied,
and was re-verified as current immediately before the write: **83,197
`budget_chunks` rows on both, 22,889 table rows on both, and a SHA-256 over
every table row's `(chunk_id, text)` identical on both**
(`4504f94a17e16a52`). `documents.json` is byte-identical (same size, same
mtime).

## 🔴 A configuration trap the rehearsal found before the live apply could

The copy's `pdfs/` started life as a **symlink** to the live one, which is
the obvious way to avoid copying a gigabyte. It silently breaks the pass.

`app.routes.pdf._resolve_blob` fully resolves each candidate path and then
requires the result to sit inside the root it was built from. A symlink
resolves *out* of the data dir, so the containment check rejects it. The
first dry run on the copy reported:

```
no source pdf: 4533          (of 4,875 in-scope tables)
   all    4875      327     4548   6.7%
```

— 6.7% instead of 95.5%, with FY2025/26/27 at 47–49% and every year before
2025 at **0.0%**. The corpus was fine; the data dir's `pdfs/` was a symlink.
This is the exact mirror of the machine-dependence section above (there the
*repo-relative* blobs failed on a worktree; here the *data-dir* blobs failed
on a symlinked copy), and between them the two halves cover both of
`_resolve_blob`'s roots.

Replacing the symlink with a real directory fixed it. A hard-link tree
(`cp -al`, 0 extra bytes) is the cheap fix but **could not be used here** —
the scratchpad is `tmpfs` and the corpus is on `btrfs`, so
`Invalid cross-device link`. A real `cp -a` of 7,628 PDFs / 1.1 GB took
**1.8 seconds** into tmpfs.

**For the live apply this trap does not arise** — the real data dir's
`pdfs/` is a real directory. It matters for any future rehearsal, and it is
why the "run from a checkout where `data/cached-pdfs/` resolves" condition
now has a twin: **the rehearsal data dir's `pdfs/` must be a real directory
too.**

## The pre-apply dry run reproduced the recorded run to the row

Spec §6.1's condition — re-run the dry run immediately before the apply,
because the plan is a hypothesis about rows as they are *now*.

```
JLBC_DATA_DIR=<copy> uv run python -m chunking.repair_tables \
  --report <scratch>/table-rebuild-predry.json --pairs 20
```

| | recorded run (2026-09-02, live, read-only) | pre-apply run (the copy) |
|---|---|---|
| in-scope tables | 4,875 | **4,875** |
| rebuilt | 4,656 | **4,656** |
| unverified | 219 | **219** |
| overall rate | 95.5% | **95.5%** |
| `no source pdf` | 0 | **0** |
| arithmetic / anchor / two-figures / no-header / last-row | 143 / 47 / 12 / 10 / 7 | **143 / 47 / 12 / 10 / 7** |
| source extractor / html | 4,533 / 342 | **4,533 / 342** |
| byte-identical rebuilds | 66 (1.4%) | **66 (1.4%)** |
| digit disagreements | 1,141 on 613 tables | **1,141 on 613 tables** |
| eval intersection | q-013 `jlbc-approps-fy2025-unibor-0000` rebuilt | **identical** |

Every per-year row matched as well. **The plan is not stale.**

## The apply on the copy

```
JLBC_DATA_DIR=<copy> uv run python -m chunking.repair_tables --apply \
  --report <scratch>/table-rebuild-rehearsal.json --pairs 20
```

Start `2026-09-02T12:38:54Z`, end `2026-09-02T12:46:07Z` — **7 min 13 s**,
exit 0. Where it went:

| phase | wall clock |
|---|---|
| plan 4,771 documents (before the lock, before the snapshot) | ~00:40 |
| snapshot + CRC verify (670 MB zip) | ~00:40 |
| write 4,656 rows in 10 batches, embedder included | ~05:20 |
| verify + full-text index rebuild + optimize | ~00:35 |

⚠ **Budget more than 7 minutes for the live run.** The planning phase read
every source PDF **warm** here — the pre-apply dry run had just read the same
7,628 files minutes earlier, so they were in the OS page cache. That same
planning phase took roughly **four minutes** cold, in the dry run. On a cold
cache expect **10–12 minutes** end to end, and longer if the corpus is on the
share rather than a local disk.

The terminal's last line, verbatim:

```
wrote 4656 rows; skipped 0 (text moved); snapshot lancedb-20260902T123934Z.zip; reversal <copy>/table-rebuild-reversal-budget_chunks-2026-09-02T1239Z.json
```

and the write phase's own lines, verbatim:

```
snapshot: lancedb-20260902T123934Z.zip
writing reversal record to <copy>/table-rebuild-reversal-budget_chunks-2026-09-02T1239Z.json
reversal record written: <copy>/table-rebuild-reversal-budget_chunks-2026-09-02T1239Z.json
budget_chunks: wrote batch 1/10 (500/4656 rows, 0 skipped -- text moved)
...
budget_chunks: wrote batch 10/10 (4656/4656 rows, 0 skipped -- text moved)
budget_chunks: verified 4656 rewritten rows in full and 200 untouched rows
full-text index rebuilt and table optimized
budget_chunks: 4656 table(s) rewritten, 0 skipped (text moved)
```

**No warning banner of any kind was printed** — not the snapshot-is-the-only-
way-back message, not the reversal-record-could-not-be-rewritten message.

Checked afterwards, not assumed:

* **`skipped 0`.** The compare-and-swap found every row exactly as planned.
* **The snapshot landed and was CRC-verified before the first row moved** —
  `backups/lancedb-20260902T123934Z.zip`, 670,968,512 bytes.
* **The reversal record landed before the first row moved**, then was
  rewritten after the clean write: `stage: "written"`, `skipped_moved: []`,
  **4,656 rows**, each carrying `before` and `after` for **both** `text` and
  `table_html` (30.5 MB). Spot-read for `jlbc-baseline-fy2024-hom-0000`: the
  `before` is MinerU's `FY2022 ACTUAL` header, the `after` is the rebuilt
  `FY 2022 ACTUAL`.
* **No row was added or removed.** The full `chunk_id` set of
  `budget_chunks` is identical on the live store and the written copy —
  83,197 rows, same ids, same SHA-256 (`24aa1a2394906914`).
* **The full-text index was rebuilt**, so the rewritten rows are visible to
  BM25.

## 🔴 Idempotence is 99.9%, not 100% — and a second apply would be a small step BACKWARDS

Spec §6.2 asks the second dry run to find nothing left to change. It very
nearly does, and the exception is worth stating precisely because it turns
"don't re-run this" from tidiness into a rule.

Second dry run on the written copy:

```
   all    4875     4655      220  95.5%
Rebuilds byte-identical to the stored text: 4651 of 4655 (99.9%)
```

**Five chunks of 4,656 (0.107%) behave differently on a second pass.** All
five were read.

**Four are a wrapped fund label, and pass 1 is the CORRECT one.** JLBC prints
a long fund name over two lines. MinerU truncates it at the line break; the
rebuild walks the page and recovers the continuation word. On a second pass
the stored anchor is already the complete name, it matches the first printed
line, and the reader stops at the line boundary — dropping the word back off.
**The figures are identical in all four; only the label's last word differs.**

| chunk | MinerU (today) | pass 1 (what was written) | pass 2 would give |
|---|---|---|---|
| `jlbc-approps-fy2018-dcs-0002` | `…Needy Families Block` | **`…Needy Families Block Grant`** | `…Needy Families Block` |
| `jlbc-approps-fy2026-axs-0000` | `…Medically Needy` | **`…Medically Needy Account`** | `…Medically Needy` |
| `jlbc-approps-fy2024-axs-0000` | — | **`…Medically Needy Account`** | `…Medically Needy` |
| `jlbc-approps-fy2027-axs-0000` | — | **`…Emergency Health Services Account`** | `…Emergency Health Services` |

**The fifth changes verdict and costs nothing.**
`jlbc-approps-fy2008-dhsbehav-0000` is `rebuilt` on pass 1 (anchor 91.8%) and
`unverified — arithmetic` on pass 2 (anchor 100%): the different anchor set
locates a different region, which fails the gate. A refusal keeps the stored
text (spec D3), so pass 1's verified output simply stays. No harm.

**What this does and does not mean.**

* Applying **once** — which is what the plan does — produces the correct
  reading in all five cases, and every one of the 4,656 written tables passed
  the arithmetic gate.
* Applying **twice** would degrade four fund labels by one word each and
  leave the fifth alone. **The plan and spec need the same do-not-re-run
  banner the section-path repair carries**, and the live apply must be run
  exactly once.
* **It is NOT a defect in the ingest path.** `chunk_doc` always reads the
  cached extractor output plus the PDF and never the corpus, so a re-ingest
  reproduces pass 1, not pass 2 — which is exactly what G-OT3 below measures.
* The cause is that `repair_tables` takes its anchors from **the stored
  table**, so feeding it its own output changes its input. Fixing it (anchor
  on the extractor output rather than the corpus row) is a real follow-up,
  and it is not needed to apply once.

## G-OT3 — the repair and the ingest path agree: drift 0

40 documents sampled with a fixed seed from the 4,268 extractor-source
documents the apply rebuilt, re-chunked through the **real** `chunk_doc` with
`source_pdf` passed (spec D7), and every table chunk's body compared against
the row the apply wrote:

```
extractor-source rebuilt documents: 4268
of which the source PDF resolves: 4268
documents: 40   table chunks compared: 119   drift: 0
```

Two details that make the number mean something:

* `source_blob_path` is resolved with `_resolve_blob`, the same resolver the
  repair uses, **not** `root / path` — 329 documents record a repo-relative
  `data/cached-pdfs/…` path that `root / path` cannot find, and a
  re-chunk that silently loses its PDF reads MinerU's table and reports drift
  that is a configuration fact rather than a D5 break.
* `resolve_extract_dir` is called with the sidecar's `extraction.method`, the
  way `repair_tables` calls it. Without it, two of the forty
  (`jlbc-approps-fy2027-dis`, `jlbc-approps-fy2027-uniumain`, both
  `method: mineru`) resolved to nothing and were skipped — the first run of
  this check compared 38 documents and said so.

Line 0 is excluded from the comparison: the section-path repair owns it.

## G-OT2 — the eval, before and after, on identical query sets

Both runs are the same 47-query set, the same code (`46a3d5e`), on this
machine 17 minutes apart. The corpus is the only variable.

| | **control — LIVE corpus, unmodified** | **after the apply — the copy** |
|---|---|---|
| file | `eval/results/2026-09-02T1238Z-46a3d5e.{json,md}` (committed) | `<scratch>/eval-rehearsal/2026-09-02T1255Z-46a3d5e.{json,md}` |
| recall@5 | 85.71% | **85.71%** |
| recall@15 | 97.62% | **97.62%** |
| recall@20 | 100.00% | **100.00%** |
| refusal precision | 60.00% | **60.00%** |
| fallback rate | 30.95% | **30.95%** |
| lookup / comparison recall@5 | 89.19% / 60.00% | **89.19% / 60.00%** |
| latency p50 / p95 | 744 / 835 ms | 734 / 772 ms |

The control reproduces the recorded 2026-09-02 section-path post-apply
baseline (`eval/results/2026-09-02T0248Z-cc24905`) exactly on all four
headline figures.

**Per query, not just in aggregate:**

* **`STATUS FLIPPED: []`** — no query changed pass/fail.
* **0 rank changes** and **0 `matched_via` changes** across all 47 queries.
* **One query's top-5 list moved: `q-017`**, and it is not this pass's doing
  in any direct sense — all five of its chunks are `agao-afr-*`, an Auditor
  General document type that carries no operating tables and that this pass
  never touches. Rewriting 4,656 chunks changes corpus-wide term statistics,
  and rebuilding the full-text index re-scores every document; `q-017` still
  passes at rank 1 with the same top hit.

**`q-013`, the ONE in-scope ground-truth id** (`jlbc-approps-fy2025-unibor-0000`,
*"Board of Regents' approved General Fund appropriation in FY 2025…"*):
**pass → pass, rank 1 → rank 1, `matched_via` `dimensions_fallback` both
times, `top_score` 5.404738426208496 both times, and a byte-identical top-5
list.** It is unchanged in every recorded respect.

⚠ Read that narrowly, exactly as G-OT2 was written to be read: **one** of the
51 ground-truth ids is in scope. A clean eval says "nothing broke on the
queries we have", and the queries we have can barely see this change. G-OT3
and the read pairs are what actually check the rewrite.

## The no-op share — measured, and still not worth a branch

66 of the 4,656 rebuilds (1.4%) produce text byte-identical to what is
already stored, and spec D4 rewrites four columns unconditionally, so all 66
were re-embedded and re-written for no change. At the measured write rate
(1,500 rows in 124 s, ≈82 ms/row) that is **about 5 seconds of a 7-minute
apply, ~1.2% of the write phase**, plus 66 rows in the reversal record.
Skipping them would add a branch to the write path to save five seconds.
**Recommendation stands: leave it.**

## Two imperfections in the written output, both read and both small

* **A dash-zero carrying a footnote marker stays on the label.**
  `_is_dash_zero` knows `--` but not `--2/`, so
  `jlbc-approps-fy2007-min-0000` rebuilds as
  `Ch. 319 Aggregate Mined Land Reclamation --2/ | 0 | 0 | (empty)`.
  A corpus-wide scan of every rebuilt table finds **exactly 2** of 4,656 with
  this shape (the other is `jlbc-approps-fy2026-sos-0000`,
  `Special Election Expenses -19/`). Both are still better than what they
  replace — in the `min` case MinerU had fused the special line item and
  `AGENCY TOTAL` into one row and put the dash in the total's column. Not
  fixed; recorded.
* **18 tables (0.39%) pull one label-only prose row in**, 13 of which already
  carried the same prose inside MinerU's own table. Unchanged from the dry
  run and already described above.

---

# ⏸ CHECKPOINT — for Destin. One question at the end.

**Nothing has been written to the real corpus.** Everything above was done on
a throwaway copy. The next step needs your yes or no.

## What this is, in plain words

Every JLBC agency page has one budget table on it — the one that lists
Personal Services, Employee Related Expenditures, the special line items, the
fund sources, and the agency's total. There are **4,875** of them in the
corpus, going back to FY 2005.

Those tables were read out of the PDFs by a machine (MinerU), and it garbles
them. It fuses two rows into one, so a heading ends up glued to a data row.
It fuses two numbers into one cell. It sticks a footnote marker onto the end
of a figure, turning `147.5` into `147.51`. It drops the last word of a fund
name that runs over two lines. An analyst reading a search result sees a
number that is wrong or a label that belongs to a different row.

This pass re-reads those tables from the PDF's own text layer and **only
keeps the new reading if the table's arithmetic works out** — the parts have
to add up to the printed subtotals and totals. If it doesn't add up, the
table is left exactly as it is today. Nothing is deleted, nothing is moved,
no passage changes its identity, and no citation breaks.

## How many pass, year by year

**4,656 of 4,875 (95.5%)** rebuild and verify. The rest keep what they have.

| FY | tables | rebuilt | rate | | FY | tables | rebuilt | rate |
|---|---|---|---|---|---|---|---|---|
| 2005 | 140 | 136 | 97.1% | | 2017 | 257 | 248 | 96.5% |
| 2006 | 148 | 144 | 97.3% | | 2018 | 250 | 245 | 98.0% |
| 2007 | 146 | 136 | 93.2% | | 2019 | 231 | 230 | 99.6% |
| 2008 | 162 | 147 | 90.7% | | 2020 | 229 | 219 | 95.6% |
| **2009** | **153** | **128** | **83.7%** | | 2021 | 228 | 220 | 96.5% |
| 2010 | 150 | 133 | 88.7% | | 2022 | 229 | 221 | 96.5% |
| 2011 | 142 | 132 | 93.0% | | 2023 | 230 | 219 | 95.2% |
| 2012 | 258 | 251 | 97.3% | | 2024 | 233 | 223 | 95.7% |
| 2013 | 251 | 243 | 96.8% | | 2025 | 227 | 221 | 97.4% |
| 2014 | 251 | 239 | 95.2% | | 2026 | 227 | 220 | 96.9% |
| 2015 | 251 | 240 | 95.6% | | 2027 | 224 | 215 | 96.0% |
| 2016 | 258 | 246 | 95.3% | | **all** | **4,875** | **4,656** | **95.5%** |

The weakest stretch is FY 2007–2011 — the era of the four-column page and the
smallest agency pages. The floor the plan had to clear was 90% overall and
70% in any one year; the worst year is 83.7%.

## The 219 that stay garbled, and why

They keep exactly the text they have now, so nothing gets worse for them.

| how many | why | is it fixable? |
|---|---|---|
| **143** | **the printed page doesn't add up.** The column's own parts don't sum to the total JLBC printed | **No — and this is the check working.** For 141 of the 143, MinerU's reading doesn't add up either. `jlbc-approps-fy2012-adc-0000`'s FY 2011 operating subtotal is printed $847.6M against $849.6M for the sum of its own lines. The book is off by $2.0M. We refuse rather than store a table nobody can verify |
| **47** | the page couldn't be located confidently enough | Mostly not a real problem: the thing being matched includes the page's masthead (`Director: … JLBC Analyst: …`), which is printed as one line and can never match. Excluding those would let ~40 of them try again. Deliberately left for a separate pass with its own measurement |
| **12** | two figures crammed in one column | No |
| **10** | no header row could be found | No |
| **7** | the last row didn't match | No |

## What it looks like — 3 of the 23 pairs

The full set of 23 before/after pairs is at
`<scratchpad>/table-rebuild-pairs-23.txt` (the CLI's own seeded 20, plus 3
asked for by name). Three worth reading:

**1. FY 2006 Exposition and State Fair Board — figures on the wrong rows.**
This is the four-column page shape, and it is the strongest single argument
for doing this.

```
--- before (in the corpus today)
Full Time Equivalent Positions       186.0    186.0 4,865,100    186.0    186.0
Personal Services                3,537,100    1,131,200    4,947,800 1,291,900    4,865,100 1,153,500
Employee Related Expenditures Professional and Outside Services    740,400    3,515,400
Travel - In State                2,329,100    13,100    3,522,700 13,100    3,515,400
AGENCY TOTAL                     9,934,500   15,147,600   15,352,3001/   15,123,9001
--- after
Full Time Equivalent Positions       186.0        186.0        186.0        186.0
Personal Services                3,537,100    4,865,100    4,947,800    4,865,100
Employee Related Expenditures      740,400    1,131,200    1,291,900    1,153,500
Professional and Outside Services 2,329,100   3,515,400    3,522,700    3,515,400
Travel - In State                   11,200      13,100       13,100       13,100
AGENCY TOTAL                     9,934,500  15,147,600   15,352,300 [1/] 15,123,900 [1/]
```

Today the corpus says this agency's FY 2005 Personal Services was
**$1,131,200**. It was **$4,865,100** — the $1,131,200 is Employee Related
Expenditures, one row down. Two whole expense rows are fused into one label
with no figures at all.

**2. FY 2024 Board of Homeopathic Medicine — four defects in six lines.**

```
--- before
Other Operating Expenditures AGENCY TOTAL   16,900   17,000   17,000 51,9001/
                                            46,200   51,900
SUBTOTAL - Appropriated Funds TOTAL - ALL SOURCES   46,200 46,200   51,900 51,900   51,900
--- after
Other Operating Expenditures    16,900   17,000   17,000
AGENCY TOTAL                    46,200   51,900   51,900 [1/]
SUBTOTAL - Appropriated Funds   46,200   51,900   51,900
TOTAL - ALL SOURCES             46,200   51,900   51,900
```

`51,9001/` is stored today as this board's FY 2024 total.

**3. FY 2026 AHCCCS — a $99 million figure with a footnote stuck to it.**

```
--- before      DES Eligibility   116,083,200   98,906,500   99,294,5003/
--- after       DES Eligibility   116,083,200   98,906,500   99,294,500 [3/]
```

Also on that page, `AHCcCS Data Storage` becomes `AHCCCS Data Storage`.

## The number-fusing problem, which is the most valuable thing this found

When a footnote marker follows a figure with no space, MinerU reads them as
one number. **Twenty examples were checked figure-by-figure against the
printed page — 28 individual numbers — and the text layer is right in every
single one.** Examples:

| page | in the corpus today | what the PDF prints |
|---|---|---|
| `jlbc-approps-fy2008-judcoa-0000` | **147.51** FTE positions — and on the wrong row, leaving the FTE row's column empty | `147.5` FTE followed by footnote `1/`; the page's own footnote says *"Of the 147.5 FTE Positions for FY 2008…"* |
| `jlbc-approps-fy2008-doafs-0001` | **105.51** | `105.5` + footnote `1/` |
| `jlbc-approps-fy2022-pos-0000` | **5.01** | `5.0` + footnote — the figure `5.01` is printed nowhere on the page |
| `jlbc-baseline-fy2020-ema-0000` | **69.61** | `69.6` + footnote |
| `jlbc-approps-fy2021-uniumain-0000` | **6,021.31** | `6,021.3` + footnote |
| `jlbc-approps-fy2025-uniasu-0000` | `8,285.71`, and the accounting negative `(10,995,800)` **lost entirely** | `8,285.7` + footnote; `(10,995,800)` is printed |
| `jlbc-approps-fy2007-dhspub-0000` | six figures **missing** | `2,300,000`, `248.1`, `4,260,900`, `518,000`, `7,100,000`, `768,000`, all printed |

An FTE count roughly multiplied by ten, sitting in the corpus, citable.
In total the two readings disagree about **1,141 figures on 613 tables**.

## What else changes

* **8,666** fused cells get separated; **10,706** footnote markers get
  detached from their figures. **174** four-column FY2005–FY2010 pages are
  rebuilt in that shape. (All recomputed from the rehearsal's own plan, not
  carried over from the dry run.)
* **490** fused cells stay wrong, on the 126 refused tables.
* **18 tables (0.4%)** pull in one extra label-only line, usually the page's
  `AGENCY DESCRIPTION`. 13 of the 18 already had that text in the table. No
  figure is affected.
* **2 tables** grow by more than three rows, both read and both correct.
* Nothing else in the corpus moves: same 83,197 passages, same identities,
  same pages, same agencies, same funds.

## Does it hurt search? No — measured before and after

Same 47 questions, same code, 17 minutes apart, corpus the only difference:

| | before | after |
|---|---|---|
| recall@5 | 85.71% | **85.71%** |
| recall@15 | 97.62% | **97.62%** |
| recall@20 | 100.00% | **100.00%** |
| refusal precision | 60.00% | **60.00%** |

**Not one question changed pass/fail, and not one changed rank.** One
question's fifth result swapped for a different Auditor General passage —
a document type this pass never touches.

Be careful how much comfort you take from that: **only 1 of the 51
ground-truth passages in the eval set is one of these tables**. It passes,
at the same rank, with the same score. The eval mostly cannot see this
change; the read pairs and the arithmetic gate are what actually check it.

## How safe is it, and can it be undone

* A **CRC-verified snapshot** of the whole corpus is taken before the first
  row moves (670 MB, ~40 s).
* A **reversal record** is written before the first row moves and rewritten
  after, listing all 4,656 rows with their exact before and after text.
* Every rewritten row is **re-read and verified** after the write, plus 200
  untouched rows as a control.
* The rehearsal wrote **4,656 rows, skipped 0**, and no warning was printed.
* Verified afterwards: **no passage was added, removed, or renamed.**

**One caution.** Running the apply a *second* time would be a small step
backwards: four fund labels would lose their last word again (`…Medically
Needy Account` → `…Medically Needy`; the figures are unaffected). So it must
be run **exactly once**, and the plan will carry a do-not-re-run banner the
way the section-path repair does. Re-ingesting a document later is *not*
affected — that path re-reads the PDF, and was tested: 40 documents
re-processed from scratch produced byte-identical tables.

## Two conditions on the live run

1. **It must run from this worktree** (`~/ask-the-budget-az-worktrees/agency-tables`),
   or any checkout that has `data/cached-pdfs/`. 329 documents' PDFs are only
   findable there, and from a checkout without them 327 tables that should be
   rebuilt would be refused instead, with FY2025–27 dropping to about 48%.
2. **A fresh control eval must be run immediately before it** if any time
   passes — a remembered number is not a control.

## The question

**Apply this to the live corpus — yes or no?**

If yes, it is one command, roughly 7–15 minutes, with the snapshot and the
reversal record as the way back.
