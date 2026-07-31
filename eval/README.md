# Eval Harness — Layer 1 (Retrieval Regression Detector)

This eval measures **retrieval pipeline health** — chunking, BM25,
dense embeddings, RRF fusion, and Voyage rerank. It does NOT measure
end-to-end usefulness to analysts. Read "What this measures (and
doesn't)" before quoting the numbers.

Layer 2 (an end-to-end agent eval that scores faithfulness, citation
quality, and answer usefulness against open-ended analyst questions)
is a separate workstream, deferred until WS3 (the faithfulness
verifier) ships. See `docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md` for the original spec.

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
queries' phrasing was guided by the chunks' vocabulary, so today's
86% recall@5 is an **upper bound**, not a representative number.
Real-world questions ("spending on homelessness projects?", "actual
expenditures of opioid monies?") would hit lower numbers because real
queries don't pre-align with chunk vocabulary. Don't quote 86% as
"the system's recall" — quote it as "today's Layer 1 regression
score" and focus on deltas, not absolutes. A future Layer 2 eval will
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

Chunk boundaries can change during ingest. The historical fixer for
that is `eval/refresh_chunk_ids.py` — it walks queries.yaml, finds
successor chunk_ids for any entries whose chunk_id no longer exists,
and writes the YAML back in place (anchor-text match preferred, cosine
similarity fallback).

**It is UNPORTED to LanceDB** — it still imports the retired Postgres
`db.connection` and will crash. Until it's ported, stale chunk_ids
after a re-ingest have to be repaired by hand (or the script ported
first).

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
−10..10), not the old Voyage 0..1 scale — any prose you find pointing
at a 0.65 threshold in `mcp-server/system-prompt.md` describes the
retired pre-consolidation stack. **The calibration output's recall
number is the load-bearing one**: if recall is low at every threshold,
the retrieval-layer mechanism can't reliably refuse the failure modes
in your eval set — investing in a query classifier or faithfulness
verifier will be much higher leverage than tweaking the threshold.

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
| `results/` | Git-tracked result files (one JSON + one MD per run) |

## Windows note

All three CLI tools (run_eval, refresh_chunk_ids, calibrate_refusal)
reconfigure stdout to utf-8 at startup so the default Windows cp1252
console doesn't crash on the ✓ ✗ Δ ⚠ glyphs they print.
