# Eval Harness — Layer 1 (Retrieval Regression Detector)

This eval measures **retrieval pipeline health** — chunking, BM25,
dense embeddings, RRF fusion, and the local cross-encoder rerank
(ms-marco-MiniLM-L-12-v2 since Plan 1; Voyage before). It does NOT measure
end-to-end usefulness to analysts. Read "What this measures (and
doesn't)" before quoting the numbers.

Layer 2 (an end-to-end agent-loop eval that drives the real harness
session and scores answer key-facts, citation discipline, and output
hygiene against open-ended analyst questions) has since shipped — see
"Layer 2 — agent-loop eval" below. It no longer waits on WS3 (the
faithfulness verifier): the mechanical scorer and LLM judge below are
what stand in for it today. See
`docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md`
for the original spec.

## What this measures (and doesn't)

**What it measures:** Lookup and comparison queries were synthesized
FROM seed chunks — the LLM was shown a chunk and asked to write a
question that chunk answers. By construction, the chunk IS the
correct answer. This makes the eval a strong **regression detector**:
if recall@5 drops from 86% to 70% after a chunking change, that's a
real signal — a change that breaks the easy synthesized case will
break the harder real-analyst case too. The two detours during
implementation (BM25 apostrophe crash fix lifting recall 55%→86%; the
calibration tool surfacing that the prompt's 0.30 threshold is
effectively dead) demonstrated this is doing its job.

**What it does NOT measure:** Real analyst utility. The synthesized
queries' phrasing was guided by the chunks' vocabulary, so the
measured recall is an **upper bound**, not a representative number.
(Current baseline on the local stack: recall@5 72.41%, recall@15
96.55%, recall@20 100% — the 86% figures elsewhere in this file are
the retired Voyage-era baseline, kept for historical context.)
Real-world questions ("spending on homelessness projects?", "actual
expenditures of opioid monies?") would hit lower numbers because real
queries don't pre-align with chunk vocabulary. Don't quote the
recall number as "the system's recall" — quote it as "today's Layer 1
regression score" and focus on deltas, not absolutes. A future Layer 2 eval will
fold in real dogfood queries from the harness's records (the
month-sharded spend ledger + conversation logs on the share — the old
`bridge.log` died with the MCP bridge).

**Refusal scope:** The 5 refusal queries here test only
**corpus-boundary** cases (wrong jurisdiction, fictional entity,
future fiscal year). They do NOT test editorial-framing refusals
("should we raise taxes?", "what's the best policy?"). Editorial
queries SHOULD return relevant chunks from retrieval — the framing is
a separate concern for a query-classifier or LLM-side declination
mechanism. The two queries currently in queries.yaml that mix this
distinction (q-030 "raise income tax", q-031 "water policy
recommendation") were left in for transparency, but they shouldn't be
interpreted as retrieval failures.

## Running it

After any change to `retrieval/`, `ingest/`, `chunking/`, or
`harness/system-prompt.md`:

```bash
uv run python -m eval.run_eval
```

Takes ~30-90 seconds. Output:
- `eval/results/<UTC-ISO>-<git-sha>.json` (machine-readable)
- `eval/results/<UTC-ISO>-<git-sha>.md` (human-readable summary with
  deltas vs. previous run)

Both are committed to git so the history travels with the repo. Diff
two runs with `git diff eval/results/<old>.json eval/results/<new>.json`.

## What "pass" means per query type

- **Lookup** passes if any expected chunk is in top K (preferring
  chunk_id match, falling back to dimensions match).
- **Comparison** passes if ALL expected chunks are in top K.
- **Refusal (corpus-boundary)** passes if retrieval correctly returned
  a low-confidence top score (top_score < threshold). This is a
  defense-in-depth check; calibration's reported recall makes the
  gap with real refusal performance visible.

## After a re-ingest

Chunk boundaries can change during ingest, which invalidates the
`chunk_id` on every affected ground-truth entry.

**There is no automated fixer.** `eval/refresh_chunk_ids.py` used to do
this — anchor-text match preferred, cosine fallback — but it was never
ported off Postgres and was deleted in Plan 5 Track 4 along with `db/`.

What absorbs the damage today:

- `eval/scoring.py`'s **dimensions fallback**. An expected chunk whose
  `chunk_id` is gone still matches if publisher / doc_type / fiscal_year
  / agency all match. This is loose — it can credit a *different* chunk
  of the same document — so a run leaning heavily on it is reporting a
  softer number than it looks like.
- **`anchor_text`**, still written by the synthesizer for every expected
  chunk. It is a short distinctive phrase from the original chunk, so
  grepping the new corpus for it finds the successor. That is the manual
  repair path.

**Before a from-scratch corpus rebuild**, budget time to re-point stale
chunk_ids by hand, or re-write the refresh tool against
`store.chunk_store.ChunkStore` — the same one-import-swap shape that
`eval/synthesize_queries.py` got in that commit, plus
`ChunkStore.vector_search` in place of the pgvector cosine fallback.

## Calibrating the refusal threshold

After the corpus or rerank model changes:

```bash
uv run python -m eval.calibrate_refusal
```

This sweeps a threshold grid derived from the observed score
distribution against the most recent eval result and reports refusal
precision, **refusal recall**, and retrieval pass-rate at each. The
recommended threshold maximizes the equal-weighted average of all
three — recall is critical here because the eval's first calibration
showed precision alone could be gamed (a tight threshold catches one
obvious case and "looks perfect" while letting most refusals through).

The runtime threshold is `REFUSAL_THRESHOLD = 1.9` in
`harness/constants.py` — a single Python constant, set 2026-07-30
after the Plan 1 model swap (sweep: precision 0.67 / recall 0.40 /
pass-rate 0.97). Scores are **raw cross-encoder logits** (roughly
−10..10), not the old Voyage 0..1 scale — any prose you find pointing at
a 0.65 or 0.30 threshold describes the retired pre-consolidation stack
and does not transfer. `harness/prompt.py` renders the constant into the
system prompt, so editing prompt text cannot change the threshold — it
will produce no effect and no error. **The calibration output's recall
number is the load-bearing one**: if recall is low at every threshold,
the retrieval-layer mechanism can't reliably refuse the failure modes
in your eval set — investing in a query classifier or faithfulness
verifier will be much higher leverage than tweaking the threshold.

## Calibrating the recency weight (S21 layer 3)

Two tools, two different questions. Both drive the real pipeline and
both sweep `RECENCY_BOOST_PER_YEAR` through `retrieval.recency.recency_weight()`
rather than editing the constant.

```bash
uv run python -m eval.calibrate_recency   # minimal weight that restores recall
uv run python -m eval.sweep_recency       # recall AND chronological order
```

`calibrate_recency.py` asks *what is the smallest weight that restores
no-year recall without damaging the standing set?* It needs
`eval/queries_historical.yaml` and refuses to run until that file is
authored.

`sweep_recency.py` asks the question recall cannot express — Destin's
acceptance criterion, *"for a simple inquiry, just an agency name, no
year, no topic, results should come back roughly newest-first."* It adds
a third metric (`eval/chronological.py`) and tolerates a missing query
file by blanking that column instead of exiting.

**The headline number is `ORDER`**: of every pair of returned results
where one document is newer than the other, the share that came back
with the newer one first. 100% is perfectly newest-first, **50% means
the ranking carries no year signal at all**, 0% is exactly backwards.
Ties are excluded from the denominator, so twenty chunks from one
edition neither help nor hurt. `vintage` beside it is the mean fiscal
year of the top 5 — ordering alone is not enough, since 2010-2009-2008
scores a perfect 100%.

Three things worth knowing before reading its output:

- **`eval/queries.yaml` cannot measure this.** 32 of its 34 queries name
  a fiscal year, so S21 layer 1 hard-filters them and the boost never
  runs; the other 2 are refusal queries with no ground truth. Its recall
  column is flat at every weight, and that is not evidence of safety.
  The sweep prints a warning saying so.
- **The `prx@` columns are a stand-in, not a measurement.** With
  `queries_historical.yaml` empty, the sweep derives a set by stripping
  the year out of each explicit-year query and keeping the original
  ground truth. Every one of those targets is FY2025-2027, so the boost
  *helps* them — it is an optimistic probe, not a cost measurement.
  Delete the stand-in (`--no-proxy`) once the real file exists.
- **The sweep is fast because it retrieves once per query** and re-applies
  the boost offline at each weight, which is valid only because nothing
  upstream of the boost depends on the weight. `--verify N` re-runs N
  queries through the real pipeline and diffs the order; if that ever
  prints MISMATCH, the pipeline moved and `replay()` has to follow.

Afterwards, whatever weight is chosen, **re-run `calibrate_refusal.py`** —
a non-zero boost lowers `top_score`, which is what `REFUSAL_THRESHOLD`
is compared against.

## Adding queries

Two paths:

1. **Re-run the synthesizer — currently UNPORTED.**
   `eval/synthesize_queries.py` still imports the retired Postgres
   `db.connection` and will crash; port it to the LanceDB store before
   using it. The alternative that still works: the subagent-driven
   pattern used for the initial set — see commit `6e5f907` for an
   example where chunks were sampled into JSON and a subagent wrote
   queries.yaml inline.

2. **Hand-write directly in `eval/queries.yaml`:** follow the schema
   in `eval/schema.py::EvalQuery`. Pick a unique `id`, write the
   query and expected_chunks. Run the eval; if the hand-written
   query passes, you're done.

## Why "regression eval" instead of "the eval"

Layer 1's value is in detecting regressions when retrieval code
changes. It's NOT a measure of whether real analysts are getting
useful answers. That measurement requires:
- Open-ended queries (no pre-targeted chunks)
- Chunk-set ground truth (multiple acceptable answers per question)
- End-to-end runner (analyst question → Claude → RAG → answer → grade)
- LLM-as-judge or human rubric scoring

That's a different eval. It deserves its own design and lives outside
this directory. When that lands, expect Layer 1's role to shift to
"fast regression alarm" while Layer 2 takes over as "quality measure."

## Files

| File | Purpose |
|---|---|
| `queries.yaml` | Ground truth — 34 questions + expected_chunks (Layer 1, synthesized from chunks) |
| `schema.py` | Pydantic models for queries + results |
| `scoring.py` | Pure recall + refusal scoring functions |
| `synthesize_queries.py` | One-shot LLM-driven query generator — **UNPORTED: imports retired Postgres `db.connection`, crashes** |
| `run_eval.py` | Main runner — calls retrieve(), scores, writes results |
| `calibrate_refusal.py` | Threshold sweep + recommendation (now reports recall) |
| `calibrate_recency.py` | S21 weight sweep — minimal weight that restores recall |
| `chronological.py` | The newest-first order metric (`newest_first_rate`, `mean_fiscal_year_at_k`) |
| `sweep_recency.py` | S21 weight sweep — recall AND chronological order, at every weight |
| `results/` | Git-tracked result files (one JSON + one MD per run) |
| `agent_queries.yaml` | Layer 2 ground truth — open-ended questions + key_facts + shape + set tags |
| `agent_schema.py` | Layer 2 query schema (`AgentQuery`, `KeyFact`) — `extra="forbid"` |
| `run_agent_eval.py` | Layer 2 runner — drives real `HarnessSession`s, spends money, writes transcripts. `--workers N` runs queries concurrently |
| `run_full_layer2.py` | One-shot orchestrator — run → score → judge in one command, one pinned run dir |
| `defend_agent_run.py` | Defend mechanism — drives a fresh session to justify/amend a poorly-scored transcript (spends money) |
| `agent_transcript.py` | Layer 2 transcript read/write — degrades a truncated file to an error record |
| `agent_scoring.py` | Layer 2 mechanical scoring functions (free) |
| `score_agent_run.py` | Layer 2 scorer CLI — transcripts → `scores.json` / `scores.md` (free) |
| `judge_agent_run.py` | Layer 2 LLM judge CLI — `scores.json`'s companion, costs money. `--workers N` grades concurrently |
| `agent_judge_prompt.md` | The judge's system prompt |
| `compare_agent_runs.py` | Diffs two Layer 2 run directories into a markdown report (free) |
| `results/agent/` | Layer 2 run directories — derived artifacts committed, raw transcripts gitignored |

## Windows note

Every CLI tool in this directory reconfigures stdout to utf-8 at startup
so the default Windows cp1252 console doesn't crash on the ✓ ✗ Δ ⚠ ▲ ▼
glyphs they print.

## Layer 2 — agent-loop eval (`run_agent_eval.py`)

Everything above is Layer 1: it measures retrieval health only, by
calling `retrieve()` directly. Layer 2 drives the REAL harness session
— the production `HarnessSession` code path, no HTTP server — for a set
of open-ended analyst questions, and measures what Layer 1 structurally
cannot: agent turns, tokens, cost, whether the final answer actually
contains the right key facts, citation discipline (how often a cite
passes verification, how often it passes on the FIRST try, and how many
retries each citation cost), search efficiency including which filters
the agent chose, and output hygiene (meta-
narration leaks, internal-vocabulary leaks, a leaked download token).

**Headline metric (2026-08-16 consolidation).** The headline is
**cost-to-accurate**: `tokens_to_accurate` and `turns_to_accurate`,
computed ONLY over responses that pass all their key facts AND produce
≥1 verified citation (fast-but-wrong and fast-but-uncited are excluded).
**Wall-clock time is deliberately NOT a metric** — it is network- and
machine-load dominated, so no comparison survives a different session;
tokens and turns are load-invariant and are what trend in the over-time
archive. The `document_correctness` axis (Multi set) measures doc-type
understanding: share of verified citations pointing at a
`correct_response_doc`. Tool-error harvesting logs every failed
retrieve/cite/argument with the turn it cost.

Layer 1 stays the free, fast inner loop for retrieval-only changes;
Layer 2 is the paid outer loop for anything that touches the harness
loop or the system prompt. **Their numbers are not comparable to each
other** — a recall percentage and a key-fact rate measure different
things over different query sets.

**This layer costs real money — every run calls a real model through
OpenRouter.** Rough guide:

Queries are organized into **sets** (`set:` in the YAML). The default
selection is `quick,multi,deep,refusal`; use `--sets` to control cost
(Deep is excludable for cheap iteration):

| set | what's in it | rough cost |
|---|---|---|
| `quick` | 45 single-shot Standard-tier queries (lookup/comparison/analyze/memo/historical) | ~$0.30–0.60 |
| `multi` | (not yet authored — follow-up) | — |
| `deep` | the 3 Deep Research queries | ~$6–9 |
| `refusal` | the 5 should-refuse queries | negligible (they should refuse) |

**Deep Research is deliberately excludable** (spec Decision #2): it costs
~44× Standard per query and takes ~5 minutes, so shipping it in every
cheap iteration would multiply cost and bury Standard latency regressions.
Run `--sets quick,multi,refusal` for fast iteration; add `deep` only when
you want the worst-case synthesis numbers. The LLM judge
(`judge_agent_run.py`) is a second, separate charge on top of a run —
budget for it only when running the full set.

Query authoring lives in `agent_queries.yaml`, validated by
`agent_schema.py` (`AgentQuery` / `KeyFact`, both `extra="forbid"` so a
typo'd field name fails the load instead of silently vanishing). Each
query pins a `shape` (lookup / comparison / analyze / memo / refusal /
historical), a `corpus`, a `tier`, zero or more `key_facts` (currency /
string / regex, mechanically checkable in the final answer), and a `set`
(`quick` / `multi` / `deep` / `refusal`) — one of the four selection sets.
The retired `subsets: [smoke/full/dr-probe]` mechanism is gone
(2026-08-16 consolidation).

Workflow:

```bash
uv run python -m eval.run_agent_eval --sets quick,multi,refusal --workers 8   # live run, spends money
uv run python -m eval.run_full_layer2 --sets quick,multi,refusal --workers 8  # run + score + judge, one command
uv run python -m eval.score_agent_run eval/results/agent/<run>    # free, re-runnable
uv run python -m eval.judge_agent_run eval/results/agent/<run> --workers 8  # money — full runs only
uv run python -m eval.compare_agent_runs <baseline-dir> <candidate-dir>  # free
```

**Parallelism.** `run_agent_eval --workers N`, `judge_agent_run --workers N`
and `run_full_layer2 --workers N` all fan their paid OpenRouter calls out
across N concurrent worker threads. The Layer 2 runner is dominated by
waiting on model latency, not CPU, so issuing several queries at once
overlaps that latency instead of stacking it — a full quick run (45
Standard queries) that took ~15 minutes serially can drop to roughly a
third at `--workers 8` when the provider keeps up. The default is **1
(serial)**, preserving the historical behaviour and guarding against
accidentally hammering OpenRouter; pass `--workers` explicitly when you
want speed.
The judge is inherently network-latency-bound too, and gets the same
treatment. Both are thread-based (not process) because the paid work is
I/O — the two ONNX models are shared singletons already used concurrently
by the office app's threadpool, and full-process isolation would multiply
model memory for no wall-clock gain.

**`run_full_layer2`** is the one-shot wrapper: it drives `run_agent_eval`
→ `score_agent_run` → `judge_agent_run` in order as subprocesses (stop at
the first non-zero exit), pointing all three at one pinned run directory
so you never guess which dir was just created. `--skip-judge` runs only
run + score (judging is a second, separate charge). It re-runs cleanly
and produces byte-identical artifacts to running each step by hand.

`run_agent_eval.py` writes one directory per run —
`eval/results/agent/<UTC-ISO>-<git-sha>/` — containing `manifest.json`
(git sha, prompt sha256, query-set sha256, tier→model map, corpus row
counts — everything needed to know whether two runs are even comparable), one
`<query_id>-r<N>.jsonl` transcript per (query, repeat) via
`agent_transcript.py`, and `ledger.jsonl`. Use `--repeats N` to sample a
query more than once — **a single run is stochastic**; a small delta
between two single runs is noise, not signal, and `compare_agent_runs.py`
says so loudly whenever either side has `repeats: 1`. `--model` pins the
Standard-tier model for the run without touching `settings.json`.
`--queries` restricts to specific query ids for a quick check on one
failing case.

**Report bundle (auto-launched).** `run_full_layer2` ends with a free
"report" step that builds `eval/results/agent/<run>/report/` — a styled,
navigable HTML site — and OPENS `report/index.html` in your browser:

- `index.html` — headline metrics (accurate rate, tokens/turns-to-accurate,
  cite pass, judge means) + the full per-query table (every output metric),
  each stat with a hover tooltip explaining it in analyst terms; hover a
  query id to see its full user message; click a column to sort.
- `per-query/<id>.html` — per query: metrics, the judge review (holistic,
  chunk_relevance, load-bearing claims ✓/✗), and the conversation rendered
  with the LIVE app's chat classes (navy user bubble, white assistant
  bubbles, tool cards with the app's retrieve/cite/result look).

Regenerate/relaunch any run's report without re-running the model:
`uv run python -m eval.report_bundle eval/results/agent/<run>`. The
transcript's streamed deltas are collapsed into clean app-style messages
(the last delta of a phase carries the full message); a tool call with no
preceding deltas means the model went straight to the tool.

**Over-time archive.** Every scored run with a manifest also appends one
row to `eval/results/over-time/metrics.jsonl` (headline metrics + the
comparability keys: `queries_sha256`, corpus counts, profile) and updates
`index.json`. Trend lines split into segments at every query-set or
corpus change, so editing the query set starts a new labeled segment
instead of a misleading continuous line. The archive is committed (like
scores/judge), so change-over-time travels with the repo.

**The runner writes its OWN ledger, isolated from the office.** Every
eval query runs with `check_limit` stubbed to always-allow and
`record_usage` writing into that run's own `ledger.jsonl` instead of the
shared office spend ledger — an eval run is pre-authorized by the human
who started it, and it must neither be blocked by S19 office limits nor
silently accrue against them. If you're looking for eval spend in the
office usage totals, it deliberately isn't there.

**`ledger.jsonl` is the authoritative spend record — `total_cost_usd` in
`scores.json` is not the same number.** The ledger gets one row per model
step, written as the step happens. `total_cost_usd` is derived from each
query's terminal frame, and a query that CRASHED mid-turn produces an
error frame carrying no usage at all — so the tokens it already paid for
are invisible in `scores.json` no matter how the rows are summed.
`cost_missing_queries` in the summary counts the queries whose cost is
unknown for exactly this reason; if it is non-zero, add up `ledger.jsonl`
instead of quoting `total_cost_usd`.

**Reading the citation metrics.** Three numbers cover spec goal 4 and they
answer different questions — quoting the wrong one overstates the result:

- **`cite_pass_rate`** — passing attempts ÷ ALL attempts, retries included.
  This is the number that used to be called `first_attempt_cite_rate`; it
  never was one, and the two diverge exactly when retries happen.
- **`first_try_cite_rate`** — of the citations the answer INTENDED (a
  distinct `chunk_id` + `claim_span` pair), the share that passed on the
  first attempt. This is the genuine first-try measure.
- **`retries_per_citation`** — extra attempts per intended citation. 0 is
  perfect; anything above 0 is the model re-shooting at a claim it already
  tried. It under-counts by design: a retry that rewrites the `claim_span`
  reads as a new citation rather than a retry.

**Reading `retrieves_after_sufficient_mean`.** Never read it without
`retrieves_after_sufficient_n` beside it. The per-query value only exists
for queries where the retrieved text eventually contained every key fact,
so the population is decided by the run's own success — a run that finds
the facts on 20 of 31 queries averages over 20 where its baseline averaged
over 5. `compare_agent_runs.py` withholds the better/worse arrow and prints
a warning whenever that population moved between two runs.

**Filter/corpus-parameter usage counts** (`retrieve_calls_with_filters`,
`filtered_retrieve_rate`, `filter_dimension_counts`,
`retrieve_calls_with_intent`, `retrieve_calls_with_top_k`,
`deep_dive_calls`) are informational and carry **no** better/worse arrow.
A filter is right or wrong depending on the question, and scoring filtering
as good in itself would push the agent to filter itself out of the answer.

`score_agent_run.py` is free and re-runnable — it only reads transcripts,
so a scoring-logic improvement can be re-applied to every historical run
without spending another cent. It writes `scores.json` (machine-
readable, one row per query plus an aggregate summary) and `scores.md`
(a table + a hygiene-flags section for any query with narration hits, a
token leak, or a false refusal). `agent_transcript.py`'s reader degrades
a truncated or corrupt transcript file to a synthetic `_error` record
instead of raising, so one bad write (this project has documented flaky
writes to the shared network drive) costs one query's row, not the
whole scoring run.

`judge_agent_run.py` calls a separate judge model (default
`z-ai/glm-5.2` — see docs/superpowers/investigations/2026-08-02-judge-model-comparison.md)
against the prompt in `agent_judge_prompt.md`. The judge extracts the
answer's load-bearing claims and says whether each is backed by a
verified citation; `compute_citation_scores()` then derives
claim-coverage precision/recall FROM the judge's claim list and the
transcript's own citation count — the judge's own arithmetic is never
trusted. A malformed or non-JSON judge reply becomes one `judge_error`
row, not a run-ending crash.

**The judge is resumable and writes partial progress (2026-08-18).** A
full judge pass is slow (45 separate paid OpenRouter calls) and used to
write `judge.json` only at the very end, so any interruption — a crashed
session, a timebox kill — discarded every already-paid grade and
re-charged them on the rerun. Now it writes a partial `judge.json` after
every grade, and on a rerun it loads the existing `judge.json` and SKIPS
the transcripts already graded (matched by query_id + repeat), so it never
re-pays for work already done. Just re-run the same
`judge_agent_run <run> --workers N` command to resume; a complete run
ends with `"partial": false` in `judge.json`, an interrupted one leaves
`"partial": true`.

`compare_agent_runs.py` diffs a baseline run directory against a
candidate one into a markdown report — what differed (git sha, prompt
sha, tier models, repeats), every mechanical metric with a
better/worse arrow, judge metrics if both sides were judged, and named
per-query regressions in key-fact rate.

**Two guards, one idea: a delta is only meaningful when you know what
differed.** Both refuse by default and both take `--force`:

- **Corpus counts differ** — the corpus is still growing (see STATUS.md),
  so a delta between different corpus sizes measures the corpus.
- **`queries_sha256` differs** — the runs asked different questions. This
  hash covers each query's content (question, key facts, tier, shape), not
  just the id list, because the case that matters most is two `full` runs
  where somebody EDITED a key fact in between: the id lists are identical
  and the whole delta is authoring drift. A run recorded before this hash
  existed carries no `queries_sha256`, which reads as unknown and trips the
  guard. A forced report carries a banner saying it was forced.

Experiment loop for a change to `harness/`, `retrieval/citations.py`, or
`harness/system-prompt.md`:

1. Cheap layer first — Layer 1 `run_eval.py`, and re-score any old
   agent-eval transcripts for free if only the scorer changed.
2. A live `--sets quick,multi,refusal` run against the same query ids as
   your baseline; `compare_agent_runs.py` the two.
3. Before merging: a full run (`--sets quick,multi,deep,refusal`) plus
   `judge_agent_run.py`, then commit the compare report alongside the code
   change so the regression record travels with the diff.

**Results-committing policy.** Raw transcripts embed full retrieved
chunk text — large, and derived from the corpus rather than from the
change under test — so they stay out of git (see `.gitignore`).
`manifest.json`, `scores.json`, `scores.md`, `judge.json`, and any
`compare-*.md` report ARE committed: they're the derived regression
record a future diff needs, at a fraction of the size.

**No live baseline run has happened yet** — the harness above is built
and unit-tested (transcripts, scoring, and the judge are all exercised
against synthetic fixtures) but has never been pointed at a real
OpenRouter key. The acceptance step for whoever runs the first one is
in STATUS.md.

## Defending a weak transcript (`defend_agent_run.py`)

When a query scores poorly on the mechanical scorer, or the LLM judge
hands it a bad ranking, it is often worth letting the model DEFEND its
output before treating the score as truth. A defense frequently
uncovers a *faulty eval* rather than a bad model — a checked fact that
was actually present, a citation that genuinely supported a claim the
judge flagged as uncovered. This tool automates exactly that loop, and
it costs money (real OpenRouter calls), so it is opt-in and manual.

```bash
# defend one named query from a finished run
uv run python -m eval.defend_agent_run eval/results/agent/<run> --queries lk-k12-basic-aid-fy2026

# defend every badly-scored/flagged/under-judged query in one go
uv run python -m eval.defend_agent_run eval/results/agent/<run> --all-poorly --workers 8
```

What it does, per target:

1. reads that query's transcript from the run dir,
2. composes the evaluation's feedback for it — from `scores.json`
   (missing key facts, hygiene flags, false refusal) and/or `judge.json`
   (holistic grade, rationale, claims the judge said were uncovered) —
   or an explicit `--feedback` string you supply,
3. drives a **fresh `HarnessSession`** (the production code path, same
   as the run) whose question embeds the original question, the original
   answer, and the feedback, asking the model to *defend or revise* —
   point out where the evaluator is wrong, quoting and citing the
   supporting text, or acknowledge a fair criticism,
4. writes each defense as a normal `<id>-defend-r1.jsonl` transcript
   under `eval/results/agent/defend/<UTC>-<sha>/`, with its **own
   isolated ledger**, so you can `read_transcript` it like any other.

Deliberate non-features, so a defense never fakes a better score: it
does NOT mechanically re-score the defense (a defense has no clean
key-fact target, and re-scoring would read as a second, misleading
result). The deliverable is the justification itself, for a human to
read and judge — exactly the "audit the claim, don't grade on vibes"
ethos. `--workers` fans defenses out in parallel; defaults to serial.
One bad defense never aborts the rest, and model fallbacks are reset
per query, matching every other Layer 2 tool.
