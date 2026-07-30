# Standalone Plan 4: AI Mode — OpenRouter Harness, Tools, Chat UI Port

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cited Q&A over both corpora inside the new app: a Python OpenRouter tool-loop harness (no MCP, no YouCoded), the four tools as in-process functions plus `create_document`, the S16 Standard/Deep-Research tiers with the S19 cost ledger, and the existing chat/citation/PDF-viewer surfaces ported from `web/` into `webapp/`.

**Architecture:** New `harness/` package: `session.py` (the tool loop against OpenRouter's OpenAI-compatible `/chat/completions`, streaming, retry, truncation), `tools.py` (tool schemas + dispatch), `ledger.py` (S19), `settings.py` (share-side `settings.json`), `prompt.py` (rewritten system prompt assembly). New app routes: conversations (SSE), PDF range-streaming, document downloads. Webapp gains the ported chat stack (citation-extract, chat-reducer, chips, mascot, PDF viewer) mounted behind an AI Mode toggle on both corpus pages.

**Tech Stack:** `httpx` (only new Python dep), python-docx (already present), React 18 ports of the `web/` components, `react-markdown`+`remark-gfm`+`rehype-highlight`+`pdfjs-dist` (new webapp deps).

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S2, S3, S9, S13 (read side), S15 (harness side), S16, S19 (enforcement side), Invariants 1–3, 7, 8. Work in a worktree (`~/ask-the-budget-az-worktrees/plan4-ai-mode`).

**Ground truth (READ FIRST, binding — from the 2026-07-30 codebase review):**
- The renderer contract: the ported UI consumes the `ProviderEvent` union (`web/lib/types.ts:119-161`) via SSE frames `data: {json}\n\n` with synthetic `_done`/`_error`. Two hard rules: `assistant_text_delta.text` carries the **full accumulated text per uuid** (the reducer replaces, never appends), and `tool_result.output` is a **JSON-encoded string**.
- Tool contracts to re-express in Python are pinned in `mcp-server/src/tools/*.ts` (schemas + response shapes documented in the review); the first-call cap must become **per-conversation state**, not module-global.
- `retrieval/api.py::_validate_one_cite` is pure and reusable but `_fetch_chunk_text(s)` hardcodes `budget_chunks` — promote both into a corpus-aware `retrieval/citations.py`.
- **Threshold unification:** three contradictory refusal numbers reach the model today (1.9 in `mcp-server/system-prompt.md`, 0.65/0.30 in stale comments/tool descriptions). One Python constant, injected everywhere.
- **Known bug to fix in the port:** the old audit accumulator drops quote-only cites (requires numeric offsets). The Python accumulator must accept quote-only.
- PORT/REWRITE/DIES buckets for every `web/` file are inventoried in the review; `citation-extract.ts` ports with only an import edit; `PdfViewer` swaps `next/dynamic` → `React.lazy`; the PDF route's Range semantics are specified by `web/tests/pdf-route.test.ts`.
- `retrieve()` in-process call pattern is proven by `app/search_provider.py::LanceSearchProvider`; scores are raw logits; `NO_RESULTS_TOP_SCORE = -1e9`.

**PARALLEL-EXECUTION CONTRACT (runs concurrently with Plan 3):**
- This plan owns: `harness/`, `retrieval/citations.py`, `app/routes/conversations.py`, `app/routes/pdf.py`, `app/routes/documents.py`, `webapp/src/chat/**`, `webapp/src/pdf/**`, `webapp/src/pages/Search.tsx`, `webapp/src/pages/Home.tsx`, the successor of `mcp-server/system-prompt.md` (new `harness/system-prompt.md`), its own tests.
- Plan 3 owns: `ingest/**`, `chunking/**`, `store/**`, `app/routes/upload.py|jobs.py|fiscal_notes.py`, `webapp/src/pages/Upload.tsx`, the FiscalNotes rail block, `eval/**`. Do NOT touch these. (Exception: the FiscalNotes **AI toggle** goes in the page-head region of `FiscalNotes.tsx` — coordinate: Plan 3 edits only the rail `.fside-search` block; keep edits disjoint, merge keeps both.)
- Shared append points (keep-both on merge): `app/main.py` `include_router` lines, `App.tsx` routes, `Header.tsx` `NAV_ITEMS` (this plan adds none), `webapp/src/api.ts` additive functions, `app.css` labeled blocks, `STATUS.md` final task.
- New Python dep allowed: `httpx` only (`uv add httpx`). Webapp deps go in `webapp/package.json`.
- Follow shipped conventions: routers above the SPA catch-all; `HTTPException` with real `detail`; page-scoped CSS; `import * as api` pattern.

---

## File structure

| File | Responsibility |
|---|---|
| Create `harness/settings.py` | `settings.json` on the share: provider triple (S15), tier→model map (S16), admin username, per-user limits (S19); atomic read/write; defaults |
| Create `harness/constants.py` | `REFUSAL_THRESHOLD = 1.9` — the single source; re-exported into prompt + tool descriptions |
| Create `retrieval/citations.py` | Corpus-aware promotion of `_validate_one_cite` + chunk fetch (budget + fiscal_note tables); `retrieval/api.py` delegates to it |
| Create `harness/tools.py` | Tool registry: JSON schemas + dispatch for retrieve/cite/cite_batch/list_filter_values/create_document; per-conversation first-call cap |
| Create `harness/documents.py` | `create_document` materialization: markdown → .docx (python-docx) + .md in `%LOCALAPPDATA%\JLBC-Insight\documents\` |
| Create `harness/ledger.py` | S19 usage ledger (JSONL on share) + per-user monthly totals + limit/exemption enforcement |
| Create `harness/session.py` | The tool loop: OpenRouter streaming, tier budgets, retry/backoff, abort, pair-aware truncation, ProviderEvent emission |
| Create `harness/prompt.py` + `harness/system-prompt.md` | Rewritten prompt (CC/MCP-free), primer inlined, threshold injected, tier-aware |
| Create `app/routes/conversations.py` | `POST /api/conversations` (+ inline health), `POST /api/conversations/{id}/messages` (SSE) |
| Create `app/routes/pdf.py` | `GET /api/pdf/{doc_id}` range-streaming from `<data_dir>/pdfs` (fallback `data/cached-pdfs`) |
| Create `app/routes/documents.py` | `GET /api/documents/{token}` download of create_document artifacts |
| Create `webapp/src/chat/**` | Ported: citation-extract.ts, chat-reducer.ts, chat-types.ts, citation-context.tsx, use-chat.ts (SSE client), ChatThread, AssistantTurnBubble, CitationChip, CitedMarkdownContent, MarkdownContent, ToolCard + tool-views (retrieve/cite/list only), UserMessage, MessageInput, WelcomeHero, SuggestionRow, Footer honesty line, mascot/** |
| Create `webapp/src/pdf/**` | Ported: PdfPage, highlight-strategy, CitedTextPanel, PdfViewer (React.lazy) |
| Modify `webapp/src/pages/Search.tsx`, `FiscalNotes.tsx` (head only), `Home.tsx` | AI Mode toggle per corpus page (S9); tier toggle (S16); passage `data-chunk-id` rows open the PDF viewer; Home AI card lights up |
| Tests | Python: `tests/test_harness_settings.py`, `test_citations_module.py`, `test_harness_tools.py`, `test_create_document.py`, `test_ledger.py`, `test_harness_session.py`, `test_conversations_route.py`, `test_pdf_route.py`. Webapp: ported `citation-extract`, `chat-reducer`, `highlight-strategy`, chip/panel/viewer/mascot suites + new toggle/tier tests |

API contracts (frozen for Plan 5):

```
POST /api/conversations
  { "corpus": "budget"|"fiscal_notes" }
  -> { "conversation_id": str,
       "health": { "ok": bool, "reason"?: str },        # ai availability: key present + valid form
       "tier_default": "standard" }

POST /api/conversations/{id}/messages          (SSE response)
  { "text": str, "tier": "standard"|"deep_research" }
  frames: data: {ProviderEvent-JSON}\n\n
  terminal: data: {"type":"_done","stopReason","finalAnswer","citations","retrievedChunkIds","usage":{...,"cost":float|null}}\n\n
          | data: {"type":"_error","message"}\n\n
  -> 402-shaped SSE _error when the user is over their S19 limit
     (message: "You've reached your monthly AI usage limit ($X) — ask <admin> to raise it.")

GET /api/pdf/{doc_id}          -> 200/206 PDF bytes (Accept-Ranges; single bytes=a-b honored)
                                  415 when source_format != "pdf"; 404 unknown doc
GET /api/documents/{token}     -> .docx/.md download (created this session, this user)
GET /api/ai/status             -> { "available": bool, "reason"?: str,
                                    "tiers": {"standard": {...copy...}, "deep_research": {...copy...}},
                                    "user_usage": {"month_usd": float|null, "limit_usd": float|null, "warned": bool} }
```

ProviderEvent shapes (verbatim from `web/lib/types.ts` — the port carries the file):
`user_message{text}` · `assistant_text_delta{text: FULL-accumulated-per-uuid, model?}` · `assistant_thinking{}` · `tool_use{toolUseId, toolName, input}` · `tool_result{toolUseId, output: JSON-STRING, isError?}` · `turn_complete{stopReason, model?, usage?}` — all with `uuid`, `timestamp`.

---

### Task 1: Settings (`harness/settings.py`)

- [ ] Step 1 — failing tests (`tests/test_harness_settings.py`): `load_settings()` returns typed defaults when `<data_dir>/settings.json` absent (no key → `ai_available() == (False, "no API key configured")`); round-trip `save_settings` atomic (tmp+replace); provider triple defaults `{base_url: "https://openrouter.ai/api/v1", api_key: "", provider: "openrouter"}`; custom endpoint honored (S15: `provider: "custom"` + explicit `model` per tier); tier map defaults `{"standard": {"model": ""}, "deep_research": {"model": ""}}` — empty model + key present → `ai_available() == (False, "no model configured — ask the admin")`; S19 fields `{default_monthly_limit_usd: float|None, user_limits: {username: float}, exempt_users: [str]}` with `limit_for(user)` resolution (override > default; exempt → None); admin username field.
- [ ] Step 2 — fail. Step 3 — implement as a frozen dataclass tree + `load_settings(path=None)` (mtime-cached like `_document_metadata`) + `save_settings`. No secrets handling beyond plain JSON — accepted per S11. Step 4 — PASS. Step 5 — commit `feat(harness): shared settings.json — provider triple, tiers, limits, admin`.

---

### Task 2: Corpus-aware citation module (`retrieval/citations.py`)

- [ ] Step 1 — failing tests (`tests/test_citations_module.py`): `validate_cite(body, *, corpus="budget_chunks") -> CiteValidateResponse` reproduces the api.py behaviors (quote resolution, ambiguity rejection with up to 3 positions, span clamps, 500-char soft truncate) — port the relevant `tests/test_api.py` cases against the new module; `fetch_chunk_texts(chunk_ids, *, corpus)` works against `fiscal_note_chunks` (tmp store fixture); `retrieval/api.py` endpoints still green (they now delegate).
- [ ] Step 2 — fail. Step 3 — implement by MOVING `_validate_one_cite` + `_fetch_chunk_texts` bodies into `retrieval/citations.py` with `corpus` parameters (default `budget_chunks`), deleting the dead alignment-check functions (`_check_alignment`, `_check_afr_alignment`, `_normalize_for_match`, `_content_words`, `_numeric_value`, `_expand_dollar_amount`, both threshold constants — the review confirmed they're uncalled), and re-importing from api.py. Step 4 — `uv run pytest tests/test_citations_module.py tests/test_api.py -v` PASS. Step 5 — commit `refactor(retrieval): corpus-aware citations module; delete dead alignment heuristics`.

---

### Task 3: Tools (`harness/tools.py`)

- [ ] Step 1 — failing tests (`tests/test_harness_tools.py`), porting the contract semantics from the review's tool inventory:
  - `TOOLS` registry exposes OpenAI function-calling schemas for the five tools; `retrieve` schema mirrors the zod shape (query required; filters object with the doc_type/publisher enums + `fiscal-note` added; top_k 1..50; intent enum; deep_dive bool) and its description contains the injected `REFUSAL_THRESHOLD` (assert `"1.9" in description` — no 0.30/0.65 anywhere: `grep`-style assertion over all descriptions).
  - `ToolExecutor(conversation_id, corpus, tier)` dispatch: `execute("retrieve", args)` → calls `retrieval.retrieve()` (monkeypatched) with intent-resolved top_k (lookup 5 / compare 12 / analyze 18 / default 15) and returns the JSON string response shape (`chunks[] with doc_title via documents.json lookup, top_score, retrieval_id, counts`); **first-call cap**: first retrieve of THIS executor capped to 5 with `first_call_capped: true` unless `deep_dive` — second call uncapped; a second executor instance is independent (the per-conversation fix).
  - `cite`/`cite_batch` → `retrieval.citations.validate_cite` with the executor's corpus; response shapes `{ok, citation_id, resolved_span_start/end}` / parallel array; citation_id minted here (uuid).
  - `list_filter_values` → agency values resolved to names via `chunking.agency_catalog.id_to_name` (falls back to raw id if Plan 3's module isn't merged yet: import guarded — REMOVE the guard when both plans are merged, noted for Plan 5).
  - `create_document` schema `{title: str, body_markdown: str, format: "docx"|"md"}` → `harness.documents.materialize` (mocked) returning `{ok, download_token, filename}`.
  - **Invariant 7 test**: assert no tool schema contains a parameter named like a path (`path`, `file`, `dir`) and the executor module imports nothing from `ingest` — a cheap structural guard, plus the real one: `ToolExecutor` has no method that writes under `data_dir()` (enforced by code review; test asserts `harness.tools` has no reference to `upsert`/`delete_doc`).
- [ ] Step 2 — fail. Step 3 — implement. Step 4 — PASS. Step 5 — commit `feat(harness): in-process tools — retrieve/cite/cite_batch/list_filter_values/create_document, per-conversation first-call cap`.

---

### Task 4: `create_document` (`harness/documents.py` + `app/routes/documents.py`)

- [ ] Step 1 — failing tests: `materialize(title, body_markdown, fmt, *, user) -> (token, path)` writes under `%LOCALAPPDATA%/JLBC-Insight/documents/` (env-overridable for tests), .docx via python-docx (headings/paragraphs/bullets/tables from a small markdown subset — port the renderer loop from `primer/docx_to_md.py`'s inverse: implement `#`/`##` → Heading 1/2, `-` lists, `**bold**` runs, pipe-tables → Word tables; anything unrecognized becomes a plain paragraph — no silent drops); token is unguessable (`secrets.token_urlsafe`), maps in an in-process registry; route serves the file once with correct content-type + `Content-Disposition` filename; unknown token → 404. NEVER writes to `data_dir()` (test asserts the share tmp dir stays empty — Invariant 7).
- [ ] Step 2 — fail. Step 3/4 — implement, PASS. Step 5 — commit `feat(harness): create_document — downloadable .docx/.md artifacts, local-only storage (Invariant 7)`.

---

### Task 5: Ledger + limits (`harness/ledger.py`)

- [ ] Step 1 — failing tests: `record_usage(user, tier, model, tokens_in, tokens_out, cost_usd|None)` appends one JSON line to `<data_dir>/usage/usage-<YYYY-MM>.jsonl` (atomic append; month-sharded so files stay small); `month_total(user)` sums cost (None costs excluded, token totals kept separately); `check_limit(user, settings)` returns `allowed | warn (>=80%) | blocked` with the filled message strings from S19; exempt users always `allowed`; custom-provider mode (cost None) → limits inactive (`allowed`, reason "custom endpoint").
- [ ] Step 2 — fail. Step 3/4 — implement, PASS. Step 5 — commit `feat(harness): S19 usage ledger + per-user limit enforcement with exemptions`.

---

### Task 6: The tool loop (`harness/session.py`)

- [ ] Step 1 — failing tests (`tests/test_harness_session.py`) against a **fake OpenAI-compatible transport** (httpx.MockTransport streaming canned SSE chunks — no network):
  - Text-only turn: streams `assistant_text_delta` events whose `text` is the FULL accumulated text (assert monotonically growing prefix property), ends `turn_complete{stopReason:"end_turn"}` with usage.
  - Tool turn: model emits a `retrieve` tool_call → executor runs → `tool_use` + `tool_result` (output is a JSON string) events → results appended to messages as `{"role":"tool","tool_call_id",…}` → loop continues → final text.
  - Tier budgets: `standard` stops at step cap 15 with `stopReason:"max_steps"`; `deep_research` allows more (cap 50) — assert via a canned model that calls tools forever.
  - Retry: 429 with `retry-after: 0` retried (backoff schedule [1,2,4]s, patched sleep), 5xx retried, 400 not retried → `_error` with the provider's message extracted (incl. OpenRouter's nested `error.metadata.raw`).
  - Abort: `session.interrupt()` mid-stream ends the turn with `stopReason:"user_interrupt"` and back-fills cancelled tool results so history never ends on a dangling tool_call.
  - Truncation: history over the context budget drops oldest-first, never starting the window on an orphaned tool message (pair-aware — port the YouCoded rule).
  - Usage accounting: request sets `usage: {include: true}`; response usage (incl. `cost` when OpenRouter) flows to `ledger.record_usage` with the session's user + tier; blocked user → the S19 `_error` before any provider call.
  - Quote-only cites reach the audit accumulator (the fixed bug): `citations` in the `_done` summary include a cite made with `quote` and no offsets.
- [ ] Step 2 — fail. Step 3 — implement `HarnessSession(conversation_id, corpus, tier, user, settings, executor=None, transport=None)`:
  - Messages: system prompt (Task 7) + history; OpenRouter call via httpx streaming (`stream=True`, SSE parse of `chat.completions` chunks: `delta.content` accumulation per assistant message uuid, `delta.tool_calls` argument-fragment assembly keyed by index).
  - Emission: an `on_event(ProviderEvent-dict)` callback — the SSE route serializes them verbatim. uuid per assistant message; `assistant_thinking` heartbeat while waiting on first token.
  - Step cap from tier (`TIER_BUDGETS = {"standard": {"max_steps": 15, "deep_dive_allowed": False}, "deep_research": {"max_steps": 50, "deep_dive_allowed": True}}` — executor consults `deep_dive_allowed`: Standard-tier `deep_dive: true` is ignored with a note in the tool result, keeping Standard cheap by construction).
  - Accumulator mirrors the old `sendTurn` product: `finalAnswer` (latest-text-per-uuid joined `\n\n`), `citations` (quote-only accepted), `retrievedChunkIds`, `toolCalls`, `stopReason` → returned for the `_done` frame.
- [ ] Step 4 — PASS. Step 5 — commit `feat(harness): OpenRouter tool loop — streaming, tiers, retry, abort, truncation, ledger`.

---

### Task 7: System prompt rewrite (`harness/system-prompt.md` + `harness/prompt.py`)

- [ ] Step 1 — start from `mcp-server/system-prompt.md` (738 lines) and apply the review's strip list exactly: delete the Claude-Code/MCP/ToolSearch/CLAUDE.md-materialization preamble and "Standard Claude Code tools" section; delete `session_died`; s/session/conversation/ in the first-call-cap prose; inline `data/system-prompt-context.md` (the primer) as a prompt section instead of a file path; keep — verbatim — the constrained-agent contract, route classifier, output hygiene, cite quote recipe, doc lifecycle/3-year table/AFR hierarchy, retrieval recipes, refusal cases with the chunk-preview behavior. Add: tier awareness (one short section: Deep Research = broader iterative retrieval expected; Standard = answer from the first 1–2 retrieves), `create_document` usage guidance (offer for memo-shaped asks; never for simple answers).
- [ ] Step 2 — `harness/prompt.py::build_system_prompt(*, corpus, tier) -> str` renders the template, injecting `REFUSAL_THRESHOLD` from `harness/constants.py` (the template contains `{{REFUSAL_THRESHOLD}}` — a test asserts the rendered prompt contains exactly one threshold value and no stale 0.30/0.65 strings) and a corpus-specific scope paragraph (budget vs fiscal-notes).
- [ ] Step 3 — tests green (`tests/test_harness_prompt.py`: renders, threshold-unified, both corpora, no "Claude Code"/"MCP"/"ToolSearch" substrings). Step 4 — commit `feat(harness): rewritten system prompt — provider-neutral, threshold-unified, tier-aware`.

---

### Task 8: Conversations + PDF + status routes

- [ ] Step 1 — failing tests:
  - `tests/test_conversations_route.py`: create → id + inline `health` (settings without key → `{ok: false, reason}`); message POST streams SSE frames (`data: ` prefix, `\n\n` framing) ending `_done` with the accumulator summary (fake HarnessSession injected via `create_app(session_factory=…)` seam); over-limit user gets the `_error` frame; unknown conversation 404.
  - `tests/test_pdf_route.py`: port `web/tests/pdf-route.test.ts` semantics — 200 full body with `Accept-Ranges`, single `bytes=a-b` → 206 + `Content-Range`, suffix ranges, inverted → 416-or-full-body per the old spec, past-EOF clamped, 415 for `source_format != "pdf"` (with a `detail` telling the UI to use CitedTextPanel), 404 unknown doc. Source resolution: `documents.json` `source_blob_path` relative to `data_dir()` first, repo `data/cached-pdfs/` fallback (dev machines).
  - `GET /api/ai/status` returns availability + tier copy (the S16 explainer strings live server-side so Plan 5's admin page reuses them) + the user's usage/limit snapshot.
- [ ] Step 2 — fail. Step 3 — implement (`StreamingResponse` for SSE; conversation registry in `app.state` — in-process dict, per-machine, conversations are per-user local per spec). Step 4 — PASS. Step 5 — commit `feat(app): conversation SSE + PDF range-streaming + AI status routes`.

---

### Task 9: Webapp port — citation/chat logic layer

- [ ] Step 1 — copy `web/lib/citation-extract.ts`, `web/state/chat-reducer.ts`, `chat-types.ts`, `citation-context.tsx`, `web/lib/types.ts` (ProviderEvent section only) into `webapp/src/chat/`, edits limited to: import paths, deleting YouCoded wire types, deleting the MCP-error branch of `humanizeFailureReason`. Copy their test suites (`citation-extract.test.ts` ~70 cases, `chat-reducer.test.ts`, `citation-bus`) into `webapp/src/chat/__tests__/`.
- [ ] Step 2 — `cd webapp && npx vitest run src/chat` → all ported suites PASS unmodified (that's the port-fidelity gate). Step 3 — commit `feat(webapp): port citation extraction + chat reducer + citation bus (specs carried)`.

---

### Task 10: Webapp port — chat components + mascot

- [ ] Step 1 — `npm install react-markdown remark-gfm rehype-highlight highlight.js`. Port the component set (ChatThread, AssistantTurnBubble, CitationChip, CitedMarkdownContent, MarkdownContent, ToolCard + tool-views minus Edit/Write/Diff, UserMessage, MessageInput, WelcomeHero, SuggestionRow, SystemHealthBanner with rewritten copy, mascot/** tree). Tailwind → CSS: add a `/* ===== chat ===== */` block in `app.css` translating the token names (`bg-panel`→`var(--card)` etc. — map YouCoded's civic-warm tokens onto the mockup navy per spec S12's "one palette" rule) and carry the `.mascot-animate` keyframes from `web/app/globals.css`. Carry the component test suites (chip, panel, tool-card/body/display, mascot, use-mascot-pose, welcome-hero, suggestion-row, banner).
- [ ] Step 2 — vitest green on all carried suites (assertions on Tailwind classnames updated to the new classes — behavior assertions unchanged). Step 3 — commit `feat(webapp): port chat surfaces + mascot to the navy design system`.

---

### Task 11: Webapp port — PDF viewer + search-page source view

- [ ] Step 1 — `npm install pdfjs-dist`. Port `PdfPage`, `highlight-strategy.ts` (+ its test suite), `CitedTextPanel` (+ suite), `PdfViewer` with `React.lazy`; worker via `new Worker(new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url))` (no copy script — Vite handles it; delete nothing from `web/`, it retires wholesale in Plan 5).
- [ ] Step 2 — wire the Search page: clicking a passage row (`data-chunk-id`) opens the viewer side panel for that chunk (fetch chunk metadata through a small additive `GET /api/chunks/{chunk_id}?corpus=` route — add to `app/routes/pdf.py`, returns the RetrievedChunk fields the viewer needs; `stub-` prefixed ids never open the viewer). This gives search-only mode its click-to-source action (the G3 findability check's other half). 415/DOCX sources show CitedTextPanel only.
- [ ] Step 3 — vitest green (ported viewer suites + new search-integration tests: passage click opens panel with the right doc, stub ids inert, DOCX falls back to text panel). Step 4 — commit `feat(webapp): PDF viewer port + search-page source panel`.

---

### Task 12: AI Mode toggle + tiers on the corpus pages

- [ ] Step 1 — failing vitest specs:
  - Search page: an AI Mode toggle in the page header area (mockup pill idiom, `aria-pressed`); OFF = shipped results list unchanged; ON = the same search box submits to a conversation thread rendered below (ChatThread + composer), with the S16 **tier toggle** on the composer (`Standard` default every NEW conversation; toggle copy verbatim from the spec's S16 examples — assert both example strings render in the explainer popover); `api.aiStatus()` gate: unavailable → toggle dimmed with tooltip "AI answers require an API key — ask your admin."; over-limit `_error` renders the block message in-thread.
  - FiscalNotes page (head region only): same toggle pattern, `corpus: "fiscal_notes"`.
  - Home: the AI card flips from `is-disabled` to a live `<Link to="/search">` + "AI Mode available" line when `aiStatus.available` (keep the disabled render otherwise — copy stays honest).
  - use-chat port: SSE parser (`\n\n` frames, `data:` lines, `_done`/`_error`) against a mocked `fetch` ReadableStream.
- [ ] Step 2 — fail. Step 3 — implement (`webapp/src/chat/use-chat.ts` port with the fetch-stream reader; toggle state per page, conversation created lazily on first send; tier resets to standard on new conversation). Step 4 — vitest PASS + `npm run build`. Step 5 — commit `feat(webapp): AI Mode toggle + Standard/Deep-Research tiers on both corpus pages`.

---

### Task 13: Live E2E + STATUS + merge

- [ ] With a real OpenRouter key in `settings.json` (Destin's, temporary) and a real model in each tier slot: scripted dogfood — (1) Standard lookup question → cited answer, chips render, chip click opens PDF at highlighted bbox, CitedTextPanel shows the span; (2) Deep Research sweep question → multiple retrieves observed, answer cites across documents; (3) refusal question → honest refusal, no fabricated cites; (4) create_document request → .docx downloads and opens in Word; (5) ledger rows written with real cost; (6) kill the key → AI toggle dims with the honest reason; search unaffected. Fix what breaks; record transcript notes in the PR/commit body.
- [ ] `bash setup.sh --verify` + both vitest suites green. Run the budget eval once (no retrieval-path changes expected — confirm no regression; commit results only if numbers moved).
- [ ] STATUS.md: Plan 4 section (harness, tools, tiers, ledger, ports, known follow-ups — e.g. RefusalBanner still unwired unless Task 12 wired it, conversation persistence is in-memory per app run). Merge `--no-ff`, push, remove worktree; coordinate with Plan 3's merge (additive conflicts only).

---

## Self-review notes

- Spec coverage: S2/S3 (Tasks 3, 6), S9 (Task 12), S13-read + S15-read (Task 1; admin UI is Plan 5), S16 (Tasks 6, 12 — models per tier configured via settings; actual model *selection UI* is Plan 5, dev sets settings.json by hand), S19 enforcement (Tasks 5, 6, 8; admin panel Plan 5), Invariant 7 (Tasks 3, 4 structural guards), Invariants 1–3 (contract preserved in Tasks 2, 3, 7; WS3 faithfulness verifier remains explicitly out of scope, as in the original app).
- The three-threshold bug and quote-only-audit bug are closed by Tasks 7 and 6 respectively, with tests pinning both.
- Known deliberate gaps → Plan 5: admin/settings UI for everything Task 1 stores; model catalog validation (S13 live checks); `web/` + `mcp-server/` deletion; conversation persistence across app restarts (accepted: in-memory).
