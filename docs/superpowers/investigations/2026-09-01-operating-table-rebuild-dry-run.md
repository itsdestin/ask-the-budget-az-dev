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
