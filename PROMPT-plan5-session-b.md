# Handoff: Plan 5 Session B — Packaging & Launcher (Tasks 14–17)

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev`.

**This is the highest-risk work in Plan 5.** Nobody has built the bundle or run
it on a locked-down JLBC machine, and everything else in the project is worth
nothing if the app can't be installed.

## Read first

`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md` —
Ground truth, then **Track 3 (Tasks 14–17)**. Spec decisions **S7** (unzip to
`%LOCALAPPDATA%`, embeddable Python, all model weights pre-bundled) and **S8**
(launcher → Chrome `--app` mode) in
`docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`.

## Do Task 14 FIRST and report the number before building anything

Task 14 is a measurement spike, not a formality. Resolve the full dependency
closure and measure it **with** and **without** `mineru[pipeline]`. Expect
roughly 3–6 GB with it (torch is the bulk) and well under 1 GB without.

Then make the recorded decision in the investigation doc: one bundle, or the
**split distribution** — full bundle (search + AI Mode + ingest) on one or two
designated machines, MinerU-less client bundle everywhere else, with uploads
from a client machine queueing onto the share for the ingest machine's worker
to drain. That is not a retreat: an i5-1245U runs MinerU at 1–3 min/page, so a
210-page book is an overnight job on any office PC regardless.

**Stop and report after Task 14.** Destin decides which shape to build.

## Scope

You own `packaging/` and `docs/QUICKSTART.md` (Task 24, if you get there).

**Do not edit application code.** If the bundle needs an app change — it will,
at minimum a `--data-dir` startup flag — write it down and hand it to Session A
(Task 17 is where those land). Session A owns `app/`, `harness/`, `store/`,
`webapp/src/`, `setup.sh`.

## ⚠ A BACKFILL IS RUNNING

App server on :9300, plus an orchestrator and maintainer. **Do not restart
them.** Do not touch `data/`, `~/backfill-scripts/`, `pyproject.toml`,
`uv.lock`, or the main `.venv/`. Build your measurement venv somewhere
disposable. Do not run MinerU or the eval.

## The hard part is Windows

The Z13 is Linux. A Linux dependency closure is a useful proxy for *size* but
proves nothing about whether the bundle *runs* on a locked-down Windows PC with
no admin rights and no Python installed. Say clearly in your report which of
your findings are measured on Windows and which are inferred from Linux — the
acceptance criterion for Task 15 is **the server starting with the network
cable unplugged on a machine that has never had Python**, not a successful zip.

## Method

- Worktree: `git worktree add ~/atb-worktrees/plan5-b -b plan5-b origin/master`
- Task 14 → report → wait for the shape decision → Tasks 15–17.
- Merge `--no-ff`, push, remove the worktree.

## Report

The two measured sizes, your recommendation on one-bundle vs split, what you
verified on Windows versus inferred, and an honest read on whether S7's
"first run downloads nothing" is achievable with MinerU in the bundle.
