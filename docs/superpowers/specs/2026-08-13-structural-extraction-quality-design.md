# Structural extraction quality — design

**Date:** 2026-08-13
**Decisions:** X1–X9
**Status:** proposed

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

---

## The problem, in one paragraph

A document can produce the right *amount* of text with its *meaning* stripped
off. `agao-afr-fy2024` re-processed through the shipped ladder scores **49.0%
coverage** — comfortably over the floor, so no fallback fires and it is
written `live` — while **30.6% of its chunks are bare figures**: rows like
`TOTAL FUND 409,164.00 314,457.00 434,194.52 289,426.48` with no column
headers, and only 5 of 388 chunks carrying a units statement. Its healthy
sibling carries the whole frame — table title, `(expressed in thousands)`, and
`June 30, 2023 / June 30, 2022 / Increase (Decrease)`. Under Invariant 1 an
unlabelled figure is **worse than a missing one**, because it is still
citable: a model can quote `434,194.52` with no way to establish whether it is
revenue, an expenditure, or an ending balance, or whether it is dollars or
thousands of dollars.

**The document sits in a gap: not broken enough to trigger fallback, not good
enough to use.**

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

**🔴 Coverage ranks the structurally worse extractor higher.** From the forced
fallback run — the first real rung-to-rung fallback ever executed — comparing
each rung's raw output with HTML tags stripped:

| rung | coverage | real text | bare-figure pages |
|---|---|---|---|
| opendataloader | **49.03%** | 344,872 | **28%** |
| mineru | 44.77% | 353,141 | **13%** |
| mineru-ocr | 43.68% | 353,002 | 13% |

MinerU more than halves the bare-figure rate, and **T5's "keep whichever
scored highest" prefers OpenDataLoader anyway.** Volume and structure
disagree, and volume is wrong.

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

A chunk is **unlabelled** when letters make up **less than 15%** of its
**non-whitespace** characters, and it is at least 50 characters long.

**Excluding whitespace is load-bearing, not a detail.** With whitespace
counted, the four healthy AFRs score 5.5–12.9% because JLBC and AGAO table
chunks carry heavy tab padding that dilutes the letter ratio — a fully
labelled header chunk reads as bare. Excluding it collapses the healthy
documents to 0.0–0.5% and leaves the broken one unchanged at 30.6%: a ~60×
separation where the naive form gave ~2.4×.

No vocabulary list, no per-publisher rule, no model.

### X2 — The document-level threshold is 20%, over ≥ 10 judged chunks

**`STRUCTURE_FLOOR = 0.20`**, applied only to documents with **at least 10
judged chunks**.

20% is the **centre** of the 10–30% plateau, the same rule that put the
coverage floor at 10% — correct where a metric degrades on both sides. Below
10% it starts approaching legitimately numeric documents; above 30% the one
known case escapes.

**The minimum chunk count is not optional.** Without it, 15 documents score
≥ 15% and **14 of them are 2–5 chunk documents** where a single numeric chunk
reads as 33%. A minimum of 10 removes all 14. **The cost, stated plainly: a
small degraded document is invisible to this signal.** That is a real blind
spot, not a solved problem.

### X3 — Structure decides the WINNER, not just the gate

When more than one extraction attempt exists, the attempt kept is the one with
the **lowest unlabelled fraction**, not the highest coverage. Coverage remains
the pass/fail floor; structure breaks the tie.

This is the correction the evidence forces. Without it the ladder
systematically selects the structurally worse output for this failure class,
whatever the floor is set to.

**Ties and absent measurements:** where two attempts have the same unlabelled
fraction, coverage decides, preserving today's behaviour. Where an attempt's
fraction cannot be computed (fewer than 10 judged chunks), it does not
participate in structural ranking and is ranked by coverage.

### X4 — Tripping the threshold triggers a fallback the coverage floor would not

A document that **passes** the coverage floor but **fails** the structure
threshold advances to the next rung anyway, and X3 picks the winner.

This is what closes the gap: FY2024 passes on volume today and is never
retried.

### X5 — Unlabelled chunks are dropped from the winning attempt

Chunks that are unlabelled by X1 are **not written to the corpus**. The rest of
the document is written and is searchable and citable exactly as it is today.

**An unlabelled figure that is never written cannot be falsely cited**, which
is the Invariant 1 payoff, and the ~70% of the document that is properly
labelled remains available.

### X6 — Dropping applies ONLY within a document that tripped X2

A document below the structure threshold has **nothing dropped**, even if a
handful of its chunks are individually unlabelled.

Healthy documents contain occasional legitimately-numeric chunks whose labels
live in an adjacent chunk, and dropping those would be a silent regression
across 2,227 documents to fix one. **The threshold rejects; it never
approves** — the same principle as the coverage floor, and the reason 2,227
documents are wholly unaffected by everything in this spec.

### X7 — A drop is visible to the analyst AND to the administrator

**Silently dropping content recreates the exact defect Plan B exists to
fix**, in miniature: an analyst searching for a figure that is in the PDF gets
silence and concludes the corpus lacks it.

- **The administrator** sees the document, how many of its chunks were
  dropped, and which extraction methods were tried.
- **The analyst** sees a short note wherever the document appears in search,
  saying part of it could not be read and is not searchable, and pointing at
  the PDF.

**One source of wording, rendered in both places.** This project has a
recorded history of server and UI copy drifting apart; the sentence is
authored server-side, exactly as the AI-tier explainer copy is.

**No copy anywhere may describe the kept portion as verified, checked,
validated, healthy or good.** This measure detects one specific failure shape;
a document that passes has not been certified.

### X8 — Scope: new ingests and deliberate re-processing only

No corpus sweep, no backfill.

Changing which extractor produced a live document **re-mints its chunk IDs**,
and `eval/queries.yaml` ground truth is pinned to chunk IDs — the tool that
re-bound them after a re-ingest (`eval/refresh_chunk_ids.py`) was deleted and
nothing replaces it. Since exactly **one** document in the corpus trips the
threshold, a sweep would carry the full risk to fix a single case that can be
re-processed by hand.

### X9 — The coverage floor is unchanged

`COVERAGE_FLOOR` stays **0.10**, calibrated across all 7,434 documents. A
ratio above 1.0 stays normal and uncapped — healthy AFRs score 278–286%
because chunk text carries table markup the source text layer does not.

---

## Risks

**🔴 Risk 1 — calibrated against ONE positive example.** The false-positive
side is well established: 2,227 of 2,228 documents score under 1%, so a 20%
threshold will not fire on healthy material. **The false-negative side is
unknown and cannot be estimated from one example.** This is why X3/X4 route to
*trying another extractor and comparing*, never to a verdict on the signal
alone — the comparison is self-checking in a way a threshold is not.

**Risk 2 — the fallback may not help.** MinerU halves the bare-figure rate on
the one known case; it does not eliminate it (13% remain). A document can trip
the threshold, pay for a second extraction, and still lose chunks. The design
must not imply the retry is a fix.

**Risk 3 — `mineru-ocr` earns nothing on a document that has a text layer.**
Measured: 353,002 characters against `mineru`'s 353,141, and the same 13%
bare. The ladder runs it anyway when the first two fail. Whether the OCR rung
should be skipped when `has_text_layer` is true is **not decided here** — it
is a T5 question, it interacts with the scan path the rung exists for, and it
deserves its own measurement.

**Risk 4 — a dropped chunk is a real loss.** X7 makes it visible, but visible
is not the same as recoverable. The analyst's route to the dropped content is
the PDF, which the citation viewer already opens.

---

## Testing

Per CLAUDE.md: mechanism in pytest, quality in the eval.

**pytest:**
- The measure computes the values recorded above for fixtures of known shape,
  including the whitespace case that the naive form gets wrong — a fixture of
  tab-padded labelled text must score as **labelled**.
- A document below the threshold has **nothing** dropped, even when it
  contains individually unlabelled chunks (X6). This is the guard that keeps
  2,227 documents unaffected, and it must fail if X6 is removed.
- Structural ranking beats coverage ranking: given the measured pair —
  coverage 49.03% at 28% bare versus 44.77% at 13% bare — the second attempt
  wins. This is the whole point of the change and must fail loudly if the
  ranking reverts.
- A document with fewer than 10 judged chunks is never judged on structure.
- The analyst-facing and admin-facing sentences come from **one** source.
- Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.

**Eval:** Layer 1 must be **unmoved** — no existing document is re-extracted
by this change. Any movement is a finding to explain, not noise.

**Acceptance:** re-process `agao-afr-fy2024`. Expected: it trips X2, falls to
MinerU under X4, MinerU wins under X3, its unlabelled chunks are dropped under
X5, and the result is visible under X7. **Then READ the kept chunks** — the
count is not the gate. If the kept chunks still carry unlabelled figures, stop
and report rather than tuning the threshold.

## Explicitly out of scope

- **No corpus sweep** (X8).
- **No change to the coverage floor** (X9).
- **No decision on skipping `mineru-ocr`** for text-layer documents (Risk 3).
- **No new extractor.** This chooses better between the three that exist.
- **No structural repair.** Nothing here reconstructs a lost column header; it
  detects the loss, prefers the extractor that loses less, and refuses to ship
  what is left.
