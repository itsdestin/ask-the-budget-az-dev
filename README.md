# Ask the Budget AZ

A Q&A tool over Arizona state budget documents — JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, and the Governor's Executive Budget proposals.

**Audience:** JLBC staff and fiscal analysts (initially). Public-facing access is a possible Phase 4, gated on internal trust metrics.

**The product is auditable retrieval, not chat.** Every claim links to the exact PDF page and bounding box that supports it. Faithfulness is checked at generation time; failed citations are visibly stripped rather than silently accepted.

## Status

**Phases 0, 1a, 1b — ✓ Done** (slice-validated through 2026-05-07). Phase 1c is substantially done; volume ingest pending. **For the canonical, kept-current state see [STATUS.md](STATUS.md).** The phase plans under `docs/superpowers/` capture historical design intent but have not been updated as features shipped.

**Corpus today (2026-05-12):** **382 documents / 7,755 chunks** across all four publishers (JLBC + Legislature + Gov + AGAO) for FY 2025 (enacted), FY 2026 (baseline + budget bill), and FY 2027 (baseline + executive budget). Older FYs and a few in-cycle gaps (FY26 + FY27 approps reports) are not yet ingested — full breakdown in [STATUS.md](STATUS.md). Hand-off prompt for additional ingest at [`PROMPT-volume-ingest.md`](PROMPT-volume-ingest.md).

For architectural context, see [`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md). For the v1 decisions that shape Phase 1b/1c, see [`docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md).

## Running it locally

After cloning, the one-shot setup is:

```bash
bash setup.sh                 # installs deps, brings up Postgres
# bash setup.sh --verify      # ...also runs every test suite
```

Then create `.env.local` at the repo root (Voyage API key required) and start the three runtime processes in separate terminals:

```bash
# 1. FastAPI retrieval sidecar (port 9200) — feeds the Budget MCP server
set -a; source .env.local; set +a
uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200

# 2. Budget MCP server — registers with YouCoded
node mcp-server/scripts/register.mjs    # writes ~/.claude.json; restart YouCoded

# 3. Web UI (port 3000) — Next.js dev server
( cd web && npm run dev )
# Open http://localhost:3000 (requires YouCoded running; reads
# the persisted token from ~/.claude/.remote-tokens.json).
```

### Daily startup (after a reboot or first launch of the day)

Run these in order; each step's success unblocks the next. The
SystemHealthBanner at the top of the chat surfaces problems at the
sidecar layer; the steps below cover everything below it.

1. **Docker Desktop running.** Check the system tray icon. Postgres
   lives in a container — without Docker the sidecar can't connect.
2. **Postgres container up.**
   ```bash
   cd db && docker compose up -d
   ```
3. **Retrieval sidecar (port 9200).** Auto-loads `.env.local`; fails
   fast at startup if `VOYAGE_API_KEY` is missing or Postgres is
   unreachable.
   ```bash
   uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200
   ```
4. **YouCoded running.** Open the YouCoded UI on the device. The
   budget app needs `ws://localhost:9900` reachable.
5. **Web UI (port 3000).**
   ```bash
   ( cd web && npm run dev )
   ```

Open http://localhost:3000. If the SystemHealthBanner says the source
documents service is offline, step 3 didn't succeed — re-run it and
read its stderr for the specific failure reason.

## Eval / regression detection

A retrieval-only eval harness lives at [`eval/`](eval/README.md). It
runs in ~30-90 seconds and produces a JSON + Markdown result file
diffable against previous runs — the regression alarm for retrieval
pipeline changes.

**Run it whenever you change** `retrieval/`, `ingest/`, `chunking/`,
or `mcp-server/system-prompt.md`. Commit the resulting
`eval/results/<UTC-ISO>-<git-sha>.{json,md}` files alongside the
change so regressions are visible in PR diffs.

```bash
set -a; source .env.local; set +a
uv run python -m eval.run_eval
```

This is "Layer 1" — measures retrieval-pipeline regressions, not
end-to-end usefulness to analysts. The
[eval/README.md](eval/README.md) calls out the caveats (lookup
queries were synthesized FROM chunks, so the recall numbers are an
upper bound; trust deltas across runs, not absolute values). Layer 2
(open-ended analyst-query eval with LLM-as-judge or rubric scoring)
is a future workstream — see the README for what it would look like.

Two companion tools live alongside the runner:
- `uv run python -m eval.refresh_chunk_ids` — run after a re-ingest;
  walks `eval/queries.yaml` and repoints any stale chunk_ids at their
  successors (anchor-text match → cosine-similarity fallback).
- `uv run python -m eval.calibrate_refusal` — sweeps refusal
  thresholds against the most recent result and reports refusal
  precision, recall, and retrieval pass-rate at each. Useful when the
  rerank model changes or the corpus shifts; the runtime threshold
  lives in `mcp-server/system-prompt.md` so applying the
  recommendation is a manual prompt edit.

## Moving to a new device

Everything is in this single git repo. To launch on a fresh device:

```bash
# Prereqs (install once per device): docker, node 20+, npm, python 3.12, uv
git clone https://github.com/itsdestin/ask-the-budget-az-dev.git
cd ask-the-budget-az-dev
bash setup.sh
```

What setup.sh does NOT bring across (you must handle these manually):

1. **`.env.local`** — `scp` it from a working machine, or recreate by hand. Voyage API key is mandatory for embeddings + reranking.
2. **The Postgres data** — chunks + embeddings live in `db/data/` (gitignored). Two options:

   ```bash
   # Option A — fast: copy the volume from a working machine.
   scp -r olduser@oldhost:/path/to/ask-the-budget-az-dev/db/data ./db/data
   ( cd db && docker compose restart )

   # Option B — slow: re-run the ingest pipeline. Costs Voyage API calls
   # and several hours. See PROMPT-volume-ingest.md for the hand-off.
   ```

3. **Cached PDFs** (optional) — `data/cached-pdfs/` is also gitignored but regenerable from source URLs by the ingest pipeline.

External dependencies that live OUTSIDE the repo:
- **Docker Desktop** for the Postgres container
- **YouCoded** (or Claude Code) running on the device — provides the LLM session via `ws://localhost:9900`. Not in this repo.

For the current state of every feature + the open-issues list, see [STATUS.md](STATUS.md).

## v1 architecture in one paragraph

v1 is a multi-turn budget Q&A web app on Destin's machine that hard-depends on a running YouCoded instance. The budget app's Node backend talks to YouCoded over `ws://localhost:9900`; YouCoded provides the Claude Code session, Pro/Max OAuth, transcript-watcher, and MCP host. A small Budget MCP server (separate Node process registered with YouCoded) exposes `retrieve(query, filters)` and `cite(...)` tools. Claude in each conversation calls `retrieve()` (constrained agent pattern — system prompt requires it before answering) and emits `cite()` per claim. The budget UI is a chat thread with citation chips and a side-panel PDF viewer. Standalone companion app, DOCX viewer, verify-mode toggle, and multi-analyst distribution all defer to Phase 2.

## Repos in this project

| Repo | Purpose | Status |
|---|---|---|
| `ask-the-budget-az-dev` (this) | Workspace + ingest + retrieval + MCP server + web app (v1 lives here) | Active |
| `ask-the-budget-az-companion` | Standalone companion (lifts YouCoded PTY/wrapper) — only when v2 distributes to analysts who don't run YouCoded | Planned (Phase 2) |

## Quick links

- **[Current status + open issues](STATUS.md)** — the canonical state of the project
- [Design spec](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) (post-2026-05-06 reframe)
- [v1 decisions doc](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c
- [Citation-tool schema](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked `retrieve()` / `cite()` shape
- [Workspace conventions](CLAUDE.md)
- Phase 1a → Phase 1b hand-off contract: [`data/chunks/MANIFEST.md`](data/chunks/MANIFEST.md)
- Phase 1b plan (shipped on slice): [`docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`](docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md)
- Phase 1c plan (in progress): [`docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`](docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md)
- Budget MCP server: [`mcp-server/README.md`](mcp-server/README.md)
- Phase 0 findings memo: [`docs/superpowers/investigations/2026-05-06-phase-0-findings.md`](docs/superpowers/investigations/2026-05-06-phase-0-findings.md)
- Chunk-shape decisions: [`docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md`](docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md)
- Source-data model: [`docs/superpowers/investigations/2026-05-06-data-model.md`](docs/superpowers/investigations/2026-05-06-data-model.md)

## Why this exists

Fiscal analysts spend significant time finding the right line item across many heterogeneous documents that name the same program differently and present numbers in different formats. The hard part isn't summarizing — it's *locating with provenance*. This tool tries to accelerate that work without sacrificing the rigor analysts need.
