# Handoff: Plan 5 Session A — Admin & Settings + Resilience (Tasks 1–13)

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, venv at
`.venv`).

## Read first

`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md` —
**the whole thing**, especially the **Ground truth** block (14 binding facts;
getting one wrong produces a plausible change that breaks something real), the
frozen **API contracts**, and the **parallel-execution contract**. Then
`STATUS.md` for current state. Do not read the phase plans for status — they
are historical and were never updated as features shipped.

## Your scope

**Tasks 1–13.** Track 1 (admin identity, ledger breakdown, settings API,
OpenRouter catalog, model fallback + notices, corpus/backups, usage endpoints,
Admin page, Settings page) and Track 2 (per-machine config, health ladder,
repair screen, admin lockout recovery).

You own `app/`, `harness/`, `store/` (additive only), `webapp/src/`, `setup.sh`.

**Do NOT touch:** `packaging/` (Session B), `docs/HANDBOOK.md` and
`scripts/jlbc_memo.py` (Session C), `ingest/`, `chunking/`, `eval/`.

**Do NOT do Track 4 (tasks 18–20).** Deletion and the remaining ingest defects
come after your tracks land, and Task 20 touches the live ingest path.

## ⚠ A BACKFILL IS RUNNING

Three detached processes (app server on :9300, orchestrator, maintainer) are
ingesting continuously. Editing files does not affect a running Python process
— your changes land at the next natural restart, which is the intended path.

- **DO NOT restart the app server, orchestrator, or maintainer.**
- **DO NOT touch:** `data/`, `~/backfill-scripts/`, `~/backfill-progress.log`,
  `pyproject.toml`, `uv.lock`, or the main `.venv/`.
- **DO NOT run** `eval.run_eval` or MinerU — CPU contention, and the corpus is
  moving under you, so the numbers would be meaningless anyway.
- Test with `.venv/bin/python -m pytest ...` directly. Never `uv run` in a
  worktree — it provisions a second multi-GB venv and fights for the uv cache.

You WILL edit `store/config.py` (Task 10) and `app/main.py`. That is fine —
the running process already has its code loaded.

## Method

- Worktree: `git worktree add ~/atb-worktrees/plan5-a -b plan5-a origin/master`
- TDD, task by task, in order. Commit per task using the plan's commit message.
- WHY comments on non-obvious decisions — CLAUDE.md rule; Destin is
  non-technical and relies on them to understand his own system.
- Run the suites each task names, plus `cd webapp && npx vitest run` for UI work.
- Merge `--no-ff` to master and push. Remove the worktree.

## The three places most likely to go subtly wrong

1. **API key redaction (Task 3).** Reads must never return the key; writes take
   a `"__unchanged__"` sentinel. Both failure modes are silent — a leaked key
   looks fine until it's in a screenshot, a clobbered one looks like "AI Mode
   randomly stopped working" a week later. Both get their own test.
2. **Model fallback is a runtime override, NOT a settings write (Task 5).**
   Three machines hitting one dead model would otherwise stage three concurrent
   writes to one `settings.json` on an SMB share.
3. **Lockout recovery must fail OPEN (Task 13).** A corrupt settings file
   already degrades to "admin claimable" — keep that, and preserve the corrupt
   bytes before overwriting them, because they may hold the only recoverable
   copy of the API key.

## Report

What shipped per task, test evidence, anything in the plan that turned out to
be wrong about the codebase (say so plainly — the plan was written against a
moving master), and anything you think belongs in the handbook that Session C
would not know to write.
