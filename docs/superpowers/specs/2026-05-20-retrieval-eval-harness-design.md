---
title: Retrieval Eval Harness (Layer 1) — Design Spec
date: 2026-05-20
status: shipped
authors: Destin Moss, Claude
audience: implementer of `eval/`, future implementer of Layer 2 agent eval (post-WS3)
supersedes_in_part:
  - docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md WS8 — closes the deferred eval workstream with a richer design
---

> **2026-05-22 amendment header.** ✓ Shipped (merge `3a26c19`).
> For current state see [STATUS.md](../../../STATUS.md) and
> [eval/README.md](../../../eval/README.md). What diverged from
> this spec during execution:
>
> - **Refusal scope split.** The spec mixed corpus-boundary and
>   editorial refusals; Layer 1's README now explicitly limits
>   the refusal queries to corpus-boundary cases (wrong
>   jurisdiction, fictional entity, future FY). Editorial framing
>   ("should we...", policy opinions) belongs in a future query-
>   classifier layer, not retrieval. Two of the 5 refusal queries
>   in `eval/queries.yaml` (q-030, q-031) straddle this line and
>   are kept for transparency, but their "failure" to be refused
>   at the retrieval threshold isn't a retrieval bug.
> - **Calibration formula changed.** `combined_score` is now
>   `(precision + recall + retrieval_pass_rate) / 3` (was
>   `(precision + retrieval_pass_rate) / 2`). Surfaces refusal
>   recall instead of hiding it — the first calibration sweep
>   recommended threshold 0.60 with refusal recall 0.20 (catching
>   1 of 5 refusals) under the old formula; the new formula
>   correctly recommends 0.70 (recall 0.80).
> - **Construction-bias caveat made explicit.** Lookup queries
>   were synthesized FROM chunks, so the 86% recall@5 baseline is
>   an upper bound, not representative of real analyst usage. The
>   README now frames this as "Layer 1 retrieval regression
>   detector," not "the eval system." Layer 2 (open-ended analyst
>   queries with set-based ground truth + LLM-as-judge or rubric
>   scoring) is a separate workstream.
> - **Synthesizer ran via subagent, not the Anthropic CLI.**
>   `.env.local` lacked an `ANTHROPIC_API_KEY` at execution time,
>   so a subagent walked the sampled chunks and wrote
>   `eval/queries.yaml` inline. The CLI path is still wired and
>   unit-tested; future re-syntheses can use either.
> - **Detour fixes landed in the same branch.** BM25 apostrophe
>   sanitizer (closed STATUS.md #47 — 14 of 34 queries had been
>   crashing); Windows stdout encoding fix on all three CLI
>   tools; `::text` casts on agency-filter SQL in the refresh
>   tool (psycopg `IndeterminateDatatype`; mocked tests missed
>   it).
> - **Plan-side patches before execution.** The original plan had
>   a `retrieve()` signature bug (called as a string, not
>   `RetrievalRequest`), a `RetrievedChunk`-vs-dict shape bug,
>   and an inverted precision/recall formula in calibration. All
>   patched in commit `c61202b` before the implementer started.
>
> The base spec below is left intact as the original design
> record; STATUS.md and eval/README.md are the current truth.

# Retrieval Eval Harness — Layer 1

Closes the Phase 1b WS8 eval workstream that was deferred during the
vertical-slice reframe ("blocked on volume corpus"). The volume corpus
landed in 2026-05-12 (382 docs / 7,755 chunks); WS8's pass bar
(`Recall@20 ≥ 80% on lookup queries`) is now testable.

This spec covers **Layer 1 only**: the retrieval pipeline (BM25 +
dense + RRF + Voyage rerank). The end-to-end agent eval that scores
faithfulness, citation precision/recall, and answer-text matching is
**Layer 2** — gated on WS3 (faithfulness verifier) landing first, gets
its own spec.

## Goals (in priority order)

1. **Iteration confidence.** "Did my change to retrieval / chunking /
   prompt make recall up or down?" answerable in 30 seconds. The
   alternative today is dogfooding and guessing.
2. **Refusal-threshold calibration.** Move the `top_score < 0.30`
   placeholder in `retrieval/pipeline.py` (deferred since Phase 1b)
   onto data drawn from a real eval set.
3. **Failure-mode visibility.** Per-query results expose patterns
   ("all FY24 queries fail because not ingested") that dogfood
   discovers one painful query at a time.

## Non-goals (deferred to follow-up specs)

- **End-to-end agent eval (Layer 2).** Faithfulness rate, citation
  precision/recall against expected answer text, refusal correctness
  on the rendered answer. Gated on WS3 (faithfulness verifier) being
  built — without WS3, agent-side faithfulness numbers are noisy and
  ungate-able. Layer 2 extends the same `queries.yaml` schema with new
  scoring dimensions.
- **CI / GitHub Actions integration.** Manual `uv run python -m
  eval.run_eval` for v1. Add Actions when a second contributor joins
  the repo or when regressions start biting in practice.
- **Postgres `eval_runs` table.** Spec §13 of the design spec
  describes this; we defer until SQL queries on cross-run metrics
  become useful. v1 stores results as git-tracked files.
- **Bridge JSONL miner.** Lifting real dogfood queries from
  `~/.claude/ask-the-budget-az/bridge.log` into the eval set. Separate
  brainstorm when there's enough representative dogfood traffic to
  harvest (today's dogfood is heavy on engineering, light on the
  analyst-style queries the eval needs).

## Design — Section 1: `queries.yaml` schema

Hand-curating queries was rejected by Destin ("I don't feel like
hand-writing queries"); the synthesizer (Section 2) builds the set.
But the schema must support:
- Direct chunk-level scoring (tight precision when chunk_ids are
  stable)
- Dimension-level scoring (durability across re-ingest / re-chunk)
- An "anchor text" hook so the refresh tool (Section 4) can find the
  successor chunk after a re-chunk without re-synthesizing the whole
  set

### Schema

```yaml
- id: q-001
  query: "What was AHCCCS's FY26 General Fund appropriation?"
  type: lookup                       # lookup | comparison | refusal
  expected_chunks:                   # omitted for type=refusal
    - chunk_id: "fy26-jlbc-baseline-ahccs::3"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:ahccs"
      anchor_text: "$2,587,400 from the General Fund"
  expected_refusal: false            # true for type=refusal
  synthesized_by: claude-opus-4-7    # provenance
  synthesized_at: 2026-05-20T18:00Z
```

### Scoring semantics

- **Lookup query passes recall@K** if any of `expected_chunks` is in
  the top-K results, preferring chunk_id exact match, falling back to
  dimensions (all fields satisfied by a single returned chunk).
- **Comparison query passes recall@K** if ALL of its `expected_chunks`
  are in the top K (otherwise the comparison can't be answered).
- **Refusal query passes** if `top_score < REFUSAL_THRESHOLD`. The
  scoring direction inverts: passing here means retrieval correctly
  declined.
- **Fallback match** logged when a query's expected chunk_id is no
  longer present in the corpus (typically after a re-ingest or
  re-chunk) but a returned top-K chunk still satisfies the recorded
  dimensions. The runner surfaces "fallback rate: N/total" in the
  summary — Destin's cue to run `eval/refresh_chunk_ids.py` or
  re-synthesize. The query still counts as a pass (recall is recall),
  just flagged for follow-up.

## Design — Section 2: Synthesizer

**File:** `eval/synthesize_queries.py`.

A one-shot generator that produces the initial `queries.yaml`. Re-run
after a corpus expansion to grow the set (overwrites by default; pass
`--append` to add to existing). Uses Anthropic API via the `anthropic`
SDK with Claude Opus 4.7.

### Composition (matches design spec §13)

- **25 lookup queries.** Sample chunks balanced across `(publisher ×
  agency-tier × fiscal_year)`. For each chunk, prompt Claude with the
  chunk text and ask for a realistic analyst question whose answer
  lives in it, plus an anchor_text fragment.
- **5 comparison queries.** Sample chunk PAIRS where both chunks stamp
  to the same `agency_canonical_id` across two different
  `fiscal_year` values. Prompt Claude for a comparison question
  requiring both chunks.
- **5 refusal queries.** Prompt Claude with the corpus boundaries
  (publishers covered, FY range, doc types, agencies) and ask for
  questions OUT of scope. Mix: opinion-based, future FY, missing
  entity, conflated topics.

Total: 35 starter queries. Destin reviews once (10-15 min), edits or
deletes outliers, commits.

### Vocabulary-contamination mitigation

LLM-synthesized queries from chunks tend to borrow rare terms from
the source chunk, making BM25 retrieval artificially easy. The
synthesizer's prompt includes:

> "Phrase the question naturally, the way a JLBC fiscal analyst would
> ask it in conversation. Do NOT borrow rare or distinctive terms
> from the source chunk verbatim. Use synonyms, paraphrase numeric
> figures into rounder form (e.g. '$3.3M' instead of '$3,290,400'),
> and avoid quoting the chunk's exact phrasing."

No post-validation in v1. If first-eval-run recall numbers look
suspiciously high (e.g., recall@5 above 95% on lookups), revisit with
a stronger check: post-synthesis, strip the query's two rarest tokens
and check that retrieval still surfaces the expected chunk. Defer
unless the cheap mitigation visibly fails.

### Cost

35 calls × ~3K token context × Opus 4.7 pricing ≈ $2-3 per full
synthesis. Re-synthesis on `--append` adds incrementally.

### Tests (`tests/test_eval_synthesize.py`)

- Synthesizer outputs valid YAML matching the schema.
- Lookup queries carry a non-empty `expected_chunks[0].chunk_id`.
- Refusal queries carry `expected_refusal: true` and no
  `expected_chunks`.
- The Anthropic API call is mockable (handler injectable for tests).

## Design — Section 3: Runner

**File:** `eval/run_eval.py`. Invoked as `uv run python -m eval.run_eval`.

### Behavior

1. Load `eval/queries.yaml`. Validate schema.
2. For each query, call `retrieve()` from `retrieval/__init__.py` —
   bypasses MCP, bypasses Claude, calls the Python pipeline directly
   for deterministic measurement.
3. Score each result against the query's expected outcome (rules in
   Section 1).
4. Aggregate metrics: recall@5, recall@20, latency p50/p95, fallback
   rate, refusal precision/recall.
5. Compute deltas against the most recent prior result file under
   `eval/results/`.
6. Write `eval/results/<UTC-ISO-timestamp>-<git_sha>.json` + `.md`.

### Output shape — JSON

```json
{
  "git_sha": "cc0dcb2",
  "timestamp": "2026-05-20T18:30Z",
  "summary": {
    "recall_at_5": 0.76,
    "recall_at_20": 0.84,
    "fallback_rate": 0.10,
    "latency_p50_ms": 1200,
    "latency_p95_ms": 2100,
    "refusal_precision": 0.80,
    "refusal_recall": 0.86,
    "by_type": {
      "lookup":     {"recall_at_5": 0.83, "recall_at_20": 0.92, "count": 25},
      "comparison": {"recall_at_5": 0.60, "recall_at_20": 0.80, "count": 5},
      "refusal":    {"precision": 0.80, "count": 5}
    }
  },
  "per_query": [
    {"id": "q-001", "type": "lookup", "status": "pass",
     "matched_via": "chunk_id", "rank": 2, "latency_ms": 850,
     "top_score": 0.84},
    {"id": "q-007", "type": "lookup", "status": "pass",
     "matched_via": "dimensions_fallback", "rank": 4, "latency_ms": 1100,
     "top_score": 0.72},
    {"id": "q-024", "type": "lookup", "status": "fail",
     "matched_via": null, "rank": null, "latency_ms": 920,
     "top_score": 0.41, "top_chunk_ids": ["...", "..."]}
  ]
}
```

### Output shape — Markdown summary

Human-readable mirror with: the summary table, deltas vs. the
previous run (per-query passes-now / fails-now lists), and a "Per-
failure analysis" section listing each failing query, its top
returned chunks, and the expected chunk's dimensions for quick
diagnosis.

### Why git-committed JSON+MD

- `git diff eval/results/<old> eval/results/<new>` is the regression
  diff for free.
- Bisecting a regression is just `git log eval/results/` to find when
  recall dropped.
- Cross-machine portability: results travel with the repo, no DB
  dependency.
- ~50 results files = a few MB; sustainable for years.

### Tests (`tests/test_eval_runner.py`)

- Runner parses the YAML schema and calls `retrieve()` with the right
  shape.
- Scoring is correct for all four cases: chunk_id match, dimensions
  fallback, refusal pass (top_score below threshold), refusal fail
  (top_score above threshold but query expected refusal).
- Aggregate metrics computed correctly from per-query results.
- JSON + MD writers emit the expected shape.

## Design — Section 4: Refresh tool

**File:** `eval/refresh_chunk_ids.py`. Invoked as `uv run python -m
eval.refresh_chunk_ids`.

### Behavior

For each query in `queries.yaml`:
1. Connect to Postgres. Check whether `expected_chunks[].chunk_id`
   still exists in the `chunks` table.
2. If yes → no-op.
3. If no (stale) → find a successor chunk via:
   a. Query Postgres for all chunks matching the dimensions (publisher
      + doc_type + fiscal_year + agency).
   b. Prefer the chunk containing `anchor_text` (substring match,
      normalized via the same `normalizeForMatch` used by the cite
      validator).
   c. If no anchor hit, pick the chunk with the highest cosine
      similarity to the query embedding (the same Voyage embedding
      model the ingest pipeline uses — `voyage-3-large` per
      `retrieval/rerank.py`).
   d. If no candidates match the dimensions, flag the query for
      manual review — the script leaves the YAML entry unchanged and
      prints the query id so Destin knows to edit `eval/queries.yaml`
      by hand (or delete the query if the underlying entity is gone).
4. Write the updated chunk_ids back to `eval/queries.yaml` in-place
   (preserving YAML structure and comments via `ruamel.yaml`).
5. Report summary: refreshed N, manual-review M, unchanged K.

### Run after re-ingest

The CLAUDE.md before-push reminder (Section 7) explicitly calls out
running `refresh_chunk_ids` after any ingest pipeline change.

### Tests (`tests/test_eval_refresh.py`)

- Anchor-text match correctly picks a chunk containing the anchor.
- Dimensions-only fallback when anchor isn't found.
- Manual-review flag emitted when dimensions match no candidates.
- YAML round-trip preserves field order + comments.

## Design — Section 5: Refusal threshold calibration

**File:** `eval/calibrate_refusal.py`. Invoked as `uv run python -m
eval.calibrate_refusal`.

### Behavior

1. Sweep candidate thresholds `[0.10, 0.15, 0.20, 0.25, 0.30, 0.35,
   0.40]`.
2. For each threshold, re-score the most recent eval run's per-query
   `top_score` values:
   - **Refusal precision** — of queries the threshold would cause to
     refuse, how many were `expected_refusal: true`?
   - **Retrieval pass rate** — of queries with retrievable answers
     (`expected_refusal: false`), how many still pass recall@20?
3. Print a sweep table. Recommend the threshold maximizing
   `(refusal_precision + retrieval_pass_rate) / 2`.

### Why separate from `run_eval.py`

- Run-eval should be fast and on-demand. Calibration is periodic.
- Calibration depends on already-run per-query data; can re-use any
  recent result file without re-running retrieval.
- Updating `REFUSAL_THRESHOLD` in `retrieval/pipeline.py` is a manual
  decision Destin makes after reading the sweep — the script
  recommends, doesn't modify code.

### Tests (`tests/test_eval_calibrate.py`)

- Sweep produces the expected precision/recall numbers given a known
  per-query input.
- Recommended threshold is the one with the highest combined score.

## Design — Section 6: Documentation + CLAUDE.md addition

**File:** `eval/README.md` — explains:
- How the eval set is built (synthesizer) and refreshed (refresh tool)
- The query schema, with one annotated example
- How to run the eval (`uv run python -m eval.run_eval`)
- How to interpret results (which metrics matter, what a fallback
  match means)
- How to add a manually-written query (yes you can hand-write; the
  synthesizer just isn't the only path)

**File:** `CLAUDE.md` — add one line under "Working Rules":

> **Run the eval after any change to `retrieval/`, `ingest/`,
> `chunking/`, or `mcp-server/system-prompt.md`.** Command: `uv run
> python -m eval.run_eval`. ~30 seconds. Commit results alongside the
> code change so regressions are visible in PR diffs.

## Scope summary

In scope (one branch, ~3-4 days):

| File | Purpose |
|---|---|
| `eval/queries.yaml` | 35 synthesized starter queries |
| `eval/synthesize_queries.py` | One-shot LLM-driven query generator |
| `eval/run_eval.py` | Main runner; emits JSON+MD |
| `eval/refresh_chunk_ids.py` | Post-reingest fixer |
| `eval/calibrate_refusal.py` | Threshold sweep + recommendation |
| `eval/README.md` | Operator-facing docs |
| `eval/results/` | Git-tracked result files |
| `tests/test_eval_*.py` | Unit tests for the four scripts |
| `CLAUDE.md` | Before-push reminder addition |

Out of scope (deferred):
- Layer 2 agent eval (waits for WS3)
- CI / GitHub Actions integration (when a second contributor lands)
- `eval_runs` Postgres table (when SQL trend queries become useful)
- Bridge JSONL miner (separate brainstorm when dogfood is rich enough)
- Synthesizer's stronger vocabulary-contamination check (revisit if
  cheap mitigation visibly fails)

## Estimated landing

One feature branch (`eval-harness-v1`), ~3-4 days end-to-end:

- **Day 1.** Schema + synthesizer. End-of-day: one real synthesis run
  to spot-check output quality.
- **Day 2.** Runner + scoring + JSON/MD writers + first real eval
  run.
- **Day 3.** Refresh tool + calibration tool.
- **Day 4.** Tests + README + CLAUDE.md update + Destin's skim-review
  of the synthesized queries + PR.

## Open items deferred to writing-plans

- Exact prompt for the synthesizer (the contamination-mitigation
  clause is sketched here; final wording during implementation).
- Which Anthropic SDK version pins to use (current `pyproject.toml`
  may need an update).
- Whether the JSON output should include the actual top-K chunk
  records (verbose, useful for debugging) or just chunk_ids (compact,
  enough for scoring). Plan-time call based on file-size impact.
