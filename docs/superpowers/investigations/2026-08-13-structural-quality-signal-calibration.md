# A structural quality signal — calibrated corpus-wide

**Date:** 2026-08-13
**Corpus:** 7,433 documents / 80,854 budget chunks + 14,161 fiscal-note chunks
**Motivated by:** Plan B Task 8, which stopped rather than passed.

---

## Why this exists

Plan B's coverage floor (T6) measures **volume**: characters of chunk text
produced ÷ characters in the source's own text layer. It catches a document
that produced almost nothing. It cannot catch a document whose text all
arrived with its **meaning stripped off**.

That is not hypothetical. Re-processing `agao-afr-fy2024` through the shipped
ladder on 2026-08-13 scored **49.0% coverage** — comfortably over the 10%
floor, so the fallback never fired and the document was written `live`. Reading
its chunks showed why that is not good enough:

```
TOTAL FUND 409,164.00 314,457.00 434,194.52 289,426.48
```

Four figures, no column headers, no units. Its healthy sibling carries the
whole frame:

```
STATE OF ARIZONA GENERAL FUND COMPARATIVE BALANCE SHEET
FOR THE FISCAL YEAR ENDED JUNE 30, 2023 (expressed in thousands)
        June 30, 2023   June 30, 2022   Increase (Decrease)
Cash with the State Treasurer  $ 5,265,789  $ 6,664,017  $ (1,398,228)
```

Under Invariant 1 an unlabelled figure is **worse than a missing one**,
because it is still citable. Only 5 of FY2024's 388 chunks carry a units
statement, so a cited figure cannot resolve its own scale.

**The gap in one line: coverage measures how much came out, and nothing
measures whether it still means anything.**

---

## The signal

Fraction of a document's chunks that are **almost entirely digits**:

- a chunk is judged if it is ≥ 50 characters
- **whitespace is excluded from the denominator** (see below — this is
  load-bearing, not a detail)
- a chunk is *bare* when letters ÷ non-whitespace characters < 0.15

No vocabulary list, no per-publisher rule, no model.

## 🔴 The whitespace correction is what makes it work

The first version divided by total length. On that version the four **healthy**
AFRs scored 5.5–12.9% — because JLBC/AGAO table chunks carry heavy tab
padding, which dilutes the letter ratio and makes a fully-labelled header
chunk look bare. Reading the flagged chunks is what exposed it: FY2021's
"bare" chunks turned out to carry both a breadcrumb heading **and** the column
headers.

Excluding whitespace collapses the healthy documents to zero and leaves the
broken one untouched:

| document | raw ratio | whitespace-corrected |
|---|---|---|
| `agao-afr-fy2021` | 12.9% | **0.0%** |
| `agao-afr-fy2022` | 5.5% | **0.0%** |
| `agao-afr-fy2023` | 5.8% | **0.5%** |
| `agao-afr-fy2025` | 8.2% | **0.0%** |
| **`agao-afr-fy2024`** | **30.6%** | **30.6%** |

A ~60× separation where the naive version gave ~2.4×.

---

## The distribution

Corpus-wide, restricted to the **2,228 documents with ≥ 10 judged chunks**
(see the small-denominator trap below):

| percentile | bare-figure share |
|---|---|
| p50 | 0.00% |
| p90 | 0.00% |
| p99 | 0.88% |
| p99.9 | 6.25% |
| **max** | **30.63%** |

| threshold | documents caught |
|---|---|
| ≥ 5% | 3 |
| **≥ 10% … ≥ 30%** | **1 — `agao-afr-fy2024`** |

**Every threshold from 10% through 30% catches exactly the one document known
to be degraded.** The highest healthy document sits at 7.14%. That is a
plateau with a 4× gap on one side, so **20% is its centre** — the right pick
when a metric degrades on both sides, by the same rule that put the coverage
floor at 10%.

## 🔴 The small-denominator trap

Without a minimum chunk count the signal is worthless. Unrestricted, 15
documents score ≥ 15% — and **14 of them are 2–5 chunk documents** where a
single numeric chunk out of three reads as 33%. Only `agao-afr-fy2024`, at 382
judged chunks, is real.

A minimum of **10 judged chunks** removes all 14. The cost is stated plainly:
**a small degraded document is invisible to this signal.** That is a real
blind spot, not a solved problem.

## What legitimately scores high, and correctly stays below

The cluster just under the threshold is the Board of Regents (`unibor`)
per-agency pages at 2.4–2.9% across seven editions, and two `detailed-list-pdf`
documents at 6.25–7.14%. These are genuinely table-dense budget documents,
they are consistent across years, and they sit **4× below** the threshold. A
legitimately numeric document class does not look like a broken one.

---

## 🔴 The limitation that matters most

**This is calibrated against exactly ONE positive example.**

The distribution above establishes the **false-positive** side well: 2,227 of
2,228 documents score below 1%, so a 20% threshold will not fire on healthy
material. It says nothing about the **false-negative** side — there is no way
to estimate how many degraded documents this misses, because only one is
known.

Two consequences:

1. **Do not read "catches 1 of 2,228" as "the corpus has one bad document."**
   It means the corpus has one document bad *in this particular way*, at this
   threshold, among documents large enough to judge.
2. The signal should **route to a comparison, never to a verdict.** It is
   evidence that a second extractor is worth trying, not proof the document is
   broken.

## The evidence that a second extractor helps

Measured on the same page, same source file, page 100 of `agao-afr-fy2024`:

| | OpenDataLoader | MinerU |
|---|---|---|
| blocks | 17 paragraph, **0 table** | **1 table** |
| output | `‐‐ 5,338,307 ‐5,338,307 ‐ ...` | `<td>CAPITAL OUTLAY APPROPRIATIONS</td><td>REVERSIONS AND ADJUSTMENTS</td><td>NET APPROPRIATIONS</td>…` |

Every figure matches between the two — 5,338,307 / 5,441,241 / 1,558,759 /
12,338,307 / 10,779,549 — so nothing is lost or invented. MinerU recovers the
column semantics because it reads the page **visually** and ignores the
structure tree, and the structure tree is exactly what is wrong here: GAO
tagged FY2023's financial statements as tables and FY2024's as loose
paragraphs.

**Caveat:** MinerU's cell alignment is imperfect at the pinned 3.1.6 — some
currency markers land in adjacent cells. STATUS.md records that 3.4.4 fixes a
table row-misalignment seen at 3.1.6.

---

## Why neither shipped approach catches this

- **Inspect the input** (spec S26, superseded): its rule is *structure tree
  present → OpenDataLoader*. FY2024 **is** tagged, so S26 routes it exactly
  where it already goes. The two AFRs are indistinguishable on inspection —
  which the current spec states outright as the reason it judges output
  instead.
- **Measure output volume** (T6, shipped): 49% of the text did arrive.

The failure is **structural**, and it is a property of the individual
**document**, not of its type — same publisher, same series, consecutive
years, opposite outcomes. No per-doc-type rule can express it.

## Proposed shape, not yet built

1. Score the first rung's output with this signal — pure text analysis on
   chunks already in hand, no extra extraction, so healthy documents pay
   nothing.
2. Above the threshold, **probe** the alternative extractor on a sample of
   pages, score both the same way, keep the winner, run the winner in full.
   (A 5-page MinerU probe runs in minutes against ~30 for all 191.)

This must be a new spec decision with its own plan. Two things to settle
first: whether the probe's cost is acceptable for office uploads, and that
**changing a live document's extractor re-mints its `chunk_id`s**, which eval
ground truth is pinned to — so it applies to new uploads and deliberate
re-processing, never as a silent sweep.

## Reproducing

Script: `scratchpad/structure_calibration.py` (not committed — a one-shot
measurement whose input is the live corpus). Method fully specified above.

⚠ **Scan BOTH chunk tables.** `budget_chunks` alone omits all 2,103 fiscal
notes, which then score zero and read as catastrophically broken — the exact
error that wrecked the first pass of the coverage calibration.
