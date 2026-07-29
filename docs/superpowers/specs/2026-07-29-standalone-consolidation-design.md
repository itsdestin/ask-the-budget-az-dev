# Standalone Consolidation — Design Spec

**Date:** 2026-07-29
**Status:** Approved in brainstorming session; awaiting written-spec review
**Supersedes:** the YouCoded-dependent v1 architecture described in
`2026-05-06-phase-1bc-architecture.md` (D-decisions referencing YouCoded, MCP
hosting, and the ws://9900 bridge). Retrieval-pipeline and citation-schema
decisions carry forward except where amended here.

## Why

Destin is leaving JLBC soon. The two work projects on this machine —
**ask-the-budget-az** (budget Q&A with auditable citations) and the **JLBC
Website Revamp** mockup (`C:\Users\desti\JLBC Website Revamp\`, static
HTML/CSS with an in-browser semantic search page and a fiscal-notes
directory) — consolidate into **one self-contained Windows application**
that colleagues can use and feed with new documents after he's gone, with
**zero technical maintenance** beyond uploading/refreshing documents.

Primary post-departure users: budget analysts (search + Q&A) and the
**fiscal note coordinator**, who triages prior fiscal notes for similarity
when a new fiscal note request arrives.

## Hard constraints

- Runs on **standard locked-down JLBC Windows PCs**: no Docker, no admin
  rights, no GPU. Reference hardware: i5-1245U, 16 GB RAM. Chrome and Edge
  are present; **Chrome is the default** launch target.
- Corpus and settings live on a **shared network drive** (UNC path);
  the app installs per-machine.
- **No paid API is load-bearing.** Everything except AI-generated answers
  works with zero keys. One optional key (OpenRouter) unlocks AI Mode.
- **No technical successor.** No auto-update, no telemetry, no component
  that requires a developer to keep working.

## Core invariants

Invariants 1–6 from `CLAUDE.md` carry over unchanged (auditable claims,
verified citations, refusal over hallucination, no automated action on
outputs, no "hallucination-free" language, internal-first).

**New Invariant 7 — AI Mode is read-only against shared state.** The
model-callable tool surface contains no filesystem access of any kind: no
shell tool, no file read/write tool, no path-typed arguments. Corpus tools
are read-only LanceDB queries. The model's only write primitive is
`create_document`, which materializes a user-downloadable artifact in
per-user local storage (`%LOCALAPPDATA%`), never on the network share.
Share writes exist only in the ingest worker, which the harness cannot
reach through any tool, and all share-write code paths go through the
single-writer lock module, which logs its caller.

## Decisions (settled during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| S1 | **Unified single-process Python app** (Approach A). FastAPI serves static React UI, retrieval, harness, ingest queue, scraper. | One bundle, one process, smallest failure surface on machines nobody can debug. Retrieval + eval + MinerU are already Python. |
| S2 | **Drop MCP entirely.** Tools become in-process Python functions. No rebuild on the 2026-07-28 spec. | YouCoded's own native harness uses no MCP; protocol layer between same-process components is pure overhead. Tool *logic* survives verbatim. |
| S3 | **Drop YouCoded.** Harness is a clean-room Python port of the native-model loop pattern (system prompt + tool loop + streaming against an OpenAI-compatible API), talking to **OpenRouter**. | Removes the ws://9900 bridge, PTY, per-conversation `.mcp.json`, and the hard dependency on a running desktop app. |
| S4 | **Local-only retrieval stack; Voyage dropped.** Bundled ONNX models on CPU: embeddings (candidates: EmbeddingGemma-308M, Qwen3-Embedding-0.6B, bge-small — eval picks), rerank (mxbai-rerank-xsmall class). No dual-vector columns, no hosted-embedding upgrade path. | Hybrid BM25+RRF compresses the quality gap; recall@20 already 100%. Dual-stack machinery was the most complexity-adding "optional" feature. Eval-gated (G1 below); embedder stays behind an interface so a hosted rung could be re-added later if ever needed. |
| S5 | **LanceDB** replaces Postgres + pgvector + ParadeDB. One embedded, file-based DB on the share: vectors + native BM25 FTS (tantivy family, same as ParadeDB) + metadata filtering. | No server, no Docker, works on SMB, corpus ≪ 1 GB. |
| S6 | **Shared-drive data layout with single-writer locking.** Unlimited concurrent readers; writes (ingest/refresh) take `ingest.lock` with heartbeat-based stale-lock expiry. | Uploads are rare events; single-writer is a non-constraint in practice. |
| S7 | **Install = unzip to `%LOCALAPPDATA%`; bundled python.org embeddable runtime + prebuilt site-packages** (not PyInstaller). All ONNX/MinerU model weights pre-bundled; first run downloads nothing. | PyInstaller is fragile with torch/MinerU-class deps. No admin rights needed. Offline-first. |
| S8 | **Launcher exe → Chrome app mode** (`chrome.exe --app=http://127.0.0.1:<port>`), fallback Edge, then default browser. Server keeps running when the window closes; relaunch reuses it. | Native-app feel with zero Electron. Chrome/Edge are on every JLBC machine; Chrome is the office default. |
| S9 | **Two corpora, one pattern**: budget documents and fiscal notes. Every corpus page = zero-inference semantic search + an **AI Mode toggle** (same search box; off = results list, on = cited chat answer). | Matches the coordinator triage workflow and the "fancy search without inference" requirement. |
| S10 | **Fiscal notes become a full RAG corpus** with in-app refresh: port the mockup's `fiscal-notes-build/build.py` scraping into the app; refresh diffs azjlbc.gov sessions, downloads only new note PDFs, feeds the normal ingest queue. | Stays current across sessions with zero maintenance; scraper breakage degrades to last-good corpus, loudly but harmlessly. |
| S11 | **Per-user cost tracking + soft-gated admin surface.** Users are Windows usernames. Every OpenRouter call logs exact billed cost (OpenRouter usage accounting) to a ledger on the share. Users see only their own total. One designated admin (username in `settings.json`, transferable) gets an Admin page. | Non-technical admin manages the key and sees costs without advertising individual spend office-wide. Explicitly *not* real security — accepted trade. |
| S12 | **Port, don't redesign (UI).** Home/search/fiscal-notes reuse the JLBC Website Revamp's actual structure and design tokens; AI Mode reuses the existing ask-the-budget chat surfaces. New-build UI (upload, Settings, Admin) is assembled from mockup components. Where chat renders inside mockup-styled pages, chat components adopt the mockup's navy token values — structure from each source, one palette. | Both UIs are already validated; novelty is risk. |
| S13 | **Model selection is admin-only, live-validated.** Analysts never see model names — they choose a *tier* (S16); the admin assigns a model to each tier from a shipped recommendation list (analyst-readable descriptions, per-tier). The list is validated against OpenRouter's live model catalog (`/api/v1/models`) whenever the admin page opens: live pricing shown, vanished models greyed out. Catalog and picker filter to **tool-calling-capable models only** (the harness requires function calling). An "advanced" searchable full-catalog picker sits below the recommendations. If the configured model starts failing (deprecated/outage), the app auto-falls-back down the recommendation order and posts an admin-page notice — AI Mode degrades to a different model, never to a dead feature. | One less concept for users; predictable costs; a hardcoded-only list would rot and break AI Mode with no maintainer. |
| S14 | **Dropped ideas** (considered, rejected): rebuilding the MCP layer on spec 2026-07-28; an MCP shim for staff to use personal claude.ai/ChatGPT subscriptions (web clients require a publicly reachable endpoint — tunnels fail the zero-maintenance and IT-policy tests; user opted to drop the desktop-app variant too); Electron shell; Voyage as an optional upgrade rung. | Recorded so future sessions don't re-litigate. |
| S15 | **Custom-provider escape hatch (admin-enabled).** Admin page "Provider" panel: **OpenRouter (default, recommended)** vs **Custom endpoint** (base URL + API key + exact model ID — any OpenAI-compatible chat-completions endpoint: direct OpenAI/Anthropic/Google compat endpoints, Azure/Bedrock-style gateways, local Ollama on future hardware). The custom pane explains in plain language why someone would use it (state-approved endpoint, OpenRouter terms change, local models) and states the caveats **in the UI itself**: per-user cost tracking degrades from exact dollars to token counts; no model catalog/recommendations/live pricing; the model must support tool calling or AI Mode fails; self-support territory. One click returns to OpenRouter. Harness-side this is only a configurable `base_url`/`api_key`/`model` triple — the protocol is identical. | Future-proofs the sole-key decision (S4/S13) without adding a second supported vendor; costs ~3 lines in the harness plus one admin panel. Added 2026-07-29 at user request. |
| S16 | **Two analyst-facing AI tiers: "Standard" (default) and "Deep Research".** Each tier = an admin-assigned model (S13) **plus a harness effort budget**: Standard keeps the tight progressive-retrieval posture (low step cap ~15, first-call cap active) for quick lookups; Deep Research raises the step cap (~50) and permits `deep_dive` retrieval for broad multi-year sweeps. Every **new** inquiry defaults to Standard; the tier toggle sits on the AI Mode input with plain copy: Deep Research "for open-ended, historical, broad-scope research — e.g. 'a comprehensive accounting of appropriated vs actual expenditures for all border-enforcement programs across the past 10 fiscal years'"; Standard "for quick lookups — e.g. 'how much did we spend on X last year?' or 'did we appropriate money for xyz in FY 2020?'". Ship-time model guidance (illustrative, finalized against the live catalog at implementation): Deep Research = a cost-effective frontier-class open model (e.g. Kimi K3-class); Standard = best opus-level-performance-per-dollar open model (e.g. Qwen-class). Deliberately NOT first-party flagship models (Fable/Opus/GPT) — open-weight alternatives deliver most of the quality at a fraction of the per-token cost. The usage ledger records the tier per call so the admin sees cost by tier. | Cost management that survives Destin's departure: the default path is cheap, the expensive path is a deliberate, explained choice, and the admin can retune either tier's model without touching code. Added 2026-07-29 at user request. |

## Architecture

```
Browser window (Chrome --app mode; fallback Edge)
  Home ─ Budget Search ─ Fiscal Notes ─ Settings ─ [Admin]
  static React build, mockup design system, SSE for chat streaming
        │ http://127.0.0.1:<port>
        ▼
JLBC Insight (working name) — one Python process
  ├─ FastAPI: static files + JSON APIs + SSE
  ├─ Retrieval: BM25 (LanceDB FTS) + dense (local ONNX) + RRF + local rerank
  │             (pipeline logic carried over from retrieval/)
  ├─ Harness: OpenRouter chat-completions tool loop (~400 lines, ported
  │             pattern: step cap 25, backoff w/ retry-after, abort-safe
  │             streaming, pair-aware history truncation)
  │   └─ tools: retrieve · cite · cite_batch · list_filter_values
  │             (+ corpus param) · create_document  — all read-only vs share
  ├─ Ingest worker: persistent queue → MinerU (CPU) → chunkers → embed →
  │             LanceDB atomic flip; single-writer lock; crash-resume
  └─ Fiscal-note scraper (ported build.py) → same queue
        │ file access
        ▼
\\share\...\jlbc-insight-data\
  lancedb\ (budget_chunks, fiscal_note_chunks, jobs, usage_ledger)
  pdfs\  uploads\  settings.json  ingest.lock  logs\
```

### Data layout notes

- `pdfs\` is content-addressed; the PDF viewer streams from it.
- `settings.json`: OpenRouter key, admin username, model default, share
  paths. Readable by anyone with drive access (accepted; spend-capped key).
- Conversations are per-user, per-machine local — never on the share.
- Migration: one-time script (run by Destin) exports Postgres → re-embeds
  locally → writes LanceDB. Eval harness is the acceptance gate.

### Retrieval specifics

- Hybrid shape, intent routing, first-call cap, refusal behavior all carry
  over from the current pipeline.
- Refusal threshold re-calibrated against the local reranker's score
  distribution via `eval/calibrate_refusal.py` (current 0.65 is
  Voyage-specific and invalid after the swap).
- Fiscal-note chunks carry bill number, session, sponsor, and agency
  metadata for the coordinator's filtered similarity triage.
- Embedder/reranker sit behind interfaces; swapping models is a config +
  re-embed operation, not a code change.

### Ingest specifics

- Upload page: drag-and-drop PDF/DOCX, corpus choice, small metadata form
  pre-filled by filename/first-page heuristics.
- Queue states: `queued → extracting → chunking → embedding → live`, with
  per-doc progress in the GUI; journal persisted in LanceDB so restarts
  resume. Failed docs quarantine with reason + retry button; the queue
  never stalls on a bad doc.
- Known publisher layouts keep the tuned per-publisher chunkers; anything
  else gets a general-purpose structural chunker with page/bbox fidelity.
- Search stays live against the old corpus during processing; new docs
  flip searchable atomically.

### Cost tracking / admin

- Ledger row: username, timestamp, tier (S16), model, tokens in/out,
  billed cost (billed cost is null on custom endpoints — S15 — and the
  UI labels those totals "tokens; exact dollar costs unavailable on
  custom endpoints").
- Settings page (everyone): own monthly usage; AI Mode availability
  explainer.
- Admin page (admin username only): monthly/per-user/per-model/per-tier
  costs; key add/replace/test; the S15 Provider panel (OpenRouter
  default vs custom endpoint, caveats stated in the UI); the S13/S16
  model pickers — one slot per tier (Standard / Deep Research), each
  with live-validated recommendations + tool-calling-filtered
  full-catalog search; optional soft monthly budget → warning banner
  (never a cutoff); corpus health + queue; admin transfer; log
  locations.

### Error handling

- Launch health ladder (server → share → DB → models), each failure a
  plain-English full-page message; never a stack trace.
- Share offline: banner + auto-retry; atomic writes mean no corruption.
- OpenRouter failure: in-chat error + retry; key-invalid notices go to the
  admin page; AI Mode failures never affect search.
- Scraper failure: loud error, corpus stays last-good.
- Rolling plain-text logs per machine + on the share.

## Out of scope

- DOCX viewer (bills/fiscal notes render via CitedTextPanel-style text
  fallback when no PDF backing — same as today's stopgap).
- Faithfulness verifier (WS3) and audit-log writer (WS5) remain unbuilt;
  citation enforcement stays chunk-id + quote-in-text + span sanity.
- Multi-office deployment, public access, mobile.
- The other ~24 mockup pages (remain a separate website-proposal artifact).

## Testing & acceptance gates

Carryover: retrieval/eval/chunker pytest (storage layer swapped);
web component tests (citation extraction, chip dedup, PDF matching).
Retired: WS/YouCoded-provider tests, MCP server vitest.
New: harness loop vs mocked OpenRouter (tool loop, retry, truncation,
read-only tool-surface invariant), queue state machine (crash-resume, lock
contention), cost ledger, scraper fixtures, launcher smoke.

Hard gates before handoff:

- **G1 (quality)**: local stack passes the 34-query eval at an agreed bar
  (expectation: recall@5 in the low 80s, recall@20 ≈ 100%). If it craters
  (< ~70 recall@5 after trying ≥ 2 candidate embedders), revisit S4.
- **G2 (migration)**: full corpus migrated; spot-checked citations resolve
  to correct PDF pages/bboxes.
- **G3 (cold start)**: someone who is not Destin installs from a zip on a
  real JLBC machine using a one-page quickstart — search, upload, and an
  AI Mode chat all work without narration.

## Open items (deliberately deferred to the implementation plan)

- Final app name ("JLBC Insight" is a placeholder).
- Exact embedder/reranker model choice (eval decides, G1).
- Chunk-count/latency budgets per page; port assignment strategy.
- Whether the home hero search routes to Budget Search or a merged
  results view (start with routing to the corpus with hits; adjust in
  dogfood).
