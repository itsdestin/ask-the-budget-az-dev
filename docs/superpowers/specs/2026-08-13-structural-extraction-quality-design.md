# Structural extraction quality — design

**Date:** 2026-08-13
**Decisions:** X1–X9, X11, X12 (X10 withdrawn)
**Status:** proposed — revision 3, 2026-08-13. All four prerequisite
measurements have now been RUN (results near the top). **One new blocker:** a
chunker heading-inheritance defect found by reading the winning chunks, which
must be decided before X4 ships.

## What this amends

This **amends T5 and T6** in
`docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`,
which shipped as Plan B on 2026-08-13 (merge `cb94195`).

T6 measures extraction **volume** — characters of chunk text produced ÷
characters in the source file's own text layer — and T5 falls back when that
volume is below a floor, keeping "whichever result scored highest".

Both are correct for the failure they were designed against, and both are
blind to the failure documented below. **Nothing here weakens the coverage
floor**; it stays at the calibrated 0.10 and keeps doing its job.

## What changed in revision 1

The first draft (decisions X1–X9) was reviewed against the investigations it
cites and against the shipped ladder code. Six changes:

1. **X1 strips markup before measuring** — believed at the time to be a defect
   fix. Revision 2 finds it is not (see below), and demotes it.
2. **X5 and X6 (dropping chunks) are deferred**, and the analyst-facing half of
   X7 defers with them. They were built on a measure with a defect and one
   positive example, and their behaviour was undefined at the exact document
   they were written for.
3. **X3's diagnosis was wrong and is corrected.** The shipped ladder does not
   mis-rank the extractors — it never compares them at all, because it stops at
   the first rung that passes.
4. **X10 restores the sample probe** the investigation recommended and the
   first draft silently dropped, along with the cost figure that motivates it.
   Revision 2 withdraws it.
5. **X11 records the score for every attempt, always** — the only path out of
   "calibrated against one example".
6. `STRUCTURE_FLOOR` is renamed `MAX_UNLABELLED`: it is a **ceiling**.

## What changed in revision 2

Revision 1's claims were checked against the shipped readers, chunk builders
and ladder, line by line. Six changes, three of them corrections of things
revision 1 asserted as established fact:

1. **🔴 X1's markup argument was aimed at the wrong layer and is demoted.**
   Chunk text never contains HTML on either reader path — MinerU's `table_body`
   is parsed into rows before chunking and the original markup is kept in a
   *separate column*. Stripping stays as a cheap forward-guard; the claim that
   its absence was "the worst defect" was wrong, and the test revision 1
   mandated for it would have passed while proving nothing.
2. **🔴 X9's explanation of the 278–286% coverage figures was wrong**, from the
   same false belief. The number is real; the stated cause is not.
3. **🔴 X3 gains a volume-collapse guard.** As written, "lowest unlabelled
   fraction wins among attempts that clear the floor" let an attempt that
   recovered 12% of a document beat one that recovered 49%. That is a new
   silent failure introduced by the fix, and nothing in revision 1 caught it.
4. **X4's "one change at one line" was false and is corrected.** Three
   coordinated edits are required, and getting only the first one produces a
   document **held out of search entirely** — worse than today.
5. **X10 (the sample probe) is WITHDRAWN**, and the cost problem it existed for
   is solved directly by the new **X12**: skip the OCR rung on a document that
   has a real text layer. That is one boolean, against a probe that needed its
   own sampling rule, contradicted X2's minimum chunk count, and collided with
   a hazard the shipped code documents in a comment.
6. **X11 additionally commits the corpus-wide scan that already exists.**
   Waiting for new uploads to produce a second example has no date on it; the
   scan costs nothing and re-extracts nothing.

Plus two smaller corrections carried into the text where they belong: revision
1's acceptance test for structural ranking was **written backwards** (it
asserted the coverage winner wins), and X12 must test `has_text_layer is True`
rather than truthiness, because `None` means *unknown* and skipping the OCR
rung on an unknown removes the rescue path from exactly the damaged documents.

## What changed in revision 3

**The four prerequisite measurements were RUN** rather than argued about. Full
results are the next section. What they changed:

1. **X3/X4 are strongly confirmed** — MinerU is 0.00% unlabelled at chunk level
   against OpenDataLoader's 30.63%. Risks 6 and 7 are both closed, and Risk 7
   turned out to be a false alarm with a useful answer: coverage prefers
   OpenDataLoader **because it counts the junk**.
2. **The letter ratio moves 0.15 → 0.10.** It was the load-bearing number all
   along, and 0.15 sits closer than anyone knew to the value that flags the
   healthy AFRs. The judging minimum turns out to be inert.
3. **🔴 Reading the winning chunks found a defect neither the counts nor the
   review could see:** the chunker propagates a section heading across pages
   that have none, attaching `(expressed in thousands)` from page 5 to a
   whole-dollar schedule on page 10 — a 1,000× units error in a chunk scoring a
   perfect 0.00%. It is on master today and X4 sends more documents down the
   path that carries it. **New precondition for shipping.**
4. **Revision 2's own optimism is corrected.** The corpus scan was predicted to
   yield a near-miss band; it was run, and the band is empty. Risk 1 stands.

---

## Prerequisite measurements — RUN 2026-08-13, all four

Run against the extractor output already on disk from the forced-fallback run
and against the live 95,015-chunk corpus. **Nothing was extracted, embedded,
written or re-minted.** Scripts in the session scratchpad
(`prereq_1_3_4.py`, `prereq4_followup.py`, `read_page10.py`,
`prereq2_sweep.py`); the corpus sweep is the one X11 says to commit.

### 1 — X1 at chunk level: the answer is emphatic, and Risk 6 is closed

| rung | chunks | judged | bare | **unlabelled** | vs 0.20 ceiling |
|---|---|---|---|---|---|
| opendataloader | 388 | 382 | 117 | **30.63%** | **ABOVE** |
| **mineru** | 450 | 450 | **0** | **0.00%** | under |
| mineru-ocr | 450 | 450 | 1 | 0.22% | under |

The 30.63% reproduces the investigation's figure **exactly**, from a different
script on a different day — the method is sound. MinerU does not merely halve
the problem at chunk level; **it removes every bare chunk**. X4's swap is
justified on the metric actually being adopted, not on a page-level proxy.

### 4 — the coverage anomaly is fully explained, and it indicts coverage

| | chunk characters |
|---|---|
| opendataloader total | 565,478 |
| mineru total | 516,399 |
| difference | 49,079 |
| **MinerU ÷ ODL** | **0.9132** |
| **shipped coverage 44.77 ÷ 49.03** | **0.9131** |

The two ratios agree to four decimal places, so the coverage gap is *entirely*
the chunk-character totals. **Nothing is being discarded — Risk 7 is resolved
and was a false alarm.**

What the extra 49,079 characters are is the finding: **186,184 of
OpenDataLoader's 565,478 characters (32.9%) sit inside its bare digit runs.**
Excluding them, OpenDataLoader carries 379,294 labelled characters against
MinerU's 516,399 — **MinerU carries 137,105 MORE labelled characters and still
scores lower on coverage.** The volume metric is rewarding the junk. The
structural split behind it: OpenDataLoader produced **1** table chunk out of
388; MinerU produced **422** out of 450.

### 2 — both unswept numbers swept; one is load-bearing, one is inert

**Letter ratio** (judging minimum 50, ceiling 0.20), documents flagged:

| ratio | flagged | what else gets caught |
|---|---|---|
| 0.05 – 0.175 | **1** | nothing — the known document, alone |
| 0.20 | 3 | two healthy JLBC baseline documents |
| 0.25 – 0.30 | 8 | **`agao-afr-fy2025`, `fy2021`, `fy2022` — the healthy siblings** |

**The plateau is 0.05–0.175 and it degrades on ONE side only.** Per the
CLAUDE.md rule that is a safe-edge pick, not a centre pick — and the shipped
0.15 sits 0.025 from a cliff that flags the healthy AFRs this whole spec uses
as its control. **Recommend 0.10**: the known document scores 30.63% at every
ratio from 0.05 to 0.30, so lowering it costs *nothing measured* and doubles
the margin. This is now a calibrated number, not a guess.

**Judging minimum** (ratio 0.15): 20, 30, 40, 50, 75, 100, 150 all flag
**exactly 1** document, with the known-bad score moving only 30.23%–30.71%.
**The 50-character minimum is inert.** Risk 4's specific worry — that it is
biased against short bare rows — is measured and does not matter. Keep 50 and
stop worrying about it.

### 3 — a real flagged chunk, verbatim

`agao-afr-fy2024-0033`, page 10, **0 letters of 697 non-whitespace
characters**, `is_table=False`, `section_path=[]`:

```
34,863,017 34,863,017    ‐34,863,017    ‐ ‐ 4,423,700    ‐4,423,700    ‐ ‐
1,415,900    ‐1,415,900    ‐ ‐ 151,400    ‐151,400    ‐ ‐ 1,661,900 …
```

This is what the measure actually catches, and it is worse than the line the
spec used to quote — the values are duplicated and sign-mangled as well as
unlabelled. **Use this one everywhere from now on.**

---

## 🔴 What reading the chunks found, which no count would have

The spec's own gate is "READ the kept chunks — the count is not the gate." Done,
on page 10, and it changes two claims.

**Page 9 and page 10 are one landscape spread.** Page 9 carries
`AGY BFY APCAT APPROPRIATION NAME` and the first money column; page 10 carries
the remaining five money columns and **no row labels at all**. MinerU recovers
page 10's column headers (`NET APPROPRIATIONS`, `EXPENDITURES`, `LAPSED
APPROPRIATION AUTHORITY`, …) where OpenDataLoader emitted pure digits — a large,
real improvement. But the line-item names live in the *previous* chunk, and the
chunker's multi-page table reassembly did not join them.

**🔴 And the heading it did attach is WRONG.** MinerU's page-10 chunk text
opens with:

> `… > STATE OF ARIZONA GENERAL FUND STATEMENT OF REVENUES, EXPENDITURES AND
> CHANGES IN FUND BALANCE APPROPRIATION (BUDGET) TO ACTUAL FOR THE FISCAL YEAR
> ENDED JUNE 30, 2024 (expressed in thousands)`

Pages 9, 10 and 11 contain **no heading block whatsoever** — only footers and
page numbers. That heading lives on **page 5**, and the chunker inherited it
forward across four pages *and across page 8, which is literally stamped "THIS
PAGE INTENTIONALLY LEFT BLANK"*. Page 5's statement genuinely is in thousands
(`Taxes … 7,900,090` = $7.9 billion). Pages 9–11 are an appropriations schedule
in **whole dollars** (`ARIZONA POWER AUTHORITY PLANNING AND NEEDS … 1,000,000`
is a $1 million line, not a $1 billion one).

**So the chunk carries a units statement that is wrong by a factor of 1,000,
and it scores a perfect 0.00% on this spec's new measure.** Under Invariant 1
that is worse than OpenDataLoader's bare digits: an unlabelled figure refuses to
answer, while a confidently mislabelled one answers wrongly. OpenDataLoader's
page-10 chunks carry `section_path=[]` and make no such claim.

**Three consequences, and they are load-bearing:**

1. **X1 can be satisfied by harmful content.** It counts letters; a wrong
   heading is letters. This is the coverage-versus-error-rate lesson again —
   the measure detects one failure shape and certifies nothing.
2. **Risk 2's wording must change** (below). "MinerU halves the bare-figure
   rate" was measured on pages; at chunk level it zeroes it. But "the document
   ends up better, not correct" is now *more* true, not less, and for a
   different reason.
3. **There is a chunker defect on master today**, independent of this spec:
   section headings propagate onto pages that carry none, including an
   intentionally blank one and across a statement boundary.

   **Scope, stated precisely, because the mechanism and the harm are not the
   same size.** The *mechanism* is live for **12 of the 14 PDF document types**
   — every one that defaults to MinerU, which is JLBC books, fiscal notes and
   almost everything else; only `afr` and `governors-budget` default to
   OpenDataLoader. The *harm* has been observed on **exactly one document**.
   Documents with a heading on most pages would inherit over a short distance
   and probably correctly; this AFR's financial statements run for pages with
   no heading block at all, which is what let a page-5 heading reach page 10.
   **How far this generalises is UNVERIFIED and must not be assumed in either
   direction.**

   **That needs its own investigation, and this spec should not ship without a
   decision on it** — X4 deliberately routes more documents onto the MinerU
   path, which is the path that carries the mechanism.

---

## The problem, in one paragraph

A document can produce the right *amount* of text with its *meaning* stripped
off. `agao-afr-fy2024` re-processed through the shipped ladder scores **49.0%
coverage** — comfortably over the floor, so no fallback fires and it is
written `live` — while **30.6% of its chunks are bare figures**, and only 5 of
388 chunks carry a units statement. Its healthy sibling carries the whole
frame — table title, `(expressed in thousands)`, and
`June 30, 2023 / June 30, 2022 / Increase (Decrease)`. Under Invariant 1 an
unlabelled figure is **worse than a missing one**, because it is still
citable: a model can quote a bare figure with no way to establish whether it
is revenue, an expenditure, or an ending balance, or whether it is dollars or
thousands of dollars.

**🔴 The line everyone quotes is NOT one this measure catches.** The
investigation introduces the problem with
`TOTAL FUND 409,164.00 314,457.00 434,194.52 289,426.48` — 9 letters of 49
non-whitespace characters, **18.4%, which X1 calls labelled**. The 30.6% figure
is real and was computed programmatically; that particular line simply is not
one of the chunks that produced it. **A genuinely flagged chunk is now recorded
above (prerequisite 3) — use that one everywhere instead.** A spec whose worked
example contradicts its own rule teaches the next reader the wrong rule.

**The document sits in a gap: not broken enough to trigger fallback, not good
enough to use.**

---

## The evidence

All measured on the live corpus, 2026-08-12/13. Full write-ups:
`docs/superpowers/investigations/2026-08-13-structural-quality-signal-calibration.md`
and `…/2026-08-12-coverage-floor-calibration.md`.

**The signal separates cleanly.** Fraction of a document's chunks that are
almost entirely digits, whitespace excluded from the denominator, over the
**2,228 documents with ≥ 10 judged chunks**:

| | bare-figure share |
|---|---|
| p50, p90 | 0.00% |
| p99 | 0.88% |
| p99.9 | 6.25% |
| highest healthy document | 7.14% |
| **max** | **30.63% — `agao-afr-fy2024`, alone** |

Every threshold from **10% through 30%** catches exactly that one document.

**The two extractors differ structurally.** From the forced fallback run — the
first real rung-to-rung fallback ever executed, with `COVERAGE_FLOOR`
temporarily raised to 0.52 so the ladder would fall past OpenDataLoader —
comparing each rung's raw output with HTML tags stripped:

| rung | coverage | real text | **pages** that are bare figures |
|---|---|---|---|
| opendataloader | **49.03%** | 344,872 | **28% (53/186)** |
| mineru | 44.77% | 353,141 | **13% (22/162)** |
| mineru-ocr | 43.68% | 353,002 | 13% |

MinerU more than halves the bare-figure rate while recovering the same
figures — every value on the sampled page matches between the two. Volume and
structure disagree, and structure is the one that tracks usability.

**🔴 A measurement gap, stated before anything is built on it.** That last
column is a share of **pages**, measured on raw extractor output. X1 measures a
share of **chunks**. They are not the same number and cannot be compared.
**No rung has yet been scored with X1 at chunk level** — so it is not currently
known whether MinerU's chunk-level unlabelled fraction lands above or below the
0.20 ceiling. That measurement is a prerequisite (see Testing → Prerequisite
measurements), not a nice-to-have: X3's entire justification rests on it.

**🔴 The same gap invalidated revision 1's markup argument, and there is a
second unexplained number here.** Raw output and chunk text are different
things in a way this spec kept forgetting. Verified in code 2026-08-13:
`chunking/readers/mineru_reader.py` parses MinerU's `table_body` HTML into
rows and cells before chunking; `chunking/builders/table_chunk.py` writes
tab-joined plain text and keeps the original markup on a **separate
`table_html` column** that search never reads; the OpenDataLoader reader
handles no HTML at all. **Chunk text therefore contains no tags on any path.**

That leaves a number nobody has explained: MinerU produced **more** raw text
(353,141 vs 344,872 tag-stripped characters) and **more** chunks (450 vs 388),
yet scored **lower** coverage (44.77% vs 49.03%) — and coverage is measured on
chunk text. Something between MinerU's output and its chunks is discarding
content that OpenDataLoader's path keeps. Whatever it is, it is upstream of
everything in this spec, and it may be a larger effect than the one being
fixed here. **Prerequisite 4 measures it before implementation.**

**Why neither existing approach catches it.** Spec S26 (superseded) inspects
the input — but the two AFRs are indistinguishable on inspection, and FY2024
**is** tagged, so S26 routes it exactly where it already goes. T6 measures
volume — and 49% of the text did arrive. The failure is **structural**, and it
is a property of the individual **document**, not of its type: same publisher,
same series, consecutive years, opposite outcomes, because GAO tagged FY2023's
financial statements as tables and FY2024's as loose paragraphs.

---

## Decisions

### X1 — The measure

A chunk is **unlabelled** when, **after markup is stripped**, letters make up
**less than 10%** of its **non-whitespace** characters, and it is at least 50
characters long.

*(0.15 in revisions 1 and 2; moved to 0.10 by the 2026-08-13 sweep — see below.)*

**🔴 Correcting revision 1: stripping markup is a cheap forward-guard, NOT the
defect it was billed as.** Revision 1 claimed that "nothing in `ingest/` strips
tags before chunking", so an unstripped MinerU chunk would score a false 0%
unlabelled. **That is false, and it was checked in the wrong place.** The
investigation measured MinerU's *raw output*, where the tags genuinely are;
X1 measures *chunk text*, where they never are — see the code references in the
evidence section above. Stripping tags from tag-free text is a no-op.

It stays in the spec for one honest reason: a reader that starts passing markup
through would silently break the measure, and stripping costs nothing. It is a
**guard against a future change**, and it must be described that way in the
code comment. Revision 1's stated justification would tell the next reader
something untrue about their own pipeline.

**The test revision 1 mandated for it was worse than useless** and is replaced
(see Testing). It asserted that a chunk shaped like
`<table><td>NET APPROPRIATIONS</td>…` scores as labelled. **The pipeline cannot
produce that chunk**, so the test would pass forever, including if the whole
feature were deleted — the same "green test that proves nothing" shape STATUS.md
records five instances of in the Budget Documents highlighting work alone.

**Excluding whitespace is equally load-bearing.** With whitespace counted, the
four healthy AFRs score 5.5–12.9% because JLBC and AGAO table chunks carry
heavy tab padding that dilutes the letter ratio — a fully labelled header chunk
reads as bare. Excluding it collapses the healthy documents to 0.0–0.5% and
leaves the broken one unchanged at 30.6%: a ~60× separation where the naive
form gave ~2.4×.

**✅ All three numbers are now calibrated (swept 2026-08-13).** The 0.20 ceiling
sits on a measured plateau (X2). The **judging minimum is inert** — every value
from 20 to 150 flags exactly one document — so 50 stays and Risk 4's worry about
short bare rows is measured and dismissed.

**🔴 The letter ratio is the load-bearing number, and 0.15 is closer to the
cliff than anyone realised.** The plateau runs 0.05–0.175 flagging exactly one
document; at **0.20** two healthy JLBC baselines are caught, and at **0.25** the
three healthy AGAO AFRs — the control group this spec reasons from — are caught
too. It degrades on one side only, so the rule is safe edge, not centre.
**Move it to 0.10.** The known document scores 30.63% at every ratio from 0.05
to 0.30, so the change costs nothing measurable and doubles the margin to a
cliff that would flag the good siblings as broken.

No vocabulary list, no per-publisher rule, no model.

### X2 — The ceiling is 20% unlabelled, over ≥ 10 judged chunks

**`MAX_UNLABELLED = 0.20`**, applied only to documents with **at least 10
judged chunks**.

**It is a ceiling, not a floor.** A document fails by scoring **above** it —
the opposite direction from `COVERAGE_FLOOR`. The first draft named it
`STRUCTURE_FLOOR`, which is precisely how a `>=` gets typed as a `<=` six
months from now by someone pattern-matching on the neighbouring constant.

20% is the **centre** of the 10–30% plateau, the same rule that put the
coverage floor at 10% — correct where a metric degrades on both sides. Below
10% it starts approaching legitimately numeric documents (the highest healthy
document is 7.14%); above 30% the one known case escapes.

**The minimum chunk count is not optional.** Without it, 15 documents score
≥ 15% and **14 of them are 2–5 chunk documents** where a single numeric chunk
reads as 33%. A minimum of 10 removes all 14.

**🔴 What this signal can actually see, in the honest denominator.** 2,228
documents have ≥ 10 judged chunks. The corpus has **7,434**. The other **~5,200
documents are invisible to this measure entirely** — not judged healthy, judged
not at all. "2,227 of 2,228 unaffected" is a true statement about 30% of the
library, and the first draft's phrasing invited it to be read as coverage of
the whole thing. A small degraded document remains a real blind spot, not a
solved problem.

### X3 — Structure picks the winner among attempts of comparable size

When more than one extraction attempt exists, the attempt kept is the one with
the **lowest unlabelled fraction**, not the highest coverage — **but only among
attempts that recovered a comparable amount of the document.** Coverage remains
the pass/fail floor; structure breaks the tie inside the comparable set.

**🔴 The comparability rule is not optional, and revision 1 had no such rule.**
`COVERAGE_FLOOR` is 0.10. "Lowest unlabelled fraction among attempts that clear
the floor" therefore lets an attempt that recovered **12%** of a document beat
one that recovered **49%**, because the 12% it recovered happened to be clean.
The result is a document quietly reduced to a quarter of itself, written
`live`, with the queue green — which is a **new** silent failure created by the
fix, and closely related to the one the whole ladder exists to prevent.

**`STRUCTURE_TIE_BAND = 0.75`.** An attempt participates in structural ranking
only if its coverage is at least 75% of the best measured coverage among the
attempts. Everything outside the band is ranked by coverage as it is today. On
the one measured pair (49.03% and 44.77%, a ratio of 0.91) both attempts are
comfortably inside the band, so this changes nothing about the known case and
exists entirely to bound the unknown ones.

**0.75 is a bound, not a calibration, and must be labelled as one in the code.**
There is no plateau behind it — one measured pair is not a distribution. It is
picked to be visibly looser than the known-good 0.91 and visibly tighter than
the floor. **X11's recorded scores are what will eventually let it be swept**;
until then it is a guard rail, and a guard rail that fires is a signal to
measure, not to widen.

**🔴 Correcting the first draft's diagnosis.** It claimed T5's "keep whichever
result scored highest" prefers OpenDataLoader over MinerU. It does not, because
it never runs: `ingest/worker.py::_extract_and_chunk` (**not** `_ladder` — no
function of that name exists, and revision 1 named it three times) **returns at
the first rung that passes the coverage floor** (`if outcome.passed: return
outcome`, worker.py:503), so `_outcome_rank` only ever compares rungs that all
failed — and its own docstring records that nothing downstream reads its
result. The forced-fallback run saw ranking only because the floor was
temporarily set to 0.52. **On the shipped code today, MinerU never runs on this
document at all.**

The order of the argument matters because it locates the cost: **X4 is the
change that fixes the document** and it is the one that buys extra extractions;
X3 is the rule X4 makes necessary, and it is free.

**Which output is judged: each attempt, on its own chunks.** Where two attempts
tie, coverage decides, preserving today's behaviour. Where an attempt's
fraction cannot be computed (fewer than 10 judged chunks), it does not
participate in structural ranking and is ranked by coverage. Where every rung
is above the ceiling, the lowest still wins and is written — a degraded
document that is the best available reading is still the best available
reading, and X7 makes that visible.

**A document type with only ONE rung is unchanged in every respect.** Word
documents (`budget-bill`) have a single extractor, so there is no second
reading to prefer and nothing for X3 or X4 to do. Such a document that trips
the ceiling is **still written live**, exactly as today, with its score
recorded under X11 and shown under X7. Revision 1 left this undefined, and the
two plausible readings of it differ by whether a whole document class
disappears from search.

### X4 — A tripped document does not stop at the first passing rung

A document that **passes** the coverage floor but is **above** the structure
ceiling advances to the next rung anyway, and X3 picks the winner.

This is what closes the gap: FY2024 passes on volume today and is never
retried.

**🔴 Revision 1 called this "one change at one line". It is three, and doing
only the first is worse than doing nothing.** `_extract_and_chunk` today has
exactly one exit for a healthy document (the early `return` at worker.py:503)
and one exit for a document where everything failed (the `best` path at
worker.py:514–523, whose result the caller holds out of search at
worker.py:314). A passing-but-tripped attempt currently belongs to neither. All
three must move together:

1. **The early return** becomes conditional on the ceiling as well as the
   floor.
2. **`_outcome_rank`** (worker.py:526) ranks by coverage and, by its own
   docstring, has only ever seen *failing* outcomes. It must now also rank
   passing ones, by X3's rule and inside X3's comparability band.
3. **The end-of-loop path** must be able to return a **passing** outcome. Today
   everything reaching it is assumed to have failed.

**If only the first is done, a tripped document falls out of the bottom of the
loop and is held out of search entirely** — an analyst who could previously
find FY2024's figures, badly labelled, now cannot find the document at all.
That is a strictly worse outcome than shipping nothing, and it is the single
likeliest way this change goes wrong. There is a named test for it below.

**A healthy document must still short-circuit.** The early return is what stops
every ordinary upload from paying for three extractions. Under the measured
distribution 2,227 of 2,228 judged documents keep today's behaviour exactly;
the guard for that is a test, not a hope (see Testing).

**Cost, which the first draft did not state.** A full MinerU rung on this
191-page document is roughly **30 minutes**. Revision 1 doubled that figure by
noting the ladder then runs `mineru-ocr` as well, and answered it with a probe
(X10). **X12 answers it directly instead**, by not running the OCR rung on a
document that has a real text layer — where it has been measured to change
essentially nothing. The honest remaining cost of a tripped document is
therefore **one extra extraction, roughly 30 minutes on a 191-page book**, and
proportionally less on the 2-page documents that make up most of the corpus.

### X5 — DEFERRED: dropping unlabelled chunks

**Not in this spec.** The first draft dropped unlabelled chunks from the
winning attempt so they could never be falsely cited. That is the right
long-term shape and it is not ready:

- **The measure's own numbers are not settled** (X1: two of three unswept,
  and revision 2 found the reasoning behind a third to be wrong). Dropping is
  irreversible; every other decision here is not.
- **One positive example.** Every other decision here routes to *trying another
  extractor and comparing*, which is self-checking. Deleting content on the
  strength of a threshold is not.
- **It was undefined at the exact document it was written for.** After X4 the
  winner is a different attempt, which may score *below* the ceiling. The draft
  could not say whether such a document should still have chunks dropped:
  judging the winner made its own acceptance test fail, and judging the
  discarded attempt meant deleting content from a result the measure calls
  healthy — contradicting X6's stated reason for existing.
- **X3 + X4 already do most of the work and are reversible.** They choose
  between two readings of the same PDF, and the losing output survives on disk.

**What deferring costs, stated plainly.** Invariant 1 is not enforced. FY2024
keeps some unlabelled figures live and citable — MinerU still leaves 13% of
pages bare. **The document ends up better, not correct.**

**What unblocks it:** X11's recorded scores **and its committed corpus scan**,
plus the X1 sweeps. The scan is the fast half — it can surface a second
example from documents already on disk, where waiting on new ingests cannot.
When the corpus has more than one positive example and the measure's own
numbers are calibrated, dropping is a small follow-up spec with its
analyst-facing notice.

### X6 — DEFERRED with X5

The rule that must survive into that follow-up: **a document below the ceiling
has nothing dropped**, even if a handful of its chunks are individually
unlabelled — healthy documents contain legitimately-numeric chunks whose labels
live in an adjacent chunk. **The threshold rejects; it never approves.**

### X7 — The administrator sees which rung won and why

Per document, the admin surface shows every extraction method tried, **each
one's coverage and unlabelled fraction**, and which one was kept.

**This is required even though nothing is dropped.** X4 changes which extractor
produced a live document, which re-mints its chunk IDs and changes its text. A
change of that size that leaves no trace is how a corpus becomes unexplainable
a year later.

**The analyst-facing notice defers with X5.** Nothing is withheld from search,
so there is nothing to tell an analyst. When dropping ships, its notice and the
admin wording are authored **server-side from one source** — this project has a
recorded history of server and UI copy drifting apart.

**No copy anywhere may describe the kept portion as verified, checked,
validated, healthy or good.** This measure detects one specific failure shape;
a document that passes has not been certified.

### X8 — Scope: new ingests and deliberate re-processing only

No corpus sweep, no backfill.

Changing which extractor produced a live document **re-mints its chunk IDs**,
and `eval/queries.yaml` ground truth is pinned to chunk IDs — the tool that
re-bound them after a re-ingest (`eval/refresh_chunk_ids.py`) was deleted and
nothing replaces it (verified 2026-08-13: no such file in `eval/`). Since
exactly one document in the corpus trips the ceiling, a sweep would carry the
full risk to fix a single case that can be re-processed by hand.

**Verified for the acceptance run:** `eval/queries.yaml` contains **no
reference to `agao-afr-fy2024`**. Its six pinned AGAO chunks are all
`agao-afr-fy2025-*` (`rg -n "agao" eval/queries.yaml`, 2026-08-13).
Re-processing FY2024 by hand therefore does not move Layer 1 ground truth,
which resolves the first draft's contradiction between "no existing document is
re-extracted by this change" and an acceptance step that re-extracts one. **The
converse is the warning: `agao-afr-fy2025` must not be re-processed casually**
— it is pinned, and no tool exists to re-bind its chunk IDs.

### X9 — The coverage floor is unchanged

`COVERAGE_FLOOR` stays **0.10**, calibrated across all 7,434 documents. A ratio
above 1.0 stays normal and uncapped — healthy AFRs score 278–286%.

**🔴 The reason revision 1 gave for that is wrong.** It said chunk text "carries
table markup the source text layer does not". It does not carry markup — see
the evidence section. The likelier causes are that section paths and header
rows are re-stamped into every chunk of a table, and that PyMuPDF's text layer
(the denominator) reads less of a table-heavy page than the extractors do.
**Neither has been measured.** The floor is unaffected either way — it only
rejects at the bottom — but the wrong explanation is what produced revision 1's
markup argument, so it is corrected here rather than left as harmless colour.

### X10 — WITHDRAWN: the sample probe

**Not in this spec.** Revision 1 restored the investigation's proposal that a
tripped document extract a **sample of pages** with the next rung, score both,
and pay for the full rung only if the alternative wins. It saves real time and
it is the wrong trade here. Four reasons, in order of how hard they are to work
around:

- **🔴 It collides with a hazard the shipped code documents.**
  `ingest/worker.py:436–452` carries an explicit warning that the page-journal
  reset is positional, and that *"if per-range incremental journalling is ever
  added within a single rung, this positional rule would clear a mid-rung
  journal it should have kept."* A probe is exactly per-range journalling
  within a single rung: it extracts some of rung 2's pages, then the full run
  must extract the rest of rung 2. On a crash-resume — which is the normal case
  for a 30-minute extraction — this can silently discard the probe's work or
  re-extract pages already paid for.
- **It contradicts X2.** X2 refuses to judge a document with fewer than 10
  judged chunks. A five-page sample will rarely produce ten chunks of 50+
  characters, so **the probe cannot be scored by the rule this spec adopts.**
  Revision 1 said "both samples are scored with X1" and never noticed.
- **The sample shape it specified is the worst possible one for MinerU.**
  MinerU reloads its models on every non-contiguous page range
  (`scripts/run_mineru.py:60–79`, whose comment says so). Revision 1's "evenly
  spaced across the document" means one model load **per page** — ten scattered
  pages cost ten startups. Contiguous blocks would be required, which is a
  third rule to author and calibrate.
- **It is not comparing like with like.** The incumbent's chunks were built by
  chunking the *whole* document; the challenger's from five pages. Chunk
  boundaries, section paths and multi-page table reassembly all differ.

**The cost problem is real and X12 solves it directly** — one boolean against a
mechanism needing its own sampling rule, its own scoring rule, its own tests
and a resume-safety proof.

**The warning inside X10 outlives it and must be carried into any future probe
work.** The investigation records a 5-page sample picked *because* it was the
pathological table section: it projected MinerU at 1.53× OpenDataLoader's
character count, where the true corpus-wide ratio is **0.91×**. Almost all of
the apparent advantage was HTML tags. **A sample chosen by the symptom only
confirms what you already believed.**

### X11 — Every attempt's unlabelled fraction is recorded, always

The score is written to the job record for **every rung that runs**, whether or
not it trips the ceiling, whether or not it changes anything. It is free — the
number is already computed.

**This is the mechanism that retires Risk 1 over time.** Today there is exactly one
positive example and no mechanism that would ever produce a second: documents
in the 10–19% near-miss band are silently ignored, and nothing writes down that
they were close. A threshold that never records its inputs can only ever be
re-argued, never re-tuned with evidence.

**It is also the only place the evidence can survive X5's eventual arrival.**
Once dropping ships, a document's post-drop score is 0.00 by construction — the
measurement erases its own reason for firing. Recorded per attempt, at the time
of the attempt, is the only point where the number is true.

**🔴 And on its own it is slow enough to be theoretical, so the existing corpus
scan is committed with it.** X8 forbids a sweep, so under X11 alone evidence
accrues only as new documents happen to be ingested. The corpus that exists —
7,434 documents — was built by a backfill that is finished, so the arrival rate
from here is whatever the office uploads, and nothing suggests that is fast.
"Wait for a second example" is therefore not a plan with a date on it. The
corpus-wide
scan that produced this spec's entire distribution **already exists**, reads
chunks that are already on disk, **re-extracts nothing and re-mints no chunk
IDs**, and therefore carries none of X8's risk. It is promoted from a
throwaway (`scratchpad/structure_calibration.py`, currently uncommitted) to a
committed script, and its per-document scores are committed as a dated
artefact.

**🔴 Correcting revision 2's own claim: the scan has now been RUN, and there is
no second example.** Revision 2 predicted the scan would deliver a near-miss
band today. It does not. At the shipped settings the entire corpus between 5%
and the ceiling holds **two** documents — `jlbc-baseline-fy2020-531` at 7.14%
and `jlbc-baseline-fy2018-545` at 6.25% — both already identified as
legitimately table-dense and healthy. **Between 7.14% and 30.63% the corpus is
empty.**

Two things follow, and the second is the one that matters:

1. **The ceiling is safer than claimed.** With a 23-point void around it, every
   value from roughly 8% to 30% behaves identically. 0.20 is not a delicate
   choice.
2. **Risk 1 is NOT retired, and the scan cannot retire it.** There is one
   positive example, the corpus contains no second, and only genuinely new
   documents can produce one. The scan is still worth committing — it is the
   instrument, the dated record, and the thing that makes the void auditable —
   but it buys evidence, not the evidence that was hoped for. **X5 stays
   deferred on exactly the ground it was deferred on.**

### X12 — The OCR rung is skipped when the document has a real text layer

`mineru-ocr` does not run when **`inspection.has_text_layer is True`**, unless
every earlier rung failed the coverage floor outright.

**`is True`, not truthiness — and this is the whole safety of the decision.**
`has_text_layer` is `bool | None` (`ingest/inspection.py:47`), and `None` means
*we could not tell*, which is not the same as *there is a text layer*.
`ingest/ladder.py:52-60` already carries a comment explaining that it tests
`is False` for exactly this reason. Skipping the OCR rung on an unknown would
quietly remove the rescue path from every document the inspector could not
read — which is disproportionately the damaged ones.

**Revision 1 deferred this and then spent a whole decision (X10) working around
the cost it creates.** That is backwards: the deferred decision is what sets
the cost figure the workaround was sized against.

**Measured, not assumed:** on `agao-afr-fy2024`, `mineru-ocr` produced 353,002
characters against `mineru`'s 353,141 and **the same 13% bare pages**. It cost
a full extraction to change essentially nothing. That is the expected result —
OCR earns its cost by reading a *scan*, and a document with a text layer is not
one.

**The escape hatch is what keeps this safe.** If every rung has failed the
coverage floor, the document is being held out of search anyway and OCR is the
last thing that might rescue it, text layer or not. So the skip applies only
where there is already a usable reading in hand. **A scan is unaffected**: it
has no text layer, so nothing about the OCR rung changes for the document class
that rung exists to serve.

**This is a T5 amendment, and it is stated as one.** It changes the shipped
ladder for every document, not only tripped ones, which is a wider blast radius
than anything else in this spec — hence the explicit test that a document with
no text layer still reaches the OCR rung.

---

## Risks

**🔴 Risk 1 — calibrated against ONE positive example.** The false-positive
side is well established: 2,227 of the 2,228 judgeable documents score under
1%, so a 20% ceiling will not fire on healthy material. **The false-negative
side is unknown and cannot be estimated from one example.** This is why X3/X4
route to *trying another extractor and comparing*, never to a verdict on the
signal alone, and why X5 is deferred rather than shipped. X11 is the mechanism
that makes this risk shrink with time instead of persisting forever.

**🔴 Risk 2 — REWRITTEN 2026-08-13, and it is now the most serious open item.**
Revision 1 said MinerU "halves the bare-figure rate; it does not eliminate it."
Measured at chunk level it *does* eliminate it — 0 of 450. **That is not the
good news it looks like.** Reading the winning chunks found the residual harm
has changed shape rather than gone away:

- **Row labels can end up in a different chunk.** Pages 9/10 are one landscape
  spread; MinerU recovers page 10's column headers but its line-item names sit
  in the page-9 chunk, and multi-page table reassembly did not join them.
- **🔴 The heading MinerU's chunk DOES carry can be wrong.** The page-10 chunk
  inherits `(expressed in thousands)` from page 5, across an intentionally blank
  page, onto a whole-dollar appropriations schedule — **a 1,000× units error
  stated with authority, in a chunk scoring a perfect 0.00%.**

Under Invariant 1 a confidently mislabelled figure is worse than an unlabelled
one. So the retry is still an improvement — MinerU recovers headers and, on
ordinary pages, full row labels — but **"better, not correct" is now a stronger
statement than it was, and nothing may imply the retry is a cure.**

**🔴 Risk 2b — the measure can be satisfied by harmful content.** X1 counts
letters; a wrong heading is letters. It detects one failure shape and certifies
nothing, which is what X7's "no copy may say verified, checked, validated,
healthy or good" already demands — this is the concrete example proving that
rule was not decorative.

**🔴 Risk 2c — the heading-inheritance defect is on master TODAY**, for every
MinerU-extracted document in the corpus, independently of this spec. X4
deliberately routes *more* documents onto that path. **A decision on it is a
precondition for shipping X4**, and it belongs in its own investigation, not
buried here.

**Risk 3 — RESOLVED as X12.** `mineru-ocr` earns nothing on a document that has
a text layer, and is now skipped there. Revision 1 left this open and paid for
it with X10.

**Risk 4 — RESOLVED by the 2026-08-13 sweep.** Both numbers now have plateaus.
The judging minimum is inert (20–150 identical); the letter ratio moves to 0.10
on a safe-edge argument, with the cliff located at 0.20–0.25 where healthy
documents — including the AFR control group — start being flagged. **X3's 0.75
band remains an uncalibrated bound**, and is the only number here still chosen
rather than measured.

**Risk 5 — upload latency.** A tripping document costs one extra full
extraction while someone waits — roughly 30 minutes on a 191-page book, less on
a short document. The measured distribution says this is roughly 1 document in
2,228, but that ratio is from the existing corpus and new uploads are not
guaranteed to resemble it. X12 removes the OCR rung's share of that cost for
every text-layer document, including ones that never trip.

**Risk 6 — RESOLVED.** The chunk-level comparison has now been run:
OpenDataLoader 30.63%, MinerU 0.00%, `mineru-ocr` 0.22%. X3 is justified on the
metric being adopted, not on a page-level proxy.

**Risk 7 — RESOLVED, and it was a false alarm.** Nothing discards MinerU
content. The coverage gap is exactly the chunk-character ratio (0.9132 measured
against 0.9131 implied), and OpenDataLoader's extra 49,079 characters are inside
its 186,184 characters of bare digit runs. **Coverage ranks OpenDataLoader
higher because it counts the junk** — which is the clearest single argument this
spec has for X3.

**Risk 8 — the fix can make a document worse if X3's band is wrong.** Preferring
structure over volume is only safe while the two attempts are comparable in
size. The band is the guard; one measured pair is the whole evidence behind it.
A document that arrives at the band's edge is a measurement to run, not a
threshold to loosen.

---

## Testing

Per CLAUDE.md: mechanism in pytest, quality in the eval.

**Prerequisite measurements: ✅ ALL FOUR RUN 2026-08-13** — results in the
section near the top of this spec. Summary: MinerU is 0.00% unlabelled at chunk
level against OpenDataLoader's 30.63%; the coverage gap is entirely
OpenDataLoader's bare digit runs; the letter ratio moves to 0.10 and the judging
minimum is inert; a real flagged chunk is recorded.

**🔴 A FIFTH prerequisite, created by what reading the chunks found:** decide
what to do about the chunker's **heading inheritance across pages that have no
heading of their own** — which today attaches a wrong `(expressed in thousands)`
to a whole-dollar schedule. It is a defect on master, not of this spec, but X4
routes more documents onto the path that carries it, so it must be decided
before X4 ships.

**pytest:**
- **Tab-padded labelled text scores as labelled** — the whitespace case the
  naive form gets wrong, and the one real behaviour of the measure that a unit
  test can pin.
- **Markup stripping is a no-op on chunk text as the pipeline produces it.**
  The test asserts what is true: a table chunk built by
  `build_table_chunk` contains no `<`, so stripping changes nothing. **Do NOT
  write revision 1's test** — a hand-built chunk full of `<td>` tags is a shape
  the pipeline cannot produce, so that test passes whether or not the feature
  exists.
- A document with fewer than 10 judged chunks is never judged on structure.
- **A document under the ceiling still short-circuits at the first passing
  rung.** This is what keeps 2,227 documents paying nothing, and it is the
  test that fails if X4 is written as "always run every rung".
- **🔴 A document that trips the ceiling and finds nothing better is still
  written live.** This is the X4 failure mode that is worse than shipping
  nothing: only the early return gets changed, the outcome falls out of the
  bottom of the loop, and the document is held out of search. The test drives
  `_extract_and_chunk` to the end of the rung list with a passing-but-tripped
  best attempt and asserts `outcome.passed` is True.
- Structural ranking beats coverage ranking **inside the band**: given a
  lower-coverage, lower-unlabelled attempt against a higher-coverage,
  higher-unlabelled one, **the FIRST wins** — the one with better structure.
  Pin it to the real measured pair (49.03 / 44.77) once prerequisite 1 exists.
  (Revision 1's wording said "the second wins", which describes coverage
  ranking — the behaviour this decision exists to replace. A plan transcribing
  it would have written a test that pins the bug.)
- **🔴 Structural ranking does NOT beat coverage ranking outside the band.**
  An attempt at 12% coverage with a perfect unlabelled fraction loses to one at
  49% coverage that trips the ceiling. This is the guard for the silent
  quarter-document, and it must be verified failing against an implementation
  with the band removed.
- A single-rung document type that trips the ceiling is written live, not held
  out (X3).
- **A document with no text layer still reaches the OCR rung** (X12) — the
  test that keeps scans working.
- **A document whose earlier rungs all failed the floor still reaches the OCR
  rung even with a text layer** (X12's escape hatch).
- Every rung that runs leaves an unlabelled fraction on the job record, including
  rungs that pass and rungs that lose (X11).
- Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.

**Eval:** Layer 1 must be **unmoved** — no corpus document is re-extracted by
this change, and the one hand-run acceptance document is not referenced by
`queries.yaml` (X8). Any movement is a finding to explain, not noise.

**Acceptance:** re-process `agao-afr-fy2024`. Expected: it exceeds
`MAX_UNLABELLED`, the ladder continues to MinerU under X4, MinerU is inside
X3's comparability band and wins on structure, `mineru-ocr` never runs (X12),
and the swap is visible under X7.

**Then READ the kept chunks** — the count is not the gate. The honest expected
outcome is **better, not fixed**: with X5 deferred, unlabelled figures remain.
If the kept chunks are no better than today's, stop and report rather than
tuning the ceiling.

**Also check the office-visible cost on an ordinary upload.** Upload one
healthy short document and confirm it still pays for exactly one extraction and
finishes in today's time. 2,227 of 2,228 documents must notice nothing, and the
person who will report it if they do is an analyst waiting on a queue page, not
a test.

## Explicitly out of scope

- **No dropping of chunks** (X5/X6, deferred to a follow-up spec).
- **No analyst-facing notice** (X7, defers with X5).
- **No sample probe** (X10, withdrawn — X12 solves the cost directly).
- **No corpus sweep, no re-extraction of any live document** (X8). The one
  scan X11 commits reads chunks already on disk and re-mints nothing.
- **No change to the coverage floor** (X9).
- **No new extractor.** This chooses better between the three that exist.
- **No structural repair.** Nothing here reconstructs a lost column header; it
  detects the loss and prefers the extractor that loses less.
- **No chunker change.** The failure has a chunking half — GAO's
  paragraph-tagged tables reach a narrative chunker that was never built for
  them — and fixing that is a different spec. This one changes which extractor
  is chosen, nothing about how its output is cut up.

---

## What this actually is, in four sentences

Everything above is four changes wearing twelve numbers:

1. **Measure** each extraction attempt for "figures with no words attached"
   (X1, X2).
2. **Don't stop early** at a rung that clears volume but fails structure, and
   keep the structurally better attempt *of comparable size* (X3, X4, X12).
3. **Write down every attempt's score, always**, and commit the scan that
   scores the corpus we already have (X11).
4. **Show the administrator** what was tried and what won (X7).

X5, X6, X8, X9 and X10 are all "we are not doing that." If the implementation
grows past one measurement function, one changed decision in
`_extract_and_chunk`, one number on the job record and one admin line,
something has been misread.
