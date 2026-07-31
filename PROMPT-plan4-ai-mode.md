> **✓ SHIPPED** (see STATUS.md "Standalone consolidation — Plan 4 shipped").
> Historical handoff — do not execute.

# Handoff: Execute Plan 4 — AI Mode (OpenRouter Harness, Tools, Chat UI Port)

You are executing a pre-approved implementation plan in `ask-the-budget-az-dev`.
The design is settled — do not re-litigate it; the spec records every decision.

## Read first (in order)

1. `STATUS.md` (auto-loaded) — Plans 1 and 2 shipped; read both ship sections
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S2, S3, S9, S15, S16, S19, Invariants 7 + 8
3. `docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — YOUR plan (13 tasks). Its **Ground truth** block cites exact contracts from the 2026-07-30 codebase review (ProviderEvent SSE shapes, tool schemas, the two known bugs to fix) — binding facts; verify against the code as you go.

## What you're building

A Python OpenRouter tool-loop harness (`harness/`) with the four corpus
tools + `create_document` as in-process functions, Standard/Deep-Research
tiers with the cost ledger and per-user limits, SSE conversation routes,
and the existing chat/citation/PDF-viewer surfaces ported from `web/`
into `webapp/` behind an AI Mode toggle on both corpus pages.

## Setup

```bash
cd ~/ask-the-budget-az-dev && git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/plan4-ai-mode -b plan4-ai-mode
cd ~/ask-the-budget-az-worktrees/plan4-ai-mode
```

Requirements: `uv`, Node 20+. All harness tests run against mocked
transports — no API key needed until the final E2E task (Destin supplies
a temporary OpenRouter key + tier models in `data/insight-data/settings.json`
at that point; ask when you get there).

## Execution

Invoke `superpowers:subagent-driven-development`; work tasks in order; TDD
every task; commit per task. The webapp port tasks carry the OLD test
suites as the fidelity gate — ported logic must pass the ported tests
unmodified (behavior assertions, not classnames).

## PARALLEL-SESSION CONTRACT (important)

A second session is concurrently executing Plan 3 (ingest) on branch
`plan3-ingest`. File ownership is in both plans' contract blocks. Yours:
`harness/**`, `retrieval/citations.py`, `app/routes/conversations.py|pdf.py|documents.py`,
`webapp/src/chat/**`, `webapp/src/pdf/**`, `Search.tsx`, `Home.tsx`,
FiscalNotes **head region only** (AI toggle), `harness/system-prompt.md`.

Do NOT touch: `ingest/**`, `chunking/**`, `store/**`,
`app/routes/upload.py|jobs.py|fiscal_notes.py`, `Upload.tsx`, the
FiscalNotes rail block, `eval/**`.

Shared append-only points (trivial keep-both merges): `app/main.py`
include_router lines, `App.tsx` routes, `api.ts`, `app.css` (own labeled
block), `STATUS.md` (own section, final task only). Python deps: `httpx`
ONLY (`uv add httpx` — expect a uv.lock merge with Plan 3? No: Plan 3
adds no deps; your lock change merges clean).

One import seam: `harness/tools.py` uses `chunking.agency_catalog` (a
Plan 3 module) behind a guarded import with raw-id fallback — build it
with the guard; do not wait on Plan 3.

## Hard rules

- **Invariant 7 is structural**: no tool schema takes paths; no harness
  module imports ingest/write machinery; `create_document` writes ONLY to
  per-user local storage. The plan has tests asserting this — keep them.
- One refusal threshold (1.9) from `harness/constants.py`, injected
  everywhere; the plan's tests assert no stale 0.30/0.65 anywhere.
- SSE contracts: `assistant_text_delta.text` = full accumulated text per
  uuid; `tool_result.output` = JSON-encoded string. The ported reducer
  breaks silently if you violate either.
- Quote-only cites must survive the audit accumulator (known bug being
  fixed — there's a test).
- `bash setup.sh --verify` + `cd webapp && npx vitest run` green before merge.

## Done looks like

All 13 tasks committed; the live E2E script (cited answer with working
chip→PDF-highlight, Deep Research multi-retrieve, honest refusal,
create_document .docx download, real ledger rows, key-removal degradation)
passing with a real key; STATUS.md updated; branch merged `--no-ff` +
pushed; worktree removed; short report (what shipped, deviations,
follow-ups for Plan 5).
