# Handoff: Execute Plan 3 — Ingest (Upload GUI, Queue, Fiscal-Note Corpus)

You are executing a pre-approved implementation plan in `ask-the-budget-az-dev`.
The design is settled — do not re-litigate it; the spec records every decision.

## Read first (in order)

1. `STATUS.md` (auto-loaded) — Plans 1 and 2 shipped; read both ship sections
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S6, S10, S17, Invariant 8, ingest section
3. `docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md` — YOUR plan (15 tasks). Its **Ground truth** block cites exact shipped signatures/gotchas from the 2026-07-30 codebase review — treat those as binding facts, verify against the code as you go.

## What you're building

Colleagues upload PDFs/DOCX in the GUI → persistent background queue runs
MinerU → chunking → stamping → local embedding → LanceDB, with progress,
crash-resume, single-writer locking, and S17 pre-write snapshots. The
fiscal-note corpus gets populated and refreshable from azjlbc.gov. Postgres/
Docker leave the ingest path entirely.

## Setup

```bash
cd ~/ask-the-budget-az-dev && git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/plan3-ingest -b plan3-ingest
cd ~/ask-the-budget-az-worktrees/plan3-ingest
```

Requirements: `uv`, Node 20+ (webapp tests/build), the dev LanceDB corpus at
`data/insight-data/` (already on this machine), MinerU installed via the
project venv (`uv run mineru --version` should work). No Docker, no
DATABASE_URL, no API keys needed.

## Execution

Invoke `superpowers:subagent-driven-development`; work tasks in order; TDD
every task; commit per task. The plan deliberately reuses audited existing
callables (`chunk_doc`, `EntityStamper`, `make_doc_id`, dispatcher, readers,
`LocalEmbedder`, `write_documents_sidecar`) — do not reimplement what the
REUSE list names.

## PARALLEL-SESSION CONTRACT (important)

A second session is concurrently executing Plan 4 (AI Mode) on branch
`plan4-ai-mode`. File ownership is spelled out in both plans' contract
blocks. Yours: `ingest/**`, `chunking/**`, `store/**` (additive),
`app/routes/upload.py|jobs.py|fiscal_notes.py`, `webapp/src/pages/Upload.tsx`,
the FiscalNotes **rail search block only**, `eval/**`.

Do NOT touch: `harness/`, `retrieval/citations.py`, `app/routes/conversations*|pdf|documents`,
`webapp/src/chat/**`, `webapp/src/pdf/**`, `Search.tsx`, `Home.tsx`,
`mcp-server/system-prompt.md`.

Shared append-only points (expect trivial keep-both merges): `app/main.py`
include_router lines, `App.tsx` routes, `Header.tsx` NAV_ITEMS, `api.ts`,
`app.css` (own labeled block), `STATUS.md` (own section, final task only).
Python deps: NONE new (Plan 4 adds httpx; don't touch pyproject/uv.lock).

## Hard rules

- Invariant 8 (public-record-only notice + required checkbox) is not
  optional polish — it gates the upload endpoint server-side (400).
- The write phase ALWAYS runs: ingest lock → S17 snapshot → delete_doc →
  upsert → build_fts_index → optimize → documents.json merge. Never skip
  the FTS rebuild (new rows are invisible to BM25 without it).
- Honest latency copy in the UI: big books process overnight on office
  CPUs. Do not promise minutes.
- Run `uv run python -m eval.run_eval` at the end (ingest touches the
  corpus path — CLAUDE.md rule) and commit the results.
- `bash setup.sh --verify` + `cd webapp && npx vitest run` green before merge.

## Done looks like

All 15 tasks committed; a real PDF uploaded through the GUI reaching
`live` and searchable with a real title; one live fiscal-note refresh
ingesting real note PDFs; fiscal-note eval baseline committed; STATUS.md
updated; branch merged `--no-ff` + pushed; worktree removed; short report
(what shipped, corpus counts, deviations, follow-ups).
