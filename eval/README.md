# Eval Harness — Layer 1 (Retrieval)

Pure-retrieval eval. Calls `retrieve()` directly (bypasses MCP and
Claude) so changes to chunking, BM25 weights, rerank config, and
filter logic are measurable in 30 seconds instead of dogfooded.

Layer 2 (end-to-end agent eval with faithfulness scoring) is deferred
until WS3 (faithfulness verifier) ships.

## Running it

After any change to `retrieval/`, `ingest/`, `chunking/`, or
`mcp-server/system-prompt.md`:

```bash
set -a; source .env.local; set +a
uv run python -m eval.run_eval
```

Takes ~30-90 seconds. Output:
- `eval/results/<UTC-ISO>-<git-sha>.json` (machine-readable)
- `eval/results/<UTC-ISO>-<git-sha>.md` (human-readable summary with
  deltas vs. previous run)

Both are committed to git so the history travels with the repo. Diff
two runs with `git diff eval/results/<old>.json eval/results/<new>.json`.

## The query set

`eval/queries.yaml` has ~34 queries (24 lookup + 5 comparison + 5
refusal). Each query carries:
- The question
- One or more expected_chunks (hybrid: chunk_id + dimensions +
  anchor_text)
- Type (`lookup` / `comparison` / `refusal`)

Scoring:
- **Lookup** passes if any expected chunk is in top K (preferring
  chunk_id, falling back to dimensions match).
- **Comparison** passes if ALL expected chunks are in top K.
- **Refusal** passes if retrieval correctly declined (top_score <
  threshold).

## After a re-ingest

Chunk boundaries can change during ingest. Run:

```bash
uv run python -m eval.refresh_chunk_ids
```

This walks queries.yaml, finds successor chunk_ids for any entries
whose chunk_id no longer exists, and writes the YAML back in place
(only when changes are made — no-op invocations don't rewrite the
file, keeping git diffs clean). Anchor-text matching is preferred
(deterministic); cosine similarity is the fallback. Entries that
can't be repaired are flagged for manual review.

## Calibrating the refusal threshold

After the corpus or rerank model changes:

```bash
uv run python -m eval.calibrate_refusal
```

This sweeps candidate thresholds (0.10-0.90) against the most recent
eval result and recommends the one with the best precision/recall
balance. The runtime threshold currently lives in the MCP system
prompt (`mcp-server/system-prompt.md` — search for `refusal_no_retrieval
— top_score < 0.30` and the rules-table reference); updating it means
editing those prompt lines, not flipping a Python constant.

## Adding queries

Two paths:

1. **Re-run the synthesizer to add more (requires Anthropic API key):**
   ```bash
   uv run python -m eval.synthesize_queries --append --lookup 10
   ```
   Adds 10 new lookup queries to the existing set without disturbing
   the existing ones. Costs ~$1 in Anthropic API spend.

   Without an API key in `.env.local`, you can also follow the
   subagent-driven pattern used for the initial set — see the commit
   history around `6e5f907` for an example where chunks were sampled
   into JSON, then a subagent wrote queries.yaml inline.

2. **Hand-write directly in `eval/queries.yaml`:** follow the schema
   in `eval/schema.py::EvalQuery`. Pick a unique `id` like `q-100`,
   write the query and expected_chunks. Run the eval; if your hand-
   written query passes you're done.

## Files

| File | Purpose |
|---|---|
| `queries.yaml` | Ground truth — questions + expected_chunks |
| `schema.py` | Pydantic models for queries + results |
| `scoring.py` | Pure recall + refusal scoring functions |
| `synthesize_queries.py` | One-shot LLM-driven query generator |
| `run_eval.py` | Main runner — calls retrieve(), scores, writes results |
| `refresh_chunk_ids.py` | Post-reingest stale-chunk_id fixer |
| `calibrate_refusal.py` | Threshold sweep + recommendation |
| `results/` | Git-tracked result files (one JSON + one MD per run) |

## Windows note

The runner, refresh tool, and calibration tool print unicode glyphs
(✓ ✗ Δ ⚠) for status. They all reconfigure stdout to utf-8 at startup
so the default Windows cp1252 console doesn't crash on them. If you
hit `UnicodeEncodeError`, your invocation path may not be going
through main() — wrap the call so it does.
