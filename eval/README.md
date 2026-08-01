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
| `refresh_chunk_ids.py` | Post-reingest stale-chunk_id fixer — **UNPORTED: imports retired Postgres `db.connection`, crashes** |
| `calibrate_refusal.py` | Threshold sweep + recommendation (now reports recall) |
| `calibrate_recency.py` | S21 weight sweep — minimal weight that restores recall |
| `chronological.py` | The newest-first order metric (`newest_first_rate`, `mean_fiscal_year_at_k`) |
| `sweep_recency.py` | S21 weight sweep — recall AND chronological order, at every weight |
| `results/` | Git-tracked result files (one JSON + one MD per run) |
| `agent_queries.yaml` | Layer 2 ground truth — open-ended questions + key_facts + shape/subset tags |
| `agent_schema.py` | Layer 2 query schema (`AgentQuery`, `KeyFact`) — `extra="forbid"` |
| `run_agent_eval.py` | Layer 2 runner — drives real `HarnessSession`s, spends money, writes transcripts |
| `agent_transcript.py` | Layer 2 transcript read/write — degrades a truncated file to an error record |
| `agent_scoring.py` | Layer 2 mechanical scoring functions (free) |
| `score_agent_run.py` | Layer 2 scorer CLI — transcripts → `scores.json` / `scores.md` (free) |
| `judge_agent_run.py` | Layer 2 LLM judge CLI — `scores.json`'s companion, costs money |
| `agent_judge_prompt.md` | The judge's system prompt |
| `compare_agent_runs.py` | Diffs two Layer 2 run directories into a markdown report (free) |
| `results/agent/` | Layer 2 run directories — derived artifacts committed, raw transcripts gitignored |

## Windows note

All three CLI tools (run_eval, refresh_chunk_ids, calibrate_refusal)
reconfigure stdout to utf-8 at startup so the default Windows cp1252
console doesn't crash on the ✓ ✗ Δ ⚠ glyphs they print.

## Layer 2 — agent-loop eval (`run_agent_eval.py`)

Everything above is Layer 1: it measures retrieval health only, by
calling `retrieve()` directly. Layer 2 drives the REAL harness session
— the production `HarnessSession` code path, no HTTP server — for a set
of open-ended analyst questions, and measures what Layer 1 structurally
cannot: agent turns, tokens, cost, whether the final answer actually
contains the right key facts, citation discipline (how often a cite
passes verification on the first attempt), and output hygiene (meta-
narration leaks, internal-vocabulary leaks, a leaked download token).
Layer 1 stays the free, fast inner loop for retrieval-only changes;
Layer 2 is the paid outer loop for anything that touches the harness
loop or the system prompt. **Their numbers are not comparable to each
other** — a recall percentage and a key-fact rate measure different
things over different query sets.

**This layer costs real money — every run calls a real model through
OpenRouter.** Rough guide, Standard tier: `smoke` (~10 queries) ≈
$0.15–0.30, `full` (~30 queries) ≈ $0.50–1.50. `dr-probe` (4
Deep Research queries) ≈ $2–3 — Deep Research runs at roughly 40× the
per-query cost of Standard (see the Plan 4 dogfood numbers in
STATUS.md). The LLM judge (`judge_agent_run.py`) is a second, separate
charge on top of a run — budget for it only when running `full`.

Query authoring lives in `agent_queries.yaml`, validated by
`agent_schema.py` (`AgentQuery` / `KeyFact`, both `extra="forbid"` so a
typo'd field name fails the load instead of silently vanishing). Each
query pins a `shape` (lookup / comparison / analyze / memo / refusal /
historical), a `corpus`, a `tier`, zero or more `key_facts` (currency /
string / regex, mechanically checkable in the final answer), and which
`subsets` it belongs to (`smoke`, `full`, `dr-probe`).

Workflow:

```bash
uv run python -m eval.run_agent_eval --subset smoke        # live run, spends money
uv run python -m eval.score_agent_run eval/results/agent/<run>   # free, re-runnable
uv run python -m eval.judge_agent_run eval/results/agent/<run>   # money — full runs only
uv run python -m eval.compare_agent_runs <baseline-dir> <candidate-dir>  # free
```

`run_agent_eval.py` writes one directory per run —
`eval/results/agent/<UTC-ISO>-<git-sha>/` — containing `manifest.json`
(git sha, prompt sha256, tier→model map, corpus row counts — everything
needed to know whether two runs are even comparable), one
`<query_id>-r<N>.jsonl` transcript per (query, repeat) via
`agent_transcript.py`, and `ledger.jsonl`. Use `--repeats N` to sample a
query more than once — **a single run is stochastic**; a small delta
between two single runs is noise, not signal, and `compare_agent_runs.py`
says so loudly whenever either side has `repeats: 1`. `--model` pins the
Standard-tier model for the run without touching `settings.json`.
`--queries` restricts to specific query ids for a quick check on one
failing case.

**The runner writes its OWN ledger, isolated from the office.** Every
eval query runs with `check_limit` stubbed to always-allow and
`record_usage` writing into that run's own `ledger.jsonl` instead of the
shared office spend ledger — an eval run is pre-authorized by the human
who started it, and it must neither be blocked by S19 office limits nor
silently accrue against them. If you're looking for eval spend in the
office usage totals, it deliberately isn't there; add up `ledger.jsonl`
rows (or read `total_cost_usd` in `scores.json`) instead.

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
`anthropic/claude-sonnet-5` — deliberately not the model under test)
against the prompt in `agent_judge_prompt.md`. The judge extracts the
answer's load-bearing claims and says whether each is backed by a
verified citation; `compute_citation_scores()` then derives
claim-coverage precision/recall FROM the judge's claim list and the
transcript's own citation count — the judge's own arithmetic is never
trusted. A malformed or non-JSON judge reply becomes one `judge_error`
row, not a run-ending crash.

`compare_agent_runs.py` diffs a baseline run directory against a
candidate one into a markdown report — what differed (git sha, prompt
sha, tier models, repeats), every mechanical metric with a
better/worse arrow, judge metrics if both sides were judged, and named
per-query regressions in key-fact rate. **It refuses to compare two
runs whose `manifest.json` corpus counts differ** (`--force` to
override) — the corpus is still growing (see STATUS.md), and a delta
between different corpus sizes measures the corpus, not the change
under test.

Experiment loop for a change to `harness/`, `retrieval/citations.py`, or
`harness/system-prompt.md`:

1. Cheap layer first — Layer 1 `run_eval.py`, and re-score any old
   agent-eval transcripts for free if only the scorer changed.
2. A live `--subset smoke` run against the same query ids as your
   baseline; `compare_agent_runs.py` the two.
3. Before merging: a `--subset full` run plus `judge_agent_run.py`,
   then commit the compare report alongside the code change so the
   regression record travels with the diff.

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
