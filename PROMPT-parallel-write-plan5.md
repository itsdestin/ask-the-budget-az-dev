# Handoff: Write Plan 5 — admin UI, packaging, cleanup, handoff gates

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev`. **This is a
documentation task — write the implementation plan, do not implement it.**

## ⚠ A BACKFILL IS RUNNING — but it cannot collide with you

Three detached processes are ingesting documents. You are writing one markdown
file, so the only rules are: **do not touch `data/`, `~/backfill-scripts/`, any
running process, or any source file.** Do not run the eval or MinerU.

## Read first (in this order)

1. `STATUS.md` — the whole file, but especially "What's next", the four
   "Plan N shipped" sections, the live "Z13 backfill" section, and the **Known
   follow-ups (Plan 5 unless noted)** list, which is long and is your primary
   input.
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` —
   decisions **S7** (packaging), **S8** (launcher), **S11/S13/S15/S16/S19**
   (admin surface, provider, tiers, spend limits), **S17** (backup/restore),
   **S18** (share relocation), **S22/S23** (AI hardening), Invariants 7 + 8, and
   gates **G2/G3**.
3. `docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — its
   "Task 8 amendments" block is the as-shipped HTTP contract Plan 5 builds on.
4. The shipped app: `app/routes/`, `webapp/src/pages/`, `harness/settings.py`.
   Plan 5's admin page configures what `settings.py` already stores, and the
   tier explainer copy already lives server-side in `/api/ai/status` so the
   admin page and webapp cannot drift — build on that, don't duplicate it.

## What Plan 5 must cover

- **Admin page** (soft-gated on the admin Windows username): costs per
  user/model/tier; the S15 provider panel (OpenRouter default vs custom
  endpoint, with the caveats stated in the UI); the S13/S16 model pickers, one
  slot per tier, validated against OpenRouter's live catalog and filtered to
  tool-calling-capable models; the S19 spend-limits panel with per-user
  overrides and exemptions; the S17 "Restore last good corpus" action; corpus
  health + ingest queue; admin transfer; log locations.
- **Settings page** for everyone: own monthly usage, AI Mode availability
  explainer.
- **S18 share-relocation repair flow** + the launch health ladder with
  plain-English failure pages.
- **Packaging (S7) and launcher (S8)** — `%LOCALAPPDATA%` bundle with embedded
  Python, prebuilt site-packages, and **all model weights pre-bundled** so first
  run downloads nothing; launcher opens Chrome in `--app` mode with Edge and
  default-browser fallbacks. **Flag this as the highest-risk task in the plan** —
  nobody has yet built the bundle or proved it on a locked-down JLBC PC, and
  MinerU's dependency tree is the hard part.
- **Legacy deletion**: `web/`, `mcp-server/`, `db/`, dead `retrieval/` modules,
  and their test suites — plus removing them from `setup.sh --verify`.
- **AI-Mode hardening S22 + S23** — note that a separate session may already be
  implementing these (see `PROMPT-parallel-ai-hardening.md`); if so, Plan 5
  should reference rather than duplicate them.
- **The defect list from STATUS's follow-ups**, triaged and sequenced. Do not
  just copy it — decide what is handoff-blocking, what is polish, and what
  should be explicitly declined. The 🔴 items (worker auto-start, `make_doc_id`
  collisions, DownloadCache concurrency, the >120 s cross-machine lock-steal
  window) may also be in flight elsewhere (`PROMPT-parallel-ingest-defects.md`).
- **Gates G2 (citation spot-verification corpus-wide) and G3 (cold-start
  install by someone who is not Destin, including the ~10-query human
  search-findability check)**, plus the one-page quickstart the G3 tester
  follows — which must include setting a hard monthly credit limit on the
  OpenRouter dashboard.

## How to write it

Follow the house format of the existing plan docs (`2026-07-30-standalone-plan-3-ingest.md`
is the best model): a Goal/Architecture/Spec header, a file-structure table, a
parallel-execution contract if applicable, then numbered TDD tasks with exact
file paths, real code in every step, exact commands with expected output, and
commit messages. **No placeholders** — "TBD", "add error handling", or "write
tests for the above" without the test code are plan failures.

Save to `docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md`,
commit, push. Then update `STATUS.md`'s "What's next" to point at it.

## Report

The task list with your sequencing rationale, which items you judged
handoff-blocking vs deferrable, anything in the follow-up list you think should
be explicitly declined rather than built, and your honest read on the packaging
risk.
