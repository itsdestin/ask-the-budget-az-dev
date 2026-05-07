# Ask the Budget AZ

A Q&A tool over Arizona state budget documents — JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, and the Governor's Executive Budget proposals.

**Audience:** JLBC staff and fiscal analysts (initially). Public-facing access is a possible Phase 4, gated on internal trust metrics.

**The product is auditable retrieval, not chat.** Every claim links to the exact PDF page and bounding box that supports it. Faithfulness is checked at generation time; failed citations are visibly stripped rather than silently accepted.

## Status

**Phase 0 — Investigation:** ✓ closed 2026-05-06. Outcomes in [`docs/superpowers/investigations/2026-05-06-phase-0-findings.md`](docs/superpowers/investigations/2026-05-06-phase-0-findings.md) (memo), [`2026-05-05-chunk-shape-decisions.md`](docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md) (chunking), and [`2026-05-06-data-model.md`](docs/superpowers/investigations/2026-05-06-data-model.md) (publisher landscape + cross-doc relationships).

**Phase 1a — Ingest + chunking:** ✓ closed 2026-05-06 (slice-validated). Tag `phase-1a-validated-slice`. 5 docs / 161 chunks / 91.3% agency-stamped / 227 funds. Hand-off contract at [`data/chunks/MANIFEST.md`](data/chunks/MANIFEST.md).

**Phase 1b — Storage + retrieval:** ✓ shipped on slice (2026-05-07). Postgres + pgvector + ParadeDB; full hybrid pipeline `retrieve(RetrievalRequest) → RetrievalResult` (BM25 → dense → RRF → Voyage rerank-2.5). 373 pytest passing. WS8 (eval / recall@K) blocked on volume corpus and runs concurrent with Phase 1c. See [`docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`](docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md).

**Phase 1c — Synthesis + UI:** in progress. Shipped: Budget MCP server with `retrieve` + `cite` tools (`mcp-server/`), FastAPI retrieval sidecar (`retrieval/api.py`), `YouCodedSessionProvider` over `ws://localhost:9900` (`web/lib/`), Next.js chat skeleton with theme tokens mirroring YouCoded (`web/app/`, `web/components/`, `web/state/`). Pending: per-tool tool cards, citation chips, refusal banner, PDF viewer, faithfulness verifier, audit-log writes, eval expansion. 53/53 vitest in `web/`. See [`docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`](docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md).

**Volume ingest** (Phase 1b WS8 prerequisite): handed off to a desktop session via [`PROMPT-volume-ingest.md`](PROMPT-volume-ingest.md). Targets all four publishers (JLBC + Legislature + Gov + AGAO) per decision D12.

For architectural context across all phases, see [`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md). For the v1-specific decisions that shape Phase 1b/1c, see [`docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md).

## Running it locally

```bash
# 1. Postgres + retrieval pipeline (Phase 1b — already populated on the slice)
cd db && docker compose up -d
cd .. && uv run python -m db.validate

# 2. FastAPI retrieval sidecar (Phase 1c WS6) — feeds the Budget MCP server
uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200

# 3. Budget MCP server (Phase 1c WS1) — register with YouCoded
cd mcp-server && npm install && npm run build
node scripts/register.mjs    # writes ~/.claude.json; restart YouCoded

# 4. Web UI (Phase 1c WS4a) — Next.js dev server
cd web && npm install && npm run dev
# Open http://localhost:3000 (requires YouCoded running; reads
# the persisted token from ~/.claude/.remote-tokens.json).
```

## v1 architecture in one paragraph

v1 is a multi-turn budget Q&A web app on Destin's machine that hard-depends on a running YouCoded instance. The budget app's Node backend talks to YouCoded over `ws://localhost:9900`; YouCoded provides the Claude Code session, Pro/Max OAuth, transcript-watcher, and MCP host. A small Budget MCP server (separate Node process registered with YouCoded) exposes `retrieve(query, filters)` and `cite(...)` tools. Claude in each conversation calls `retrieve()` (constrained agent pattern — system prompt requires it before answering) and emits `cite()` per claim. The budget UI is a chat thread with citation chips and a side-panel PDF viewer. Standalone companion app, DOCX viewer, verify-mode toggle, and multi-analyst distribution all defer to Phase 2.

## Repos in this project

| Repo | Purpose | Status |
|---|---|---|
| `ask-the-budget-az-dev` (this) | Workspace + ingest + retrieval + MCP server + web app (v1 lives here) | Active |
| `ask-the-budget-az-companion` | Standalone companion (lifts YouCoded PTY/wrapper) — only when v2 distributes to analysts who don't run YouCoded | Planned (Phase 2) |

## Quick links

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
