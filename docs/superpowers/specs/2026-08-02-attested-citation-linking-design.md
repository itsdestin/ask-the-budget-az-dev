# Attested citation linking — design

**Date:** 2026-08-02
**Status:** Approved design, not yet planned or implemented.
**Supersedes:** the linking policy of
`docs/superpowers/specs/2026-08-02-citation-linking-design.md` (the figure
extractor, annotation contract, chip rendering, and judge integration from
that spec survive; its authority-ranked source selection does not).
**Motivating record:**
`docs/superpowers/investigations/2026-08-02-citation-linking-review.md` —
read it first; every decision below answers a measured defect in it.
**Related:** Core Invariants 1–3; the unbuilt faithfulness verifier (WS3),
which remains out of scope here.

---

## 1. The problem, in one paragraph

Two citation systems have now failed for mirror-image reasons. The old
`cite()`-everything system asked the model to do what the system is good at —
re-type exact source text — and 74% of figures cannot be quoted verbatim
(67% scale-shifted, plus corrupted table extractions). The current post-hoc
linker asks the system to do what the model is good at — know *which* source
a number came from — and 34.2% of linked figures match values in more than
one document, where the tie is broken by a document-authority rule that
cannot see topic, agency, or fund. Provenance is a fact that exists in
exactly one place: the model's context while it writes the sentence. Any
design that discards it must reconstruct it by inference, and the review
memo's §5.1 measured what that costs.

## 2. Requirements (Destin, 2026-08-02)

- **R1 — never wrong-doc.** A figure must never be attributed to a document
  that is not its source.
- **R2 — cite every citable number.** Every figure the model took from the
  retrieved documents gets a citation when the value is genuinely present.
- **R3 — citations render in reading order** (one sequence; already shipped
  by the unified-numbering work and kept).
- **R4 — narrowest relevant PDF highlight.** Clicking a figure chip lands on
  the value itself, not a chunk-sized rectangle.
- **R5 — format-variance tolerant.** `$10,297,300.17` = `$10.297M` = `10.3M`
  = `10,297,300` must all bind to the same source value.
- **R6 — no significant time/token increase** over the current pipeline.

**Acceptance is measured on the false-link rate, not coverage** (memo §7).
Coverage is a floor constraint, not the goal.

## 3. Design decisions

Numbered A1–A9 so plans and code comments can cite them.

### A1 — The model attests provenance with inline chunk-alias markers

Every chunk in a `retrieve()` result carries a short per-turn alias
(`c1`…`cN`). The server assigns aliases in order of first appearance and the
numbering continues across multiple retrieves within a turn, so an alias is
never reused or ambiguous inside a turn. The system prompt instructs the
model to append the alias of the chunk it read a figure from, immediately
after the figure:

```
…grew to $8,287.7 million [[c3]] while agency counts fell [[c3,c7]] …
```

Syntax: `[[c3]]`, multiple sources `[[c3,c7]]`. ASCII, a few output tokens,
one regex to strip, effectively collision-proof in budget prose. Markers are
stripped server-side before the answer reaches any consumer; a malformed
marker (unclosed bracket, unknown alias) is also stripped, logged, and
treated as "no tag" — it must never render.

Prose (non-numeric) claims are unchanged: they keep the `cite()` quote path,
which verifies something markers cannot (that a quote is faithful) and
already passes at 84–99%.

Cost accounting (R6): ~3–5 output tokens per figure (~150 on a heavy table
answer) plus ~2 input tokens per chunk for the aliases — noise against the
measured 138k input tokens per answer. No new tool round-trips; if anything,
figures stop triggering cite retries entirely.

### A2 — A marker is a hypothesis; the system verifies it and may refuse it

A tagged figure is searched for **only in the chunk(s) the marker names**,
scale-aware and precision-aware (A4). Found → `linked`, carrying the
source's own rendering of the value, its character offsets in the chunk, and
full document metadata. Not found → the fallback (A3) runs; if that also
fails, verdict `unverified`, and the annotation records both that the model
attributed it to the named chunk and the nearest value found there (A6).

R1 rests on this compounding: a false link now requires the model to name
the wrong chunk AND that chunk to coincidentally contain the value inside
the precision window. Both rates are individually small; the false-link
harness (A8) puts a measured number on the product.

### A3 — Untagged figures link only when unambiguous; authority ranking is deleted

For a figure with no (surviving) marker, the system searches the turn's full
chunk pool. It links **only when exactly one document contains the value**
at the stated precision. Two or more candidate documents → `unverified`,
reason `ambiguous (found in N documents)`. The AFR > Approps > Baseline >
Governor tie-break rule (`citation/authority.py`) is deleted, not demoted —
it is the mechanism behind the memo's wrong-doc case and no longer has a
job. This fallback is also what bounds the marker-compliance risk: a model
that never tags degrades to an honest version of today's system, never
below it.

### A4 — Written precision defines the match window; one rule replaces three constants

A figure's written form certifies an interval: `$10.3M` certifies
[10.25M, 10.35M]; `$10,297,300.17` certifies exactly itself; a grouped
integer certifies ±0.5. A source value matches iff it falls inside the
interval after scale normalization. This single rule replaces the flat
±0.1% match window, replaces `reconcile`'s flat 1% tolerance, and satisfies
R5 outright — the four renderings in R5 are one value at three precisions.

Scale handling: when the figure's scale is pinned by its own suffix
(`M`/`B`/`K`, "million"), or by table/header context ("$ in thousands"),
search that one scale only. The four-rung ladder (×1/10³/10⁶/10⁹) runs only
when the scale is genuinely unknown, and always under the specificity floor.

`_significant_digits` is fixed to match its own docstring — trailing zeros
ignored, so `$12.49 billion` is 4 significant digits, not 11 — and the
specificity floor is re-calibrated against *true* significant digits using
the false-link harness (A8).

### A5 — `derived` only over linked inputs, at written precision

`derived` is asserted only when every input of the reconstructed arithmetic
is itself a `linked` figure and the equation holds within the written
precision of the result. `13.24 + 3.53 = 16.77` can never again "explain" a
stated `$16.83 billion`. Because linking (including A3's fallback) always
runs before reconciliation, a sourced figure the model tagged cannot be
misexplained as arithmetic — the Forecast = Actual − Variance identity trap
(memo §5.3) dies on both prongs. Derived chips display the equation.

### A6 — A failed link surfaces the near-miss

Whenever a figure ends `unverified`, the annotation carries the nearest
value found in the relevant search space (the named chunk for tagged
figures, the turn pool otherwise) with its relative distance:
*"Nearest source value: $12.515B (differs by 0.2%)."* This converts the
memo's §6 finding — the model stated numbers its sources do not contain,
the refusal was CORRECT, and it still read as breakage — into a legible
warning an analyst can act on. The renderer copy must never call an
unverified figure an error; it reports what the sources say.

### A7 — Highlighting becomes a lookup: the ingest-side coordinate map

New per-document artifact, the **coordinate map**: for each chunk, a list of
`(char_start, char_end, page, bbox)` entries at the extraction span
granularity, recorded while `chunking/builder.py` assembles chunk text from
extraction blocks. A linked figure's source offsets resolve to an exact
bbox by lookup. The highlight is the value's own span, widening to its line
where span granularity is unavailable. The pdf.js text-layer *search* stops
being the primary mechanism.

Backfill: `extractor-output/` is retained for 7,058 of 7,434 documents
(verified 2026-08-02). Re-run **chunking only** — deterministic and cheap —
over the retained output, and accept a coordmap **only where the re-derived
chunk text is byte-identical to the text in LanceDB**. A mismatch means the
chunking code has drifted since that document was ingested; fall back
rather than risk highlighting the wrong words. Fallback chain everywhere:
coordmap → text-layer search (current behavior) → whole-chunk bbox with an
honest "couldn't pinpoint". Nothing gets worse; ~95% of the corpus gets
exact. New ingests write the coordmap as part of the normal write phase.

### A8 — The false-link harness is the gate

The memo's §5.2 methodology — invent figures at controlled digit profiles,
attempt to link them against real turn pools, count every link as false by
construction — becomes a committed script under `eval/`, alongside the
near-miss diagnostic (memo §9). The ship decision is the before/after
false-link rate at each digit profile. Floor constraints, not goals:
figure coverage (linked + derived) ≥ the current 92.9%, and Layer 2
`key_fact_rate` not regressed.

### A9 — Marker compliance is measured, and a live run is mandatory

Layer 2 gains two metrics: **marker coverage** (share of figures carrying a
tag) and **tag accuracy** (share of tags that verify against their named
chunk). These are the early-warning instrument for the design's one real
unknown — how reliably the configured tier models follow the marker
instruction. Additionally, because the prompt changes, shipping requires a
**live smoke run plus a browser session**, not just recorded transcripts —
the review memo's defect 3 proved a fixed transcript corpus says nothing
about the sentence shapes it happens not to contain.

## 4. Components and data flow

```
retrieve() ──> ToolExecutor assigns aliases c1..cN, records alias→chunk map
                    │
model writes answer with [[cN]] markers; cite() still used for prose claims
                    │
turn end (in-process, before _done frame):
  1. strip markers, record figure↔alias associations + offsets
  2. extract figures        (citation/figures.py — A4 fixes)
  3. verify tagged figures  (citation/matching.py against named chunks — A2)
  4. fallback link untagged (unambiguous-only — A3; authority.py deleted)
  5. reconcile leftovers    (citation/reconcile.py — A5)
  6. near-miss for failures (A6)
  7. assemble annotation    (citation/annotate.py — verdicts, source
                             renderings, offsets, doc metadata, near-miss)
                    │
        ┌───────────┴───────────┐
   webapp chips            eval judge markers
   (reading-order          (same annotation —
    numbering, R3)          cannot drift)
                    │
   chip click ──> coordmap lookup (A7) ──> exact bbox highlight
                  └─ fallback: text-layer search ──> chunk bbox + honest miss
```

The annotation contract from the 2026-08-02 spec is extended, not replaced:
per-figure it adds `attested_chunk_ids` (what the model claimed),
`link_basis` (`tag` | `unambiguous-fallback` | `derived`), `near_miss`
(value, rendering, distance, chunk), and `ambiguity_count`. Existing fields
(verdict, source rendering, offsets, doc metadata) are unchanged, so the
judge and the chips keep working during the transition.

## 5. Error handling

- Linker failure still yields an empty annotation and the answer renders —
  unchanged from the current system.
- Malformed markers are stripped and logged; they must never reach the UI.
- A marker naming an alias from a *previous* turn is treated as unknown
  (aliases are per-turn); the figure falls to A3.
- Coordmap absent, stale, or text-mismatched → the existing highlight chain,
  with the existing honest-miss badge. The coordmap can only add precision.
- The refusal-banner rule is unchanged: a linked figure counts as
  verification; `derived` and `unverified` do not.

## 6. Testing and measurement

- Unit: alias assignment across multi-retrieve turns; marker stripping
  (well-formed, malformed, unknown-alias, previous-turn alias); written-
  precision intervals for every R5 rendering; scale pinning vs ladder;
  `_significant_digits` against its docstring; unambiguous-fallback refusing
  2-document candidates; derived requiring linked inputs at written
  precision; near-miss payloads; coordmap byte-identity acceptance.
- End-to-end: extend `tests/test_citation_end_to_end.py` — real
  `HarnessSession` through the real SSE route, answer containing tagged,
  untagged-unambiguous, untagged-ambiguous, derived, and near-miss figures;
  assert verdicts, `link_basis`, stripped markers, reading-order indices.
- Offline gates (A8): false-link harness before/after at all three digit
  profiles; verdict distribution over the 31-query baseline transcripts;
  coverage floor.
- Live gates (A9): Layer 2 smoke with marker coverage / tag accuracy;
  token-delta check (expected ≈ +150 output / +30 input per answer); one
  browser session covering chip click → exact highlight, near-miss tooltip,
  derived equation display.

## 7. Risks

| risk | bound |
|---|---|
| Models under-tag or mis-tag | A3 fallback floors quality at "today, but honest"; A9 metrics detect it immediately; prompt iterates |
| Marker syntax leaks into prose | strip-everything-plausible policy + tests; a leaked marker is a P1 render bug |
| Coordmap backfill text mismatch | byte-identity gate; mismatches keep current behavior |
| Unambiguous-only lowers coverage | measured against the 92.9% floor before ship; near-miss/ambiguous verdicts keep the information visible even when a link is refused |
| Prompt change perturbs answer quality | Layer 2 `key_fact_rate` in the gate; live smoke mandatory |

## 8. Out of scope

- Prose faithfulness verification (WS3) — `cite()` semantics untouched.
- Re-running MinerU for the ~376 documents without retained extractor
  output.
- The corpus-picker/both-corpora retrieval change (deferred v2 item) —
  though A1's alias map is corpus-agnostic and will not block it.
