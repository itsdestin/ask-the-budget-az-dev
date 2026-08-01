# CLAUDE.md

Workspace guidance for Claude Code working on **Ask the Budget AZ** — a Q&A tool over Arizona state budget documents (JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, Governor's Executive Budget proposals).

Everything — app code, ingest pipeline, docs, plans, specs, dev tooling — lives in this single repo. The once-planned split into separate `ask-the-budget-az/` / `ask-the-budget-az-companion/` repos died with the standalone consolidation: the standalone app IS the companion.

## Project North Star

The system's job is **retrieval with auditable provenance**. Answer generation is secondary. A fiscal analyst who can't trust a claim won't use the tool twice.

Read `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` before any non-trivial change — it records the current architecture (decisions S1–S21, Invariants 7–8, gates G1–G3). The invariants section of the original design spec (`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`) is still load-bearing. `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md` is historical background only — the YouCoded/MCP architecture it describes was retired by the consolidation.

**Current project status: @STATUS.md** (auto-loaded into every Claude Code session via the `@file` import). `STATUS.md` is the **single source of truth** for what's shipped, what's open, and what's blocked. The Project Phases table below is a stable conceptual map of the phases (their design intent + where each runs) — it intentionally carries **no status**. If you want to describe what's shipped/open/blocked, that data lives in STATUS.md and **only** in STATUS.md. Do not re-record status here; do not infer status from this file. When STATUS.md and CLAUDE.md disagree about status, STATUS.md is right by construction (this file says nothing about status).

## The app in one paragraph

The app is a single FastAPI process (`app/`, port 9300) serving a built Vite/React SPA (`webapp/`) — home, budget search, fiscal notes, upload, AI Mode chat, and an admin page. Storage is embedded LanceDB (`store/`) with local ONNX models on CPU: `snowflake-arctic-embed-m` embeddings + `ms-marco-MiniLM-L-12-v2` reranker (refusal threshold `REFUSAL_THRESHOLD = 1.9` in `harness/constants.py`). Ingest is a GUI upload → background queue (`ingest/`) → MinerU extract → chunk → embed → LanceDB write. AI Mode is an in-process OpenRouter tool loop (`harness/`; system prompt at `harness/system-prompt.md`, rendered by `harness/prompt.py`) that calls `retrieve()` before answering and emits verified citations per claim (constrained agent pattern), with a chat UI, citation chips, and a side-panel PDF viewer. **Search, fiscal notes, and upload work with zero API keys**; one OpenRouter key in `<data_dir>/settings.json` plus a chain of switches (master AI Mode toggle → key → per-mode toggle → model choice) unlocks AI Mode. A custom endpoint must additionally declare both per-million prices — without them there is no spending cap, so it is refused at save time. The admin page is gated on the Windows username; that gate is **not authentication** and must not be described as such. The corpus + settings live on the shared drive (`JLBC_DATA_DIR`, then a per-machine pointer file, then the dev default `data/insight-data/`). No Postgres, no Docker, no Voyage, no `.env.local`, no YouCoded — anywhere. Run it: `cd webapp && npm run build` once, then `uv run uvicorn app.main:create_app --factory --port 9300`. The legacy trees (`web/`, `mcp-server/`, `db/`, `retrieval/api.py` + `bm25/dense/rerank/sql`) were deleted 2026-08-01 — every directory in the repo is live.

## Core Invariants (override anything else when in conflict)

1. **Every claim is auditable.** No claim renders without a passing citation. Citations link to exact PDF page + bbox highlight in the side panel.
2. **Citations are verified, not just emitted.** Post-generation faithfulness check runs on every citation. Failed citations are visibly stripped, not silently dropped or quietly accepted.
3. **Refusal beats hallucination.** When the system can't ground an answer, it says so and shows the raw chunks. High refusal rate = fixable. Confident hallucination = trust-destroying.
4. **No automated action on outputs.** The tool informs analysts; analysts decide. No workflow ever triggers on a system-generated answer.
5. **No "hallucination-free" or "grounded" marketing language.** Stanford's Lexis study (2024) is the canonical reason. Honest about limits or we don't ship.
6. **Internal first, public later, never until earned.** Phase 4 (public) is gated on hard metrics defined in the spec. Not vibes.

## Working Rules

**Never touch a running production deployment to debug it.** All testing happens against a local dev instance or a deliberately-isolated test environment.

**Always sync before working.** Before any change, plan, or investigation:
```bash
cd <repo> && git fetch origin && git pull origin master
```

**Use worktrees for non-trivial work.** Any work beyond a handful of lines must be done in a separate git worktree (or use the Agent tool with `isolation: "worktree"`). Prevents concurrent Claude sessions from overwriting each other. Worktrees live at `~/ask-the-budget-az-worktrees/<branch-name>/`.

**Annotate non-trivial code edits with a WHY comment.** Destin is a non-developer relying on comments to understand what code does and why. Example: `// Strip citation chip when faithfulness check returns < 0.7 — better to show "no source" than fake confidence.`

**"Merge" means merge AND push.** Don't stop at a local merge.

**Verify cross-cutting changes on both the retrieval and citation paths.** A change to chunking can break citations downstream. A change to the LLM prompt can quietly tank the eval set. Run the eval set whenever the retrieval pipeline or LLM prompt changes.

**Pushing to master green-lights closing the dev server.** If you started a local dev server to verify a change, shut it down once the commit lands on `origin/master`. Don't leave orphan processes.

**Run the eval after any change to `retrieval/`, `ingest/`, `chunking/`, or `harness/system-prompt.md`.** Command: `uv run python -m eval.run_eval`. Takes ~30-90 seconds; commit the resulting `eval/results/<...>.{json,md}` files alongside the code change so regressions are visible in PR diffs. The refusal threshold lives in `harness/constants.py` (`REFUSAL_THRESHOLD`), not in the prompt. (`eval/refresh_chunk_ids.py` is unported — it still imports the retired Postgres `db.connection` and will crash; do not run it.)

**Clean up worktrees after merging.** `git worktree remove <path>` then `git branch -D <branch>`. Stale worktrees confuse future sessions.

**Sample primary sources go in `samples/raw-<format>/` and are committed.** When the user uploads a primary-source document (legislative bill DOCX, agency report, etc.) that can't be auto-fetched from a public URL the way JLBC PDFs can, drop it under `samples/raw-<format>/` (e.g. `samples/raw-docx/`) and commit it. These files are load-bearing test fixtures for the chunking/retrieval suites; treating them as gitignored runtime data means they're lost on every worktree create / fresh clone, and the user has to re-upload. PDFs are different — they live under `samples/raw-pdfs/` (gitignored) because the DownloadCache fetches them from public URLs on demand.

## Workspace Layout

One repo, one process. The live directories:

| Directory | What it is |
|-----------|------------|
| `app/` | FastAPI app server (port 9300) — API routes + serves the built SPA |
| `webapp/` | Vite + React SPA — home, budget search, fiscal notes, upload, AI Mode chat |
| `harness/` | AI Mode — in-process OpenRouter tool loop, settings, spend ledger, system prompt |
| `store/` | Embedded LanceDB storage layer + local ONNX model wiring |
| `ingest/` | GUI ingest queue — jobs, SMB-safe lock, worker, MinerU runner, LanceDB writer |
| `chunking/` | Per-publisher extractors + chunkers (Phase 1a lineage; still the live chunking path) |
| `retrieval/` | Retrieval pipeline + citation validation — all live |
| `eval/` | Layer 1 retrieval eval harness |
| `packaging/` | Windows bundle builder + launcher (Plan 5 Track 3) |
| `docs/` | Specs, plans, investigations, decisions, reference material |

**Every directory above is live code.** The retired pre-consolidation trees — `web/` (Next.js UI), `mcp-server/` (Budget MCP server), `db/` (Postgres) and the dead `retrieval/` modules (`api.py`, `bm25.py`, `dense.py`, `rerank.py`, `sql.py`) — were deleted in Plan 5 Track 4 on 2026-08-01. They live in git history; `git log --diff-filter=D -- web/` finds the deletion. Comments elsewhere in the tree that cite a `web/…` path as provenance ("ported from web/components/ChatThread.tsx") resolve against that history and are not stale references to fix.

## Active handoffs

Long-running handoff prompts that may need to be picked up live as standalone files at the repo root. See `STATUS.md` for which handoffs are active vs. done.

- [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md) — **ACTIVE** — historical-year corpus backfill + recency-ranking calibration, run on the Z13 Linux machine.
- `PROMPT-plan1-storage-retrieval.md`, `PROMPT-plan2-app-shell.md`, `PROMPT-plan3-ingest.md`, `PROMPT-plan4-ai-mode.md`, `PROMPT-volume-ingest.md` — retired/shipped historical records. Do not execute.

## Project Phases

This table is a **conceptual map** of the phases — what each phase IS and where it runs. Status (closed, in-progress, blocked) is intentionally absent; that data lives in `STATUS.md`.

| Phase | What it is | Where it runs |
|---|---|---|
| **Phase 0 — Investigation** | Per-doc-type extractor routing, 157-agency canonical catalog, JLBC four-layout structure mapping, chunk-shape decisions D1–D7. | Destin's machine |
| **Phase 1a — Ingest + chunking** | Per-publisher extractor + chunking pipeline. Hand-off contract at `data/chunks/MANIFEST.md`. | Destin's machine |
| **Phase 1b — Storage + retrieval** | Postgres + pgvector + ParadeDB hybrid pipeline (D2 array agency stamping). BM25 + dense + RRF + Voyage rerank-2.5. **Superseded by Standalone consolidation Plans 1–4 (see STATUS.md)** — storage is now embedded LanceDB + local ONNX models. Plan at `docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md` (historical). | Destin's machine |
| **Phase 1c — Synthesis + UI** | Budget MCP server (`mcp-server/`) + FastAPI retrieval sidecar (`retrieval/api.py`) + Next.js chat UI (`web/`), hard-depending on a running YouCoded instance. **Superseded by Standalone consolidation Plans 1–4 (see STATUS.md)** — synthesis is now the in-process `harness/` OpenRouter loop inside `app/`. Plan at `docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md` (historical). | Destin's machine + running YouCoded |
| **Standalone consolidation — Plans 1–5** | Replaces the 1b/1c architecture and absorbs Phase 2's companion goal: embedded LanceDB + local models (Plan 1), one FastAPI app + Vite SPA (Plan 2), GUI ingest queue (Plan 3), in-process OpenRouter AI Mode (Plan 4), admin UI + packaging + legacy deletion (Plan 5). Spec at `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`. | Office machines off the shared drive |
| **Phase 2 — Standalone companion + first deploy** | Originally: lift YouCoded PTY/wrapper into a separate process, DOCX viewer + verify mode, free-tier hosting, onboard 2-3 trusted analysts. The companion goal was absorbed by the standalone consolidation; distribution + verify mode remain. | Vercel/Supabase + each analyst's machine |
| **Phase 3 — Internal pilot** | Wider JLBC use. Tier 2 entity resolution. Eval set expansion. | Same |
| **Phase 4 — Public-launch consideration** | Gated on hard metrics in the spec. | Same, plus public host |

## Documentation Structure

- `docs/superpowers/specs/` — design specs, one per major decision area
- `docs/superpowers/plans/` — implementation plans, derived from specs
- `docs/superpowers/investigations/` — research memos, Phase 0 findings, ad-hoc investigations
- `docs/superpowers/decisions/` — decision artifacts that supersede portions of specs/plans (e.g., `2026-05-06-phase-1bc-architecture.md` for the v1 reframe)
- `docs/reference/` — domain primers and reference material (the system-prompt-context primer itself lives at `data/system-prompt-context.md`)
- `.claude/rules/` — auto-loaded rules for specific subsystems (currently empty placeholder — e.g., `live-app-safety.md` once we have a deployed instance)

## Compaction Guidance

When compacting context (`/compact`), always preserve:
- The current task objective and success criteria
- The Core Invariants section above
- Architectural invariants discovered during this session
- File paths of files currently being modified
- Uncommitted work state

Do NOT preserve: full file contents already read, intermediate debugging output, or resolved sub-tasks.
