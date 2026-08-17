# Consolidated Eval Pipeline — Design

**Date:** 2026-08-16
**Status:** Draft — approved in principle by Destin (2026-08-16 brainstorming session), consolidated 3 sets + re-tag-then-add/tune query policy + wall-clock dropped as a metric (2026-08-16 review session); two Open Decisions noted inline for confirmation at review.
**Supersedes:** Replaces the smoke/full/dr-probe organization of the Layer 2 agent-loop eval as the *primary quality pipeline*. Layer 1 (`eval/run_eval.py`) is retained as the free, fast, deterministic retrieval-regression inner loop. The Layer 2 spec (`docs/superpowers/specs/2026-08-01-agent-loop-eval-design.md`) is extended — not discarded — by this design: its transcript format, mechanical scorer, judge, and comparison machinery carry forward.

## Why now

The current eval surface is two systems with a split identity:

- **Layer 1** calls `retrieve()` directly and measures chunk recall/refusal only. It is free and fast but cannot see agent turns, cost, citations, or whether the answer is *actually what an analyst wanted*.
- **Layer 2** drives the real harness and measures answer-level quality, but is organized around `smoke` / `full` / `dr-probe` subsets whose boundaries do not map to the questions a developer actually asks ("is retrieval finding the right chunks?", "is the agent searching efficiently?", "does it understand that a Baseline isn't the same as an Appropriations Report?").

The consolidated pipeline exists to answer those questions directly and consistently, and to make token/tool efficiency and **cost-to-accurate-response** (tokens and turns per query that passes key facts with verified citations) the headline number the whole system optimizes. It also (a) makes the runner's already-existing `--workers` parallelism part of one profile, (b) harvests every tool-call error as optimization guidance, and (c) archives every run in one place so change over time is visible.

The project's North Star — *retrieval with auditable provenance* — is unchanged. This pipeline is the instrument for shaping the system prompt, retrieval tools, and filters toward it.

## Goals → headline metrics

Three measurement priorities, consolidated into one report, plus a headline.

| Priority | What it measures | Primary metric(s) |
|---|---|---|
| **Headline** | Cost of getting to a *correct* answer | **tokens_to_accurate** and **turns_to_accurate** (both load-invariant, trend honestly across sessions). Computed ONLY over responses that pass key facts AND produce verified citations. Fast-but-wrong does not count. Wall-clock time is deliberately NOT a metric — see scoring (a). |
| 1 — Retrieval/chunk quality | Chunks match what the query actually asks | Layer 1 recall (free inner loop) + judge-scored chunk-relevance pass + `retrieval_efficiency` |
| 2 — Agent filter/search efficiency | Choosing filters/queries well, minimizing turns/tokens/tools | steps, retrieve calls, tokens (prompt/cached/output), `retrieves_after_sufficient`, `retrieve_calls_with_filters`, cost; consolidated per query/set/model |
| 3 — Doc-type relationship understanding | Baseline vs Approps Report vs AFR vs Exec Budget in ambiguous cases | **document_correctness** (share of verified citations pointing at a `correct_response_doc`), on the Multi set |

Output-hygiene checks (meta-narration, internal-vocab, token-leak) and citation discipline (`cite_pass_rate`, `first_try_cite_rate`, `retries_per_citation`, figure coverage) carry forward unchanged as secondary signals.

## Query sets (replaces smoke/full/dr-probe)

One file — `eval/agent_queries.yaml` — **re-tag, then add and tune**. The existing 35 queries (31 `full`, 11 `smoke`, 4 `dr-probe`) carry corpus-verified key facts paid for with full-table scans and reachability checks; they are re-tagged onto the new sets (`subsets:` → `set:`), tuned where the approval task finds them wrong or weak, and only then extended with genuinely new queries. Nothing is re-authored from scratch while a verified original works.

| Set | Target count | Authoring contract | Measures |
|---|---|---|---|
| **Quick Lookup** (`quick`) | ~25 | A well-tuned model/retrieval tool should answer in **one retrieve call**. Single fact, single agency/FY. The existing single-call queries re-tag in here, and the set grows to ~25 with new queries of the same shape (this absorbs what was earlier drafted as a separate "Extended Quick Lookup" set — same authoring rule, no separate tag needed). | Retrieval precision + minimal-turn efficiency |
| **Multi (Agency/Year) Lookup** (`multi`) | ~10 | Spans **2–3 narrow agencies × 2–3 fiscal years**. Each carries a defined `correct_response_docs` list — the document(s) a correct answer *must* cite. | Doc-type relationship understanding (priority 3) |
| **Deep Research** (`deep`) | 3 | Extremely broad scope over wide time spans (see below). | Synthesis + citation discipline + cost-to-response at worst case |
| **Refusal** (tag, not a set) | 5 | The existing `should_refuse: true` queries. `set: refusal` exists so `--sets` can select/exclude them; it is a tag, not a headline set — refusal correctness is scored by the existing pass. | Honesty / refusal discipline |

Total ~43.

**Deep Research — the family.** Three queries, each in the long-broad style of Destin's General Fund revenue example (wide time spans, projection-vs-actual, multi-agency synthesis, underspend, etc.). The current file has 4 `dr-probe` queries; the seed below is one of them, and the implementer picks two of the remaining three that best match this shape (the fourth is either re-homed into `quick`/`multi` if it actually fits a narrower shape, or dropped — decide explicitly at re-tag time, do not let it vanish silently). Seed, verbatim from the session:

> List all General Fund revenue projections in the last 10 years, then compare them to actual year-end collections and year-end actual expenditures; explain which agencies received the largest appropriations in each of those years and which of them underspent their appropriations by the largest sums.

Each Deep query may carry FEW key facts, but never zero — at least one verifiable fact per temporal slice the judge_notes name. Reason: `agent_scoring` sets `key_fact_rate = None` when `total_facts == 0`, which would make the headline's "accurate" bar ("passes key facts AND ≥1 verified citation") vacuously true and let a Deep query count toward the headline on a citation alone. `judge_notes` must name the correct source documents for each temporal slice.

**Schema change.** Each `AgentQuery` gains a `set:` field (one of `quick`, `multi`, `deep`, `refusal`) and an optional `correct_response_docs: [<document id>]` field used on the Multi set. Key facts, shape, corpus, tier, judge_notes are unchanged. The `tier: deep_research` marker is retired in favour of `set: deep`; a per-query `tier` may remain for model-routing if desired but is no longer the subset mechanism.

**Tuning an existing query means re-verifying it.** If a key fact, question, or `correct_response_docs` entry changes, the same verification the original paid (corpus scan for presence, a top-20 retrieve of the verbatim question for reachability) must be re-run — a tuned query that silently lost its fact is worse than an old one. The approval task below is where this happens.

## THE SINGLE QUERY-APPROVAL TASK

One task in the plan exists for Destin to **approve / iterate on the final query sets** before any scoring runs against them. Method, verbatim from the session:

- The implementer runs each query through the real app, AND
- manually navigates the budget documents to find the most correct answer the judge should score against.

So ground truth is **analyst-chosen answer/document correctness**, not synthesized-from-chunk. For the Multi set this means pinning the `correct_response_docs` by hand against the live corpus (the identity-consistency audit and `store.chunk_store.ChunkStore().scan(...)` are the reference for how). Until Destin approves this set, no model is scored on it.

Scope note: "run each query through the real app" is itself a paid pass (~43 queries × 1 run each) BEFORE any scored run exists — budget it as a distinct cost line, and run it serially or with modest `--workers` since its purpose is ground-truth inspection, not measurement. Re-tagged queries whose key facts are untouched can lean on their prior verification; the full pass is owed by NEW and TUNED queries.

## Profile-driven runner (the orchestrator)

**Extend `eval/run_full_layer2.py`, do not create a new entry point.** That orchestrator already drives run → score → judge as subprocesses with crash isolation, `--workers` passthrough, and stop-on-first-failure; the profile additions ride on it. (Naming it `eval/run_eval` would collide with the Layer 1 entry point `eval/run_eval.py`, which this design explicitly retains.) Profile selection:

- **models** — exactly **1 (single run) or 2 (head-to-head)**, run **in parallel through the full chosen set**. Two models = one run dir each, compared by the existing `compare_agent_runs.py`. A 1-model run is the same code path with one side, so a later A/B is free.
- **sets** — `--sets quick,multi,deep,refusal` (any subset; Deep is excludable to control cost).
- **workers** — `--workers N` thread-based fan-out, already implemented (network-latency-bound work, two ONNX models are shared singletons).
- **judge** — on/off (`--judge`), judge stays a separate charge and is manual.

Flow, reusing existing machinery: `run_agent_eval` (transcripts) → `agent_scoring` + **new scorer modules** → `judge_agent_run` (when requested) → `compare_agent_runs` (when 2 models) → write the consolidated report + append to the over-time archive.

## Scoring — the four axes

**New scorer modules, additive** — they extend `eval/agent_scoring.py` and add sibling modules; nothing about the hard-won currency tolerance, citation-retry logic, or honesty guards is rewritten.

**a) Cost-to-accurate-response (headline).** Per query, `tokens_to_accurate` (prompt + output + cache-read tokens) and `turns_to_accurate` (steps) **only when** the response passes its key facts AND produces ≥1 verified citation. Aggregated per set and per model. Fast-but-wrong and fast-but-uncited are excluded (their token/turn counts remain recorded, so a regression that trades correctness for speed is visible as accuracy dropping while the headline counts fewer queries).

**Wall-clock time is dropped as a metric entirely** (Destin's call): it is dominated by network latency to the provider and machine load (~70% absolute swings on this box per CLAUDE.md), so no comparison survives contact with a different session, network condition, or `--workers` value. The transcript keeps stamping `wall_ms` — it is an existing, free field and a useful forensic detail when debugging one slow run — but the scorer does not report it, the consolidated report does not surface it, and nothing trends on it.

**b) Retrieval/chunk quality (priority 1).** Layer 1 recall stays the free inner loop. `retrieval_efficiency` **already exists** in `eval/agent_scoring.py` and is retained UNCHANGED: distinct chunks counted as used (cited, OR containing a currency/regex key fact that also appears in the final answer) ÷ distinct chunks retrieved. (Earlier drafting proposed narrowing "used" to cited-only; the shipped definition survives because cited-only was already measured and rejected — it saturated near 1.0 on topically-adjacent chunks, the failure the shipped comment records.) The NEW half is judge-scored chunk relevance (do the retrieved chunks match what this query is actually asking?), run where the judge runs — that is the "match what we'd actually be looking for" signal chunk-id recall cannot give.

**c) Tool-call efficiency (priority 2).** Consolidate existing signals into one per-query view: steps, retrieve calls, token split, cost, `retrieves_after_sufficient`, filter/intent/top_k usage, deep_dive calls. Reported per query/set/model so the exact spot where the agent burns turns before an accurate answer is visible. These remain informational (no better/worse arrow — a filter is right or wrong depending on the question).

**d) Doc-type relationship understanding (priority 3).** **document_correctness** = share of verified citations that point at a `correct_response_doc` (Multi set only). This is the "cited the Baseline when it should have cited the Appropriations Report" test — the exact ambiguous case the repo's identity audit documented. It is mechanical (verified cite → chunk's document id ∈ `correct_response_docs`) and feeds the judge. Two edges are reported distinctly, not folded into the share: a Multi query with zero verified citations scores `document_correctness = None` plus an explicit `unanswered` flag (cited nothing ≠ cited the wrong doc-type — key facts still say whether the answer was right), and a correctly-refused Multi query is excluded from the set average rather than scored 0.

## Tool-error harvesting (every error is guidance)

A new mechanical pass over each transcript extracts **every tool-call error** — retrieve failures, cite failures/retries, argument/validation errors, ambiguity rejections, filter rejections, malformed outputs, crashed queries. Emits a structured **error ledger per run**: error kind × frequency × query × model, plus a rationale line and a "what to improve" hint. This is an explicit input to shaping the system prompt, tool descriptions, and filter schema. Consistent with the repo's boring invariant, each error is tied to the turn it cost — not just counted.

## Result storage & change-over-time monitoring

One consistent archive, written by every orchestrator (`run_full_layer2`) invocation:

```
eval/results/agent/<UTC-ISO>-<git-sha>/     # existing per-run dir: transcripts, manifest, scores, judge  [unchanged]
eval/results/over-time/
    index.json                               # every run: git sha, profile, sets, model(s), timestamp, cost
    metrics.jsonl                            # append-only, one line per run: headline metrics (tokens_to_accurate,
                                             #   turns_to_accurate, document_correctness, key_fact_rate,
                                             #   efficiency, error counts), plus profile echoes (workers,
                                             #   sets, model) so a trend line is never plotted across
                                             #   incomparable conditions
```

Over time `metrics.jsonl` becomes the plottable trend ("document_correctness 0.71 → 0.83 → 0.90 across last month's runs"). Comparison honesty guards port into it: runs with different `queries_sha256` or different corpus counts are flagged, never silently trended together.

## Honesty guards preserved

- **No repeats** (Destin's call). The orchestrator banners single-run stochasticity exactly as `compare_agent_runs.py` already does; deltas within noise are labeled, not celebrated.
- **Headline comparisons need a control, not a remembered baseline.** Any run whose `tokens_to_accurate`/`turns_to_accurate` is compared against a prior run must link the prior run's `metrics.jsonl` row in the comparison report. Tokens and turns are load-invariant (the reason wall-clock was dropped as a metric), so they do compare across sessions — but query-set sha256, model, and `--workers` still must match, and a "fixed" number from an earlier run is a hypothesis until re-checked (CLAUDE.md measurement discipline).
- **Money-spending runs are manual, never CI.** The live runner, the judge, and the Deep set all spend through OpenRouter; pytest over synthetic fixtures stays free.
- `queries_sha256` and corpus-count guards carry into the over-time archive. Expect the sha256 to churn while the approval task iterates on queries — that is correct behaviour, not a bug: each edited set starts a new trend segment. The report renderer splits `metrics.jsonl` trend lines at every sha256/corpus-count change and labels each segment with the query-set edit, instead of plotting one misleading continuous line or refusing to trend at all.
- A run's `manifest.json` records everything needed to know whether two runs are comparable (git sha, prompt sha256, queries sha256, `tier_models` map, corpus counts) — unchanged.

## Open Decisions (confirm at review)

1. **The "accurate" bar.** Default: a response counts toward the headline (`tokens_to_accurate` / `turns_to_accurate`) when it passes key facts AND has ≥1 verified citation (mechanical, cheap). A stricter alternative also requires the judge's holistic grade to clear a bar (more expensive, since it makes the headline depend on the paid judge). Default chosen: mechanical bar; judge holistic is reported as a secondary metric, not the gate.
2. **Deep Research cost.** Each Deep query is expensive (the old DR tier ~$2–3 for a full probe). Default: all 3 are in a normal run, but the Deep set is **excludable per profile** (`--sets` without `deep`) so a cheap iteration need not pay for it.

## Out of scope

- Bringing the money-spending machinery into CI.
- Adding repeats for statistical power (Destin explicitly declined).
- Parallelising search *inside* the agent (Destin wants faster production responses via better tool calls/results, not agent-level parallelism).
- Fiscal-note agent eval (separately tracked; Layer 1 already has fiscal-note ground truth via `eval/fiscal_note_queries.yaml`, Layer 2 deliberately stays budget-corpus-only).
- The improvement experiments themselves (the eval measures; tuning the prompt/tools follows on, each in a worktree).
