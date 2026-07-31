# Handoff: AI Mode Hardening — S22 prompt caching + S23 quote validation

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, Python
venv at `.venv`). Two spec decisions are already approved; implement them.

## ⚠ A BACKFILL IS RUNNING RIGHT NOW — read this first

Three detached processes (app server on :9300, orchestrator, maintainer) are
ingesting documents continuously. **Do not disturb them.**

- **DO NOT touch:** `ingest/`, `store/`, `chunking/`, `eval/`, `data/`,
  `~/backfill-scripts/`, `~/backfill-progress.log`, the running server, or
  `pyproject.toml` / `uv.lock`.
- **DO NOT run** `eval.run_eval`, MinerU, or anything CPU-heavy — it competes
  with the backfill and the corpus is changing under you, so eval numbers would
  be meaningless anyway.
- **DO NOT restart the app server.** Your changes take effect at the next
  natural restart; that is fine and expected.
- Use `.venv/bin/python -m pytest ...` directly. Do **not** run `uv sync` or
  `uv run` in a worktree — it provisions a second multi-GB venv and fights for
  the uv cache.

Your files (`harness/`, `retrieval/citations.py`) are completely disjoint from
the ingest path, which is why this work is safe to do now.

## Read first

1. `STATUS.md` — especially "Standalone consolidation — Plan 4 shipped" and the
   Plan 5 follow-ups list.
2. Spec decisions **S22** and **S23** in
   `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`.
3. `docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — the
   as-shipped harness contracts.

## What to build

### S22 — prompt caching (the single biggest cost lever in the app)

The system prompt renders at ~40 KB (~13.5K tokens) and is resent on **every
step** — up to 50 steps in one Deep Research turn — while every candidate model
prices cache reads ~10× below input.

Requirements:
- The request prefix (system prompt + tool schemas) must be **byte-identical
  across steps and turns**. No timestamps, no per-turn content, nothing dynamic
  ahead of the conversation messages. Dynamic context belongs in user/tool
  messages. **Add a test that pins this** — render the prefix twice under
  different conditions and assert equality; that test is what stops a future
  edit from silently destroying cache hits.
- Send `cache_control` breakpoints through OpenRouter for models that require
  explicit marking (Anthropic-style); rely on implicit prefix caching elsewhere
  (OpenAI/DeepSeek/Moonshot-style).
- Record `cached_tokens` from the usage payload on each ledger row. Billed cost
  already reflects the discount (the ledger logs OpenRouter's exact cost), so
  this is for visibility, not arithmetic.
- Context-window truncation breaks the prefix when it fires. That is accepted
  and rare — note it in a comment rather than engineering around it.
- Acceptance: a multi-step turn shows nonzero cache reads in usage and per-step
  cost visibly drops after step 1. You cannot verify this without a live key —
  if none is configured, build it, test the prefix-stability property, and say
  plainly in your report that live verification is outstanding.

### S23 — normalization-tolerant quote validation

Models emit quotes that differ from chunk text only by whitespace, smart quotes,
dashes, or casing. Exact-substring validation rejects them as "quote not found",
burning retry round-trips on citations that are actually faithful.

Requirements:
- In `retrieval/citations.py`, add a fallback **after** exact match fails:
  normalized matching (NFKC, whitespace collapse, smart-quote/dash folding,
  case-insensitive) with an **index map back to the original chunk text**.
- `resolved_span_start` / `resolved_span_end` must ALWAYS reference original
  offsets — PDF bbox highlighting and the cited-text panel depend on it. This is
  the requirement most likely to be got subtly wrong; test it explicitly with a
  quote whose normalized and original offsets differ.
- The webapp already solves this exact problem client-side in
  `webapp/src/chat/citation-extract.ts` (`normalizeForMatch` + `indexMap`).
  **Port its semantics** rather than inventing a second dialect.
- Ambiguity rejection (quote appearing multiple times) still applies
  post-normalization.
- Validation becomes formatting-tolerant, **never semantically looser** —
  Invariant 2 is unchanged. Say so in a comment.
- Add the prompt nudge in `harness/system-prompt.md`: quote SHORT, distinctive
  spans copied exactly.

## Method

- Worktree: `git worktree add ~/atb-worktrees/ai-hardening -b ai-hardening origin/master`
- TDD, commit per logical unit, WHY comments on non-obvious decisions (CLAUDE.md
  rule — Destin is non-technical and relies on them).
- Run only the relevant suites: `tests/test_harness_*.py`,
  `tests/test_citations_module.py`, plus anything you add.
- Merge `--no-ff` to master and push. Remove the worktree.

## Report

What shipped, test evidence, whether S22 could be verified live, any place the
webapp and server normalizers could still diverge, and anything you found that
belongs on the Plan 5 list.
