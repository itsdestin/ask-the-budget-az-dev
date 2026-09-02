---
status: shipped
---

# The reconciliation gate, calibrated on the stored corpus (G-OT0)

Task 5 of `docs/superpowers/plans/2026-08-26-agency-table-rebuild-design.md`
Task list; spec §4 and §4.1. This is the calibration step spec §4.1 asks
for: run `chunking/table_gate.py::reconcile` over the operating-table
chunks that are already "clean" — no merged cell, no fused marker — and
see whether they reconcile as printed, **before any rebuild code (the
text-layer reader) exists.** Nothing was written to the corpus; this is a
read-only scan (`ChunkStore(create=False)` + `.scan`).

## The command and its final output

```
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
  uv run python -m chunking.repair_tables --calibrate
```

```
  year   clean  passed   rate
  2005      18      14  77.8%
  2006      29      21  72.4%
  2007      31      20  64.5%
  2008      37      27  73.0%
  2009      35      21  60.0%
  2010      43      13  30.2%
  2011      38      25  65.8%
  2012     118      97  82.2%
  2013     108      86  79.6%
  2014     101      81  80.2%
  2015     100      84  84.0%
  2016     143     113  79.0%
  2017     120     103  85.8%
  2018     111      99  89.2%
  2019      97      88  90.7%
  2020      76      66  86.8%
  2021      68      54  79.4%
  2022      72      63  87.5%
  2023      73      65  89.0%
  2024      73      66  90.4%
  2025      78      67  85.9%
  2026      87      75  86.2%
  2027      69      60  87.0%
   all    1725    1408  81.6%
```

Population, for scale: 4,875 in-scope chunks (spec D1: `is_table` and one
of the two operating-table doc types and a ladder marker in the text) —
matches the spec's own count exactly. Of those, 1,725 (35.4%) are "clean"
by the two cheap filters (`has_merged_cell`, `has_fused_marker`) — a bit
below the spec's "roughly half" estimate, which was never more than an
estimate.

**The overall rate is 81.6%, well under the brief's 95% trigger for
investigation.** What follows is that investigation: whether the shortfall
is a bug in `reconcile`'s arithmetic (fixable — and one real bug WAS found
and fixed this way, see below), or something else.

## One real rule bug, found and fixed

`parse_figure` crashed with `decimal.InvalidOperation` on a lone
accounting-dash token (`-`, JLBC's printed zero) whenever the cell was
**not exactly** `-` — e.g. `-` glued to other text on the same tab cell
after `peel_markers` ran, or simply because `figure_tokens("-")` returns
`["-"]` (a non-empty list), which skipped the old whole-cell shortcut
(`if not tokens: return Decimal(0) if cell.strip() == "-" ...`) and fell
through to `Decimal(tok.strip("()$")...)` with `tok == "-"`, which is not
a valid `Decimal` literal. This crashed the calibration run outright on
its first pass (`decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]`)
against real corpus rows — no fixture in `tests/test_table_gate.py` has a
lone accounting-dash cell, so the sketch's own tests never exercised it.

Fixed in `chunking/table_gate.py::parse_figure`: the `-`-is-zero check now
looks at the TOKEN, not the whole cell. A regression test,
`test_accounting_dash_is_zero_even_alongside_other_tokens`, is in
`tests/test_table_gate.py`. This is the only rule change this calibration
produced.

## Why the rest is not a rule bug — read, not assumed

After the fix above, the calibration ran to completion at 81.6%. Before
accepting that number, ~50 of the 317 failing chunks were read in full —
across the worst year (2010, 30.2%), the "other" bucket (a check row
whose own label carries no obvious extra words: bare `AGENCY TOTAL`,
`OPERATING SUBTOTAL`, `TOTAL - ALL SOURCES`), the small-dollar-difference
bucket (≤ $500 off, 13 cases — the ones most likely to be a subtle rule
bug rather than a wholesale row mixup), and a random sample of 20 more.

**None of them is a rule bug. Every one traces to one of two things
already present in the STORED table text (Phase A's MinerU-cell
rendering), neither of which `reconcile` can see or fix:**

1. **Row/label misalignment — the dominant class, most of the 317.** A
   group heading's label bleeds onto the following body row's line (`Other
   Appropriated Funds Information Technology Fund` — heading + the one
   fund under it, glued into one printed line with the fund's values), or
   a check row's label bleeds onto the PRECEDING body row while its
   VALUES land on the next line with a blank label (`Operating Budget
   Lump Sum Reduction AGENCY TOTAL` on one line, `1,016,000  1,064,400
   995,300` with no label on the next). Both shapes make `_classify`
   correctly report what it sees — a body row it cannot tell is really a
   heading, or a check row whose value column doesn't match anything
   because half its real content sits one line away. The rule is not
   wrong about the input; the input is wrong. Read examples, chunk ids:
   `jlbc-approps-fy2025-hla-0000`, `jlbc-approps-fy2025-paz-0000`,
   `jlbc-approps-fy2025-wifa-0000` (see class 2 below too),
   `jlbc-baseline-fy2014-cpd-0000`, `jlbc-baseline-fy2027-lan-0000`,
   `jlbc-approps-fy2012-cpd-0000`, `jlbc-baseline-fy2012-wei-0000`,
   `jlbc-baseline-fy2017-wei-0000` (`Equipment AGENCY TOTAL` fused),
   `jlbc-baseline-fy2013-wei-0000` (`Vapor Recovery AGENCY TOTAL` fused),
   `jlbc-baseline-fy2016-sdb-0000`, `jlbc-approps-fy2011-spb-0000` (`5th
   Special Session Reduction AGENCY TOTAL` fused), `jlbc-approps-fy2005-usl-0000`,
   `jlbc-approps-fy2008-rev-0000` (severely column-shifted, not just one
   row), `jlbc-approps-fy2006-nur-0000` (a header row fused with the
   analyst's name, then the FTE row's values land one row early — this is
   the source of the $39.2 "OPERATING SUBTOTAL" near-miss in the
   small-diff sample), `jlbc-baseline-fy2027-acc-0000` (a large
   multi-program tribal-aid table — `STEM Aid STEM Aid - Cochise` and
   `Subtotal-STEM Aid Rural Aid` both show the same fusion). **2010 is the
   worst year (30.2%) because its four-column header (`FY2008 ACTUAL /
   FY 2009 ESTIMATE / FY2010 / APPROVED` — the last year's label
   literally split across two header cells) makes MinerU's row/column
   segmentation fail even more often than the three-column years** —
   sampled 6 of its 30 failures and all 6 show this same class, several
   badly enough that whole columns are shifted, not just one row
   (`jlbc-approps-fy2010-rad-0000`, `jlbc-approps-fy2010-bae-0000`).

2. **A footnote marker printed without its trailing slash — one case
   found, `jlbc-approps-fy2025-wifa-0000`.** `Long-Term Water Augmentation
   Fund Deposit  01  189,200,000  02/` — the FY2023 cell reads `01`, which
   is JLBC's `0` plus a dropped `1/` (every other marker in the same
   table has its slash: `02/`). `chunking/table_text.py::MARKER_RE`
   requires the slash, so `has_fused_marker` — correctly, per its own
   scope, which is figures fused with a WELL-FORMED marker — does not
   flag this. `parse_figure("01")` reads it as the literal number 1
   (which is exactly what those two characters spell), so `AGENCY TOTAL`
   comes out $1 too high. This is a genuine corpus text-extraction
   artifact outside both `has_fused_marker`'s and `reconcile`'s scope.
   Three more of the small-dollar-difference cases
   (`jlbc-approps-fy2007-dis-0000` off by exactly 1.0,
   `jlbc-baseline-fy2012-sbo-0001` off by exactly 3.0,
   `jlbc-approps-fy2016-boe-0000` / `jlbc-baseline-fy2023-dmb-0000` /
   `jlbc-approps-fy2006-osh-0000` off by exactly 1) look like the same
   shape but were not individually traced back to their source PDF.

**No failure read shows JLBC's own printed numbers failing to add up.**
Every one is explained by the CURRENTLY STORED representation
misattributing a label to the wrong row or column — which is a property
of Phase A's MinerU-cell-structure rendering, not of the page itself.

## Why this is not a reason to change the gate, and not a surprise either

The brief's own Step 4 already carries the number that puts this in
context: **the gate run against the phase-B reader — which rebuilds a
table's rows from the PDF's own text layer instead of trusting MinerU's
cell/row boundaries — passed 199 of 206 real agency pages (96.6%) on
2026-09-01**, with the two refusals being a genuinely wrong printed total
and one anchor match under threshold. That is the number that measures
whether the GATE is right. This calibration measures something different
and narrower, on purpose (spec §4.1): whether MinerU's EXISTING row
structure, on the subset that looks superficially clean, already adds
up. It mostly does not, and the reason is now characterized rather than
guessed at: MinerU's vision-based table reconstruction gets row/label
boundaries wrong far more often than it fuses two figures into one cell
or fuses a marker onto a figure — the two things `has_merged_cell` and
`has_fused_marker` were built to catch. That is exactly the defect class
phase B's rebuild-from-text exists to remove by construction (it never
consults MinerU's cell boundaries at all), and this calibration is the
first quantified measurement of how much of it there currently is: **1
in 5 "clean" tables, worse than 2 in 3 in the four-column years around
FY2010.**

**Per this task's brief ("never loosen it to tolerance"), the rule in
`table_gate.py` was left as specified beyond the one real bug fixed
above.** Building a new detector for row/label fusion would be scope
creep onto the phase-B reader's job (a later task) and would risk hiding
the exact defect class the rebuild exists to fix, rather than gating on
it honestly.

## What this means for later tasks

- **The "clean" filter (`has_merged_cell` / `has_fused_marker`) is a
  weaker signal than spec §4.1's framing assumed.** It rules out
  value-cell ambiguity only; it says nothing about row/label
  misalignment, which is the dominant real-world failure. Whoever reads
  §4.1 next should not expect "clean implies arithmetically whole" to
  hold on the stored corpus — it holds on the phase-B REBUILD, which is
  the point.
- **This is diagnostic of the corpus as currently stored, not a blocker
  for Task 5 or for phase B.** The dry run (a later task) measures the
  REBUILT tables against this same gate; 81.6% here is not a number that
  needs to reach 95% — 96.6% on the rebuild already does, and that
  number stands.
- A full per-chunk accounting of all 317 failures was not attempted here
  — that is disproportionate for a calibration step whose job is to
  validate the RULE, and the rule is validated. The chunk ids listed
  above are a representative, hand-read sample across years, magnitudes
  and failure shapes, not an exhaustive audit.

## Suite state at this commit

`uv run pytest tests/test_table_gate.py tests/test_repair_section_paths.py -q`
→ 54 passed (11 new gate tests + 43 unchanged `repair_section_paths` tests).
