# Handoff: Execute Plan 2 — App Server + Search UI Shell

You are executing a pre-approved implementation plan in the
`ask-the-budget-az-dev` repo. The design work is done; do not
re-litigate decisions — the spec records them.

## Read first (in order)

1. `STATUS.md` (auto-loaded) — current project state
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — the approved spec (S1, S9, S12 matter most to you)
3. `docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md` — YOUR plan (13 tasks)

## What you're building

The consolidated app's front door: a FastAPI server (`app/`, port 9300)
serving a Vite/React SPA (`webapp/`) — home shell, budget search page,
and fiscal notes page — ported faithfully from the JLBC Website Revamp
mockup (spec S12: **port, don't redesign**). Tasks 1–11 run against a
stub search provider; Task 12 flips to real retrieval.

## Setup

```bash
cd ~/ask-the-budget-az-dev && git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/plan2-app-shell -b plan2-app-shell
cd ~/ask-the-budget-az-worktrees/plan2-app-shell
```

Requirements: Node 20+, `uv`. The mockup source lives at
`C:\Users\desti\JLBC Website Revamp\` — your plan's Task 1 vendors the
needed files into the repo; everything after that reads only the
vendored copies.

## Execution

Invoke `superpowers:subagent-driven-development` and work the plan
task-by-task in order. Every task is TDD: failing test → implement →
pass → commit. Do not skip the "run and verify" steps. When porting UI
(Tasks 7–10), the vendored mockup files are the source of truth —
copy tokens/markup/behavior, don't reinterpret them.

## PARALLEL-SESSION CONTRACT (important)

A second session is concurrently executing Plan 1 (LanceDB + local
models) on branch `plan1-storage-retrieval`. To keep merges trivial:

- Touch ONLY: `app/`, `webapp/`, `scripts/export_fiscal_notes_snapshot.py`,
  your tests (`tests/test_app_*.py`, `tests/test_search_route.py`,
  `tests/test_fiscal_notes_*.py`, `tests/test_lance_provider.py`),
  `.gitignore` (webapp lines), `STATUS.md` (final task only).
- Do NOT modify `store/`, `retrieval/`, `eval/`, `db/`, `mcp-server/`,
  `pyproject.toml`, or `uv.lock`. No new Python dependencies — FastAPI
  and pytest are already installed; frontend deps go in
  `webapp/package.json` only.
- Do NOT import from `store/` or `retrieval/` before Task 12.
- **Task 12 is gated:** it requires Plan 1 merged to `origin/master`.
  At the Task 11 checkpoint, push your branch, then check
  `git fetch origin && git log origin/master --oneline -5` for Plan 1's
  merge. If it isn't there, STOP at the checkpoint and report — do not
  start Task 12.
- `STATUS.md`: append your own subsection; if it conflicts at merge
  time, keep both sections.

## Hard rules

- Spec S12 is binding: pages must visibly BE the mockup's design
  (verbatim `:root` tokens, same class names where practical), not an
  interpretation of it.
- The API contracts in the plan's file-structure section are frozen —
  Plans 3 and 4 build against them. Don't rename fields.
- `bash setup.sh --verify` plus `cd webapp && npx vitest run` must be
  green before merging.

## Done looks like

All 13 tasks committed (or 1–11 + a checkpoint report if Plan 1 hasn't
merged), the app serving the real corpus at `http://127.0.0.1:9300`
(post-Task-12), `STATUS.md` updated, branch merged `--no-ff` to master
and pushed, worktree removed, and a short report: what shipped, any
plan deviations, and screenshots or a described walkthrough of the
three pages.
