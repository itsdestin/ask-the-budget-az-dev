# Citation linking — how it works, and what is wrong with it

**Date:** 2026-08-02
**Status:** Shipped to `master`, then found to overclaim. Direction not yet decided.
**Spec:** `docs/superpowers/specs/2026-08-02-citation-linking-design.md`
**Plan:** `docs/superpowers/plans/2026-08-02-citation-linking.md`
**Related:** Invariants 1–3; the unbuilt faithfulness verifier (WS3).

This memo exists because the feature shipped green — 2,000 passing tests and
a 92.9% coverage measurement — and then three browser sessions in one
afternoon found eight defects, two of them fundamental. It records how the
old system worked, why it was replaced, what replaced it, and exactly what
is still wrong, with the measurements rather than the impressions.

---

## 1. How the old system worked

The model was responsible for its own citations. It called
`cite(chunk_id, quote, confidence, claim_span)` — or `cite_batch` for
several at once — and the server validated three things:

- the `chunk_id` came from a real `retrieve()` result in this conversation,
- the `quote` appeared verbatim in that chunk's text (exact match first,
  then S23's normalization for smart quotes, dashes, casing, `\$` escapes),
- the span offsets were sane, and the quote was unique within the chunk
  (a quote appearing more than once was rejected outright).

Provenance was then reconstructed by **string matching four times in
series**, any one of which could fail on its own:

| # | stage | what it matches | where |
|---|---|---|---|
| 1 | model emits | re-types a `quote` it saw | `harness/tools.py` |
| 2 | server validates | `quote` ⊂ `chunk.text` | `retrieval/citations.py` |
| 3 | UI places the chip | `claim_span` ⊂ rendered answer | `webapp/src/chat/citation-extract.ts` |
| 4 | PDF highlights | `chunk.text[span]` searched in the pdf.js text layer, bbox-restricted | `webapp/src/pdf/highlight-strategy.ts` |

Two structural weaknesses sat underneath: the model was asked to re-type
text the system already held, and `bbox` is one box per chunk rather than
per token, so the highlighter had to *re-find* the text instead of looking
it up.

## 2. Why it was replaced

Three causes, measured against the 31-query Layer 2 baseline rather than
assumed:

- **Only 26% of figures appear in their source as an exact string. 67% are
  scale-shifted** — the answer renders `$8,287.7` under a "$ Millions"
  header while the document says `8,287,700,000`. So when the model quoted
  a figure it had just written, that string usually was not in the chunk.
  Validation was right to reject it. This is a units mismatch inherent to
  the task, and *any* design that asks the model to quote its own rendered
  numbers fights it.
- **Table text is corrupted by extraction.** Rows collapse into one,
  columns interleave, adjacent cells fuse
  (`...677,970,200643,700...1,320,598,100643,700`). No clean row exists to
  quote, so honest quotes were correctly rejected while bare-number quotes
  happened to succeed — that was the apparent randomness. The pattern
  appears in ~2% of chunks, concentrated in cross-agency summary tables.
- **Chip numbering used emission order, not reading order**, so the numbers
  shuffled (1 → 3 → 4 → 2).

The reported symptom: a ten-row table in which **two** numbers carried a
citation chip, numbered arbitrarily.

## 3. What we changed

A new `citation/` package runs **in-process at the end of a turn**, after
the final answer is assembled and before the terminal frame is emitted. Its
only inputs are the answer text and the chunk text already recorded on the
turn — no new retrieval, no store access.

| module | job |
|---|---|
| `citation/figures.py` | find every figure with character offsets + the scale its context implies |
| `citation/matching.py` | locate that value in retrieved chunk text across ×1 / ×10³ / ×10⁶ / ×10⁹, returning **the source's own rendering** and its offsets |
| `citation/authority.py` | rank candidate chunks: AFR > Appropriations > Baseline > Governor, same-FY preferred |
| `citation/reconcile.py` | explain unmatched figures as sum / difference / percent-change over linked ones |
| `citation/annotate.py` | assemble the annotation — the one artifact both consumers read |

Each figure gets a verdict: `linked`, `derived`, or `unverified`. The
annotation rides on the `_done` frame and never raises — a linker failure
yields an empty annotation and the answer still renders.

Consumers: the webapp renders it as chips; the eval judge renders the same
annotation as inline markers, so what the analyst sees and what the eval
grades cannot drift. The system prompt now tells the model **not to cite
figures at all** — `cite()` survives, scoped to non-numeric claims. The PDF
highlighter searches for the *source's* rendering of a number rather than
the answer's.

## 4. Defects found in the first three browser sessions — fixed

All eight shipped against a green suite. Each is a distinct lesson about
what those tests covered.

| # | defect | why no test caught it |
|---|---|---|
| 1 | **The refusal banner fired on every fully-linked numeric answer**, announcing "no verified citation" over an answer where every number was linked, and burying it under five raw passages | the change removed the signal (`cite()` acks) that another component was reading, and nothing tested the consumer |
| 2 | **Figure chips could never open the PDF.** `PdfViewer` gates on `resolved.docId` + `pageStart`; the annotation carried only `chunk_id` | every test asserted the annotation was *produced*, none that it was *usable* |
| 3 | **A real figure was silently dropped** — "took in $27,362,036.72" — because the year guard read the bare word "in" as a year cue | the recorded 31-transcript corpus never contained that sentence shape |
| 4 | **Two colliding numbering sequences** — figures numbered by the server, prose citations by the webapp | each was internally consistent; nothing rendered them together |
| 5 | **Orphan citations rendered as bare pills** at the foot of the answer, reading as a numbering bug | pre-existing behaviour, made visible by the new numbering |
| 6 | `find_in_chunks` applied the context scale **twice**, so `scale_used` always returned 1 | caught by the plan's own test, which the plan's implementation failed |
| 7 | The extractor did not recognise **`M`/`B`/`K` suffixes**, though answers write `+$243.5M` far more often than `$243.5 million` | found only by calibrating against real transcripts |
| 8 | Both plan test fixtures carried **offsets that did not index their own answer** (`12:20` slices `'287.7 an'`) | the assertions passed by substring luck |

**Defect 3 carries the sharpest lesson.** Re-running the 31-transcript
measurement after fixing it gives *byte-identical* numbers — 435 figures,
92.9% coverage, before and after. The recorded corpus simply never
contained that shape, and the first live answer found one. A clean offline
measurement over a fixed transcript set says nothing about the shapes it
happens not to contain.

## 5. What is still wrong — the fundamental problems

### 5.1 A third of links are chosen by a rule that cannot see relevance

Measured over the 31-query baseline, 357 linked figures:

| distinct documents containing the value | count | share |
|---|---|---|
| 1 | 235 | 65.8% |
| 2 | 72 | 20.2% |
| 3 | 25 | 7.0% |
| 4 | 8 | 2.2% |
| 5+ | 17 | 4.8% |

**34.2% of linked figures match a value in more than one document.** For
every one of those the primary source is chosen by *document authority*,
which knows nothing about whether the chunk concerns the right agency,
fund, or topic. This is the mechanism behind the reported case of `$16.28
billion` being linked to a completely irrelevant source.

The spec did acknowledge this — *"a link proves the figure appears in that
source, not that the source means what the sentence claims"* — but at 34%
ambiguity that caveat is not a footnote, it is the dominant behaviour.

### 5.2 Rounded figures are weak fingerprints; exact figures are strong

Method: take a real turn's retrieved chunks and attempt to link **invented**
figures that appear in no answer. Every resulting link is false by
construction. 1,080 trials per profile across all 31 baseline pools.

| figure profile | falsely linked |
|---|---|
| 4 significant digits, billions (`$12.49B`) | **3.7%** |
| 4 significant digits, millions (`$376.2M`) | **2.9%** |
| exactly-written grouped integer (`1,391,157,700`) | **0.4%** |

Nearly a 10× difference, and the code treats the two cases identically.
`$12.49 billion` carries four significant digits, gets a ±0.1% window, and
is searched at four scales — a wide net through a pool of hundreds of
numbers. `1,391,157,700` is nearly unique.

### 5.3 "Derived" is asserted on figures that are not computed

Two compounding causes:

- `reconcile`'s tolerance is a flat **1%**, which accepted
  `13.24 + 3.53 = 16.77` as an explanation for a stated `$16.83 billion`.
  Those are different numbers.
- In any table carrying a Variance column, `Forecast = Actual − Variance`
  is a **true identity**. So an unmatched forecast — a real, sourced figure
  the linker simply failed to find — is automatically "explained" as
  arithmetic. Verified: `16.56 − 3.53 = 13.03` is exactly the FY2022
  forecast.

The chip then tells the analyst the model computed a number it did not.

### 5.4 The specificity floor is bypassed exactly where it is needed

`_significant_digits` documents itself as *"ignoring trailing zeros"* and
does not:

| value | returned | actually significant |
|---|---|---|
| `37` | 2 | 2 |
| `1,320,598,100` | 10 | 9 (the docstring's own example says 9) |
| `$12.49 billion` | **11** | **4** |

It measures magnitude, not distinctiveness. The main guard against
incidental links therefore does not apply to rounded figures — the class
that needs it most (§5.2).

### 5.5 "Not found" discards the most useful thing the system knows

When a figure fails to link, the matcher has already computed the nearest
value in the retrieved sources. It says nothing. For `$12.49 billion` the
nearest source value is `$12.515 billion` — which is precisely the fact an
analyst needs to catch a wrong answer.

## 6. One finding that is NOT a bug

Reproducing the reported "Projected vs. Actual General Fund Revenues"
question and instrumenting every figure:

| figures | distance from the nearest value in the retrieved sources |
|---|---|
| every **linked** figure | 0.003% – 0.073% |
| every **unverified / derived** figure | 0.19% – 2.8% |

The source values *are* in the retrieved chunks; the model's numbers do not
match them. `$12.49B` is not a rounding of `$12.515B` — a model reading
12,515 writes 12.52. **In that answer the model stated numbers its sources
do not contain, and the refusals were correct.** That is Invariant 3
working. The chips communicated it so poorly that it read as citation
failure.

Also checked and ruled out: table numbers hiding in `table_html` where the
linker cannot see them. Table chunks carry their numbers in `text` as well.

## 7. The methodological failure underneath

The work was gated on **92.9% coverage** — a number measuring how often the
system *produces* a link, never whether a link is *right*. There was no
false-link measurement at all until after the defects were reported, and
building one took about ten minutes against transcripts already on disk.

That is why three browser sessions found what ~2,000 tests did not, and it
is the thing to fix first in any future ranking- or matching-quality work:
**measure the error rate, not the production rate.**

## 8. Options, if the approach is continued

Not decided. Recorded so the next session does not re-derive them.

1. **Link only when unambiguous** within the turn — converts the 34.2% in
   §5.1 into honest "ambiguous" rather than a guess.
2. **Written-precision tolerance** — `$16.83 billion` certifies only
   16.825–16.835 B, so `16.77` stops qualifying. Replaces both the flat
   0.1% match window and reconcile's flat 1%.
3. **Stop searching four scales** when the figure's scale is already known
   from its suffix or table header; the ladder multiplies collisions.
4. **Use the metadata the corpus already carries** — `agency_canonical_ids`,
   `fund_canonical_id`, `fiscal_year` are on every chunk — to reject
   topically unrelated candidates. This is the only one of the four that
   attacks §5.1 at its root.
5. **Surface the near-miss** (§5.5) instead of a bare refusal.
6. **Fix `_significant_digits`** to match its docstring, and re-calibrate
   the floor against significant digits rather than magnitude.

Whatever is chosen, the acceptance criterion should be the **false-link
rate** from §5.2, reported before and after — not coverage.

## 9. Reproducing the measurements

All of these run offline against transcripts already on disk
(`eval/results/agent/2026-08-02T0900Z-0b08221/*-r1.jsonl`, gitignored) and
cost nothing:

- **verdict distribution** — annotate each baseline answer against its own
  retrieved chunks, count verdicts.
- **cross-document ambiguity (§5.1)** — for each linked figure, count
  distinct `doc_id`s among its hits.
- **false-link rate (§5.2)** — generate figures at a given digit profile,
  attempt to link them against a real pool, count any link as false.
- **near-miss distance (§6)** — for each figure, scan every grouped number
  in the turn's chunks at all four scales and report the minimum relative
  distance.

The last one is the most useful diagnostic and should probably become a
committed script rather than living in this memo.
