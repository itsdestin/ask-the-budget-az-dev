# Citation Linking — Design

**Date:** 2026-08-02
**Status:** Approved by Destin 2026-08-02 (brainstorming session)
**Supersedes:** the figure half of the current cite/cite_batch contract.
Prose citation via `cite`/`cite_batch` survives, scoped down.
**Related:** Invariants 1–3; the unbuilt faithfulness verifier (WS3); the
deferred per-token coordinate capture (STATUS.md follow-up #57).

## The problem, as observed

A live question — *"what are the biggest agencies by budget"* — returned a
ten-row table in which **two numbers carried a citation chip**, the chips
were numbered 1 → 3 → 4 → 2, and which rows got one looked arbitrary.

Destin's requirement, verbatim: *"i don't mind if there are a lot of
citations, but they should be consistent and applied to all numbers
directly with a direct link to that number in the pdf."*

### Why it happens — four fragile joints

Provenance is currently **reconstructed by string matching four times in
series**, and any one of them can fail independently:

| # | Stage | Matches | Where |
|---|---|---|---|
| 1 | Model emits | model re-types a `quote` it saw | `harness/tools.py` |
| 2 | Server validates | `quote` ⊂ `chunk.text` (exact, then S23 normalized) | `retrieval/citations.py` |
| 3 | UI places chip | `claim_span` ⊂ rendered answer | `webapp/src/chat/citation-extract.ts` |
| 4 | PDF highlights | `chunk.text[span]` searched in the pdf.js text layer, bbox-restricted | `webapp/src/pdf/highlight-strategy.ts` |

Two structural weaknesses underneath:

- **The model is asked to re-type text the system already holds.** Every
  quote is a round-trip through the model's tokenizer.
- **`bbox` is one box per chunk, not per token** (`store/schema.py`), so the
  highlight must *re-find* the text rather than look it up.

### Three measured root causes

Reproduced against the live harness and corpus on 2026-08-02:

1. **Table text is corrupted by extraction.** The chunk behind that table
   reads `Child Safety, Department ofChiropractic Examiners, State Board
   of\t677,970,200643,700\t...1,320,598,100643,700`. Two rows collapsed into
   one, columns interleaved, DCS's `$1,320,598,100` fused to Chiropractic's
   `$643,700`. **No clean row exists to quote**, so honest quotes are
   correctly rejected; bare-number quotes happen to succeed. That is the
   "randomness". Corpus-wide the jamming pattern appears in ~2% of chunks,
   concentrated in cross-agency summary tables.
2. **Empty-quote `cite_batch` slots.** Four citations in one turn went out
   with `quote: ""` and were rejected outright.
3. **Chip numbering uses emission order, not reading order**
   (`citation-extract.ts`, the `.map((c, i) => ({...c, index: i + 1}))` at
   the end of the retry-collapse pass). Its comment claims reading order;
   chips are *placed* by matching into the answer, so the numbers shuffle.

### The finding that reframes the problem

Measured over the 31 recorded answers of the Layer 2 full baseline:
**only 26% of figures appear in their source as an exact string. 67% are
scale-shifted** — the answer renders `$8,287.7` under a `$ Millions`
header while the document says `8,287,700,000`.

**So when the model quotes a figure it just rendered, that string usually
does not exist in the chunk.** Validation is right to reject it. This is a
units mismatch inherent to the task, not model carelessness, and *any*
design that asks the model to quote its own rendered numbers fights it.

## Feasibility, measured before committing

A throwaway linker was run offline over the 31 recorded transcripts —
no model calls, no cost — asking: of every figure an answer states, how
many can be located in the chunks that answer actually retrieved?

| outcome | share |
|---|---|
| locatable in retrieved chunks | **93.6%** |
| — unambiguous (single chunk) | 55.4% |
| — ambiguous (multiple chunks) | 38.2% |
| not found | **6.4%** |

Both residuals were characterised rather than assumed:

- **81% of the ambiguity is the same figure in different editions** (a
  value present in both the FY2026 Baseline and the FY2026 Appropriations
  Report). Only 14% is ambiguity within a single document.
- **The not-found 6.4% is almost entirely derived numbers** — sampled and
  read: year-over-year deltas (`+$376.2 million`), percentages (`+6.9%`),
  sums, and approximations (`~10,000–11,000`).

## Decisions (locked during brainstorming)

1. **Derived numbers are marked as derived, not silently source-backed.**
   A computed total gets a distinct treatment that expands to show the
   figures it came from. Rejected: forbidding derived numbers, and letting
   them carry an ordinary source chip. Rationale: a computed total that
   looks source-backed is the kind of thing that erodes trust in the whole
   table.
2. **No corpus re-ingest.** Per-token coordinate capture and fixing the
   table serialization both require re-extraction (~7 h for 3,527 documents
   at the measured batch rate, plus re-pointing Layer 1's pinned
   `chunk_id` ground truth). Deferred to a v2 of the app. **This design
   must work against the corpus as stored** and accepts a ceiling on
   PDF-highlight precision.
3. **Architecture = the system links figures; the model cites prose.**
   Rejected: addressable unit-ids (fixes quote-matching but leaves coverage
   to model diligence, which is the failing part), and hardening the
   existing chain (same objection).
4. **Ambiguity resolves to one primary + visible corroboration.** A single
   primary citation chosen by authority order, with the outranked sources
   shown as "additional references" when the citation is opened.
5. **One annotated answer, two consumers.** The linker's output is a
   structured annotation over the answer text. The UI renders it as chips;
   the eval judge renders the same annotation as inline markers. They
   cannot drift.

## Architecture

**Where it runs.** In-process in `harness/`, after the turn's final answer
is assembled and before the terminal frame is emitted — so the annotation
travels with the answer to both consumers, and no HTTP round-trip is added.
Its inputs are already in hand: the assembled answer text, and the chunk
text of every retrieve result in this turn (recorded per tool call by the
session accumulator). No new retrieval, no store access on the answer path.

Five units with clear boundaries, each testable alone.

### 1. Figure extractor

Finds every figure in the final answer **with its character offsets**, plus
the scale implied by context — a `$ Millions` column header, a `billion`
suffix, a bare grouped integer. Offsets are what make chip placement
deterministic and reading-order numbering free.

### 2. Scale-aware matcher

Locates a figure's value in retrieved chunk text across ×1 / ×10³ / ×10⁶ /
×10⁹, returning **the source token as the source renders it** plus its
offsets in `chunk.text`. Returning the source form (not the answer's form)
is load-bearing: it is what the PDF highlight must search for.

Guards against spurious links:
- a **minimum-specificity floor** for bare matches, because short figures
  (`$37`) collide incidentally. The floor is a significant-digit threshold,
  and its value is **calibrated empirically against the recorded
  transcripts** — raise it until incidental links disappear, then stop,
  reporting the coverage given up at each step. It is not a guessed
  constant, and the calibration is committed alongside it.
- preference for candidates whose chunk `fiscal_year` matches the figure's
  context.
A figure that can only be matched below the floor is reported unverified
rather than linked to something plausible-looking.

### 3. Authority ranker

Orders candidate chunks by the document hierarchy the system prompt already
teaches — **AFR > Appropriations Report > Baseline > Governor's proposal** —
with same-fiscal-year preferred. Deterministic and explainable: it encodes
the rule an analyst would apply. Highest-ranked candidate becomes the
primary; the rest become additional references.

### 4. Reconciler

For figures the matcher cannot locate, tests whether the value is a simple
function — difference, sum, percent change — of figures already linked in
the same answer. A hit yields `derived from [i], [j]`; a miss yields
`unverified`. This is what makes Decision 1 real rather than a label, and
it is mechanical, so it cannot be gamed by the model.

### 5. Citation assembler

Emits the annotation: per figure, its answer offsets, verdict
(`linked` | `derived` | `unverified`), primary chunk + source-token offsets,
additional references, and derivation inputs. This is the artifact both
consumers read.

## What the analyst sees

- **Linked** — chip at the number, numbered in reading order. Opening it
  shows the primary source highlighted at the source's rendering of the
  figure, then "Also appears in:" for outranked editions.
- **Derived** — visually distinct chip; opening it shows "Computed from
  [1] and [4]" with those figures. No PDF link is claimed.
- **Unverified** — a figure neither located nor reconciled is visibly
  marked. Expected to be rare; when it fires it is either a retrieval gap
  or a fabrication, and both deserve the analyst's eye (Invariant 3).

## What this removes

The model stops citing figures, so three failure modes disappear rather
than being mitigated: quote-not-found, empty-quote slots, and cite
retries. In the reproduction of the live question that is **18 tool calls
removed from a single turn**, which also serves the Layer 2 goals of fewer
turns and tokens.

`cite` / `cite_batch` remain, scoped to non-numeric claims. The system
prompt changes from "cite everything" to "state figures; cite non-numeric
claims" — and its table-quoting guidance becomes moot rather than needing
repair.

## Eval integration

`build_judge_payload` currently sends raw answer text plus a detached list
of citation objects, so the judge cannot see where chips landed or which
figures got none. That gap produced a real misdiagnosis on 2026-08-01: the
judge reported `claim_coverage_precision` 0.54 and the finding was written
up as "the model over-cites", which Destin immediately identified as wrong
— the visible failure is *under*-coverage and erratic placement.

The judge therefore receives the **same annotation the UI renders**, as
inline markers:

```
| 1 | K-12 Education (ADE) | $8,287.7 [1]                 |
| 2 | AHCCCS               | $2,613.7 [UNCITED]           |
|   | Total                | $17,654.2 [DERIVED: 1+2+3…]  |
```

New metrics, replacing `claim_coverage_precision` **for figures**:

- **figure coverage** — figures linked or derived ÷ figures stated
- **placement correctness** — chip on the correct figure (judge-scored)
- **unverified rate** — figures neither linked nor reconciled

`claim_coverage_precision` / `_recall` survive for the prose claims the
model still cites. Citation *volume* stops being a target: completeness and
accuracy replace it, matching Destin's stated preference.

The annotation is recorded in the eval transcript so the free offline layer
can re-score citation behaviour without re-spending money.

**Acceptance:** the answer in the reported screenshot must score badly on
figure coverage. It scores respectably today; a regression detector that
passes the reported defect is not a regression detector.

## Honest limitations

- **A link proves the figure appears in that source, not that the source
  means what the sentence claims.** Today's quote-matching proves exactly
  the same thing with more failure modes, so this is not a regression — but
  it is not semantic verification. That remains WS3, unbuilt.
- **PDF highlighting stays a text-layer search** because re-ingest is
  deferred. It should improve materially — a distinctive numeric token is
  far more findable than a prose quote, and the matcher hands it the
  *source* form — but it can still miss. The v2 coordinate capture is what
  makes it a lookup.
- **Mangled table text is untouched.** Out of scope by Decision 2. The
  linker tolerates it (a fused `1,320,598,100643,700` still yields a
  correct offset for either figure) but does not repair it.
- **Small-figure collisions** are handled by refusing to link rather than by
  being clever; some correct figures will read `unverified` as a result.

## Out of scope

- Table-serialization repair and per-token coordinates (v2 re-ingest).
- The WS3 faithfulness verifier.
- Prose-citation behaviour beyond narrowing its scope.
- The Layer 2 improvement experiments this unblocks.
