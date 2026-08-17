# Consolidated Eval Pipeline — Design

**Date:** 2026-08-16
**Status:** Draft — approved in principle by Destin (2026-08-16 brainstorming session); three Open Decisions noted inline for confirmation at review.
**Supersedes:** Replaces the smoke/full/dr-probe organization of the Layer 2 agent-loop eval as the *primary quality pipeline*. Layer 1 (`eval/run_eval.py`) is retained as the free, fast, deterministic retrieval-regression inner loop. The Layer 2 spec (`docs/superpowers/specs/2026-08-01-agent-loop-eval-design.md`) is extended — not discarded — by this design: its transcript format, mechanical scorer, judge, and comparison machinery carry forward.

## Why now

The current eval surface is two systems with a split identity:

- **Layer 1** calls `retrieve()` directly and measures chunk recall/refusal only. It is free and fast but cannot see agent turns, cost, citations, or whether the answer is *actually what an analyst wanted*.
- **Layer 2** drives the real harness and measures answer-level quality, but is organized around `smoke` / `full` / `dr-probe` subsets whose boundaries do not map to the questions a developer actually asks ("is retrieval finding the right chunks?", "is the agent searching efficiently?", "does it understand that a Baseline isn't the same as an Appropriations Report?").

The consolidated pipeline exists to answer those questions directly and consistently, and to make **time-to-accurate-response** the headline number the whole system optimizes. It also (a) parallelizes the eval runner for iteration speed, (b) harvests every tool-call error as optimization guidance, and (c) archives every run in one place so change over time is visible.

The project's North Star — *retrieval with auditable provenance* — is unchanged. This pipeline is the instrument for shaping the system prompt, retrieval tools, and filters toward it.

## Goals → headline metrics

Three measurement priorities, consolidated into one report, plus a headline.

| Priority | What it measures | Primary metric(s) |
|---|---|---|
| **Headline** | Time to a *correct* answer | **time_to_accurate**: wall-clock per query, computed ONLY over responses that pass key facts AND produce verified citations. Fast-but-wrong does not count. |
| 1 — Retrieval/chunk quality | Chunks match what the query actually asks | Layer 1 recall (free inner loop) + judge-scored chunk-relevance pass + `retrieval_efficiency` |
| 2 — Agent filter/search efficiency | Choosing filters/queries well, minimizing turns/tokens/tools | steps, retrieve calls, tokens (prompt/cached/output), `retrieves_after_sufficient`, `retrieve_calls_with_filters`, cost; consolidated per query/set/model |
| 3 — Doc-type relationship understanding | Baseline vs Approps Report vs AFR vs Exec Budget in ambiguous cases | **document_correctness** (share of verified citations pointing at a `correct_response_doc`), on the Multi set |

Output-hygiene checks (meta-narration, internal-vocab, token-leak) and citation discipline (`cite_pass_rate`, `first_try_cite_rate`, `retries_per_citation`, figure coverage) carry forward unchanged as secondary signals.

## Query sets (replaces smoke/full/dr-probe)

One file — `eval/agent_queries.yaml` — authoring **~40 queries**, each tagged `set:` instead of `subsets:`.

| Set | Count | Authoring contract | Measures |
|---|---|---|---|
| **Quick Lookup** | ~12 | A well-tuned model/retrieval tool should answer in **one retrieve call**. Single fact, single agency/FY. | Retrieval precision + minimal-turn efficiency |
| **Extended Quick Lookup** | 15 | **Same shape as Quick Lookup** — additional single-call queries for extra signal / higher coverage of the one-shot pattern. No different authoring rule. | Same as Quick Lookup, more samples |
| **Multi (Agency/Year) Lookup** | ~10 | Spans **2–3 narrow agencies × 2–3 fiscal years**. Each carries a defined `correct_response_docs` list — the document(s) a correct answer *must* cite. | Doc-type relationship understanding (priority 3) |
| **Deep Research** | 3 | Extremely broad scope over wide time spans (see below). | Synthesis + citation discipline + time-to-response at worst case |

Total ~40.

**Deep Research — the family.** Three queries, each in the long-broad style of Destin's General Fund revenue example (wide time spans, projection-vs-actual, multi-agency synthesis, underspend, etc.). Destin provided one; the implementer authors the other two in the same shape. Seed for the first, verbatim from the session:

> List all General Fund revenue projections in the last 10 years, then compare them to actual year-end collections and year-end actual expenditures; explain which agencies received the largest appropriations in each of those years and which of them underspent their appropriations by the largest sums.

Each Deep query may carry few or zero `key_facts` (the meaningful scoring is judge-driven and doc-correctness-driven at this scale); `judge_notes` must name the correct source documents for each temporal slice.

**Schema change.** Each `AgentQuery` gains a `set:` field (one of `quick`, `extended_quick`, `multi`, `deep`) and an optional `correct_response_docs: [<document id>]` field used on the Multi set. Key facts, shape, corpus, tier, judge_notes are unchanged. The `tier: deep_research` marker is retired in favour of `set: deep`; a per-query `tier` may remain for model-routing if desired but is no longer the subset mechanism.

## THE SINGLE QUERY-APPROVAL TASK

One task in the plan exists for Destin to **approve / iterate on the final query sets** before any scoring runs against them. Method, verbatim from the session:

- The implementer runs each query through the real app, AND
- manually navigates the budget documents to find the most correct answer the judge should score against.

So ground truth is **analyst-chosen answer/document correctness**, not synthesized-from-chunk. For the Multi set this means pinning the `correct_response_docs` by hand against the live corpus (the identity-consistency audit and `store.chunk_store.ChunkStore().scan(...)` are the reference for how). Until Destin approves this set, no model is scored on it.

## Profile-driven runner (the orchestrator)

A single entry point, `eval/run_eval`, driven by an **eval profile** (CLI flags and/or YAML) selecting:

- **models** — exactly **1 (single run) or 2 (head-to-head)**, run **in parallel through the full chosen set**. Two models = one run dir each, compared by the existing `compare_agent_runs.py`. A 1-model run is the same code path with one side, so a later A/B is free.
- **sets** — `--sets quick,extended_quick,multi,deep` (any subset; Deep is excludable to control cost).
- **workers** — `--workers N` thread-based fan-out, the existing pattern (network-latency-bound work, two ONNX models are shared singletons).
- **judge** — on/off (`--judge`), judge stays a separate charge and is manual.

Flow, reusing existing machinery: `run_agent_eval` (transcripts) → `agent_scoring` + **new scorer modules** → `judge_agent_run` (when requested) → `compare_agent_runs` (when 2 models) → write the consolidated report + append to the over-time archive.

## Scoring — the four axes

**New scorer modules, additive** — they extend `eval/agent_scoring.py` and add sibling modules; nothing about the hard-won currency tolerance, citation-retry logic, or honesty guards is rewritten.

**a) Time-to-accurate-response (headline).** Per query, `time_to_accurate` = `wall_ms` **only when** the response passes its key facts AND produces ≥1 verified citation. Aggregated per set and per model. Fast-but-wrong and fast-but-uncited are excluded (their wall time is still recorded separately as `wall_ms`, so a regression that trades correctness for speed is visible as accuracy dropping while `time_to_accurate` counts fewer queries).

**b) Retrieval/chunk quality (priority 1).** Layer 1 recall stays the free inner loop. The scorer additionally counts `retrieval_efficiency` (chunks actually used ÷ chunks retrieved) per query, and the judge scores a chunk-relevance verdict (do the retrieved chunks match what this query is actually asking?) on runs where the judge runs. This addresses the "match what we'd actually be looking for" half that chunk-id recall cannot.

**c) Tool-call efficiency (priority 2).** Consolidate existing signals into one per-query view: steps, retrieve calls, token split, cost, `retrieves_after_sufficient`, filter/intent/top_k usage, deep_dive calls. Reported per query/set/model so the exact spot where the agent burns turns before an accurate answer is visible. These remain informational (no better/worse arrow — a filter is right or wrong depending on the question).

**d) Doc-type relationship understanding (priority 3).** **document_correctness** = share of verified citations that point at a `correct_response_doc` (Multi set only). This is the "cited the Baseline when it should have cited the Appropriations Report" test — the exact ambiguous case the repo's identity audit documented. It is mechanical (verified cite → chunk's document id ∈ `correct_response_docs`) and feeds the judge.

## Tool-error harvesting (every error is guidance)

A new mechanical pass over each transcript extracts **every tool-call error** — retrieve failures, cite failures/retries, argument/validation errors, ambiguity rejections, filter rejections, malformed outputs, crashed queries. Emits a structured **error ledger per run**: error kind × frequency × query × model, plus a rationale line and a "what to improve" hint. This is an explicit input to shaping the system prompt, tool descriptions, and filter schema. Consistent with the repo's boring invariant, each error is tied to the turn it cost — not just counted.

## Result storage & change-over-time monitoring

One consistent archive, written by every `run_eval` invocation:

```
eval/results/agent/<UTC-ISO>-<git-sha>/     # existing per-run dir: transcripts, manifest, scores, judge  [unchanged]
eval/results/over-time/
    index.json                               # every run: git sha, profile, sets, model(s), timestamp, cost
    metrics.jsonl                            # append-only, one line per run: headline metrics (time_to_accurate,
                                             #   document_correctness, key_fact_rate, efficiency, error counts)
```

Over time `metrics.jsonl` becomes the plottable trend ("document_correctness 0.71 → 0.83 → 0.90 across last month's runs"). Comparison honesty guards port into it: runs with different `queries_sha256` or different corpus counts are flagged, never silently trended together.

## Honesty guards preserved

- **No repeats** (Destin's call). The orchestrator banners single-run stochasticity exactly as `compare_agent_runs.py` already does; deltas within noise are labeled, not celebrated.
- **Money-spending runs are manual, never CI.** The live runner, the judge, and the Deep set all spend through OpenRouter; pytest over synthetic fixtures stays free.
- `queries_sha256` and corpus-count guards carry into the over-time archive.
- A run's `manifest.json` records everything needed to know whether two runs are comparable (git sha, prompt sha256, queries sha256, model map, corpus counts) — unchanged.

## Open Decisions (confirm at review)

1. **The "accurate" bar.** Default: a response counts toward `time_to_accurate` when it passes key facts AND has ≥1 verified citation (mechanical, cheap). A stricter alternative also requires the judge's holistic grade to clear a bar (more expensive, since it makes the headline depend on the paid judge). Default chosen: mechanical bar; judge holistic is reported as a secondary metric, not the gate.
2. **Deep Research cost.** Each Deep query is expensive (the old DR tier ~$2–3 for a full probe). Default: all 3 are in a normal run, but the Deep set is **excludable per profile** (`--sets` without `deep`) so a cheap iteration need not pay for it.
3. **Over-time location.** Default: `eval/results/over-time/`. (Alternative: a top-level `monitoring/` dir.)

## Out of scope

- Bringing the money-spending machinery into CI.
- Adding repeats for statistical power (Destin explicitly declined).
- Parallelising search *inside* the agent (Destin wants faster production responses via better tool calls/results, not agent-level parallelism).
- Fiscal-note agent eval (separately tracked; layer 1 only has fiscal-note ground truth).
- The improvement experiments themselves (the eval measures; tuning the prompt/tools follows on, each in a worktree).
