# Project Status

**Last updated:** 2026-05-12

This file is the single source of truth for what's shipped, what's
open, and what's blocked. The phase plans under `docs/superpowers/`
remain as the historical record of design intent — but those plans
have NOT been updated as features shipped, so use this file (not the
plans) to understand current state.

---

## Phase summary

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Investigation | ✓ Done (2026-05-06) | Findings memo + chunk-shape + data-model docs |
| Phase 1a — Ingest + chunking | ✓ Done on slice (2026-05-06), volume ingest substantially complete (2026-05-12) | 382 docs / 7,755 chunks; missing older FYs + a few in-cycle gaps |
| Phase 1b — Storage + retrieval | ✓ Done on slice (2026-05-07), volume-validated implicitly | Hybrid pipeline live and serving 7K+ chunks; eval harness (WS8) still pending |
| Phase 1c — Synthesis + UI | 🟡 Substantially done | All user-visible surfaces shipped; faithfulness verifier + audit log not built |
| Volume ingest | 🟡 Mostly done | FY25 + FY26 + FY27 across all 4 publishers; gaps: older FYs (FY24 and back), FY26 Approps Report, FY27 Approps/Budget bill |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |

---

## What's shipped (Phase 1c)

### Retrieval sidecar (`retrieval/api.py`)
- FastAPI service on `127.0.0.1:9200`
- `POST /retrieve` — BM25 + dense + RRF + Voyage rerank, returns chunks with `text_length` for span-bound checks
- `POST /cite/validate` — chunk_id existence + span bounds + span-breadth + content-alignment
- `POST /list_values` — returns canonical_id slugs with chunk counts + sample doc titles
- `GET /docs/{doc_id}` — document metadata for the PDF viewer
- 41 pytest passing

### Citation validator behavior
- **AFR currency-only path** when `doc_type=afr` (raw table cells have no English; check dollar amounts only)
- **Verbatim cite path:** strict substring fast-path, then ≥70% content-word overlap
- **Paraphrase cite path:** ≥60% content-word overlap
- **Auto-clamp** small `span_end` overflows (≤ max(50 chars, 5%))
- **Normalize** strips CommonMark backslash escapes, collapses both `$(X)` and `($X)` accounting-negatives, expands `$X million` ↔ `$X,000,000`, canonicalizes currency tokens to bare-number form
- On any failure, echoes the first ~500 chars of the cited slice back to the model

### MCP server (`mcp-server/`)
- Three tools registered: `retrieve`, `cite`, `list_filter_values`
- System prompt (~1000 lines) covers: constrained-agent contract, filter dimensions + agency cheat sheet, doc lifecycle (Governor → Baseline → Approps → AFR), 3-year table structure, AFR accuracy hierarchy, retrieval recipes, claim-span anti-patterns, refusal cases
- 32 vitest passing

### Web app (`web/`)
- Next.js multi-turn chat UI on `127.0.0.1:3000`
- Citation rendering:
  - Inline-underlined chips for successful cites; red-X wavy-underline for failed
  - Retry chips collapse via chunk_id + substring-chain dedup
  - Tooltip shows verbatim quote (success) or claim-vs-actual-cited side-by-side (failure)
  - MCP zod errors humanized (not raw JSON)
  - Markdown table-row claims inject sentinel inside the last cell
- Tool cards: friendly labels (Search corpus, Cite claim, Shell, …) with per-tool body views (RetrieveView, CiteView, ListFilterValuesView, EditView, ShellView, …)
- PDF viewer:
  - pdfjs-dist canvas render with bbox highlight
  - Multi-pass text-layer search (claim slice → full chunk → individual currency tokens)
  - "Couldn't pinpoint" badge instead of misleading chunk-bbox fallback
- ChatThread auto-scroll: event-driven (wheel/touch/keyboard) detection, only follows bottom when the user is actually at bottom
- 154 vitest passing

---

## What's open

### Modeling / behavior gaps
- **Model occasionally writes verbose `claim_spans` that don't substring-match the rendered answer.** Latest prompt rule explicitly forbids this, but no measurement yet of whether the rule sticks.
- **Model still emits meta-commentary in answer prose when its cites fail** ("…the chip attachments fail. Treat those numerical values as cited…"). User-visible UX leak — should never happen if the cites just work.
- **Some PDF text-layer matches still fall back to the "couldn't pinpoint" badge.** Likely causes: chunk text formatting drift (e.g. tabs in chunk vs spaces in PDF, ligature differences), or the cited region isn't actually present in the PDF text layer due to OCR drift. Needs case-by-case investigation.

### Not yet implemented (per the Phase 1c plan)
- **Faithfulness verifier (WS3).** Post-generation NLI-style check that strips claims whose cites don't actually back them. Currently the server-side `/cite/validate` is doing the catch-most-failures work but isn't NLI-grade.
- **Audit log writer (WS5).** No persistent record of `(retrieval_id, citation_id, claim_span)` tuples for offline review.
- **Eval expansion (Phase 1b WS8).** Recall@K, citation-faithfulness rates, refusal precision. No longer blocked on volume ingest (the corpus is now 7K+ chunks across the FY25–FY27 cycle), just unbuilt.

### Volume ingest — current corpus
**382 documents / 7,755 chunks** as of 2026-05-12. Coverage:

| Publisher | FY 2025 | FY 2026 | FY 2027 |
|---|---|---|---|
| JLBC | Approps Report (111 per-agency) | Baseline (110 per-agency + 6 bd-pdf + 7 bh-pdf + 16 detailed-list + 2 topic) | Baseline (110 per-agency + 15 s-pdf + 2 topic) |
| Legislature | — | budget-bill | — |
| Governor | — | — | Executive Budget |
| AGAO | AFR (1) | — | — |

**Known gaps to fill** (none blocking but worth scoping):
- Older FYs entirely — FY24, FY23, FY22 baselines + approps reports + AFRs
- FY 2026 Approps Report (summarizes what actually passed in 2025 session)
- FY 2027 Approps Report / Budget bill (if/when it passes)
- Older Governor's Budgets (FY26, FY25)
- AGAO AFRs for FY24 and FY23

Hand-off prompt for additional ingest at [`PROMPT-volume-ingest.md`](PROMPT-volume-ingest.md).

### Recently fixed (this session) — verify in next dogfood pass
- Citation hover tooltip (now stays open as cursor crosses the 4px gap)
- Auto-scroll fighting user scroll
- Tool-card raw MCP names
- "Citations 1-6 invisible" bug (markdown table sentinel placement)
- 3-chip-per-cell retry pile-up (now collapses to one chip per chunk)
- Raw MCP zod errors in chip tooltips (now humanized)

---

## Repo + portability

### Single git repo
Everything lives in `ask-the-budget-az-dev` →
`github.com/itsdestin/ask-the-budget-az-dev`. No multi-repo workspace,
no submodules.

### What's tracked vs not
- **Tracked:** all source, the MinerU manifests, the JLBC primer, agency/fund catalogs, raw DOCX user uploads (samples/raw-docx/), test fixtures
- **Gitignored:** `node_modules/`, `.venv/`, `db/data/` (Postgres volume), `data/cached-pdfs/`, `data/extractor-output/`, `data/chunks/*` (except MANIFEST.md), `.env.local`, build outputs

### What must travel for a fresh device
1. **`.env.local`** — Voyage API key (paid; not in git)
2. **The Postgres data** — `db/data/` directory holds every chunk + embedding. Two paths:
   - **Fast:** copy `db/data/` from old machine, then `docker compose up -d`. Live in seconds.
   - **Slow:** re-run the ingest pipeline against PDFs. Costs Voyage API + several hours.

See [README.md → Moving to a new device](README.md#moving-to-a-new-device) for the exact commands.

### What's installed externally (NOT in the repo)
- Docker (or Docker Desktop on Windows/Mac)
- Node 20+ and npm
- Python 3.12 and `uv` (`pip install uv`)
- A running **YouCoded** or **Claude Code** instance — provides the LLM session via `ws://localhost:9900`

---

## Working conventions

- `setup.sh` — one-shot installer for everything regenerable. Run after `git clone`. Does NOT restore DB data.
- `bash setup.sh --verify` — runs all test suites (pytest + 2× vitest). Use before merging non-trivial work.
- All three services run in separate processes; `npm` is in `mcp-server/` and `web/`; `uv` drives Python.

---

## Doc map

- [README.md](README.md) — how to run it, launch sequence, links
- [STATUS.md](STATUS.md) — this file (current state)
- [CLAUDE.md](CLAUDE.md) — workspace conventions for Claude Code sessions
- [PROMPT-volume-ingest.md](PROMPT-volume-ingest.md) — hand-off prompt for the volume-ingest task
- [docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — overall design spec (historical)
- [docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c
- [docs/superpowers/decisions/2026-05-06-citation-tool-schema.md](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked schema for `retrieve()` + `cite()`
- [docs/superpowers/plans/](docs/superpowers/plans/) — phase plans (historical; not kept in sync with shipped features)
- [data/chunks/MANIFEST.md](data/chunks/MANIFEST.md) — Phase 1a → Phase 1b hand-off contract
