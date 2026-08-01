# Agent-Loop Eval (Layer 2) — Design

**Date:** 2026-08-01
**Status:** Approved by Destin 2026-08-01 (brainstorming session)
**Supersedes nothing.** Extends — does not touch — the Layer 1 retrieval eval
(`eval/run_eval.py`, spec `2026-05-20-retrieval-eval-harness-design.md`).
This is the "Layer 2 eval" STATUS.md has deferred since Phase 1c, redesigned
for the standalone `harness/` architecture instead of the retired MCP stack.

## Why now

The Layer 1 eval calls `retrieve()` directly. It measures chunk recall and
refusal thresholds and nothing else: agent turns, tokens, latency, citation
behavior, and answer quality are all invisible to it. The Plan 4 live run
demonstrated exactly the failure modes that matter and that nothing measures:

- Two identical memo prompts produced 20 citations (12 passing) and then zero.
- First-attempt cite failure burned retry round-trips (12/20 and 5/7 passing).
- Meta-narration and a raw download token leaked into answer prose.
- Deep Research cost 44× Standard with no way to know if the extra searching
  was buying anything.

Preconditions that make this the right moment, verified 2026-08-01 on this
machine (the Z13):

- **The S20 backfill is complete.** Orchestrator work list exhausted at
  24,841 budget chunks + 13,278 fiscal-note chunks / 3,527 documents. The
  corpus is stable, so baselines are meaningful.
- **A live OpenRouter key is configured** in `<data_dir>/settings.json`
  (Standard = `z-ai/glm-5.2`, Deep Research = `moonshotai/kimi-k3`), so live
  agent-loop runs can execute here.

## Goals → metrics

Four goals, each reduced to numbers a run emits:

| # | Goal | Metrics |
|---|------|---------|
| 1 | Minimize turns/tokens | steps per answer, retrieve calls per answer, total tokens (prompt / completion / **cached** split), cost USD per answer |
| 2 | Accuracy + speed | key-fact match rate, refusal correctness on refusal-expected queries, wall-clock per answer |
| 3 | Search efficiency / self-awareness | **retrieval efficiency** = chunks actually used (cited, or containing a matched key fact) ÷ chunks retrieved; **retrieves-after-sufficient** = retrieve calls issued after every key fact was already present in prior results; filter/corpus-parameter usage counts |
| 4 | Fewer, higher-value, narrower, first-try citations | citations per answer, **first-attempt cite pass rate**, retries per citation, median quote length (narrowness proxy), ambiguity rejections, and the judge-scored headline metric **claim-coverage precision** (below) |

Plus output-hygiene checks derived from observed live failures: meta-narration
lexicon hits ("let me search", "I have what I need", retry narration), leaked
download-token patterns, internal-vocabulary leaks (corpus mechanics, tool
names, threshold values).

## Decisions (locked during brainstorming)

1. **Layered cost model.** A free deterministic layer runs on every change
   (Layer 1 eval, static prompt-token delta, citation-validation replay over
   recorded transcripts, mechanical re-scoring of old transcripts). The live
   model-driven eval runs at two grains: a ~10-query smoke subset for
   iteration, the full set before merging a change.
2. **Answer correctness = key-fact rubric + LLM judge.** Each query carries
   mechanically checkable key facts (deterministic, free, catches wrong
   numbers). An LLM judge adds holistic grading on full runs only.
3. **Citation headline metric = claim-coverage precision.** The judge
   identifies the answer's load-bearing claims; score = load-bearing claims
   cited AND verified ÷ total citations issued. Uncited key claims hurt;
   padding citations on trivial prose also hurt. Verified-rate alone was
   rejected because it rewards citing less and citing only easy claims —
   the opposite of Invariant 1.
4. **Tier scope = Standard for the full set + a fixed 4-query Deep Research
   probe** run on demand / before releases. Full-set DR runs (~$15–20,
   hours) were rejected as incompatible with fast iteration.
5. **Architecture = in-process Session runner, transcript-first**
   (Approach A). The runner drives the real `harness/` session in Python —
   the production code path — with no server. A black-box SSE runner
   (Approach B) and extending Layer 1 in place (Approach C) were rejected:
   B tunes plumbing we aren't changing and needs a live server; C mixes a
   deterministic regression detector with a stochastic agent eval, which the
   repo already deliberately separates.

## Components

### 1. Query set — `eval/agent_queries.yaml`

~30 queries authored by agents sampling the real post-backfill corpus (the
synthesize-from-chunks technique of `eval/synthesize_queries.py`), then
human-reviewed before being committed. Shape coverage, chosen because each
shape exercises different agent behavior:

**BUDGET CORPUS ONLY.** Every query targets `budget_chunks`. Destin's
direction, 2026-08-01: *"this eval set should NOT utilize the fiscal note
path, we are solely evaluating budget queries."* The harness itself remains
corpus-capable (the runner takes a corpus per query, and `AgentQuery.corpus`
still accepts `fiscal_notes`), so a fiscal-note set can be added later
without reworking anything — but this set does not mix them, because a
metric averaged across two corpora answers no question about either.

Shape coverage, chosen because each shape exercises different agent
behavior:

- quick lookups (single figure, single agency, single FY)
- multi-year comparisons (the 3-year-table pattern)
- analyze-shaped questions (multi-retrieve synthesis)
- one memo / `create_document` ask (the observed zero-citation failure shape)
- refusal-expected out-of-scope questions
- historical-year questions — the OLDEST budget-book years in the corpus,
  where retrieval is most likely to struggle. Measured 2026-08-01,
  `budget_chunks` spans FY2021–FY2027 (FY2021 is a 169-chunk fragment), so
  "historical" means FY2022–FY2023 today. The 27 pre-FY2022 JLBC book
  editions are a deliberate MVP deferral recorded in STATUS.md, not a gap in
  this design: when that backfill lands, this shape extends to the older
  editions and the historical queries get re-authored against them.

Per-entry schema:

```yaml
- id: aq-001
  question: "..."
  corpus: budget            # always "budget" in this set — see above
  tier: standard            # dr-probe entries say deep_research
  subset: [smoke, full]     # membership tags
  should_refuse: false
  key_facts:
    - kind: currency        # matched with formatting tolerance ($1,234.5M == 1234.5 million)
      value: "..."
    - kind: string | regex
      value: "..."
  judge_notes: "free text — what a correct answer covers, known traps"
```

A pinned `smoke` subset (~10 queries spanning shapes) and a fixed 4-query
`dr-probe` subset.

### 2. Runner — `eval/run_agent_eval.py`

Drives the real harness session in-process per query. Output is
**transcript-first**: one JSONL per query under
`eval/results/agent/<UTC-ISO>-<git-sha>/`, recording every step, every tool
call and result, token usage per step (prompt / completion / cached), the
OpenRouter-reported cost, wall time, and every citation attempt with its
validation outcome and retry chain.

A run manifest records: model, tier, `system-prompt.md` content hash, corpus
table counts, settings snapshot (key redacted), git sha, query-set hash — so
no two runs are ever compared without knowing what differed.

Flags: `--subset smoke|full|dr-probe`, `--repeats N` (default 1),
`--queries <ids>`.

The results-prefix convention from Layer 1 carries over: agent-eval results
live in their own directory and can never be diffed against a Layer 1 run.

### 3. Mechanical scorer — free, decoupled

A separate pass (`eval/score_agent_run.py`) that reads transcripts and emits
all Goal 1–4 mechanical metrics plus hygiene checks. Because scoring is
decoupled from running:

- improving a metric lets us re-score historical transcripts without
  spending tokens;
- a change to `retrieval/citations.py` can be evaluated by **replaying**
  recorded citation attempts against the new validator, zero model calls.

### 4. Judge layer — `eval/judge_agent_run.py`, full runs only

Temperature-0 LLM judge via the same OpenRouter key; judge prompt versioned
in-repo and hashed into the run manifest. Per answer, from the transcript
plus the cited chunk texts, it emits: the load-bearing claims list, which
are cited-and-verified, claim-coverage precision, a holistic 1–5 grade, and
hedging / meta-narration flags. Judge model configurable in the manifest;
default is a cheap capable model, not the model under test.

### 5. Comparison + reports — `eval/compare_agent_runs.py`

Diffs two run directories into a committed markdown report:
metric-by-metric deltas, per-query drill-down for regressions. Guardrails:

- refuses to compare runs whose corpus counts differ;
- flags any single-run (repeats=1) comparison as stochastic — deltas within
  noise bands are labeled, not celebrated.

Reports are committed alongside code changes, same convention as Layer 1.

## Experiment workflow

The harness is the measuring instrument; improvements are follow-on
experiments, each in a worktree:

1. **Cheap layer first**: Layer 1 eval + static prompt-token delta +
   citation-replay where applicable.
2. **Live smoke run** (~10 queries, ~$0.20) against the candidate.
3. **Full live run** before merge; compare report committed with the change.

Baseline: taken on current master immediately after the harness lands.
Re-baselined whenever a retrieval-path change lands (e.g. the pending
Phase D recency calibration), keyed by git sha + corpus counts.

Candidate experiment backlog (from STATUS.md known issues — none designed
here): system-prompt self-awareness rewrite (what the agent is, its exact
tools/filters/corpora), tool-description improvements, first-call-cap
tuning, cite steering toward short distinctive quotes and `cite_batch`,
meta-narration suppression, retrieve-result trimming for token reduction.

## Testing

- pytest over fixture transcripts: scorer metrics, key-fact matchers
  (currency-formatting tolerance cases), hygiene lexicon, judge-output
  parsing, compare-tool guardrails.
- Runner exercised against the harness's existing fake-OpenRouter test
  client — CI never spends money.
- The live layers are money-spending by definition and are run manually,
  never in CI.

## Out of scope

- WS3 faithfulness verifier (semantic claim–chunk entailment) — claim
  coverage here is judge-scored, not NLI-verified.
- Phase D recency calibration (separate active workstream).
- The improvement experiments themselves.
- Fiscal-note Layer 1 ground truth (`eval/fiscal_note_queries.yaml`) — worth
  doing now that the corpus is complete, but it is Layer 1 work.
