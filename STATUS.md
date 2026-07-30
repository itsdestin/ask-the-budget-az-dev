# Project Status

**Last updated:** 2026-05-22

This file is the single source of truth for what's shipped, what's
open, and what's blocked. The phase plans under `docs/superpowers/`
remain as the historical record of design intent — but those plans
have NOT been updated as features shipped, so use this file (not the
plans) to understand current state.

`CLAUDE.md` auto-imports this file via `@STATUS.md`, so every Claude
Code session sees the latest contents in context. **Do not duplicate
status info into CLAUDE.md** — every duplication is a future drift
source. When something ships, update only this file.

---

## Phase summary

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Investigation | ✓ Done (2026-05-06) | Findings memo + chunk-shape + data-model docs |
| Phase 1a — Ingest + chunking | ✓ Done on slice (2026-05-06), volume ingest substantially complete (2026-05-12) | 382 docs / 7,755 chunks; missing older FYs + a few in-cycle gaps |
| Phase 1b — Storage + retrieval | ✓ Done (slice 2026-05-07, volume-validated implicitly, WS8 eval harness shipped 2026-05-22) | Hybrid pipeline live and serving 7K+ chunks; eval harness baseline: recall@5 86%, recall@20 100% on 34-query set |
| Phase 1c — Synthesis + UI | 🟡 Substantially done | All user-visible surfaces shipped; 2026-05-19/20 dogfood-hardening pass landed Items 1-8 plus four follow-up fix waves; faithfulness verifier (WS3) + audit log (WS5) still not built |
| Volume ingest | 🟡 Mostly done | FY25 + FY26 + FY27 across all 4 publishers; gaps: older FYs (FY24 and back), FY26 Approps Report, FY27 Approps/Budget bill |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |
| Standalone consolidation — Plan 1 (storage + retrieval) | ✓ Shipped (2026-07-30) | Postgres/pgvector/ParadeDB → embedded LanceDB; Voyage → local ONNX models. See the section below |
| Standalone consolidation — Plan 2 (app server + search UI) | ✓ Shipped (2026-07-30) | New `app/` (port 9300) + `webapp/` SPA: home, budget search (real corpus), fiscal notes directory. See the section below |

---

## Standalone consolidation — Plan 1 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(decisions S4/S5). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md`.

- **Store:** new `store/` package — embedded LanceDB at `<data_dir>/lancedb`
  (`JLBC_DATA_DIR` env override; dev default `data/insight-data/`, gitignored).
  Vector search (cosine) + native Lance BM25 FTS + DataFusion filters, one
  table per corpus (`budget_chunks` live, `fiscal_note_chunks` reserved for
  Plan 3). No server, no Docker on the retrieval path.
- **Models (local ONNX via fastembed, CPU):** embeddings
  `snowflake/snowflake-arctic-embed-m` (768-dim, query-instruction prefix
  applied query-side), reranker `Xenova/ms-marco-MiniLM-L-12-v2`. Fused
  RRF pool lowered 50 → 20 so the rerank stage stays ≤ ~3s interactive
  (measured 2.7s mean / 3.1s max at 20; 4.9s at 50).
- **Score scale changed:** reranker scores are raw cross-encoder logits
  (≈ −10..10), not Voyage's 0..1. No-results sentinel is
  `NO_RESULTS_TOP_SCORE = -1e9` (0.0 would outrank a genuinely-bad hit).
  Refusal threshold recalibrated 0.65 → **1.9** in
  `mcp-server/system-prompt.md` (sweep: precision 0.67 / recall 0.40 /
  pass-rate 0.97).
- **Gate G1 — passed as amended.** The original gate (recall@5 ≥ 0.80)
  was missed by both local embedder candidates (best 0.69–0.72; every
  local cross-encoder ranks worse than Voyage rerank-2.5) and the
  plan's stop rule fired. Destin reframed G1 mid-execution (spec commit
  `835900f`): **recall@15 ≥ 90% and recall@20 ≥ 95%**, with recall@5
  tracked and reported in every run so the gap stays visible. Final
  numbers: recall@5 72.41%, recall@15 96.55%, recall@20 100%, latency
  p95 ~3.0s (Voyage baseline: 86% / — / 100%, p95 2.6s). **Future
  sessions: the recall@5 gap vs the Voyage baseline is a known,
  accepted trade — do not rediscover it as a regression.** The consuming
  model reads all 15 returned chunks, which is what the amended gate
  measures.
- **Migration:** `scripts/migrate_to_lancedb.py` (one-time; re-runnable;
  `--docs-only` refreshes metadata without the ~50-min re-embed).
  Chunk_ids preserved verbatim; eval ground truth unchanged. G2 spot
  checks: exact chunk-id parity, 60-row full-column diff clean,
  provenance (page+bbox / source_anchor) intact corpus-wide.
- **Sidecar (`retrieval/api.py`):** same endpoints/shapes on LanceDB —
  no `VOYAGE_API_KEY`/`DATABASE_URL`; preflight = data-dir writable +
  corpus non-empty; `/health` reports `corpus_chunks`,
  `documents_metadata`, and returns 503 `degraded` with the real error
  when the store is unreachable. `top_k` validates ≥ 1 (422).
- **documents.json:** per-doc metadata sidecar (title, source_format,
  source_blob_path, source_url) written by the migration next to
  `lancedb/`. This is what lets the web PDF viewer open sources; if it's
  missing, `/health` shows `documents_metadata: 0` and
  `migrate_to_lancedb.py --docs-only` regenerates it in seconds. Titles
  fall back to a doc_id humanizer when absent.
- **Eval harness:** now computes recall@15 alongside 5/20;
  `calibrate_refusal.py` derives its sweep grid from the observed score
  distribution (survives future model swaps); a crashed retrieve can no
  longer masquerade as a confident refusal.
- **Still Postgres/Docker:** ingest only (until Plan 3). Legacy modules
  (`retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`,
  `db/`) stay in-tree unused; removal is Plan 5.
- **Known follow-ups:** web PDF route can't distinguish "metadata
  missing" from "actually DOCX" (415 either way — Plan 2 web-side fix);
  lancedb `table_names()` deprecation (pagination-shaped `list_tables()`
  migration pending); stale data-file versions accumulate after
  `optimize()` (`cleanup_old_versions` not exposed — matters for the SMB
  share); ingest-side title quality is poor for a few docs ("GOVERNOR
  FY2027 fy2027") — Plan 3; expose fastembed `parallel=` for faster bulk
  re-embeds — Plan 3; PRE-EXISTING test-isolation debt (predates Plan 1,
  verified on pre-merge master): when `.env.local` exists, dotenv loading
  during the api tests leaks `DATABASE_URL` into the process env, which
  un-skips the legacy Postgres suites (test_connection/test_loader/
  test_embeddings) mid-run and they fail with UndefinedTable against a
  schema they don't own — run suites without `.env.local` (fresh-clone
  behavior) or fix the skip gates to snapshot env at collection time.

---

## Standalone consolidation — Plan 2 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S1, S9, S12). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md`
(its frozen API-contract block is what Plans 3/4 build against — note the
Task 3 amendments recorded there: `fiscal_note_url` on bills, real
`leg_session()` names, non-unique `bill_number`).

- **App server (`app/`, port 9300):** FastAPI factory serving the built SPA
  (SPA fallback for client-side routes, JSON 404s under /api/, traversal-safe
  static serving) + `POST /api/search` + `GET /api/fiscal-notes` + `/health`.
  Provider seam: `_default_provider()` probes the LanceDB corpus once at
  startup — real `LanceSearchProvider` (Plan 1 stack) when `budget_chunks`
  has rows, fixture `StubSearchProvider` otherwise with the reason on stderr.
  Startup-only by design: a share outage mid-session surfaces as an honest
  JSON 503 from the search route, never a silent swap to fake rows. Run:
  `uv run uvicorn app.main:create_app --factory --port 9300` (set
  `JLBC_DATA_DIR` for a non-default corpus location).
- **Webapp (`webapp/`):** Vite + React 18 SPA ported from the JLBC Website
  Revamp mockup per S12 (verbatim `:root` tokens; page-scoped CSS convention
  documented in `webapp/src/styles/app.css` — the three mockup sources
  conflict on ~74 shared selectors). Pages: Home (hero search + gateway
  cards), Budget Search (see next bullet), Fiscal Notes (28-session /
  2,126-bill directory from the committed snapshot — Plan 3 swaps in the live
  corpus behind the same contract; safe `<strike>/NOW:` title rendering;
  session rail tuned live with Destin).
- **Budget Search — FINAL UI (iterated live with Destin 2026-07-30; the
  "As shipped" section of the Plan 2 doc + the spec's S12 amendment are the
  baseline for Plans 3/4/5):** results group by report family; each card =
  a linked headline row (best agency document, title ONLY — the mockup
  index's display title via exact source-URL join, 373/382 docs; `doc_url`
  from Plan 1's documents.json; relevance BAR with no visible number —
  sigmoid of the reranker logit; "Open" pill) → a collapsed "Matching
  passages" card (snippets + page pills, `data-chunk-id` stubs for Plan 4's
  viewer) → a bottom "Part of the FY YYYY <family>" card with collapsed
  sibling documents and the **Full report** chooser (the mockup's modal:
  Linked TOC vs Single File PDF, hand-verified URLs per family in
  `webapp/src/reportFamilies.ts`). NO publisher pills, NO taglines, NO
  percentages (removed at Destin's direction). Filters: publisher chips +
  curated type buckets + FY dropdown; retry + stale-while-revalidate states.
- **Fiscal-notes snapshot:** `scripts/export_fiscal_notes_snapshot.py`
  (parser transcribed from the vendored mockup generator) → committed
  `app/data/fiscal-notes-snapshot.json`, exact-count pinned (28 / 2,126).
- **Vendored references:** `webapp/reference/` now holds the mockup pages
  (including the GENERATED `subpage-fiscal-notes.html` — base.html's body is
  a superseded scaffold, do not port from it) plus the mockup's in-browser
  search engine (`assets/search/search.js` — report families, curated
  buckets, ranking blend) and its 419-doc URL index (`index-lite.js`), kept
  as input for retrieval tuning and the report-format chooser follow-up.
- **UI score display:** the relevance bar maps Plan 1's raw cross-encoder
  logits through a sigmoid (the model's own probability reading); no numeric
  score is displayed anywhere (Destin, 2026-07-30).
- **Tests:** 24 app pytest (`tests/test_app_server.py`, `test_search_route`,
  `test_fiscal_notes_route`, `test_fiscal_notes_snapshot`,
  `test_lance_provider`) + 39 webapp vitest. `setup.sh` now installs/builds
  `webapp/` and `--verify` runs its suite.
- **Known follow-ups:** book-vs-agency-page open actions SHIPPED as external
  azjlbc.gov links (agency rows via the sidecar URL, whole books via the
  chooser modal) — the remaining piece is Plan 4 swapping them to the in-app
  viewer over `pdfs/` (offline-first per spec S7); doc titles come from the
  mockup-index URL join (373/382 docs) with the slug humanizer covering the
  9 unmatched — Plan 3's ingest should write real titles into
  `documents.json` for docs the website never indexed; filter-chip counts
  need a facets endpoint (corpus-wide numbers, not per-search); Nunito is
  named but never loaded by the mockup (one `<link>` if the approved look
  was really Nunito); `db/migrations/0001` doc_type enum comment is stale
  vs live data (`baseline-agency` vs `baseline-per-agency`).

---

## What's shipped (Phase 1c)

### Retrieval sidecar (`retrieval/api.py`)
- FastAPI service on `127.0.0.1:9200`
- `POST /retrieve` — BM25 + dense + RRF + Voyage rerank. Accepts optional `intent: "lookup" | "compare" | "analyze"` (resolves to default top_k 5 / 12 / 18 when no explicit top_k passed) and echoes intent in the response. Default `top_k` when no intent + no explicit value is 15 (was 20 through 2026-05-19; lowered after dogfood showed spillover at top_k=20).
- `POST /cite/validate` — chunk_id existence + quote-in-chunk-text + span sanity (negative / inverted / oversized). **The content-word-overlap alignment check was DROPPED 2026-05-20** — it was a string-overlap heuristic that produced ~40% false rejections on faithful-but-differently-worded claim_spans. Real faithfulness validation will come from WS3 (NLI verifier, unbuilt).
- `POST /cite/validate_batch` — validates N citations in one round-trip with bulk DB fetch (one `WHERE chunk_id = ANY(%s)` query for all unique chunks). Powers the MCP `cite_batch` tool.
- `POST /list_values` — returns canonical_id slugs with chunk counts + sample doc titles
- `GET /docs/{doc_id}` — document metadata for the PDF viewer
- Sidecar startup loads `.env.local` via python-dotenv; lifespan preflight validates `VOYAGE_API_KEY` + `DATABASE_URL` + chunks-table-non-empty before accepting requests, exiting with a clear stderr message on any failure.
- **55 pytest passing**

### Citation `cite()` / `cite_batch()` behavior
- `cite()` accepts either explicit `span_start`/`span_end` offsets OR a `quote: string` field (server scans chunk.text for the quote and derives the offsets). Quote is the preferred path; offsets are legacy. `claim_span.max` is 2000 chars on the schema; server soft-clamps to 500 with `truncated: true` flag.
- `cite_batch({citations: [...]})` is the multi-citation companion: collapses N serial round-trips into one. The model's tool_use carries an array of single-cite shapes; the response is a parallel array of single-cite results. System prompt steers toward `cite_batch` whenever an answer has more than one citation.
- Both tools return `resolved_span_start` / `resolved_span_end` on success — the sidecar-derived position of the cited text inside chunk.text. The web UI uses these for precise PDF text-layer highlighting.
- The locked schema decision doc (`docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`) has a 2026-05-20 amendment header documenting all of the above.

### MCP server (`mcp-server/`)
- Four tools registered: `retrieve`, `cite`, `cite_batch`, `list_filter_values`
- Per-conversation `.mcp.json` materialization with `alwaysLoad: true` on the budget MCP server (eliminates ToolSearch round-trips for the budget tools). Per-conversation `.claude/settings.json` allow/deny — allow: Bash, Read, the four budget MCP tools; deny: Grep, Write, Edit, MultiEdit, NotebookEdit, Glob, PowerShell, WebFetch, WebSearch, ToolSearch, plus glob denies for unrelated MCP servers (`windows-control`, `gmessages`, `imessages`, `todoist`, `spotify-services`).
- `retrieve()` first-call cap: the FIRST retrieve() of any session is capped to 5 chunks regardless of input top_k/intent. Response carries `first_call_capped: true`. Bypassable with `deep_dive: true` for explicit thorough-coverage requests. Subsequent retrieves are uncapped.
- System prompt (~1300 lines) covers: constrained-agent contract, "tools are preloaded — do NOT call ToolSearch" notice, **progressive retrieval pattern** (first call samples, model expands if needed), **Route-the-question-first classifier** (lookup/compare/analyze → answer FORMAT, not retrieve breadth), **Output hygiene** (banned leak categories: internal vocabulary, corpus mechanics, retry narration), cite() quote recipe, filter dimensions + agency cheat sheet, doc lifecycle (Governor → Baseline → Approps → AFR), 3-year table structure, AFR accuracy hierarchy, retrieval recipes, refusal cases.
- Structured per-call JSONL logging at `~/.claude/ask-the-budget-az/bridge.log` (timestamp, endpoint, duration, outcome, httpStatus, errorCategory, retrievalId). One line per /retrieve and /cite/validate(_batch) call.
- **57 vitest passing**

### Web app (`web/`)
- Next.js multi-turn chat UI on `127.0.0.1:3000`
- Citation rendering:
  - Inline-underlined chips for successful cites; red-X wavy-underline for failed
  - Retry chips collapse via two-pass dedup: (1) chunk_id + substring-chain union-find; (2) FIFO-pair fail→ok across blocks for the same chunk_id (handles claim_span-rewritten retries). Suppresses pairing within a single `cite_batch` (same `batchId`) — sibling claims in a batch are intentional distinct citations, not retries.
  - Tooltip shows verbatim quote (success) or claim-vs-actual-cited side-by-side (failure)
  - MCP zod errors humanized (not raw JSON)
  - Markdown table-row claims inject sentinel inside the last cell
  - Citation `spanStart`/`spanEnd` resolution order: ack's `resolved_span_start/end` (preferred) → explicit input offsets (legacy) → `(0, claim_span.length)` sentinel (only for in-flight or pre-fix calls; produces "couldn't pinpoint" badges in the PDF viewer).
- Tool cards: friendly labels (Search corpus, Cite claim, Cite claims, Browse filters, Shell, …) with per-tool body views (RetrieveView, CiteView, ListFilterValuesView, EditView, ShellView, …). Single status indicator on the header (pixel-glyph color encodes running/complete/failed); pulses while running.
- PDF viewer (`web/components/PdfPage.tsx`):
  - pdfjs-dist canvas render with bbox-restricted text-layer search
  - Multi-pass match strategy: chunk.text\[span_start:span_end\] → full chunk.text → individual currency tokens; bbox-restricted first, then unrestricted
  - "Couldn't pinpoint" badge instead of misleading chunk-bbox fallback when all matches fail
  - "Couldn't open source PDF" error when chunk's source isn't a PDF (DOCX legislative bills currently — DOCX viewer is Phase 2)
- ChatThread auto-scroll: event-driven detection, only follows bottom when the user is at bottom. Messages anchor to the BOTTOM of the viewport.
- UI refresh + JLBC mascot (shipped 2026-05-19, branch `ui-prettify-mascot`):
  - Civic-warm theme tokens; single-mascot architecture with pixel-aligned variant swaps (idle / typing / presenting / refusal); seated typing scene with 12-second behavior loop; welcome hero on empty thread; suggestion chips; speech-bubble assistant messages; page pinned (only chat thread + PDF viewer scroll); footer honesty line.
- Sidecar `/health` probe at session start; renders a `SystemHealthBanner` above the chat thread when the probe fails (e.g. sidecar not running). Returned inline from `startConversation` as `{conversationId, health}` — no event-subscription plumbing.
- **197 vitest passing**

### Eval harness (`eval/`) — Layer 1 retrieval eval

- 34 LLM-synthesized queries (`eval/queries.yaml`) with hybrid ground truth (chunk_id + dimensions + anchor_text)
- `eval/run_eval.py` — calls retrieve() directly, emits JSON + Markdown to `eval/results/<UTC-ISO>-<git-sha>.{json,md}`, computes delta vs previous run
- `eval/refresh_chunk_ids.py` — post-reingest stale-chunk_id fixer (anchor match → cosine fallback)
- `eval/calibrate_refusal.py` — sweep refusal thresholds + recommend
- `eval/synthesize_queries.py` — LLM-driven query generator (Anthropic SDK; subagent-driven path is also documented when no API key)
- **44 pytest passing** across 6 test modules
- **First baseline (committed under `eval/results/`)**: recall@5 86%, recall@20 100%, latency p95 2561ms on the 34-query set. Refusal precision was 0% at the hardcoded 0.30 threshold (Voyage rerank scores sit at 0.56-0.93 — calibration recommends moving the prompt threshold to 0.60 for perfect separation on this eval set).

---

## 2026-05-19 → 2026-05-20 hardening pass

Substantial reliability + UX work landed across this window. Each item ships as a feature branch merged with `--no-ff`; the merge commit is the entry point for the audit trail. All work in worktrees per CLAUDE.md convention, cleaned up after merge.

### Items 1-7 of the original dogfood-hardening plan (merge `1939347`, 2026-05-19/20)

| Item | What | Most-relevant file(s) |
|---|---|---|
| 1 | Per-session `.mcp.json` (alwaysLoad:true) + `.claude/settings.json` allow/deny (eliminates ToolSearch) | `web/lib/youcoded-session-provider.ts`, `web/lib/mcp-config-loader.ts` |
| 2 | `cite()` accepts `quote` (server derives offsets); `claim_span` relaxed 500→2000 with server soft-clamp | `mcp-server/src/tools/cite.ts`, `retrieval/api.py` `http_cite_validate` |
| 3 | `DEFAULT_PIPELINE_TOP_K` lowered 20→15 (measurement-gated by `scripts/measure_retrieve_size.py`) | `retrieval/pipeline.py` |
| 4 | `intent` parameter on `retrieve()` (lookup/compare/analyze → top_k 5/12/25); routes table in system prompt | `mcp-server/src/tools/retrieve.ts`, `retrieval/api.py` |
| 5 | Output-hygiene prompt rewrite — three banned leak categories + dogfood-test plan | `mcp-server/system-prompt.md`, `docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md` |
| 6 | Bridge JSONL logging + session-start `/health` probe + SystemHealthBanner | `mcp-server/src/lib/bridge-log.ts`, `web/components/SystemHealthBanner.tsx` |
| 7 | Sidecar `python-dotenv` auto-loads `.env.local` + startup preflight + README "Daily startup" checklist | `retrieval/api.py` `lifespan`, `README.md` |

Plan doc at `docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md` (historical — captures the pre-execution design + open-question resolutions Q1/Q2/Q3).

### Follow-up fix waves (after Items 1-7 shipped)

Each wave responded to specific issues surfaced during dogfood verification of the previous wave.

**Wave A — Citation-extract patches (commits `5981dbb`, `4620ec3`).** Quote-only cite() calls were being silently dropped at the UI extraction layer because the extractor required numeric offsets. Patched to accept quote-only with a sentinel range; added FIFO-pair-fail→OK dedup for retries that rewrite claim_span entirely.

**Wave B — `cite-batch` branch (merge `3c6bf04`).** Dropped `_check_alignment` from `/cite/validate` (~40%→~5% false-rejection rate; removed the dominant retry-loop latency source). Added the `cite_batch` MCP tool + matching `/cite/validate_batch` sidecar endpoint with bulk DB fetch — collapses N serial cite round-trips into one for analyze-shaped answers. Web `citation-extract.ts` walks the batched input/output arrays; new `batchId` field disambiguates same-batch siblings from cross-block retries in the dedup pass.

**Wave C — `cite-resolved-offsets` branch (merge `2c570e6`).** Threads sidecar-derived `resolved_span_start` / `resolved_span_end` through the cite + cite_batch tool responses to the web UI, fixing the "Citation is on this page — exact text couldn't be pinpointed" badge cluster. Also denies `ToolSearch` in `.claude/settings.json` (alwaysLoad wasn't fully eliminating model-side ToolSearch habit), tightens the route classifier to default-to-Lookup for "Show me X" / "What is X" wording, lowers analyze top_k 25→18 to stay under Claude Code's spillover threshold.

**Wave D — `first-call-cap` branch (merge `af6a673`).** Progressive retrieval: first retrieve() of any session is capped to 5 chunks regardless of intent/top_k. Bypass via `deep_dive: true` for explicit thorough-coverage requests. After the first call, pass-through behavior. Route classifier rewritten to be about answer FORMAT, not retrieve sizing — breadth comes from iterative follow-up retrieves, not one-shot top_k.

**Wave E — `citation-accuracy` branch (merge `400d674`).** Three connected improvements to citation handling. (1) Per-sentence chip placement: `planCitationPlacements` walks every sentence and places a chip wherever the claim_span or the citation's key-fact token (largest currency / percentage) appears, with anti-duplicate guard. `CitationPlacement` gains an optional `column` field; `injectCiteSentinels` splices sentinels mid-line via right-to-left injection. Restated facts across multiple sentences now each get their own chip. (2) Strict-bbox PDF highlight: text-layer search extracted into a new `HighlightStrategy` interface (`web/lib/highlight-strategy.ts`) with `TextLayerSearchStrategy` as the default and a `CoordMapStrategy` placeholder for the #57 follow-up. When a chunk has a bbox, search is strictly bbox-restricted — no whole-page fallback. A miss surfaces "couldn't pinpoint" instead of a silent wrong highlight. (3) Always-visible `CitedTextPanel` below the PDF page renders the chunk's verbatim text with the cited span underlined — verify-by-eye surface for both happy and miss cases. Plus a sidecar-side change: `_validate_one_cite` now rejects quotes that appear multiple times in chunk.text, returning up to 3 positions in the error so the model picks a longer, unique quote on retry. Plan at `docs/superpowers/plans/2026-05-20-citation-accuracy-and-per-sentence-chips.md`. Spec at `docs/superpowers/specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md`.

---

## What's open

### Modeling / behavior gaps
- **Model meta-narration leaks** ("Retrying the cites…", "All cites anchored", "Task tracking isn't relevant…") still appear in user-visible answer prose despite Task 12's Output-hygiene rewrite. The prompt-only fix isn't sufficient; needs another pass and possibly a mechanism-level intervention (e.g. stripping retry-narration text in the renderer before display).
- **Model occasionally writes verbose `claim_spans` that don't substring-match the rendered answer** — soft-fixed by the cite_batch + resolved-offsets work but not eliminated; chip attachment still fails when the model rewrites prose between cite() and final emission.

### PDF viewer accuracy (failure mode catalog — updated post-Wave E)
- **A. Source isn't a PDF (DOCX legislative bills).** UI still shows "Couldn't open source PDF" but the new always-visible `CitedTextPanel` below the viewer now shows the chunk's verbatim text with the cited span underlined, so the analyst can verify the cite even without a PDF viewer. #55's broader DOCX viewer is still a separate concern.
- **B. PDF exists, text-layer search fails to find the quote.** "Couldn't pinpoint" badge — same surface, but now the CitedTextPanel underneath shows the cited span in chunk text, so a miss is recoverable rather than dead-end. **Architectural fix still queued (#57):** capture chunk_text→PDF-coord mapping during ingest. Wave E added the `HighlightStrategy` interface so #57 can drop in as a `CoordMapStrategy` without rewriting `PdfPage`.
- **C. PDF exists, chunk's stored bbox is wrong** (MinerU mis-detection). Now produces an honest "couldn't pinpoint" badge instead of a silent wrong highlight, since Wave E removed the unrestricted-search fallback. Ingest QA still out of scope.
- **D. Citation references a chunk_id from a prior turn with no metadata** in the current turn's retrieve. `buildConversationResolvedChunkMap` exists for cross-turn fallback but is sometimes missing chunks. **Diagnosis queued (#56):** verify whether the cross-turn map is consulted, identify where the lookup fails.
- **E. Quote is ambiguous (appears multiple times in chunk.text).** Used to silently bind to the first occurrence → wrong-bbox highlight. Wave E rejects these at validate time so the model must pick a longer, unique quote.

### Not yet implemented (per the Phase 1c plan)
- **Faithfulness verifier (WS3).** Post-generation NLI-style check that strips claims whose cites don't actually back them. Core Invariant 2 says "citations are verified, not just emitted" — current enforcement is chunk_id + quote-in-chunk-text (catches invented chunks/quotes, not semantic faithfulness). The dropped `_check_alignment` was a string-overlap proxy, not real faithfulness. WS3 is the real fix.
- **Audit log writer (WS5).** No persistent record of `(retrieval_id, citation_id, claim_span, intent)` tuples for offline review. Schema-side hooks are in place — `retrieval_id` flows through retrieve() responses, `intent` echoes back, JSONL bridge log captures call-level data — but no DB writer.
- **Layer 2 eval (open-ended analyst queries, LLM-as-judge or rubric scoring).** Layer 1 (chunk-recall regression detector) shipped 2026-05-22 — see "Eval harness" subsection above. Layer 2 is what measures real analyst usefulness: open-ended queries like "spending on homelessness projects?" with multiple acceptable chunks per answer. Deferred until WS3 (faithfulness verifier) ships, since end-to-end scoring depends on it. See [eval/README.md](eval/README.md) for the framing.
- **DOCX viewer (Phase 2).** Bills are DOCX; the Phase 2 plan adds an inline DOCX viewer. Until then, #55 (text-only fallback) is the stopgap.

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

### Open follow-up tasks (tracked in TaskList)
- **#45** — Investigate `(unknown)` tool card after Item 1 ships (verification-only; needs a fresh dogfood transcript)
- **#55** — DOCX chunk fallback (render chunk text inline when no PDF backing)
- **#56** — Diagnose cross-turn metadata gap
- **#57** — Capture chunk→PDF coord map during ingest (architectural PDF-accuracy fix)
- **#58** — Post-mortem: 2026-05-20 dogfood revealed 4 distinct fix categories worth documenting

### Recently fixed — verify in next dogfood pass
- BM25 query parser crashed on apostrophes (#47) — fixed by sanitizing tantivy/Lucene special chars before query string reaches pg_search. 14 of 34 eval queries previously aborted; now 0 crash.
- MCP refusal threshold raised from 0.30 → **0.65** in mcp-server/system-prompt.md (2026-05-22). Old 0.30 was effectively dead — Voyage rerank scores on the current corpus sit at 0.56–0.93, never below 0.56. Calibration recommended 0.70 (refusal recall 0.80, precision 0.67, retrieval pass-rate 0.93); 0.65 picked as a slightly more conservative starting point (refusal recall 0.60, retrieval pass-rate 0.93). Dogfood for real failure modes; re-calibrate after any meaningful corpus or rerank-model change.
- Restated facts across multiple sentences only chipped the first occurrence (per-sentence placement + key-fact-token rule)
- Wrong yellow rectangle when bbox-restricted search missed (strict-bbox, no whole-page fallback)
- Source text only visible inside the PDF (always-visible `CitedTextPanel` below the page)
- Quote-ambiguity silent wrong highlights (sidecar duplicate-quote rejection)
- Citation chips weren't rendering at all (citation-extract required offsets; now accepts quote-only)
- Failed retries weren't collapsing with their successful replacements (FIFO-pair-fail→OK dedup)
- 40% cite() false-rejection rate (dropped alignment heuristic)
- 60s+ tool round-trips on analyze-shaped answers (cite_batch single round-trip)
- "Couldn't pinpoint" PDF badges (resolved-offsets passthrough)
- ToolSearch round-trips at session start (added to deny list)
- "Show me X" classifying as Analyze and pulling 25 chunks (route-classifier defaults to Lookup; analyze lowered 25→18)
- First retrieve always pulling too many chunks regardless of question shape (progressive-retrieval first-call cap)

---

## Repo + portability

### Single git repo
Everything lives in `ask-the-budget-az-dev` →
`github.com/itsdestin/ask-the-budget-az-dev`. No multi-repo workspace,
no submodules.

### What's tracked vs not
- **Tracked:** all source, the MinerU manifests, the JLBC primer, agency/fund catalogs, raw DOCX user uploads (samples/raw-docx/), test fixtures
- **Gitignored:** `node_modules/`, `.venv/`, `db/data/` (Postgres volume), `data/cached-pdfs/`, `data/extractor-output/`, `data/chunks/*` (except MANIFEST.md), `data/insight-data/` (LanceDB corpus + documents.json), `.env.local`, build outputs

### What must travel for a fresh device
1. **The LanceDB corpus** — copy the whole `data/insight-data/` directory
   (the `lancedb/` folder AND `documents.json` — the sidecar is what lets
   the PDF viewer locate sources; without it search still works but PDFs
   won't open, visible as `documents_metadata: 0` on `/health`). Retrieval
   is then live with zero external services — no Docker, no keys.
2. **`data/cached-pdfs/`** — the PDFs themselves (the viewer streams from
   here; re-downloadable from public URLs if lost).
3. **Ingest-only (until Plan 3):** `.env.local` (Voyage key) + the
   Postgres volume `db/data/` — needed only to ingest NEW documents or
   re-run the migration. Retrieval no longer touches either.
   - Fast: copy `db/data/`, `docker compose up -d` (from `db/`).
   - Slow: re-run ingest against PDFs (Voyage API + hours).

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
- README's "Daily startup" section is the canonical reference for the launch order: Docker → Postgres → sidecar → YouCoded → web UI.

---

## Doc map

- [README.md](README.md) — how to run it, launch sequence, links
- [STATUS.md](STATUS.md) — this file (current state)
- [CLAUDE.md](CLAUDE.md) — workspace conventions for Claude Code sessions
- [PROMPT-volume-ingest.md](PROMPT-volume-ingest.md) — hand-off prompt for the volume-ingest task
- [docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — overall design spec (historical)
- [docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c
- [docs/superpowers/decisions/2026-05-06-citation-tool-schema.md](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked schema for `retrieve()` + `cite()` (amended 2026-05-20 — quote, cite_batch, dropped alignment, resolved offsets, progressive retrieval)
- [docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md](docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md) — 18-task plan for the dogfood-hardening pass (historical; Items 1-7 shipped + four follow-up fix waves)
- [docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md](docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md) — dogfood-test plan for the output-hygiene rewrite
- [docs/superpowers/plans/](docs/superpowers/plans/) — phase plans (historical; not kept in sync with shipped features)
- [data/chunks/MANIFEST.md](data/chunks/MANIFEST.md) — Phase 1a → Phase 1b hand-off contract
- [eval/README.md](eval/README.md) — Layer 1 retrieval eval harness: when/how to run, scoring rules, caveats, calibration interpretation
- [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md) — eval harness spec (Layer 1; amended 2026-05-22 with what shipped vs diverged)
- [docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md](docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md) — eval harness implementation plan (shipped 2026-05-22, merge `3a26c19`)
