# Standalone Consolidation — Design Spec

**Date:** 2026-07-29
**Status:** Approved; Plans 1–4 executed and shipped (see STATUS.md); Plan 5 + Z13 backfill pending
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

**New Invariant 8 — public-record documents only.** The corpus is
solely for documents that are already public record: baseline books,
appropriations reports, fiscal notes, bills, executive budget requests,
agency budget requests, and Annual Financial Reports (AFRs).
Confidential state data must never be uploaded: AI Mode transmits
retrieved chunk text to external inference providers
(OpenRouter/custom endpoints), whose data-retention practices are
inconsistent and likely insufficient for confidential state data.
Enforcement is by clear communication at every ingest point, not
detection (the app cannot reliably classify confidentiality):
(a) the upload page carries an always-visible notice stating the
public-record-only rule and the reason, with the intended document
types listed; (b) the upload metadata form includes a required
"This document is public record" checkbox — a deliberate moment, not
buried fine print; (c) the quickstart/handoff doc and the admin page's
key explainer repeat the rule. The notice also states the flip side
honestly: search-only mode never sends document content anywhere, but
uploading confidential material still places it on the shared drive
and exposes it to anyone using AI Mode later.

## Decisions (settled during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| S1 | **Unified single-process Python app** (Approach A). FastAPI serves static React UI, retrieval, harness, ingest queue, scraper. | One bundle, one process, smallest failure surface on machines nobody can debug. Retrieval + eval + MinerU are already Python. |
| S2 | **Drop MCP entirely.** Tools become in-process Python functions. No rebuild on the 2026-07-28 spec. | YouCoded's own native harness uses no MCP; protocol layer between same-process components is pure overhead. Tool *logic* survives verbatim. |
| S3 | **Drop YouCoded.** Harness is a clean-room Python port of the native-model loop pattern (system prompt + tool loop + streaming against an OpenAI-compatible API), talking to **OpenRouter**. | Removes the ws://9900 bridge, PTY, per-conversation `.mcp.json`, and the hard dependency on a running desktop app. |
| S4 | **Local-only retrieval stack; Voyage dropped.** Bundled ONNX models on CPU: embeddings (candidates: EmbeddingGemma-308M, Qwen3-Embedding-0.6B, bge-small — eval picks), rerank (mxbai-rerank-xsmall class). No dual-vector columns, no hosted-embedding upgrade path. | Hybrid BM25+RRF compresses the quality gap; recall@20 already 100%. Dual-stack machinery was the most complexity-adding "optional" feature. Eval-gated (G1 below); embedder stays behind an interface so a hosted rung could be re-added later if ever needed. **2026-07-29 note:** OpenRouter now offers an OpenAI-compatible `/api/v1/embeddings` endpoint (multi-provider catalog incl. Qwen3-Embedding class). If a hosted embedding rung is ever added, it routes through the existing OpenRouter key — NOT a separate Voyage account. Local embeddings remain the mandatory zero-key floor regardless; rerank is not available via OpenRouter and stays local-only. |
| S5 | **LanceDB** replaces Postgres + pgvector + ParadeDB. One embedded, file-based DB on the share: vectors + native BM25 FTS (tantivy family, same as ParadeDB) + metadata filtering. | No server, no Docker, works on SMB, corpus ≪ 1 GB. |
| S6 | **Shared-drive data layout with single-writer locking.** Unlimited concurrent readers; writes (ingest/refresh) take `ingest.lock` with heartbeat-based stale-lock expiry. | Uploads are rare events; single-writer is a non-constraint in practice. |
| S7 | **Install = unzip to `%LOCALAPPDATA%`; bundled python.org embeddable runtime + prebuilt site-packages** (not PyInstaller). All ONNX/MinerU model weights pre-bundled; first run downloads nothing. | PyInstaller is fragile with torch/MinerU-class deps. No admin rights needed. Offline-first. |
| S8 | **Launcher exe → Chrome app mode** (`chrome.exe --app=http://127.0.0.1:<port>`), fallback Edge, then default browser. Server keeps running when the window closes; relaunch reuses it. | Native-app feel with zero Electron. Chrome/Edge are on every JLBC machine; Chrome is the office default. |
| S9 | **Two corpora, one pattern**: budget documents and fiscal notes. Every corpus page = zero-inference semantic search + an **AI Mode toggle** (same search box; off = results list, on = cited chat answer). | Matches the coordinator triage workflow and the "fancy search without inference" requirement. |
| S10 | **Fiscal notes become a full RAG corpus** with in-app refresh: port the mockup's `fiscal-notes-build/build.py` scraping into the app; refresh diffs azjlbc.gov sessions, downloads only new note PDFs, feeds the normal ingest queue. | Stays current across sessions with zero maintenance; scraper breakage degrades to last-good corpus, loudly but harmlessly. |
| S11 | **Per-user cost tracking + soft-gated admin surface.** Users are Windows usernames. Every OpenRouter call logs exact billed cost (OpenRouter usage accounting) to a ledger on the share. Users see only their own total. One designated admin (username in `settings.json`, transferable) gets an Admin page. | Non-technical admin manages the key and sees costs without advertising individual spend office-wide. Explicitly *not* real security — accepted trade. |
| S12 | **Port, don't redesign (UI).** Home/search/fiscal-notes reuse the JLBC Website Revamp's actual structure and design tokens; AI Mode reuses the existing ask-the-budget chat surfaces. New-build UI (upload, Settings, Admin) is assembled from mockup components. Where chat renders inside mockup-styled pages, chat components adopt the mockup's navy token values — structure from each source, one palette. **Amended 2026-07-30:** the search RESULTS presentation was iterated live with Destin after Plan 2 shipped and now deliberately diverges from the static search subpage's row markup — title-only linked document rows (mockup-index titles via URL join), no visible relevance numbers, no publisher pills, no taglines; per result: passages card (collapsed) then a bottom "Part of X" card with the two-format report chooser modal. The SHIPPED `webapp/src` + Plan 2's "As shipped" note are the S12 reference for search results; do NOT "restore" fidelity to `subpage-search_jlbc.html`'s result rows. | Both UIs are already validated; novelty is risk. |
| S13 | **Model selection is admin-only, live-validated.** Analysts never see model names — they choose a *tier* (S16); the admin assigns a model to each tier from a shipped recommendation list (analyst-readable descriptions, per-tier). The list is validated against OpenRouter's live model catalog (`/api/v1/models`) whenever the admin page opens: live pricing shown, vanished models greyed out. Catalog and picker filter to **tool-calling-capable models only** (the harness requires function calling). An "advanced" searchable full-catalog picker sits below the recommendations. If the configured model starts failing (deprecated/outage), the app auto-falls-back down the recommendation order and posts an admin-page notice — AI Mode degrades to a different model, never to a dead feature. | One less concept for users; predictable costs; a hardcoded-only list would rot and break AI Mode with no maintainer. |
| S14 | **Dropped ideas** (considered, rejected): rebuilding the MCP layer on spec 2026-07-28; an MCP shim for staff to use personal claude.ai/ChatGPT subscriptions (web clients require a publicly reachable endpoint — tunnels fail the zero-maintenance and IT-policy tests; user opted to drop the desktop-app variant too); Electron shell; Voyage as an optional upgrade rung. | Recorded so future sessions don't re-litigate. |
| S15 | **Custom-provider escape hatch (admin-enabled).** Admin page "Provider" panel: **OpenRouter (default, recommended)** vs **Custom endpoint** (base URL + API key + exact model ID — any OpenAI-compatible chat-completions endpoint: direct OpenAI/Anthropic/Google compat endpoints, Azure/Bedrock-style gateways, local Ollama on future hardware). The custom pane explains in plain language why someone would use it (state-approved endpoint, OpenRouter terms change, local models) and states the caveats **in the UI itself**: per-user cost tracking degrades from exact dollars to token counts; no model catalog/recommendations/live pricing; the model must support tool calling or AI Mode fails; self-support territory. One click returns to OpenRouter. Harness-side this is only a configurable `base_url`/`api_key`/`model` triple — the protocol is identical. | Future-proofs the sole-key decision (S4/S13) without adding a second supported vendor; costs ~3 lines in the harness plus one admin panel. Added 2026-07-29 at user request. |
| S16 | **Two analyst-facing AI tiers: "Standard" (default) and "Deep Research".** Each tier = an admin-assigned model (S13) **plus a harness effort budget**: Standard keeps the tight progressive-retrieval posture (low step cap ~15, first-call cap active) for quick lookups; Deep Research raises the step cap (~50) and permits `deep_dive` retrieval for broad multi-year sweeps. Every **new** inquiry defaults to Standard; the tier toggle sits on the AI Mode input with plain copy: Deep Research "for open-ended, historical, broad-scope research — e.g. 'a comprehensive accounting of appropriated vs actual expenditures for all border-enforcement programs across the past 10 fiscal years'"; Standard "for quick lookups — e.g. 'how much did we spend on X last year?' or 'did we appropriate money for xyz in FY 2020?'". Ship-time model guidance (illustrative, finalized against the live catalog at implementation): Deep Research = a cost-effective frontier-class open model (e.g. Kimi K3-class); Standard = best opus-level-performance-per-dollar open model (e.g. Qwen-class). Deliberately NOT first-party flagship models (Fable/Opus/GPT) — open-weight alternatives deliver most of the quality at a fraction of the per-token cost. The usage ledger records the tier per call so the admin sees cost by tier. | Cost management that survives Destin's departure: the default path is cheap, the expensive path is a deliberate, explained choice, and the admin can retune either tier's model without touching code. Added 2026-07-29 at user request. |
| S17 | **Corpus backup + one-click restore.** Before every ingest/refresh write, the app snapshots the LanceDB folder (zip to `<data_dir>\backups\`, rotating last 5). Admin page gets a "Restore last good corpus" action listing snapshots by date with plain-language confirmation. Restore takes the ingest lock like any writer. | The corpus is the app's crown jewels on one shared folder with no technical successor; <1 GB makes snapshots nearly free, and the worst data disaster becomes a two-click recovery. Added 2026-07-29. |
| S18 | **Share-relocation repair flow.** Each install stores the shared-data path in per-machine config (`%LOCALAPPDATA%`), not hardcoded. When the share is unreachable at launch or mid-session, the app shows a repair screen — "Can't find the shared data folder; browse to its new location" — with a folder picker that validates the target (LanceDB present) before accepting. | Over a multi-year horizon IT WILL migrate file servers; without this every install dies simultaneously with no fix path a non-technical user can execute. Added 2026-07-29. |
| S19 | **Per-user spend limits (enforced) + org-wide protections.** Admin sets an optional default per-user monthly dollar limit, per-user overrides, and an exemption list (e.g. the director) — all on the admin page. A user at their limit gets AI Mode disabled until month rollover with a clear in-UI message ("You've reached your monthly AI usage limit ($X) — ask <admin> to raise it"); a warning shows at 80%; search is never affected. The org-wide soft budget banner stays warn-only (S11). Enforcement uses the exact-cost ledger, so limits are active only on OpenRouter; on a custom endpoint (S15) the limits panel shows "inactive — exact costs unavailable" to the admin. The quickstart + admin key explainer also instruct setting a hard monthly credit limit on the OpenRouter dashboard when creating the key — true org-wide enforcement at the provider, zero code. | Real cost control that survives handoff: per-user fairness in-app, catastrophic-spend protection at the provider. Added 2026-07-29 at user request. |
| S20 | **Handoff corpus scope: the walkable era, fully ingested pre-handoff.** Before departure the corpus is backfilled with every edition that has per-agency pages — **Baselines FY2012–2027 and Appropriations Reports FY2005–2026** (~38 editions, ≈4,700 per-agency/summary PDFs) plus the full fiscal-note back catalogue — run on Destin's Ryzen AI Max (Linux) machine, whose resulting `data/insight-data/` becomes the canonical corpus deployed to the office share. The single-file-only era (approps FY1984–2004, baselines FY2007–2011) is deliberately NOT ingested: those editions stay catalogued as viewable "Full report" links only (no per-agency pages exist; the oldest are scans with unknown OCR quality). FY2000/01 approps do not exist on JLBC's site at all. Runbook: `PROMPT-z13-backfill.md`. | The app hands off pre-filled; staff only ever ADD new editions. Decided 2026-07-31. |
| S21 | **Recency-aware retrieval (budget corpus).** Three layers, all eval-gated: (1) a query year-parser (ported from the mockup's search engine: `2019`/`fy19`/`FY 2019` forms) — an explicit year in the query becomes a hard fiscal-year filter unless the caller already passed one; (2) queries naming NO year get a **soft post-rerank recency bonus** (all years remain visible and discoverable — user chose boost over default-filtering, 2026-07-31), weight calibrated by sweep against the expanded eval set: the minimal weight that restores current-set recall after backfill, while historical explicit-year queries (immune via layer 1) stay green; (3) AI Mode prompt guidance — default retrieves toward recent years unless the question is historical/comparative. The refusal threshold is re-calibrated after the boost lands (it shifts the top_score distribution). The **fiscal-note corpus gets layer 1 only** — coordinator triage deliberately seeks similar notes regardless of age; no recency bonus there. Plan: `docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md`. | 20 years of structurally near-identical per-agency pages would otherwise swamp no-year queries — the mockup's own engine carried exactly this machinery (decisive recency when no year is named, negligible when one is) for exactly this reason. Added 2026-07-31. |
| S22 | **Prompt caching is mandatory (harness).** The tool-loop request prefix — system prompt + tool schemas — must be **byte-identical across steps and turns**: no timestamps, no per-turn content, nothing dynamic ahead of the conversation messages (dynamic context goes in user/tool messages, never the prefix). Send `cache_control` breakpoints through OpenRouter for models that require explicit marking (Anthropic-style); rely on implicit prefix caching elsewhere (OpenAI/DeepSeek/Moonshot-style). Record `cached_tokens` from the usage payload on each ledger row (billed cost already reflects the discount since the ledger logs OpenRouter's exact cost). Context-window truncation breaks the prefix when it fires — accepted, rare. Acceptance: a multi-step turn shows nonzero cache reads in usage, and per-step cost visibly drops after step 1. | Measured in the Plan 4 live run: ~13.5K tokens (~40 KB prompt) resent on EVERY step, up to 50 steps per Deep Research turn, while every candidate model prices cache reads ~10× below input. The single largest cost lever in the app, currently unused. Added 2026-07-31 at user request. |
| S23 | **Normalization-tolerant quote validation (cite path).** `retrieval/citations.py` quote resolution gains a fallback when exact substring match fails: normalized matching (NFKC fold, whitespace collapse, smart-quote/dash folding, case-insensitive) with an **index map back to the original chunk text**, so `resolved_span_start/end` always reference original offsets — PDF highlighting and CitedTextPanel depend on that (same normalize+indexMap technique the webapp's `citation-extract` already uses client-side; port its semantics). Ambiguous-quote rejection (multiple occurrences) still applies post-normalization; validation is formatting-tolerant, never semantically looser — Invariant 2 unchanged. Plus one system-prompt nudge: quote SHORT, distinctive spans copied exactly. | Live dogfood shows models emitting quotes that differ from chunk text only by whitespace/quote-glyph/casing artifacts, failing as "quote not found in chunk" and burning retry round-trips on cites that are actually faithful. Added 2026-07-31 at user request. |
| S24 | **The document-type registry is declarative, and carries the ANALYST INSTRUCTION as well as the machine routing.** One file (`data/document-types.yaml`) is the single source of truth for every type: key, analyst-facing label, **allowed source formats**, extractor per format, per-agency flag, validation expectations, and — new — a short **"which file do I upload?"** instruction plus an optional "don't upload this at all, use X instead" redirect. `ingest/dispatcher.py`, `app/routes/upload.py`'s allowlist, and the webapp's upload dropdown all read it through `GET /api/document-types`; the webapp stops hand-maintaining a parallel list. **Format restriction is enforced in the UI, not only on the server**: the file picker's `accept` attribute and the validation message both come from the registry row, so a type declared docx-only cannot have a PDF selected in the first place. Two rows are called out because Destin named them: **`budget-bill` (the Feed Bill / General Appropriations Act) is DOCX-only** — it is the highest-information format the office holds, and a PDF of the same bill loses the structure the DOCX chunker depends on; and **`approps-report` / `baseline-book` carry a redirect, not an upload instruction** (see S25). | Adding a document type is a data change, not edits in Python and TypeScript that must agree. And the moment a non-technical user is choosing a type from a dropdown is exactly the moment the guidance has to be present — guidance that lives in a handbook nobody has open is guidance that does not exist. Added 2026-07-31 at user request. |
| S25 | **For JLBC book editions the correct action is "Add a JLBC book", NOT an upload — and the UI says so.** The corpus stores books as **per-agency pages** (FY2025 Approps = 111 `approps-per-agency` + 4 `detailed-list-pdf`; FY2027 Baseline = 110 per-agency + 15 `s-pdf` + 2 `topic-pdf`), which is what `ingest/book_discovery.py` produces by walking the agency index and the linked TOC. Uploading the **Single File PDF** would ingest a 400+ page book as ONE document, smearing agency stamping across every agency in the state and destroying the per-agency retrieval the whole corpus is built on. Uploading the **Linked TOC** ingests a table of contents — a few pages of links and no budget content. Neither is right, so the upload page must not present a choice between them: selecting an Approps/Baseline type shows a redirect to the book adder, and the per-agency types keep a plain upload path for the one-off case (a single agency page reissued mid-cycle). The Plan 2 report-format chooser keeps both links — for **viewing**, where "single file vs linked TOC" is a real and useful choice. Same two labels, opposite meaning at ingest time; the copy must disambiguate rather than reuse the phrase. | The failure this prevents is silent and expensive: a well-meaning colleague uploads "the Appropriations Report", it succeeds, and the corpus quietly gains one unusable 400-page document while every agency query gets worse. Added 2026-07-31 at user request. |
| S26 | **Route on what the file IS; fall back honestly for what we do not know.** Extraction routing is decided by inspecting the document (a PDF with a structure tree goes to OpenDataLoader for cell fidelity, an untagged one to MinerU) rather than by the type string a user picked from a dropdown — the registry's declared extractor becomes the hint, detection the decider, so a mislabeled upload still extracts correctly. An **unrecognised** type no longer raises: it is detected, extracted, and stamped `extraction_profile: "general"`, with a warning on the job, a flag on the admin queue, and a visible label in search. | Today `ingest/dispatcher.py` raises on any of the 13 known types being absent, so an office with no maintainer cannot ingest a report nobody anticipated — the tool refuses documents it has never seen. But a generic extraction genuinely has weaker provenance than a tuned one, so it must be *visible*, never silent. Added 2026-07-31. |
| S27 | **Per-type post-ingest expectations decide whether a document actually ingested properly.** `ingest/validate.py` grows from two advisory checks into a per-type expectation block read from the S24 registry: a chunks-per-page floor (a 300-page AFR yielding 12 chunks is broken), agency-stamp coverage for per-agency types, provenance completeness (page + bbox), title quality, and a **round-trip spot check** — take a chunk, confirm its text is findable on the page it claims. A document failing a gate is quarantined with a plain-English reason on the queue, not passed with an advisory nobody reads. | "Ingested" and "ingested properly" are different facts, and today only the first is checked. The live Plan 3 run produced a document that was 17% agency-stamped and passed. Added 2026-07-31 at user request. |
| S28 | **One document catalog for every publisher, seeded from the mockup harvest.** `data/jlbc-book-catalog.json` generalises into a catalog keyed by (publisher, doc_type, fiscal_year) covering AFRs, executive budgets, budget bills, agency budget requests and JLBC books, seeded from the website mockup's 5,854-row verified index (`webapp/reference/assets/search/index-lite.js`). Adding next year's AFR is a catalog row plus an in-app "check for new documents", not a code change. **Known limits to record with it:** agency budget requests exist in the harvest for FY2027 only and live on 78 separate agency websites with no shared URL convention, so earlier years are a research project rather than a crawl; and 18 of the 78 are behind bot protection that rejects automated fetches, so they need a human with a browser. | The four document types Destin wants next are already catalogued with verified URLs — the work is a static list and an ingest path, not five scrapers. Added 2026-07-31. |

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
  The source PDFs themselves (currently gitignored in
  `data/cached-pdfs/` on Destin's machine) are copied to
  `<data_dir>\pdfs\` as an explicit Plan 3 task — the viewer depends
  on them and they are not covered by the chunk migration.

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
- Recorded future option (not built): when an OpenRouter key is present,
  a cheap LLM can re-order the top ~20 search-mode results via the
  existing sole key (fractions of a cent per query) — the sanctioned
  upgrade path if search-mode ordering ever bothers real users, given
  local rerankers cap at ~62–69% recall@5 and OpenRouter offers no
  rerank endpoint.

### Ingest specifics

- Upload page: drag-and-drop PDF/DOCX, corpus choice, small metadata form
  pre-filled by filename/first-page heuristics. Carries the Invariant 8
  public-record-only notice and the required "This document is public
  record" checkbox. Duplicate detection by content hash: re-uploading
  an existing document shows "already in the corpus (added <date> by
  <user>)" with an explicit re-process option instead of silently
  double-ingesting.
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
  full-catalog search; the S19 spend-limits panel (default per-user
  monthly limit, per-user overrides, exemption list); optional
  org-wide soft monthly budget → warning banner (warn-only; per-user
  limits are the enforced layer); corpus health + queue; the S17
  "Restore last good corpus" action; admin transfer; log locations.

### Error handling

- Launch health ladder (server → share → DB → models), each failure a
  plain-English full-page message; never a stack trace.
- Share offline: banner + auto-retry; atomic writes mean no corruption.
  Persistently unreachable share → the S18 repair screen (browse to
  the data folder's new location) instead of a dead app.
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
contention), cost ledger + per-user limit enforcement, scraper fixtures,
backup/restore round-trip, launcher smoke. Plan 3 adds a small
fiscal-note eval set (~10–15 coordinator-triage-shaped queries:
"find prior notes similar to this request") so the fiscal-note corpus
has a measured quality bar, not an assumed one.

Hard gates before handoff:

- **G1 (quality)** *(amended 2026-07-29 after the original recall@5 gate
  triggered its stop rule)*: local stack passes the 34-query eval at
  **recall@15 ≥ 90% and recall@20 ≥ 95%**. Rationale for the reframe:
  `retrieve()` returns 15 chunks and AI Mode reads all of them, so
  top-5 ordering is nearly irrelevant to answer quality; the local
  reranker capability gap (best candidates: 62–69% recall@5 vs the
  original 80% bar, with the only stronger model at ~17 s/query on
  office hardware) is an ordering-polish problem, not a
  retrieval-coverage problem (correct chunk in-pool 100%, top-20
  96.6% with arctic-embed-m). **recall@5 remains a tracked, reported
  metric in every eval run** so the gap stays visible if better local
  rerankers appear. Default embedder: arctic-embed-m (768-dim).
- **G2 (migration)**: full corpus migrated; spot-checked citations resolve
  to correct PDF pages/bboxes.
- **G3 (cold start)**: someone who is not Destin installs from a zip on a
  real JLBC machine using a one-page quickstart — search, upload, and an
  AI Mode chat all work without narration. Includes a **search-mode
  findability check** (added 2026-07-29, standing in for the retired
  recall@5 gate): a human runs ~10 real queries on the search page and
  confirms the right document is findable in the first screen of
  grouped results.

## Open items (deliberately deferred to the implementation plan)

- Final app name ("JLBC Insight" is a placeholder).
- Exact embedder/reranker model choice (eval decides, G1).
- Chunk-count/latency budgets per page; port assignment strategy.
- Whether the home hero search routes to Budget Search or a merged
  results view (start with routing to the corpus with hits; adjust in
  dogfood).
