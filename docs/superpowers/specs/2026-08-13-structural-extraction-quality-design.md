# Structural extraction quality — design

**Date:** 2026-08-13
**Decisions:** X1–X11
**Status:** proposed — revised 2026-08-13 after review

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

## What changed in this revision

The first draft (decisions X1–X9) was reviewed against the investigations it
cites and against the shipped ladder code. Six changes:

1. **X1 now strips markup before measuring.** Its omission was a defect, not a
   detail — MinerU's `<table><td>` tags count as letters, so an unmeasured
   MinerU chunk scores a false 0%.
2. **X5 and X6 (dropping chunks) are deferred**, and the analyst-facing half of
   X7 defers with them. They were built on a measure with a defect and one
   positive example, and their behaviour was undefined at the exact document
   they were written for.
3. **X3's diagnosis was wrong and is corrected.** The shipped ladder does not
   mis-rank the extractors — it never compares them at all, because it stops at
   the first rung that passes.
4. **X10 restores the sample probe** the investigation recommended and the
   first draft silently dropped, along with the cost figure that motivates it.
5. **X11 records the score for every attempt, always** — the only path out of
   "calibrated against one example".
6. `STRUCTURE_FLOOR` is renamed `MAX_UNLABELLED`: it is a **ceiling**.

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
citable: a model can quote `434,194.52` with no way to establish whether it is
revenue, an expenditure, or an ending balance, or whether it is dollars or
thousands of dollars.

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
**less than 15%** of its **non-whitespace** characters, and it is at least 50
characters long.

**🔴 Stripping markup is load-bearing, and leaving it out was the first
draft's worst defect.** MinerU emits tables as
`<table><td>CAPITAL OUTLAY APPROPRIATIONS</td><td>REVERSIONS…</td>`, and
nothing in `ingest/` strips tags before chunking — X9 records the consequence
from the other direction (chunk text carries table markup the source text layer
does not, which is why healthy AFRs score 278–286% coverage). Tag letters count
as letters, so an unstripped MinerU chunk scores a **false 0% unlabelled**. The
investigation stripped tags before comparing rungs and says outright that doing
so is load-bearing. Without this, X3 would rank MinerU first **because of its
tags rather than its structure** — right answer, wrong reason, and wrong the
moment an extractor changes its output format.

**Excluding whitespace is equally load-bearing.** With whitespace counted, the
four healthy AFRs score 5.5–12.9% because JLBC and AGAO table chunks carry
heavy tab padding that dilutes the letter ratio — a fully labelled header chunk
reads as bare. Excluding it collapses the healthy documents to 0.0–0.5% and
leaves the broken one unchanged at 30.6%: a ~60× separation where the naive
form gave ~2.4×.

**Two of the three numbers are NOT calibrated.** The 0.20 document ceiling sits
on a measured plateau (X2). The **0.15 letter ratio** and the **50-character
minimum** were each chosen once and never swept. The 50-character minimum has a
known direction of error: bare table rows are often short, so the barest rows
are the likeliest to be excluded from judging. Illustrating the same point, the
line the investigation used to introduce the problem —
`TOTAL FUND 409,164.00 314,457.00 434,194.52 289,426.48` — is **9 letters of 49
non-whitespace characters, 18.4%, and this measure calls it labelled.** The
30.6% figure is real and was computed programmatically; the illustration simply
was not one of the chunks that produced it. Both numbers get the same plateau
treatment as X2 before implementation — cheap, because the corpus scan already
exists.

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

### X3 — Structure picks the winner among the attempts that exist

When more than one extraction attempt exists, the attempt kept is the one with
the **lowest unlabelled fraction**, not the highest coverage. Coverage remains
the pass/fail floor; structure breaks the tie.

**🔴 Correcting the first draft's diagnosis.** It claimed T5's "keep whichever
result scored highest" prefers OpenDataLoader over MinerU. It does not, because
it never runs: `ingest/worker.py::_ladder` **returns at the first rung that
passes the coverage floor** (`if outcome.passed: return outcome`), so
`_outcome_rank` only ever compares rungs that all failed — and its own
docstring records that nothing downstream reads its result. The forced-fallback
run saw ranking only because the floor was temporarily set to 0.52. **On the
shipped code today, MinerU never runs on this document at all.**

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

### X4 — A tripped document does not stop at the first passing rung

A document that **passes** the coverage floor but is **above** the structure
ceiling advances to the next rung anyway, and X3 picks the winner.

This is what closes the gap: FY2024 passes on volume today and is never
retried. It is one change at one line — the early `return` in `_ladder` becomes
conditional on the ceiling as well as the floor.

**A healthy document must still short-circuit.** The early return is what stops
every ordinary upload from paying for three extractions. Under the measured
distribution 2,227 of 2,228 judged documents keep today's behaviour exactly;
the guard for that is a test, not a hope (see Testing).

**Cost, which the first draft did not state.** A full MinerU rung on this
191-page document is roughly **30 minutes**, and the ladder then runs
`mineru-ocr` as well — measured to change essentially nothing on a document
that has a text layer (353,002 characters against MinerU's 353,141, the same
13% bare pages). A tripping document could therefore spend close to an hour
with a person watching an office upload queue. X10 exists to cut that.

### X5 — DEFERRED: dropping unlabelled chunks

**Not in this spec.** The first draft dropped unlabelled chunks from the
winning attempt so they could never be falsely cited. That is the right
long-term shape and it is not ready:

- **The measure had a defect** (X1). Dropping is irreversible, and it would
  have been aimed by tag counts rather than by structure.
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

**What unblocks it:** X11's recorded scores, plus the X1 sweeps. When the
corpus has more than one positive example and the measure's own numbers are
calibrated, dropping is a small follow-up spec with its analyst-facing notice.

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
above 1.0 stays normal and uncapped — healthy AFRs score 278–286% because chunk
text carries table markup the source text layer does not.

### X10 — A tripped document probes before it pays for a full rung

The next rung runs on a **sample of pages** first. Both samples are scored with
X1, and the full rung is paid for only if the alternative wins. The
investigation proposed exactly this and the first draft dropped it without
argument; the measured difference is **minutes against ~30 of them**.

**🔴 The sample must not be chosen for being interesting.** The investigation
records a 5-page sample picked *because* it was the pathological table section:
it projected MinerU at 1.53× OpenDataLoader's character count, where the true
corpus-wide ratio is **0.91×**. Almost all of the apparent advantage was HTML
tags. The probe's pages are therefore selected by a **fixed rule** — evenly
spaced across the document — never by where the problem looks worst. A sample
chosen by the symptom only confirms what you already believed.

**Ties go to the incumbent.** The alternative costs a full extraction and
re-mints chunk IDs; that has to be earned, not won on a coin flip.

### X11 — Every attempt's unlabelled fraction is recorded, always

The score is written to the job record for **every rung that runs**, whether or
not it trips the ceiling, whether or not it changes anything. It is free — the
number is already computed.

**This is the only thing here that retires Risk 1.** Today there is exactly one
positive example and no mechanism that would ever produce a second: documents
in the 10–19% near-miss band are silently ignored, and nothing writes down that
they were close. A threshold that never records its inputs can only ever be
re-argued, never re-tuned with evidence.

**It is also the only place the evidence can survive X5's eventual arrival.**
Once dropping ships, a document's post-drop score is 0.00 by construction — the
measurement erases its own reason for firing. Recorded per attempt, at the time
of the attempt, is the only point where the number is true.

---

## Risks

**🔴 Risk 1 — calibrated against ONE positive example.** The false-positive
side is well established: 2,227 of the 2,228 judgeable documents score under
1%, so a 20% ceiling will not fire on healthy material. **The false-negative
side is unknown and cannot be estimated from one example.** This is why X3/X4
route to *trying another extractor and comparing*, never to a verdict on the
signal alone, and why X5 is deferred rather than shipped. X11 is the mechanism
that makes this risk shrink with time instead of persisting forever.

**Risk 2 — the fallback may not fix the document.** MinerU halves the
bare-figure rate on the one known case; it does not eliminate it. With X5
deferred, "does not eliminate" means unlabelled figures stay live and citable —
a real, accepted Invariant 1 exposure, not a rounding error. Nothing here may
imply the retry is a cure.

**Risk 3 — `mineru-ocr` earns nothing on a document that has a text layer.**
Measured: 353,002 characters against `mineru`'s 353,141, and the same 13% bare
pages. Whether the OCR rung should be skipped when `has_text_layer` is true is
**not decided here** — it is a T5 question and deserves its own measurement.
X10's probe blunts the cost in the meantime, since a rung that changes nothing
loses its probe.

**Risk 4 — two of the measure's three numbers are unswept.** The 0.15 letter
ratio and the 50-character minimum have no plateau behind them, and the
50-character minimum is biased against exactly the short bare rows the measure
exists to catch. Prerequisite, not a followup.

**Risk 5 — upload latency.** Even with X10, a tripping document costs a probe
plus possibly a full second extraction while someone waits. The measured
distribution says this is roughly 1 document in 2,228, but that ratio is from
the existing corpus and new uploads are not guaranteed to resemble it.

**Risk 6 — the chunk-level comparison has not been run.** X3 is justified by a
page-level measurement of raw output. It is the strongest available evidence
and it is not the metric being adopted.

---

## Testing

Per CLAUDE.md: mechanism in pytest, quality in the eval.

**Prerequisite measurements (before implementation, not after):**
1. Score both rungs' **chunks** with X1, markup stripped, and record the two
   numbers. This closes Risk 6 and tells us whether MinerU lands under the
   ceiling.
2. Sweep the 0.15 letter ratio and the 50-character minimum across the corpus
   for plateaus, as was done for 0.20 and 0.10 (Risk 4).

**pytest:**
- **Markup is stripped before measuring.** A MinerU-shaped chunk
  (`<table><td>NET APPROPRIATIONS</td><td>5,338,307</td>…`) scores as
  **labelled** because of its header cells, and the same table with its header
  cells removed scores as **unlabelled**. This is the guard for the first
  draft's defect and must fail loudly if stripping is removed.
- Tab-padded labelled text scores as **labelled** — the whitespace case the
  naive form gets wrong.
- A document with fewer than 10 judged chunks is never judged on structure.
- **A document under the ceiling still short-circuits at the first passing
  rung.** This is what keeps 2,227 documents paying nothing, and it is the
  test that fails if X4 is written as "always run every rung".
- Structural ranking beats coverage ranking: given a lower-coverage,
  lower-unlabelled attempt against a higher-coverage, higher-unlabelled one,
  the second wins. Pin it to the real measured pair once the prerequisite
  measurement exists.
- The probe's page selection depends only on page count, never on page content
  (X10).
- Every rung that runs leaves an unlabelled fraction on the job record, including
  rungs that pass and rungs that lose (X11).
- Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.

**Eval:** Layer 1 must be **unmoved** — no corpus document is re-extracted by
this change, and the one hand-run acceptance document is not referenced by
`queries.yaml` (X8). Any movement is a finding to explain, not noise.

**Acceptance:** re-process `agao-afr-fy2024`. Expected: it exceeds
`MAX_UNLABELLED`, probes the next rung under X10, MinerU wins on structure
under X3, the full rung runs under X4, and the swap is visible under X7.
**Then READ the kept chunks** — the count is not the gate. The honest expected
outcome is **better, not fixed**: with X5 deferred, unlabelled figures remain.
If the kept chunks are no better than today's, stop and report rather than
tuning the ceiling.

## Explicitly out of scope

- **No dropping of chunks** (X5/X6, deferred to a follow-up spec).
- **No analyst-facing notice** (X7, defers with X5).
- **No corpus sweep** (X8).
- **No change to the coverage floor** (X9).
- **No decision on skipping `mineru-ocr`** for text-layer documents (Risk 3).
- **No new extractor.** This chooses better between the three that exist.
- **No structural repair.** Nothing here reconstructs a lost column header; it
  detects the loss and prefers the extractor that loses less.
