# Handoff: Fix the two handoff-blocking ingest defects

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, venv at
`.venv`). Two defects found during the Z13 backfill will degrade the office
experience **silently** after Destin leaves. Fix both.

## ⚠ A BACKFILL IS RUNNING RIGHT NOW

Three detached processes (app server :9300, orchestrator, maintainer) are
ingesting continuously.

- **DO NOT restart the app server, orchestrator, or maintainer.** Editing files
  does not affect a running Python process — your changes land at the next
  natural restart, which is the intended path. Restarting mid-run risks the run.
- **DO NOT touch:** `data/`, `~/backfill-scripts/`, `~/backfill-progress.log`,
  `pyproject.toml`, `uv.lock`, or the main `.venv/`.
- **DO NOT run** MinerU or `eval.run_eval` — CPU contention, and the corpus is
  moving.
- Test with `.venv/bin/python -m pytest ...` directly; never `uv run` in a
  worktree (it provisions a second multi-GB venv and fights for the uv cache).
- You WILL be editing `ingest/` and `app/main.py`. That is fine — the running
  process already has its code loaded. Just don't restart it.

## Read first

`STATUS.md` → "Known follow-ups (Plan 5 unless noted)". Both defects are the
🔴-marked entries at the top, with the evidence that produced them.

## Defect 1 — `IngestWorker` is built at startup but never `.start()`ed

Only the upload POST route starts the worker pool. On the shared network drive
this means **a colleague's queued job sits untouched until somebody on that
same machine happens to upload something.** Ingest appears hung, with no error
and nothing in the UI to explain it. For a non-technical office this is the
difference between "the tool works" and "the tool is broken and nobody knows
why".

Fix: start the worker in the app factory (there is an `ensure_started(app)`
seam in `ingest/worker.py`). Requirements:

- Starting must be **idempotent** — calling it from both the factory and the
  upload route must not produce two pools.
- It must not break `create_app()` in tests that never intend to run a worker.
  Look at how the existing app tests construct the app (`tests/test_app_server.py`)
  and keep them green without weakening them; add an explicit opt-out if that's
  the cleanest route, but the DEFAULT for a real run must be "the worker runs".
- A machine with an unreachable data dir must still start the app (the health
  ladder should report the problem, not crash on boot).
- Test that a job queued with no upload activity actually gets picked up.

## Defect 2 — `make_doc_id()` collides across report families, silently dropping a document

`make_doc_id()` files `detailed-list-pdf` under "approps" regardless of family,
so a baseline document and an approps document can generate the **same doc_id**;
the second write replaces the first and one document vanishes with no error.

Audited during the backfill: exactly one true collision exists today in 5,320
in-scope book documents — FY2026 Baseline staff directory vs FY2026 Approps
"General Fund and Other Fund Adjustments", both `jlbc-approps-fy2026-508`.

Fix the id scheme so family is part of the identity. **Critical constraint:**
`chunk_id` is `<doc_id>-NNNN` and the existing corpus plus `eval/queries.yaml`
ground truth depend on current ids. **Do not change ids for documents that
already exist** — the fix must apply to the colliding shape only, or be
explicitly versioned. Think this through and explain your choice in the commit
message; a naive rename would invalidate the eval set and orphan live chunks.

Requirements:
- A regression test constructing the exact known collision pair and asserting
  distinct ids.
- A test asserting that ids for existing, non-colliding shapes are UNCHANGED
  (pin a few real ids from `data/insight-data/documents.json`).

## Method

- Worktree: `git worktree add ~/atb-worktrees/ingest-defects -b ingest-defects origin/master`
- TDD, WHY comments (CLAUDE.md rule — Destin is non-technical).
- Run: `tests/test_ingest_*.py`, `tests/test_app_server.py`, `tests/test_upload_route.py`,
  `tests/test_books_route.py`, plus what you add.
- Merge `--no-ff`, push, remove the worktree.

## Report

What changed, test evidence, your reasoning on doc_id backward-compatibility,
and confirmation that you did NOT restart any running process.
