> **✓ SHIPPED** (see STATUS.md "Standalone consolidation — Plan 1 shipped").
> Historical handoff — do not execute.

# Handoff: Execute Plan 1 — Storage + Retrieval Foundation

You are executing a pre-approved implementation plan in the
`ask-the-budget-az-dev` repo. The design work is done; do not
re-litigate decisions — the spec records them.

## Read first (in order)

1. `STATUS.md` (auto-loaded) — current project state
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — the approved spec (decisions S1–S14, Invariant 7, gates G1–G3)
3. `docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md` — YOUR plan (13 TDD tasks)

## What you're building

Replace Postgres/pgvector/ParadeDB with an embedded LanceDB store and
replace Voyage embed/rerank with bundled local ONNX models (fastembed),
migrate the existing corpus, and pass eval gate G1 — all behind the
unchanged public `retrieve()` API.

## Setup

```bash
cd ~/ask-the-budget-az-dev && git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/plan1-storage-retrieval -b plan1-storage-retrieval
cd ~/ask-the-budget-az-worktrees/plan1-storage-retrieval
```

Requirements on this machine: Docker running (source Postgres for the
migration task), `uv`, network access for one-time ONNX model downloads
(~100 MB total). `VOYAGE_API_KEY` is NOT needed.

## Execution

Invoke `superpowers:subagent-driven-development` and work the plan
task-by-task in order. Every task is TDD: failing test → implement →
pass → commit. Do not skip the "run and verify" steps.

## PARALLEL-SESSION CONTRACT (important)

A second session is concurrently executing Plan 2 (`app/` + `webapp/`)
on branch `plan2-app-shell`. To keep merges trivial:

- Touch ONLY the files in your plan's file-structure table: `store/`,
  `retrieval/`, `scripts/migrate_to_lancedb.py`, `eval/`,
  `mcp-server/system-prompt.md` (threshold line only), your tests,
  `pyproject.toml`/`uv.lock`, `.gitignore` (one line), `STATUS.md`
  (final task only).
- Do NOT create or modify `app/` or `webapp/` — those belong to Plan 2.
- `STATUS.md`: append your own subsection; if it conflicts at merge
  time, keep both sections.
- Merge to master as soon as your plan completes (Plan 2's final task
  is blocked on your merge). "Merge" means merge AND push (`--no-ff`),
  then remove the worktree.

## Hard rules

- **Gate G1 (plan Task 11):** if BOTH candidate embedders land
  recall@5 < 0.70 on the 34-query eval, STOP and report to Destin —
  spec decision S4 gets revisited before any more code is written.
- Run `uv run python -m eval.run_eval` after any retrieval-path change
  (CLAUDE.md rule) and commit the results files with the change.
- Pre-existing uncommitted changes may exist in the main checkout
  (`retrieval/api.py` warmup + `.gitignore`); your plan's Task 9 folds
  the warmup in — do not blindly discard working-tree state you find.
- `bash setup.sh --verify` must be green before merging.

## Done looks like

All 13 tasks committed, eval results showing G1 pass committed,
`STATUS.md` updated, branch merged `--no-ff` to master and pushed,
worktree removed, and a short report: G1 numbers (recall@5/@20, latency
p95), chosen embedder model, new refusal threshold, and any deviations
from the plan.
