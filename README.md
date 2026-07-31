# Ask the Budget AZ

A Q&A tool over Arizona state budget documents — JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, and the Governor's Executive Budget proposals.

**Audience:** JLBC staff and fiscal analysts (initially). Public-facing access is a possible Phase 4, gated on internal trust metrics.

**The product is auditable retrieval, not chat.** Every claim links to the exact PDF page and bounding box that supports it. Citations are mechanically verified (the cited chunk must exist and contain the quoted text with a sane span); failed citations are visibly stripped rather than silently accepted. A semantic faithfulness verifier (WS3) is designed but not yet built — see STATUS.md.

## Status

**Standalone consolidation Plans 1–4 — ✓ Shipped (2026-07-30/31).** The app
is now a single FastAPI process with embedded LanceDB storage, local ONNX
models, a GUI ingest queue, and an in-process OpenRouter AI Mode. No
Postgres, no Docker, no Voyage, no `.env.local`, no YouCoded. Next up:
Plan 5 (admin/settings UI, packaging, legacy deletion) and the Z13
historical backfill ([`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md)).
**For the canonical, kept-current state see [STATUS.md](STATUS.md).**

**Corpus:** all four publishers (JLBC + Legislature + Gov + AGAO) for
FY 2025 (enacted), FY 2026 (baseline + budget bill), and FY 2027
(baseline + executive budget), plus whatever has been uploaded through the
GUI queue since — live counts come from `/health` and `GET /api/jobs`.
Older FYs backfill through the Z13 run.

For architectural context, read
[`docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`](docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md)
— the consolidation spec that defines the current system. The original
design spec ([`2026-05-04-ask-the-budget-az-design.md`](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md))
still owns the product invariants.

## Running it locally

After cloning, the one-shot setup is:

```bash
bash setup.sh                 # installs deps, builds the SPA
# bash setup.sh --verify      # ...also runs every test suite
```

Then run the app — one process, no keys, no containers:

```bash
( cd webapp && npm run build )   # once, or after webapp/ changes
uv run uvicorn app.main:create_app --factory --port 9300
```

Open http://localhost:9300. Search, fiscal notes, and upload work with
zero API keys. Set `JLBC_DATA_DIR` to point at a non-default corpus
location (dev default `data/insight-data/`); without a corpus the app
still boots and serves fixture search results.

**AI Mode** is optional and needs exactly one key: an OpenRouter key in
`<data_dir>/settings.json` —

```json
{ "provider": { "api_key": "<your-openrouter-key>" } }
```

No key means AI Mode honestly reports `no API key configured`; everything
else keeps working.

## Eval / regression detection

A retrieval-only eval harness lives at [`eval/`](eval/README.md). It
runs in ~30-90 seconds and produces a JSON + Markdown result file
diffable against previous runs — the regression alarm for retrieval
pipeline changes.

**Run it whenever you change** `retrieval/`, `ingest/`, `chunking/`,
or `harness/system-prompt.md`. Commit the resulting
`eval/results/<UTC-ISO>-<git-sha>.{json,md}` files alongside the
change so regressions are visible in PR diffs.

```bash
uv run python -m eval.run_eval
```

This is "Layer 1" — measures retrieval-pipeline regressions, not
end-to-end usefulness to analysts. The
[eval/README.md](eval/README.md) calls out the caveats (lookup
queries were synthesized FROM chunks, so the recall numbers are an
upper bound; trust deltas across runs, not absolute values). Layer 2
(open-ended analyst-query eval with LLM-as-judge or rubric scoring)
is a future workstream — see the README for what it would look like.

Companion tools alongside the runner:
- `uv run python -m eval.calibrate_refusal` — sweeps refusal
  thresholds against the most recent result and reports refusal
  precision, recall, and retrieval pass-rate at each. Useful when the
  rerank model changes or the corpus shifts; the runtime threshold is
  `REFUSAL_THRESHOLD` in `harness/constants.py`.
- `eval/refresh_chunk_ids.py` and `eval/synthesize_queries.py` are
  **UNPORTED to LanceDB** — both still import the retired Postgres
  `db.connection` and will crash. Don't run them until they're ported.

## Moving to a new device

Everything is in this single git repo. To launch on a fresh device:

```bash
# Prereqs (install once per device): node 20+, npm, python 3.12, uv
git clone https://github.com/itsdestin/ask-the-budget-az-dev.git
cd ask-the-budget-az-dev
bash setup.sh
```

What setup.sh does NOT bring across (copy these from a working machine
or the shared drive):

1. **The LanceDB corpus** — the whole `data/insight-data/` directory (the
   `lancedb/` folder AND `documents.json` — the sidecar file is what lets
   the PDF viewer locate sources; without it search still works but PDFs
   won't open, visible as `documents_metadata: 0` on `/health`).
2. **`data/cached-pdfs/`** — the PDFs the viewer streams from
   (re-downloadable from public URLs if lost).
3. **`<data_dir>/settings.json`** (optional) — only if AI Mode should work
   on the new machine. Carries the OpenRouter key, tier→model map, admin
   username, and spend limits. Without it the app runs fine and AI Mode
   reports `no API key configured`.

Nothing else travels. There is no `.env.local`, no Postgres volume, no
Docker, and no YouCoded/Claude Code dependency on any path.

For the current state of every feature + the open-issues list, see [STATUS.md](STATUS.md).

## Architecture in one paragraph

The app is a single FastAPI process (`app/`, port 9300) serving a built
Vite/React SPA (`webapp/`) — home, budget search, fiscal notes, upload,
and AI Mode chat. Storage is embedded LanceDB (`store/`) with local ONNX
models on CPU (`snowflake-arctic-embed-m` embeddings,
`ms-marco-MiniLM-L-12-v2` reranker; refusal threshold 1.9 in
`harness/constants.py`). Ingest is a GUI upload → background queue
(`ingest/`) → MinerU extract → chunk → embed → LanceDB write. AI Mode is
an in-process OpenRouter tool loop (`harness/`; prompt at
`harness/system-prompt.md`) that must call `retrieve()` before answering
and emits verified citations per claim — chat thread with citation chips
and a side-panel PDF viewer. Search, fiscal notes, and upload need zero
API keys; one OpenRouter key in `<data_dir>/settings.json` unlocks AI
Mode. Corpus + settings live on the shared drive (`JLBC_DATA_DIR`).
Legacy trees (`web/`, `mcp-server/`, `db/`, the old `retrieval/` sidecar
modules) remain in-tree unused pending Plan 5 deletion.

## Repos in this project

One repo: `ask-the-budget-az-dev` (this). The once-planned
`ask-the-budget-az-companion` split died with the standalone
consolidation — the standalone app IS the companion.

## Quick links

- **[Current status + open issues](STATUS.md)** — the canonical state of the project
- **[Standalone consolidation spec](docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md)** — the current architecture (S1–S21, Invariants 7–8, gates G1–G3)
- Plan docs: [Plan 1 — storage/retrieval](docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md) · [Plan 2 — app shell](docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md) · [Plan 3 — ingest](docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md) · [Plan 4 — AI Mode](docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md) · [recency ranking](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md)
- Active handoff: [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md) — Z13 backfill + recency calibration
- [Workspace conventions](CLAUDE.md)

Historical (retired architectures; record only):

- [Original design spec](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — invariants live on; architecture superseded
- [v1 decisions doc](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c
- [Citation-tool schema](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — `retrieve()` / `cite()` shape (semantics carried into `harness/tools.py`)
- Phase 1a → Phase 1b hand-off contract: [`data/chunks/MANIFEST.md`](data/chunks/MANIFEST.md)
- [Phase 1b plan](docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md) · [Phase 1c plan](docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md)
- Retired Budget MCP server: [`mcp-server/README.md`](mcp-server/README.md)
- Phase 0 findings memo: [`docs/superpowers/investigations/2026-05-06-phase-0-findings.md`](docs/superpowers/investigations/2026-05-06-phase-0-findings.md)
- Chunk-shape decisions: [`docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md`](docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md)
- Source-data model: [`docs/superpowers/investigations/2026-05-06-data-model.md`](docs/superpowers/investigations/2026-05-06-data-model.md)

## Why this exists

Fiscal analysts spend significant time finding the right line item across many heterogeneous documents that name the same program differently and present numbers in different formats. The hard part isn't summarizing — it's *locating with provenance*. This tool tries to accelerate that work without sacrificing the rigor analysts need.
