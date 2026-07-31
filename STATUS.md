# Project Status

**Last updated:** 2026-07-31

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
| Phase 1c — Synthesis + UI | ⬛ Superseded by Standalone consolidation (Plans 1–4) | The MCP/sidecar/Next.js stack it shipped is retired; faithfulness verifier (WS3) + audit log (WS5) remain unbuilt and carry forward |
| Volume ingest | 🟡 Backfill pending — Z13 run (`PROMPT-z13-backfill.md`); S20 scope | FY25 + FY26 + FY27 across all 4 publishers are in; older FYs and a few in-cycle gaps go through the Z13 backfill |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |
| Standalone consolidation — Plan 1 (storage + retrieval) | ✓ Shipped (2026-07-30) | Postgres/pgvector/ParadeDB → embedded LanceDB; Voyage → local ONNX models. See the section below |
| Standalone consolidation — Plan 2 (app server + search UI) | ✓ Shipped (2026-07-30) | New `app/` (port 9300) + `webapp/` SPA: home, budget search (real corpus), fiscal notes directory. See the section below |
| Standalone consolidation — Plan 3 (ingest) | ✓ Shipped (2026-07-31) | GUI upload → background queue → LanceDB; fiscal-note refresh; Add-a-JLBC-book. Postgres/Docker now needed for NOTHING. See the section below |
| Standalone consolidation — Plan 4 (AI Mode) | ✓ Shipped (2026-07-31) | In-process OpenRouter tool loop; MCP and YouCoded dropped. Cited chat + PDF viewer on both corpora, Standard/Deep-Research tiers, per-user spend ledger. See the section below |

## What's next

- **Plan 5 — admin/settings UI, packaging + launcher, legacy deletion
  (`web/`, `mcp-server/`, `db/`, dead `retrieval/` modules), gates G2/G3,
  and AI-Mode hardening: S22 prompt caching (biggest cost lever) + S23
  normalization-tolerant quote validation.**
- **Z13 backfill + recency calibration (S20/S21)** — historical-year corpus
  backfill and recency-ranking calibration on the Z13 Linux machine.
  Runbook: [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md) (the only
  active handoff). Recency plan:
  [`docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md`](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md).

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
  from Plan 1's documents.json; "Open" pill; NO relevance display — number
  and bar both removed, ranking speaks through result order) → a collapsed "Matching
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
- **UI score display:** none — scores (raw cross-encoder logits) drive
  ordering only; the relevance number and bar were both removed at Destin's
  direction (2026-07-30).
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

## Standalone consolidation — Plan 3 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S6, S7, S10, S17, Invariant 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md`.

**Postgres and Docker are now needed for NOTHING.** They were ingest-only
after Plan 1; ingest no longer touches either. The legacy `db/` modules stay
in-tree unused (removal is Plan 5), and `scripts/migrate_to_lancedb.py`
remains as the migration-era record.

- **Queue (`ingest/`):** `jobs.py` (one JSON file per job under
  `<data_dir>/jobs/`, atomic writes, state machine, crash-resume),
  `lock.py` (SMB-safe single-writer lock via exclusive-create + heartbeat
  stale-steal — S6), `worker.py` (one daemon thread in the app process:
  extract → chunk → embed → write), `mineru_runner.py` (streamed per-page
  progress, timeout, cooperative cancel that kills the child, `JLBC_MINERU_*`
  offline pinning — S7), `lance_writer.py` (Chunk→Arrow row, idempotent
  per-doc replace, documents.json merge, real titles), `validate.py`
  (advisory post-ingest checks ported from `db/validate.py`).
- **Resume granularity is the stage, and inside extraction the page range.**
  MinerU runs 1–3 min/page on an i5-1245U, so a 210-page book is an overnight
  job that WILL be interrupted. Extraction output lands on the share
  (`<data_dir>/extractor-output/<doc_id>/`) so any machine can continue.
  Chunking and embedding are re-derived rather than journalled — minutes, not
  hours.
- **Write phase, every time:** ingest lock → S17 `snapshot()` →
  `delete_doc` → `upsert_chunks` → `build_fts_index` → `optimize` →
  documents.json merge. The FTS rebuild is not optional: new rows are
  invisible to BM25 without it, which looks like a working ingest with
  silently broken keyword search.
- **Upload API + page:** `POST /api/upload` (multipart) with the Invariant 8
  gate enforced SERVER-side (400 without the public-record confirmation),
  content-hash dedup against both documents.json and pending jobs (409 with
  when/who + an explicit re-process option), `GET /api/jobs`,
  retry/cancel. `webapp/src/pages/Upload.tsx`: always-visible Invariant 8
  notice, required checkbox, filename-heuristic metadata form, live queue with
  per-stage progress. Copy states the real cost — "large books process
  overnight" — deliberately not softened.
- **Real titles.** `build_title()` retires the migration's
  "GOVERNOR FY2027 fy2027" strings for new ingests, and
  `app/search_provider.py` now consults documents.json's title (gated on
  `ingested_at`, so migration-era junk titles still lose to the humanizer) and
  re-reads the sidecar when its mtime changes. Both gaps were found by the
  end-to-end run, not by a test.
- **Fiscal notes are live (S10).** `POST /api/fiscal-notes/refresh` queues a
  `refresh`-kind job that scrapes `azjlbc.gov/fiscal-notes/?Year=`, diffs
  against the directory, downloads only new note PDFs, and feeds them to the
  normal queue. `GET /api/fiscal-notes` now serves
  `<data_dir>/fiscal-notes-directory.json` when present (mtime-checked; the
  Plan 2 `lru_cache` is gone — it would have pinned the pre-refresh copy for
  the process lifetime) and falls back to the committed snapshot otherwise, so
  a fresh install shows 28 sessions on day one. Scraper breakage degrades to
  last-good LOUDLY: a session that returns zero rows when notes are already on
  file fails the refresh instead of deleting them. The FiscalNotes rail's
  reserved search box is now a real semantic search over `fiscal_note_chunks`,
  disabled until the corpus reports passages.
- **Add a JLBC book (Task 15).** `data/jlbc-book-sources/` vendors the website
  mockup's verified URL harvest (read-only, snapshot 2026-06-16);
  `scripts/build_book_catalog.py` turns it into the committed
  `data/jlbc-book-catalog.json` — **41 approps (FY1984–2026) + 21 baseline
  (FY2007–2027) editions**, pinned by test. `ingest/book_discovery.py` is
  catalog-first (zero network on a hit) and falls back to a HEAD-verified
  candidate ladder for editions published after the snapshot, walking BOTH the
  agency index and the linked TOC (their children are disjoint). Dead hosts
  rewritten, URLs never re-encoded, case-insensitive dedupe, and a rolling
  `/budget/` guard that refuses an index whose links belong to another year.
  `GET /api/books/catalog`, `POST /api/books/discover` (no downloads),
  `POST /api/books/ingest` (one job per document, URL-only — each job fetches
  its own PDF when its turn comes).
- **Tests:** 772 pytest + 71 webapp vitest green.
- **Corpus counts** are unchanged for the shared dev corpus (382 documents /
  7,755 budget chunks); Plan 3 adds no documents on its own.

### Verified end-to-end on 2026-07-31 (real network, real MinerU)

- A real 2-page PDF uploaded through `POST /api/upload` ran
  `extracting → live` with per-page progress, produced 6 passages, took an
  S17 snapshot, copied the source into `<data_dir>/pdfs/`, and came back in
  search titled **"FY 2027 Baseline — Industrial Commission of Arizona"** —
  a title derived from the document's CONTENT, not its filename.
- The validation gate correctly flagged that document as only 17%
  agency-stamped (it is the Industrial Commission's page; the filename said
  AHCCCS) — advisory, non-fatal, visible on the queue.
- A live fiscal-note refresh scraped azjlbc.gov, detected two withheld 2026
  notes (HB 4049, HB 4092), downloaded them, ingested both, and the rail
  search returned their real text. Directory restored to 112 bills.
- A live dry-run of book discovery (listing only, nothing ingested) found the
  **FY2027 Appropriations Report** — which the harvest recorded as
  expected-but-unpublished — via the probe ladder and walked **139 documents,
  0 unreachable**. That is the exact scenario Task 15 exists for.
- Budget eval re-run against the real corpus: **recall@5 72.41%, recall@15
  96.55%, recall@20 100%** — identical to the Plan 1 baseline. No retrieval
  regression. Results committed under `eval/results/`.

### Known follow-ups

- **The fiscal-note eval set has queries but no ground truth.**
  `eval/fiscal_note_queries.yaml` holds 12 coordinator-triage-shaped queries
  and `eval/run_eval.py` takes `--corpus fiscal_notes` (with its own results
  filename prefix so a fiscal-note run can never be diffed against a budget
  one). Ground truth is deliberately empty: it must be real chunk_ids from a
  populated corpus, and populating the 2,126-note back catalogue is an
  overnight MinerU run that has not happened. The file says so at the top.
  **This is the one part of Plan 3 that is not finished.**
- The search provider's corpus probe is still startup-only (Plan 2's
  documented trade), so the FIRST ever ingest into an empty data dir needs a
  restart before search leaves the stub. Every later ingest is picked up live.
- Large historical backfills (dozens of books) are smartest run on Destin's
  machine before departure — office CPUs make it a weeks-long grind. The
  catalog + picker make it possible either way.
- FY2024/25 approps summary-section titles were partly unextractable in the
  mockup harvest; the PyMuPDF walk may recover them, humanized filenames are
  the fallback.
- `db/migrations/0001` doc_type enum comment is still stale vs live data.

---

## Standalone consolidation — Plan 4 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S2, S3, S9, S13-read, S15, S16, S19, Invariants 7 + 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — see its
**"Task 8 amendments"** block for the as-shipped HTTP contract, which is what
Plan 5 builds against.

**MCP and YouCoded are gone.** AI Mode is an in-process Python tool loop
talking to OpenRouter. No `ws://localhost:9900`, no PTY, no per-conversation
`.mcp.json`, no separate Node process, no dependency on a running desktop app.
`mcp-server/` and `web/` remain in-tree, unused and still passing their own
tests; deleting both is Plan 5.

- **Harness (`harness/`):** `settings.py` (the shared `settings.json` —
  provider triple per S15, tier→model map per S16, admin username, S19 limits),
  `constants.py` (**`REFUSAL_THRESHOLD = 1.9` is now the single source**;
  three contradictory numbers used to reach the model — 1.9 in the prompt,
  0.65 and 0.30 in stale tool descriptions), `tools.py` (the five tools as
  OpenAI function schemas + `ToolExecutor`), `documents.py` (`create_document`),
  `ledger.py` (S19), `session.py` (the loop), `prompt.py` + `system-prompt.md`.
- **The first-call cap is per-conversation, not per-process.** The Node
  original used a module-level flag because there was one process per session;
  one process now serves the whole office, so that shape would have left user
  B's first question uncapped because user A had already asked one.
- **`retrieval/citations.py`** — cite validation lifted out of the FastAPI
  sidecar module so the harness can call it in-process for either corpus. The
  dead alignment heuristics (6 functions, 2 thresholds, ~10 regex tables, 16
  tests) are deleted; the endpoint-level regression guards that assert the
  check stays dead are kept.
- **Routes (`app/routes/`):** `conversations.py` (create + SSE messages +
  stop + `/api/ai/status`), `pdf.py` (Range-streaming + `/api/chunks/{id}`),
  `documents.py` (token downloads). Conversation registry is in-process,
  LRU-capped at 40, and never evicts a conversation with a turn in flight.
- **Webapp:** the chat stack ported from `web/` into `webapp/src/chat/` and
  `webapp/src/pdf/` — citation extraction (~70 carried specs), chat reducer,
  citation bus, chips, markdown, tool cards, mascot, PDF viewer with
  strict-bbox highlighting, cited-text panel. AI Mode toggle on Budget Search
  and Fiscal Notes (**superseded 2026-07-31** — see the deviation note below);
  Home's AI card goes live when a key is present.
- **Tiers (S16):** Standard (step cap 15, `deep_dive` ignored) and Deep
  Research (cap 50, `deep_dive` allowed). Tier explainer copy lives
  **server-side** in `/api/ai/status` so Plan 5's admin page and the webapp
  cannot drift. Every new conversation starts on Standard.
- **Cost (S19):** month-sharded JSONL ledger on the share, per-user limits with
  overrides and exemptions, warn at 80%, block at 100%. Blocked users get the
  ledger's exact sentence, emitted from one place. Limits are inactive on a
  custom endpoint (S15) because exact costs are unavailable, and that state is
  distinguishable from "allowed because under limit".
- **Invariant 7 is structural, not aspirational.** No tool schema takes a path;
  `harness/documents.py` does not import `store.config`, so it has no way to
  learn where the share is; AST-based tests pin the import allowlist.
  `create_document` writes only to `%LOCALAPPDATA%`.
- **Tests:** 1209 pytest / 36 skipped, 297 webapp vitest. `setup.sh --verify`
  green (it also still runs the retired `mcp-server` 57 and `web` 220 suites).

### Verified end-to-end on 2026-07-31 (real OpenRouter key, real corpus)

Tiers as configured: Standard = `qwen/qwen3.7-plus`, Deep Research =
`moonshotai/kimi-k3`. Driven through the real SSE route, not in-process fakes.

| Check | Result |
|---|---|
| Standard lookup ("ADC General Fund, FY 2025") | 3 retrieves → 1 passing cite. **$0.0127, 50s.** Answer volunteered the AFR-vs-Baseline accuracy hierarchy from the prompt without being asked |
| Refusal (out-of-scope question) | Named its corpus, cited nothing, fabricated nothing, **did not retrieve** (correct — out-of-scope needs no search). $0.0018, 13s |
| `create_document` | Real `.docx` in `%LOCALAPPDATA%\JLBC-Insight\documents\` — Title style, memo header, Heading 2 sections, List Bullets. **Nothing written to the share (Invariant 7 held)** |
| Deep Research (3-year AHCCCS comparison) | 4 retrieves / 41 chunks → a correct 3-year table, 5 passing cites. **$0.563, 295s** |
| Ledger | 20 rows, one per step, real per-call cost, `month_total` $0.61, **0 rows with unknown cost** |
| Key removed | `/api/ai/status` → `available: false`, `"no API key configured"`; **search still returned 20 results**. Restoring the key re-enabled AI Mode with no restart (the mtime cache works) |

**Not verified — needs a human at a browser.** Chip click → PDF opens at the
highlighted bbox, and the source panel's visual behaviour. The logic underneath
has 298 vitest specs, but nobody has watched it render.

### Problems the live run surfaced (model/prompt behaviour, not code defects)

- **Citation discipline is unreliable on memo-shaped asks.** Two identical runs
  of the same `create_document` prompt produced 20 citations (12 passing) and
  then **zero** — the second wrote a memo full of specific dollar figures and
  cited nothing, which is an Invariant 1 failure in practice. The UI degrades
  honestly (this is exactly the shape `RefusalBanner` detects: complete turn,
  retrieved, no verified citation), so an analyst sees "This answer carries no
  verified citation" plus the passages rather than false confidence. But the
  prompt and/or the Standard model needs work before this is trustworthy.
- **Cite failure rate is high when cites ARE emitted** — 12/20 and 5/7 passing
  across runs. Worth reading the failure reasons in a longer dogfood.
- **The download token leaked into answer prose.** The model wrote the raw
  `token: 2DZz_Lf…` into the answer instead of leaving the UI to render the
  link. Output-hygiene rule, not a code bug.
- **Meta-narration still leaks** — "let me search the corpus", "I have what I
  need. Let me write the memo". Note `finalAnswer` concatenates *every* prose
  block including pre-tool narration by design, so it reads worse in the audit
  record than on screen.
- **Deep Research costs ~44× Standard and takes ~5 minutes.** $0.563 vs $0.0127
  on comparable questions. The tier split is doing its job, but the copy should
  probably set the time expectation.

### What review caught that tests didn't

Recorded because the same classes will recur:

- **Starlette never closes a `StreamingResponse` body iterator.** It relies on
  garbage collection, and on the disconnect path the iterator sits in a
  reference cycle. A closed browser tab left a model streaming and billing into
  a dead socket, and left a PDF file handle open (which on Windows also blocks
  re-ingest from overwriting the cached file). Cleanup rides a `BackgroundTask`
  in both routes now. `TestClient` cannot catch this — it buffers a "streamed"
  response into a `BytesIO` before returning it, so `tests/live_request.py`
  drives the real ASGI stack.
- **An abandoned SSE stream used to corrupt the conversation permanently** —
  the assistant `tool_calls` message was in history with no matching reply, so
  every later turn 400'd. `_repair_history()` back-fills cancelled results.
- **`UnicodeDecodeError` is a `ValueError`, not an `OSError`.** One mis-encoded
  byte in a month's ledger shard crashed the spend gate for every user.
- **The old system prompt was lying about the refusal threshold** — it said
  `top_score` is "between 0 and 1" and to refuse below 0.30. Both false since
  the Plan 1 model swap (raw cross-encoder logits, roughly −10..10).
- **A dropped tool call rendered as a successful, empty answer** — Invariant 3's
  exact failure shape.
- **The refusal banner denied citations the analyst could see.** It counted
  tool-block cites only, but the renderer also extracts inline `<cite>` tags,
  which open-weight models emit more often than the models that fallback was
  written for.

### 2026-07-31 — AI Mode moved to its own tab (deliberate deviation from S9)

**Do not "restore fidelity" to S9.** Spec S9 says *"Every corpus page =
zero-inference semantic search + an AI Mode toggle (same search box; off =
results list, on = cited chat answer)."* That is what Plan 4 shipped, and after
using it Destin asked for the opposite: *"I hate that 'AI Mode' is part of the
budget search tab."*

As of 2026-07-31:

- **AI Mode is a destination, not a mode.** New route `/ai` (`webapp/src/pages/Ai.tsx`),
  reached from an **icon-only sparkle pill on the right end of the nav**
  (`.nav-item.nav-ai`, accessible name "AI Mode" via `aria-label` + `title`,
  built to the house glyph's exact recipe). Home's AI card points there too.
- **`Budget Search` is renamed `Budget Documents`.** The route is still
  `/search`; only the pill label and the page's identity changed — it is the
  document browser now, and nothing else.
- **The per-page toggles are gone** from Budget Documents and Fiscal Notes.
  Both pages render their browse surface unconditionally; neither imports the
  chat stack. `AiModeToggle` still exists in `webapp/src/chat/AiModePanel.tsx`,
  imported by nothing (deletion belongs to whoever next edits that file).
- **A corpus picker replaces the two toggles.** Budget documents / Fiscal notes,
  chosen inside `/ai`. This is not cosmetic: the fiscal-note coordinator is a
  primary user in the spec, and dropping the fiscal-notes toggle without a
  replacement would have deleted their "have we written a note like this
  before?" triage path.
- **Switching corpus starts a NEW conversation**, by remounting the component
  that owns `useChat` (`key={corpus}`). This is load-bearing: `useChat` reads
  the corpus only when it lazily creates the conversation and then holds that
  `conversation_id` for the hook's lifetime, so a prop change alone would keep
  answering fiscal-note questions out of the BUDGET corpus — cited and
  confident. Three specs in `webapp/src/pages/Ai.test.tsx` fail if the remount
  is removed. It also gives S16 for free: the tier resets to Standard.
- **AI Mode's gate is now a page, not a dimmed pill.** With no key configured,
  `/ai` renders the server's own explanation and no composer, rather than a box
  that would swallow the analyst's question.
- Webapp suites: **304 vitest** (was 297/298).

### Known follow-ups (Plan 5 unless noted)

**Found during the 2026-07-31 Z13 backfill run (see `~/backfill-progress.log`
on that machine and the ROCm investigation doc). The first two are
handoff-blocking — they degrade the office experience silently.**

- **🔴 `IngestWorker` is constructed at startup but never `.start()`ed.**
  Only the upload POST route starts it. Consequence on the shared drive:
  a colleague's queued job sits untouched until somebody on *that* machine
  uploads something — ingest appears to hang for no visible reason. Start
  the worker in the app factory (`ensure_started`) so any running instance
  drains the queue.
- **🔴 `make_doc_id()` collision silently DROPS a document.** It files
  `detailed-list-pdf` under "approps" regardless of family, so a baseline
  and an approps doc can generate the same doc_id and the second write
  replaces the first. Audited all 5,320 in-scope book docs: exactly one
  true collision today (FY2026 Baseline staff directory vs FY2026 Approps
  "General Fund and Other Fund Adjustments", both `jlbc-approps-fy2026-508`),
  and run order means the substantive doc survives. Fix the id scheme to
  include the family before the next large ingest.
- **Pre-fetched PDFs landed in the wrong directory for ingest.**
  `ingest/cache.py`'s `DownloadCache` writes `data/cached-pdfs/` but the
  worker reads `<data_dir>/pdfs/`. Worked around during the backfill by
  hardlinking 7,479 blobs (0 extra GB). Decide on one canonical location —
  two caches for the same bytes is a trap for whoever maintains this next.
- **`optimize()` never drops superseded LanceDB versions** (previously
  noted, now quantified): 200 MB of on-disk table held 39 MB of live data,
  and the untouched migration-era `budget_chunks` was already ~50% dead
  weight. One-line fix: pass `cleanup_older_than` / expose
  `cleanup_old_versions`. Matters most on the SMB share.
- **Bulk-ingest snapshot mode exists** (`JLBC_INGEST_SNAPSHOT=off`, shipped
  2026-07-31 after the per-document S17 snapshot was measured as O(n²) on a
  bulk run: it re-zips all of `lancedb/` per document). Adopting it during
  the backfill took throughput 89.3 → 96.4 docs/hour and flattened a curve
  that was decaying toward ~25 docs/hour. **Better long-term design: snapshot
  once per BATCH** (per book edition / per fiscal-note session) rather than
  per document, so bulk runs keep protection without the quadratic cost.
- **Safe parallel ingest is the single biggest speedup available.** The
  worker is single-writer by design and concurrent workers would fight over
  each other's in-flight jobs on restart. With per-job claiming under the
  existing lock, a 32-thread machine could cut a multi-day backfill to hours.
- **MinerU 3.4.4 vs the pinned 3.1.6** — measured 1.35× faster on plain CPU
  (28.5s vs 38.5s on an 8-page doc; beats the ROCm GPU path outright),
  device-invariant output, and it fixes a table row-misalignment seen at
  3.1.6. Changes chunk text corpus-wide ⇒ needs an eval-gated evaluation and
  a re-ingest decision. Worth ~16h on a full backfill.
- **ROCm GPU MinerU: tested, rejected, do not re-litigate without new
  evidence.** Works trivially on gfx1151 (torch 2.13+rocm7.2, no
  `HSA_OVERRIDE`), but break-even is ~5 pages against a 2-page corpus median
  (CPU ≈61h vs GPU ≈63h over the real backfill mix — it's an APU sharing one
  power budget), and at MinerU 3.1.6 it produced device-dependent table
  extraction that put a real dollar figure on the wrong budget line. Full
  evidence: `docs/superpowers/investigations/2026-07-31-rocm-mineru-benchmark.md`.

- **Prompt caching is not requested.** The system prompt renders at ~40 KB
  (~13.5K tokens) and is resent on every step — up to 50 in a Deep Research
  turn. Every candidate model prices cache reads ~10× below input. This is the
  single largest cost lever available and it is currently unused.
  **Now spec decision S22 (2026-07-31)** — stable byte-identical prefix +
  `cache_control` via OpenRouter + `cached_tokens` on ledger rows; Plan 5
  implements.
- **Quote-not-found cite failures on faithful quotes.** Models emit quotes
  differing from chunk text only by whitespace/smart-quote/casing artifacts;
  exact-substring validation rejects them and burns retry round-trips.
  **Now spec decision S23 (2026-07-31)** — normalized matching with an index
  map back to original offsets (port the webapp `citation-extract` technique
  server-side into `retrieval/citations.py`) + a quote-short-spans prompt
  nudge; Plan 5 implements.
- **`--chat-*` / `--mascot-*` tokens on `:root`** (16 of them) deviate from
  S12's one-palette rule. The mockup palette is monochrome navy — `--az-red` is
  `#2f55c4`, a blue — so there is no error/warning colour, and a failed-citation
  chip rendered in navy would regress Invariants 1–3. **Worth Destin's eye.**
- **The footer states no corpus size.** It said "382 docs"; Plan 3's upload
  queue falsifies any hardcoded count on first use, and there is no
  corpus-count endpoint to read instead. Restore one when there is.
- Conversation persistence is in-memory per app run (accepted).
- The faithfulness verifier (WS3) and audit-log writer (WS5) remain unbuilt —
  citation enforcement is still chunk-id + quote-in-text + span sanity.
- Four `documents.json` readers now exist (`retrieval/api.py`,
  `harness/tools.py`, `app/search_provider.py`, and `app/routes/pdf.py` reusing
  the harness one). Consolidate into `store/documents.py`.
- Two corpus-name alias tables (`harness/tools.py`, `harness/prompt.py`) that
  normalise in **opposite** directions — merging them naively would be wrong.
- The `chunking.agency_catalog` import guard in `harness/tools.py` can come
  out now that Plan 3 is merged (verified binding: 157 entries,
  `agency:axs` → AHCCCS).
- A DOCX-backed citation in **AI Mode** still shows pdfjs's raw error instead of
  the backend's sentence; the search page gets the friendly wording. One
  `api.chunk()` call in `PdfViewer.Loaded` fixes it.
- The refusal banner evaluates only the latest turn by design; scrolling back
  to an earlier unverified answer shows unbannered prose.
- `eval/calibrate_refusal.py` and `eval/README.md` still tell operators to edit
  `mcp-server/system-prompt.md`; the threshold now lives in
  `harness/constants.py`.
- **Bulk-ingest mode exists (`JLBC_INGEST_SNAPSHOT=off`, 2026-07-31)** — it
  suppresses the per-document S17 snapshot for supervised backfills, because
  zipping the whole corpus once per document is O(n²) (measured: ~54 MB zip
  every ~40 s at 68 MB of corpus; projected 60–90 s/doc after the books).
  Default is unchanged (`per-doc`) and only the literal `off` disables it. The
  better long-term design is a per-BATCH snapshot — once per book edition /
  fiscal-note session rather than per document — which keeps a restore point
  without the quadratic cost.
- **Parallel ingest exists (`JLBC_INGEST_WORKERS=N`, branch
  `parallel-ingest`, 2026-07-31)** — N worker threads each claim their own
  job and extract concurrently; the write phase stays strictly serialized
  behind `IngestLock`. Default is 1 = today's behaviour, and anything that
  isn't a number above 1 (typo, blank, `0`) means 1. The request is clamped
  to `min(8, cpu_count/4)` so the same variable typed on a 4-core office PC
  clamps to 1, and the clamp is announced on stderr. Ownership is decided by
  `ingest/claim.py` — an atomic exclusive-create claim file per job AND per
  doc_id, with a heartbeat thread and stale-steal, mirroring `ingest/lock.py`.
  Measured input: a MinerU extraction averages ~3.2 CPU cores (peak ~7) and
  ~2.1 GB RSS (peak ~3.0 GB) across its 2–3 processes, and is ~90% of a
  document's wall clock. Two pre-existing concurrency defects were fixed on
  the way: the old lock-based claim was a non-atomic read-then-write (two
  workers could both take a job) and it stopped claiming entirely whenever
  any machine held the write lock; and both the lock and claim files could be
  read empty by a racing acquirer mid-create, which read as "corrupt" → "stale"
  → **steal**, i.e. two writers on one corpus. Creation is now a single
  `os.write` and an unreadable file gets 1s to settle before it is judged
  corrupt.

---

> ## ⚠ HISTORICAL FROM HERE DOWN
>
> Everything from this point through the end of the
> "Recently fixed — verify in next dogfood pass" section describes the
> **RETIRED pre-consolidation architecture** — the sidecar on `:9200`, the
> Budget MCP server, the Next.js `web/` UI, Voyage reranking, and Postgres.
> None of it is running code anymore; it is kept only as the historical
> record of what Phase 1c shipped. **Current state is the four
> "Standalone consolidation — Plan N shipped" sections above.** In
> particular: the live refusal threshold is **1.9** in
> `harness/constants.py` — the 0.65 mentioned below is the dead Voyage
> 0..1 score scale.

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
**382 documents / 7,755 chunks** as of 2026-05-12. These counts are
pre-Plan-3: the GUI ingest queue adds documents whenever someone uploads,
so the live numbers come from `/health` and `GET /api/jobs`, not this
table. Coverage at the 2026-05-12 snapshot:

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

Backfill now goes through [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md)
(`PROMPT-volume-ingest.md` is retired — superseded by the Plan 3 GUI queue).

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
3. **`<data_dir>/settings.json`** — only if AI Mode should work on the new
   machine. It carries the OpenRouter key, the tier→model map, the admin
   username and the spend limits. Without it the app runs fine and AI Mode
   reports `no API key configured`, which is the honest state, not a crash.
   It is plain JSON on the share by design (spec S11) — the protection is a
   hard monthly credit cap set on the OpenRouter dashboard, not file secrecy.

**Nothing else travels.** Post-Plan-3 there is no `.env.local` and no Postgres
volume on any path — ingest, retrieval and AI Mode all run off `data_dir()`
plus one optional key.

See [README.md → Moving to a new device](README.md#moving-to-a-new-device) for the exact commands.

### What's installed externally (NOT in the repo)
- Node 20+ and npm (build-time only — the shipped app serves a static bundle)
- Python 3.12 and `uv` (`pip install uv`)
- **Nothing else.** Docker/Postgres were ingest-only after Plan 1 and unneeded
  after Plan 3. The YouCoded/Claude Code dependency (`ws://localhost:9900`)
  died with Plan 4 — AI Mode is an in-process OpenRouter tool loop. An
  OpenRouter key unlocks AI Mode and nothing else; search, fiscal notes and
  upload all work with zero keys, which is a hard spec constraint ("no paid API
  is load-bearing").

---

## Working conventions

- `setup.sh` — one-shot installer for everything regenerable. Run after `git clone`.
- `bash setup.sh --verify` — runs all suites (pytest + 3× vitest). Use before
  merging non-trivial work. Two of those suites (`mcp-server/`, `web/`) cover
  code Plan 4 retired; Plan 5 deletes the suites and the directories together.
  **Capture its exit code directly** (`bash setup.sh --verify > log 2>&1; echo $?`)
  — piping it into `tail` returns `tail`'s status and hides a failure.
- **One process now.** `uv run uvicorn app.main:create_app --factory --port 9300`
  serves the API and the built `webapp/dist`. `npm` is used to build `webapp/`;
  `mcp-server/` and `web/` are dead weight until Plan 5.
- The launch order is: build `webapp/`, then start the one server. There is no
  Docker step, no sidecar, no MCP registration, and no desktop app to run first.

---

## Doc map

Current architecture first:

- [docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md](docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md) — **the consolidation spec** (S1–S21, Invariants 7–8, gates G1–G3). Read this before non-trivial changes.
- [docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md](docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md) — Plan 1: LanceDB + local models (shipped 2026-07-30)
- [docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md](docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md) — Plan 2: app server + search UI (shipped 2026-07-30; its frozen API-contract block is what later plans build against)
- [docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md](docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md) — Plan 3: GUI ingest queue (shipped 2026-07-31)
- [docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md](docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md) — Plan 4: AI Mode (shipped 2026-07-31; see its "Task 8 amendments" for the as-shipped HTTP contract)
- [docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md) — recency-ranking plan (S21; pending)
- [PROMPT-z13-backfill.md](PROMPT-z13-backfill.md) — **the only active handoff** — Z13 backfill + recency calibration runbook
- [README.md](README.md) — how to run it, links
- [STATUS.md](STATUS.md) — this file (current state)
- [CLAUDE.md](CLAUDE.md) — workspace conventions for Claude Code sessions
- [eval/README.md](eval/README.md) — Layer 1 retrieval eval harness: when/how to run, scoring rules, caveats, calibration interpretation

Historical (retired architectures; kept as record, do not build against):

- [docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — original design spec (invariants live on; architecture superseded)
- [docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c (superseded by the consolidation spec)
- [docs/superpowers/decisions/2026-05-06-citation-tool-schema.md](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked `retrieve()` + `cite()` schema (semantics carried into `harness/tools.py`; MCP/sidecar transport gone)
- [docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md](docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md) — dogfood-hardening pass against the retired stack
- [docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md](docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md) — dogfood-test plan for the output-hygiene rewrite
- [docs/superpowers/plans/](docs/superpowers/plans/) — phase plans (not kept in sync with shipped features)
- [data/chunks/MANIFEST.md](data/chunks/MANIFEST.md) — Phase 1a → Phase 1b hand-off contract (live ingest contract is `ingest/` + `store/schema.py`)
- [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md) — eval harness spec (Layer 1; amended 2026-05-22 with what shipped vs diverged)
- [docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md](docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md) — eval harness implementation plan (shipped 2026-05-22, merge `3a26c19`)
- [PROMPT-volume-ingest.md](PROMPT-volume-ingest.md) — retired volume-ingest handoff (superseded by the Plan 3 GUI queue)
