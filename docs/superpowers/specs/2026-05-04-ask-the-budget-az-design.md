---
title: Ask the Budget AZ — Design Spec
date: 2026-05-04
status: approved
authors: Destin Moss, Claude
audience: design implementers, future contributors, internal pilot stakeholders
---

# Ask the Budget AZ — Design Spec

A Q&A system over Arizona state budget documents, designed for JLBC staff and fiscal analysts. The product's core value is **auditable retrieval with provenance**: every claim the system makes links to the exact PDF page and bounding box that supports it.

This spec is the source of truth for v1 architecture, phasing, citation UX, refusal behavior, evaluation, and governance. The implementation plan (forthcoming) is derived from this document.

## 1. Problem Statement

Arizona produces several large, heterogeneous fiscal documents annually:

- **JLBC Baseline Books** — narrative-dense agency-by-agency program descriptions plus appropriation tables. Often 600–900 pages.
- **JLBC Appropriations Reports** — companion to the baseline; line-item appropriations across the state.
- **AGAO Annual Financial Reports (AFRs)** — GAAP-flavored financial statements with restated tables, dense footnotes, fund balance summaries.
- **Governor's Executive Budget proposals** — competing narrative + numbers from the executive branch, formatted differently again.

Fiscal analysts spend significant time **locating** information across these documents and **comparing** how the same program or line item is treated across publishers and fiscal years. The four publishers each name and structure programs differently, and the AFR's restated tables periodically rewrite the historical record.

Existing tools (full-text PDF search, ad-hoc spreadsheets, institutional memory) handle the *find one thing* case poorly and the *compare across publishers* case worse. LLM-based document Q&A is a natural fit, but only if it doesn't introduce a new failure mode (confident hallucination) that's worse than the slow manual workflow it replaces.

## 2. Audience and Use Cases

**Primary audience (v1):** JLBC staff and fiscal analysts. Domain experts. They already know the documents — they need acceleration, not orientation. UI and answer style are dense, terse, cite-heavy. No over-explanation.

**Possible Phase 4 audience:** Public users (journalists, civic researchers, AZ residents). Gated on internal trust metrics. Architectural decisions support but do not assume this transition.

**Primary use cases (in order of frequency):**

1. **Lookup** — "What was the FY25 General Fund appropriation for ADC?" "Find every mention of the Prop 204 expansion in the FY24 baseline book." Fast retrieval, exact citation, LLM mostly locates and quotes.
2. **Comparison** — "How did corrections appropriations change between FY23 and FY25?" "What changed in the AFR notes between 2022 and 2024?" "What's different between the Governor's FY26 proposal and the JLBC baseline?" Cross-document retrieval, side-by-side synthesis.
3. **Synthesis** — "Summarize the major fiscal pressures in the FY25 baseline book." "What does the AFR say about pension liability trends?" Multi-section retrieval, longer-form output. Less frequent but real.

The retrieval architecture must handle all three from day one. The chat/answer UI optimizes for #1 and #2.

## 3. Core Invariants

These override anything else in the system. Violating any of them breaks the trust model.

1. **Every claim is auditable.** No claim renders without a passing citation. The citation chip → exact PDF page + bbox highlight in the side panel. If we can't ground a claim, we don't make the claim.
2. **Citations are verified, not just emitted.** A separate post-generation faithfulness check confirms each citation actually entails the claim. Failed citations are visibly stripped from the rendered answer with an italic note, not silently dropped or quietly accepted.
3. **Refusal beats hallucination.** When retrieval can't find a relevant chunk, or synthesis can't ground an answer, the system says "I can't answer this from the corpus" and shows the raw chunks for the analyst to read. A high refusal rate means the corpus is incomplete or retrieval is weak — both fixable. Confident hallucination is the trust-destroying failure.
4. **Domain experts, not laypeople.** Dense, terse, cite-heavy. No marketing tone. No padded prose.
5. **Internal first, public never until earned.** Phase 4 is gated on hard metrics in §11 of this spec. Phase decisions are reviewed against those metrics; not vibes.
6. **No automated action triggered by system output.** The tool informs analysts; analysts decide. Outputs never drive downstream automation.
7. **No "hallucination-free" or "grounded" marketing claims.** Stanford's 2024 Lexis/Westlaw study measured 17–33% hallucination on tools that marketed as grounded. We're honest about limits or we don't ship.

## 4. System Architecture

> **Reframed 2026-05-06.** The original v1 architecture envisioned a separate "JLBC Budget Agent" companion app on each analyst's machine. v1 instead **piggybacks on a running YouCoded instance** — the user's existing chat client provides the Claude Code session, Pro/Max OAuth, PTY/wrapper machinery, transcript-watcher, and MCP host. The budget app is its own web UI + retrieval backend that connects to YouCoded's existing localhost WebSocket interface (port 9900) and registers an MCP server with two tools (`retrieve`, `cite`). The standalone companion is a **Phase 2** concern, when distributing to analysts who don't already run YouCoded. See `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md` D3 for the rationale.

v1 runtime topology — three tiers, all on the analyst's machine, hard-depending on a running YouCoded instance:

```
┌─────────────────────────────────────────────────────────────────┐
│ ANALYST'S BROWSER                                               │
│  Next.js front-end: chat thread, answer messages with citation  │
│  chips, side-panel PDF viewer (PDF.js +                         │
│  react-pdf-highlighter-extended), refusal banners               │
│  (DOCX HTML viewer + verify-mode toggle deferred to Phase 2)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ BUDGET WEB SERVER (Next.js, on analyst's machine for v1)        │
│  Next.js Server Components + API routes:                        │
│   • Conversation manager (one YouCoded session per chat thread) │
│   • Citation post-verifier (NLI/judge faithfulness pass)        │
│   • PDF byte serving (HTTP range-request, lazy paged)           │
│   • Audit log writer                                            │
└────────┬─────────────────────────┬──────────────────────────────┘
         │                         │
         │ ws://localhost:9900     │ Postgres
         │ (YouCoded remote API)   ▼
         ▼                  ┌──────────────────────────────┐
┌───────────────────────┐   │ POSTGRES + pgvector + ParadeDB│
│ RUNNING YOUCODED      │   │ (local for v1)                │
│ INSTANCE              │   │  • documents                  │
│  • Claude Code session│   │  • agencies                   │
│    per conversation   │   │  • funds                      │
│  • Pro/Max OAuth      │   │  • chunks (vector + BM25)     │
│  • Transcript watcher │   │  • conversations              │
│    (parses tool_use   │   │  • messages                   │
│    blocks)            │   │  • queries (audit log)        │
│  • MCP host (loads    │   │  • eval_runs                  │
│    Budget MCP server) │   └──────────────────────────────┘
└──────────┬────────────┘
           │ MCP (stdio / JSON-RPC)
           ▼
┌───────────────────────────────────────────────────────────┐
│ BUDGET MCP SERVER (Node, registered with YouCoded)        │
│  Tools exposed to any Claude session in YouCoded:         │
│   • retrieve(query, filters) → {chunks, top_score}         │
│   • cite(chunk_id, span_start, span_end, conf, claim_span) │
│  Calls into the Python retrieval pipeline                 │
│  (BM25 + dense + RRF + Voyage rerank-2.5 → top-K)         │
└───────────────────────────────────────────────────────────┘

INGEST PIPELINE (offline, run on Destin's machine for v1):
  raw documents (PDF + DOCX) → per-doc-type extractor routing:
    Tagged PDFs (AFR, Gov State-Agency-Detail)
      → OpenDataLoader-PDF with use_struct_tree=True
      → cell-level JSON + (page, bbox) provenance
    Untagged PDFs (JLBC Baseline, JLBC Approps, Gov Sources-and-Uses)
      → MinerU 2.5 (CLI subprocess)
      → HTML tables + (page, bbox) provenance
    DOCX (budget bills)
      → python-docx
      → JSON + (paragraph_id, cell_id) provenance
  → chunking layer (extractor-aware reader, format-agnostic output)
  → uniform Chunk rows (table chunks + narrative chunks)
  → Voyage-3-large embeddings → Postgres write
  + agency canonical map keyed by JLBC slug (`agency:<slug>`, e.g. `agency:axs` for AHCCCS)
  + cross-cut summary PDFs (JLBC s-PDFs s1–s90) ingested as small focused docs

Why format-aware: budget bills (and likely future legislative artifacts) are
distributed as .docx — a structured XML format where paragraphs, tables,
and headings are tagged explicitly. Converting to PDF and then re-extracting
discards information we already have for free. Native docx ingest is
lossless and deterministic; PDF extraction inherently performs layout
inference that is error-prone on financial docs.
```

### 4.1 Role separation

- **Browser** is dumb: UI only, no business logic.
- **Budget web server** owns conversation management (one YouCoded session per chat thread), faithfulness verification, audit logging, and source-document serving (PDF byte serving via HTTP range; DOCX HTML rendering deferred to Phase 2). **It does not embed the LLM provider directly** — it relays user messages to a YouCoded session via the active `LLMProvider` implementation (see §4.2). This separation lets us swap providers (YouCoded session / standalone companion / Anthropic API / self-hosted) without touching retrieval or UI.
- **Running YouCoded instance** owns the LLM session lifecycle: spawning Claude Code per conversation, Pro/Max OAuth, PTY/wrapper machinery, transcript-watcher (which parses `tool_use` blocks structurally), and MCP host. The budget app does **not** vendor or fork any of YouCoded's internals — it consumes them through YouCoded's existing remote-server interface (port 9900) and MCP config.
- **Budget MCP server** is the seam between Claude (running inside YouCoded) and the budget retrieval backend. Exposes two tools — `retrieve()` and `cite()` — to any Claude session in YouCoded. Implemented as a small Node process registered in the user's MCP config. Calls into the Python retrieval pipeline.
- **Postgres** is the single persistent store. Chunks, vectors, BM25 index, document metadata, agency + fund canonical maps, conversation history, message history, audit log all live in one database. Single backup, single restore.

### 4.2 Provider abstraction

The budget web server defines an `LLMProvider` interface that abstracts how a chat turn is relayed and how citations come back:

```ts
interface LLMProvider {
  // Append a user message to an existing conversation; stream events back
  // (assistant text, tool_use blocks for retrieve/cite, attention state).
  sendTurn(args: {
    conversationId: string;     // 1:1 mapping to an underlying chat session
    userMessage: string;
    onEvent: (e: ProviderEvent) => void;   // streaming hook
  }): Promise<{
    finalAnswer: string;
    citations: Citation[];      // parsed from cite() tool calls
    retrievedChunkIds: string[]; // union of chunks across all retrieve() calls this turn
    refusal?: RefusalReason;
  }>;

  startConversation(): Promise<{ conversationId: string }>;
  endConversation(id: string): Promise<void>;
}
```

Implementations:
- **`YouCodedSessionProvider`** (v1 default; only one shipped in Phase 1c) — opens a session on the analyst's running YouCoded instance via `ws://localhost:9900`. Uses YouCoded's existing Pro/Max OAuth. Tool calls (`retrieve`, `cite`) flow through the registered Budget MCP server; the provider parses YouCoded's transcript stream for `tool_use` blocks. Hard-depends on YouCoded being installed and running.
- **`LocalCompanionProvider`** (Phase 2) — runs a standalone companion process (lifts YouCoded's PTY/wrapper code into the budget repo). Use case: distributing the budget app to analysts who don't run YouCoded. Same MCP-tool-call shape as v1.
- **`AnthropicAPIProvider`** (Phase 3+) — direct Anthropic API. Different billing path; used when the budget app deploys publicly (Phase 4) or for a shared-org pilot.
- **`SelfHostedLLMProvider`** (Phase 4 option) — open-weight model.

All implementations conform to the same interface. v1 ships `YouCodedSessionProvider` only; the others slot in as their use cases become real.

## 5. Data Flow (Multi-Turn Conversation)

> **Reframed 2026-05-06.** The original flow described a single-query pipeline with a server-side classifier and decomposer. v1 uses **constrained agent-pattern retrieval**: each conversation is a multi-turn YouCoded session, and Claude itself drives `retrieve()` calls per turn (the system prompt requires at least one retrieve() call before answering any user question). Anaphora resolution, comparison decomposition, and multi-step retrieval all happen inside the model's reasoning rather than in a server-side classifier. See decisions doc D4 + D7.

### Turn 1 (new conversation)

1. Analyst types in budget UI: *"How did ADC General Fund appropriations change between FY23 and FY25?"*
2. Budget web server creates a new conversation row, calls `LLMProvider.startConversation()` → opens a fresh YouCoded session, streams the user message in.
3. Inside YouCoded, Claude (with the budget system prompt loaded) reasons that this is a comparison query needing two retrievals. Claude calls the MCP `retrieve()` tool twice (or more):
   - `retrieve(query="Department of Corrections General Fund appropriation", filters={fiscal_year: 2023, agency_canonical_id: ["agency:adc"]})`
   - `retrieve(query="Department of Corrections General Fund appropriation", filters={fiscal_year: 2025, agency_canonical_id: ["agency:adc"]})`
4. The Budget MCP server receives each call → invokes the Python retrieval pipeline (BM25 top 200 + dense top 100 → RRF fuse → Voyage rerank-2.5 → top 20) → returns `{chunks, top_score}`. If `top_score` is below the calibrated refusal threshold, the system prompt instructs Claude to refuse with `refusal_no_retrieval` for that retrieval.
5. Claude reads the returned chunks, synthesizes a comparison answer, and emits `cite(chunk_id, span_start, span_end, confidence, claim_span)` tool calls per claim. Answer + tool calls stream back to the budget web server through YouCoded's transcript-watcher.
6. **Faithfulness check** (post-streaming): budget web server runs each citation through an NLI/judge pass — does this chunk's `[span_start..span_end]` entail `claim_span`? Citations below the threshold are downgraded to ⚠ and the supported claim text is **stripped** from the rendered answer (replaced with `[claim removed: no supporting source]`).
7. Browser renders the cleaned answer with citation chips. Click a chip → side panel jumps to PDF page, scrolls cited region into center, paints yellow rect on bbox.
8. Whole turn (user message, tool calls + arguments, retrieved chunk IDs, reranker scores, chunks visible to Claude, citations emitted, faithfulness verdicts, final rendered answer, refusal type if any, latency) logged to `messages` + `queries` tables, scoped under the conversation.

### Turn 2+ (follow-up in same conversation)

9. Analyst types: *"What about FY24?"*
10. Budget web server appends to the existing conversation; relays to the same YouCoded session via `LLMProvider.sendTurn()`.
11. Claude has full conversation history (prior user message, prior retrieve() calls, prior answer). It calls `retrieve(query="Department of Corrections General Fund appropriation", filters={fiscal_year: 2024, agency_canonical_id: ["agency:adc"]})` — anaphora resolved natively because the model has the context.
12. Steps 5–8 repeat for the new turn; new `messages` row + new `queries` row scoped under the same conversation.

### Notes on the agent pattern

- **Retrieval is gated.** The system prompt requires at least one `retrieve()` call per turn. Claude cannot answer from training data alone. Refusal is enforced at the MCP-tool-result level: if every retrieve() on a turn returns no chunks above threshold, Claude refuses.
- **General Claude Code tools (Bash, Grep, Read) remain available.** Claude can read raw chunk files, grep for terms, or inspect PDF text directly when retrieval missed something or the analyst asks for verification. Retrieval is the primary path; general tools are the fallback path.
- **Eval bypasses the agent.** WS8 measures recall by calling the Python retrieval pipeline directly (single-shot mode). The agent layer gets a separate end-to-end eval focused on faithfulness and citation validity.

## 6. Data Model (v1)

> **Reframed 2026-05-06.** Three changes from the original schema, all driven by the v1 architecture decisions:
> 1. `chunks.agency_canonical_id TEXT` (scalar) → `chunks.agency_canonical_ids TEXT[]` (array). Mirrors `chunks.fund_mentions TEXT[]` already added in Phase 1b. Resolves the cross-cut single-agency-stamping bug from chunk-shape D6 without re-chunking. See decisions doc D2.
> 2. Add `funds` table — Phase 1a built the catalog; Phase 1b persists it. Plus `chunks.fund_canonical_id` + `chunks.fund_mentions TEXT[]`.
> 3. Add `conversations` + `messages` tables — multi-turn chat is the v1 UX (decision D4). The `queries` table becomes per-assistant-turn audit, FK'd to `messages`.

Postgres schema:

```sql
-- Documents in the corpus
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  publisher TEXT NOT NULL,          -- 'jlbc' | 'agao' | 'governor' | 'legislature'
  doc_type TEXT NOT NULL,           -- 'baseline-book' | 'approps-report' | 'afr' | 'governors-budget' | 'budget-bill' | ...
  fiscal_year INT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT,
  source_format TEXT NOT NULL,      -- 'pdf' | 'docx' (extensible to 'html', 'xml', etc.)
  source_blob_path TEXT NOT NULL,   -- where the original file lives; served via HTTP range (PDF) or on-demand HTML render (DOCX)
  page_count INT,                   -- nullable; populated for PDFs only
  ingested_at TIMESTAMPTZ NOT NULL,
  extractor TEXT NOT NULL,          -- 'mineru-2.5' | 'opendataloader-2.4.1' | 'python-docx' | 'sonnet-vision'
  extractor_version TEXT NOT NULL
);

-- Canonical agency map (Tier 1 entity resolution)
CREATE TABLE agencies (
  agency_id TEXT PRIMARY KEY,             -- e.g., 'adc'
  canonical_name TEXT NOT NULL,           -- 'Department of Corrections'
  short_name TEXT,                        -- 'ADC'
  aliases TEXT[] NOT NULL DEFAULT '{}'    -- ['Adult Corrections', 'Corrections Department', ...]
);

-- Canonical fund catalog (parallels agencies)
CREATE TABLE funds (
  fund_id TEXT PRIMARY KEY,               -- e.g., 'aviation'
  canonical_name TEXT NOT NULL,           -- 'Aviation Fund'
  short_name TEXT,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  present_in TEXT[] NOT NULL DEFAULT '{}' -- ['jlbc-s18', 'jlbc-bd2', 'agao-afr']
);

-- Chunks: the retrieval atom
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  text TEXT NOT NULL,
  embedding vector(1024),                  -- Voyage-3-large output dim
  -- Provenance is polymorphic by source format. PDF sources populate (page, bbox);
  -- DOCX sources populate source_anchor with paragraph and cell ids. The CHECK
  -- constraint enforces that at least one provenance shape is present.
  page INT,                                -- nullable; PDF-source chunks only
  bbox NUMERIC[],                          -- nullable; PDF-source chunks only ([x1, y1, x2, y2] in PDF points; multi-rect = flattened)
  source_anchor JSONB,                     -- nullable; non-PDF chunks. Shape for docx: {"paragraph_id": "p47", "table_cell_id": "tbl3.r5.c2"}
  section_path TEXT[],                     -- ['Department of Corrections', 'Operating Lump Sum', 'County Reimbursement']
  -- Stamping: array because cross-cut tables (e.g. s18 funds×agencies) cover ~25 agencies.
  -- Whole-table chunks stamp ALL agencies; per-agency narrative chunks stamp one.
  -- "Primary agency" status, when needed, is recoverable from section_path[0].
  agency_canonical_ids TEXT[] NOT NULL DEFAULT '{}',  -- entries reference agencies(agency_id)
  fund_canonical_id TEXT REFERENCES funds(fund_id),   -- primary fund for the chunk (nullable)
  fund_mentions TEXT[] NOT NULL DEFAULT '{}',         -- all funds mentioned in the chunk
  fiscal_year INT,                         -- denormalized from documents for fast filter
  doc_type TEXT NOT NULL,                  -- denormalized
  is_table BOOLEAN NOT NULL DEFAULT FALSE,
  table_html TEXT,                         -- preserved for is_table=true chunks
  token_count INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((page IS NOT NULL AND bbox IS NOT NULL) OR source_anchor IS NOT NULL)
);

-- BM25 index lives here via ParadeDB pg_search; not a separate table
CREATE INDEX chunks_bm25 ON chunks USING bm25 (chunk_id, text)
  WITH (key_field = 'chunk_id');

-- Dense vector index
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);

-- Metadata indexes
CREATE INDEX chunks_fiscal_year ON chunks (fiscal_year);
CREATE INDEX chunks_doc_type ON chunks (doc_type);
CREATE INDEX chunks_agency_ids_gin ON chunks USING gin (agency_canonical_ids);
CREATE INDEX chunks_fund_id ON chunks (fund_canonical_id);
CREATE INDEX chunks_fund_mentions_gin ON chunks USING gin (fund_mentions);

-- Conversations: top-level chat thread
CREATE TABLE conversations (
  conversation_id UUID PRIMARY KEY,
  user_id TEXT,                            -- nullable in v1 (single-user); used in Phase 3+
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  llm_provider TEXT NOT NULL,              -- 'youcoded-session' | 'companion' | 'anthropic-api' | ...
  external_session_id TEXT                 -- maps to YouCoded's session id (or whatever provider tracks)
);

-- Messages: one row per user/assistant turn, ordered within a conversation
CREATE TABLE messages (
  message_id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(conversation_id),
  parent_message_id UUID REFERENCES messages(message_id),  -- chains turns within a conversation
  role TEXT NOT NULL,                      -- 'user' | 'assistant' | 'system'
  content TEXT NOT NULL,                   -- raw text (assistant content is the rendered answer post-faithfulness)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX messages_conversation_created ON messages (conversation_id, created_at);

-- Per-assistant-turn audit log (one row per assistant message worth retrieving for)
CREATE TABLE queries (
  query_id UUID PRIMARY KEY,
  message_id UUID NOT NULL REFERENCES messages(message_id),  -- the assistant message this audits
  raw_user_message TEXT NOT NULL,                            -- the user message that triggered this turn
  retrieve_calls JSONB NOT NULL,                             -- list of {query, filters, returned_chunk_ids, reranker_scores, top_score}
  cite_calls JSONB NOT NULL,                                 -- list of {chunk_id, span_start, span_end, confidence, claim_span}
  faithfulness_verdicts JSONB,                               -- per-citation NLI/judge results
  refusal_type TEXT,                                         -- 'refusal_no_retrieval' | 'refusal_synthesis' | 'refusal_out_of_scope' | NULL
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX queries_message ON queries (message_id);

-- Eval runs (regression test results)
CREATE TABLE eval_runs (
  run_id UUID PRIMARY KEY,
  ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  git_sha TEXT NOT NULL,
  total_queries INT NOT NULL,
  faithfulness_pass_rate REAL NOT NULL,
  refusal_rate REAL NOT NULL,
  per_query_results JSONB NOT NULL
);
```

Programs and sub-program canonicalization (Tier 2) is **deferred**; sub-program hits are surfaced with their original names. See §8 for the staged rollout.

## 7. Phasing

| Phase | Scope | Where it runs | Users |
|---|---|---|---|
| **Phase 0 — Investigation** ✓ closed 2026-05-06 | Extractor bake-off, entity-resolution catalog, chunking validation. See `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` (memo), `2026-05-05-chunk-shape-decisions.md` (chunking), `2026-05-06-data-model.md` (source-data model). | Destin's machine | Destin |
| **Phase 1a — Ingest + chunking** ✓ closed 2026-05-06 (slice-validated) | Discovery + per-doc-type extractor dispatch + chunking layer + entity stamping + fund catalog. Tag `phase-1a-validated-slice` (commit `9ba0385`). 5 docs / 161 chunks / 91.3% agency-stamped / 227 funds. Pipeline proven on real source; full-corpus ingest deferred to Phase 1b kickoff. Hand-off contract at `data/chunks/MANIFEST.md`. | Destin's machine | Destin |
| **Phase 1b — Storage + retrieval** | Postgres + pgvector + ParadeDB. Loader, embedding pipeline (Voyage-3-large), hybrid retrieval (BM25 + dense + RRF + rerank), MCP-tool exposure of retrieve(). End-to-end `retrieve(query, filters) -> {chunks, top_score}` callable as both Python (eval) and MCP tool (production). Reframed 2026-05-06 to **vertical slice** scope: builds on the existing 5-doc / 161-chunk slice; full Week-1 ingest decoupled, runs concurrently or after. Query classifier + decomposer collapse — Claude does that work via tool-call sequences. ~2–3 weeks. Plan at `docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`. | Destin's machine | Destin (dogfooding) |
| **Phase 1c — Synthesis + UI** | Budget MCP server (retrieve, cite tools), `YouCodedSessionProvider` implementation of `LLMProvider`, multi-turn chat UI, citation chips, side-panel PDF viewer (PDF.js + react-pdf-highlighter-extended), NLI faithfulness verifier, refusal triggers, audit log writes. v1 hard-depends on a running YouCoded instance for synthesis. DOCX viewer + verify-mode toggle deferred to Phase 2. ~2–3 weeks. Plan at `docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`. | Destin's machine + running YouCoded instance | Destin (dogfooding) |
| **Phase 2 — Standalone companion + first deploy** | Build the standalone JLBC Budget Agent companion (lifts YouCoded's PTY/wrapper into a separate process so the budget app can run without YouCoded installed). Add DOCX HTML renderer + verify-mode toggle. Deploy web app to free tier. Onboard 2–3 trusted analysts. ~2–3 weeks. | Vercel/Supabase + each analyst's machine | Destin + 2–3 analysts |
| **Phase 3 — Internal pilot** | Wider JLBC use. Tier 2 entity resolution informed by real query logs. Eval set expansion. | Same | Wider JLBC |
| **Phase 4 — Public-launch consideration** | Gated on metrics in §11. Probably switches LLM provider to API mode (no companion app for the public). | Same + public host | Public, if trust is established |

Tier 0 / Phase 0 is the **only** phase where we make irreversible architecture decisions. Each subsequent phase adds capability on top.

## 8. Phase 0 Investigation (Concrete Plan)

> **Status: closed 2026-05-06.** Outcomes captured in:
> - `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` — findings memo (settled decisions, deferred decisions, Phase 1 readiness)
> - `docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md` — chunk-shape decisions D1–D7
> - `docs/superpowers/investigations/2026-05-06-data-model.md` — JLBC publishing structure, s-PDFs, slug-as-canonical-id, multi-year corpus
>
> Notable scope changes during execution:
> - **Goal 1 (winner extractor) became per-doc-type routing** — no single winner; ODL for tagged PDFs (AFR, Gov), MinerU for untagged (JLBC), python-docx for DOCX. Documented in §9 stack table below.
> - **Goal 2 (entity catalog) was bootstrapped from publisher data** — JLBC's per-year agency-index PDFs gave us 132 canonical agencies with stable slugs going back to FY 2015. `samples/entity-catalog.yaml`.
> - **Discovery of JLBC's four parallel publishing layouts** (singlefile + link-nav + per-agency PDFs + cross-cut s-PDFs) — this changes the Phase 1 ingestion shape; see data-model doc §2-§3.
>
> The original concrete plan below is preserved as the historical record of how Phase 0 was scoped.

The only phase that produces a memo instead of code. Goal: make irreversible architecture decisions on real data.

### 8.1 Sample corpus

~6–8 PDFs picked to surface every failure mode we know of:

- 1× JLBC Baseline Book FY25 (current)
- 1× JLBC Baseline Book FY23 (older, for cross-year testing)
- 1× JLBC Appropriations Report FY25
- 1× AGAO Annual Financial Report FY24 (different formatting, GAAP, restated tables)
- 1× Governor's Executive Budget FY26
- 1–2× misc (fiscal note, supplement)

Stored in `samples/raw-pdfs/` (gitignored if too large; metadata committed).

### 8.2 Extractor bake-off

Both **MinerU 2.5** and **OpenDataLoader-PDF** run on the same ~20 deliberately-chosen pages. (Originally Docling was the second extractor; pivoted 2026-05-05 — see Phase 0 plan intro.) Pages chosen:

- A 5+ page appropriations table with merged headers
- A restated AFR fund-balance table with footnote chains
- A multi-column narrative program description
- A fiscal note mixing prose and tables
- A footnote-heavy schedule
- A page where the same line item appears under different names across two doc types

Manual scoring on:
- **Cell-level numeric accuracy** (~20 cells per table)
- **Bbox quality** — does the reported bbox actually surround the right text?
- **Multi-page table reassembly**
- **Section header detection**
- **Footnote attachment**

Output: scorecard at `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md`. Winner = v1 primary; loser = documented fallback.

### 8.3 Entity-resolution catalog

Manually pick ~20 fiscal entities at three levels and document their names across all four doc types:
- Agency level (~10): hypothesis trivial, confirm
- Program level (~7): hypothesis tractable but messy, catalog variance
- Sub-program / line item (~3): hypothesis very messy, likely Tier 2

Output: `data/entity-variance-catalog.csv` plus a confidence rating per tier in the bake-off memo.

### 8.4 Chunking shape validation

Take the winning extractor's output, manually mark up where chunks should split. Validate the structure-aware approach (section boundaries, tables atomic, 512-token target / 1024 max) against real Arizona content.

### 8.5 Phase 0 deliverables

1. `samples/raw-pdfs/` — the 6–8 PDFs
2. `samples/extractor-output/` — JSON+Markdown side-by-side
3. `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md` — scorecard + memo
4. `data/entity-variance-catalog.csv` — entity name catalog
5. **Go/no-go decision** for Phase 1: does open-source quality clear the bar? If both extractors choke (most likely on AFR restatements), revisit the paid-extractor question with concrete data.

## 9. v1 Stack Decisions

| Layer | Choice | Why |
|---|---|---|
| **Format-aware ingest router** | Trivial extension-based dispatch (`.pdf` → PDF path, `.docx` → DOCX path) | Native processing of structured formats avoids the lossy `docx → pdf → re-extract` round-trip. |
| **PDF extraction (tagged docs: AFR, Gov State-Agency-Detail)** | OpenDataLoader-PDF v2.4.1 with `use_struct_tree=True` | Tagged PDFs carry a structure tree; ODL surfaces it as cell-level JSON with row/col indices. Apache-2.0, JDK-only, ~15× faster than MinerU. (Replaces Docling, which proved unworkable on Windows — see Phase 0 plan "Pivot — 2026-05-05".) |
| **PDF extraction (untagged docs: JLBC Baseline, JLBC Approps, Gov S&U)** | MinerU 2.5/3.x via CLI subprocess | Untagged PDFs lose column structure under ODL; MinerU detects tables and emits HTML with row/col attribution. Validated in Phase 0 inspection on JLBC pages 164/513. |
| **PDF extraction (escalation, deferred)** | Claude Sonnet/Opus 4.x vision | Defer to Phase 1+ if MinerU's residual error rate proves unacceptable. Three response strategies in chunk-shape D-defer-1: accept + UI surfacing / confidence-flagging / custom JLBC extractor. |
| **DOCX extraction** | `python-docx` direct | Reads the .docx XML directly. Lossless: paragraphs, tables, headings, and styles are explicit in the source. No layout inference needed. |
| **Chunking** | Structure-aware, tables atomic, 512-token target / 1024 max, ~15% overlap | 2026 consensus for financial RAG (recall 0.877 vs. 0.759 for semantic-only chunking). |
| **Vector + lexical store** | Postgres + pgvector + ParadeDB pg_search | Single store, transactional metadata, easy SQL fan-out for comparison queries. Fits free tier (Supabase or Neon). |
| **Embeddings** | Voyage-3-large | Measurably leads MTEB on legal+financial sub-benchmarks. 1024-dim. |
| **Reranker** | Voyage rerank-2.5 (or Zerank-1 for cost) | Strong financial/legal performance; ~600ms. Pull 200 BM25 + 100 dense → fuse RRF → rerank → top 20 returned from each `retrieve()` tool call. |
| **Query routing + decomposition** | **Constrained agent-pattern** — the LLM does it via tool-call sequences | Reframed 2026-05-06 (decision D7). Phase 1b's original server-side classifier + decomposer collapses. Claude calls `retrieve()` one or more times per turn (system prompt requires ≥1 call before answering). Anaphora resolution + comparison decomposition + multi-step retrieval all fall out of conversation context. Eval bypasses the agent and calls retrieval directly for deterministic recall measurement. |
| **v1 chat host** | **Running YouCoded instance** (port 9900) | Reframed 2026-05-06 (decision D3). Provides Claude Code session, Pro/Max OAuth, PTY/wrapper, transcript-watcher (parses `tool_use` blocks), MCP host. Budget app is a thin client; v1 hard-depends on YouCoded being installed AND running. Standalone companion is a Phase 2 concern. |
| **Custom tools (retrieve, cite)** | **Budget MCP server** — Node, registered in YouCoded's MCP config | Native shape for custom Claude Code tools. `@modelcontextprotocol/sdk` Node implementation. Single process, two tools, calls into Python retrieval pipeline. The `wecoded-marketplace/spotify-services` plugin is a working precedent. |
| **LLM (synthesis)** | Claude Opus 4.7 via the running YouCoded session | Pro/Max-backed via YouCoded's existing OAuth. No separate API key, no separate companion process for v1. |
| **Citation emission** | Tool calls — `cite(chunk_id, span_start, span_end, confidence, claim_span)` | Span-level anchoring + structured output + verification hook in one. Captured via YouCoded's transcript-watcher's existing `tool_use` block parsing. `claim_span` carries the answer text the citation supports — drives the underlined region in the rendered answer. |
| **Faithfulness verifier** | NLI / judge pass post-generation | Single highest-leverage trust feature per research. Strips chip + claim if it fails. |
| **PDF viewer** | PDF.js + react-pdf-highlighter-extended | 2026 winner; supports text + rect highlights with programmatic API. HTTP range-request streaming for large PDFs. |
| **DOCX viewer** | mammoth.js (Node, server-side render) | Deferred to Phase 2 — only one DOCX in the v1 slice corpus. |
| **Web framework** | Next.js (App Router) + React + TypeScript | Matches Destin's existing stack; native Vercel deploy. |
| **Hosting (Phase 1)** | Destin's machine | $0 |
| **Hosting (Phase 1.5/early Phase 2)** | Destin's machine port-forwarded | $0; one-day move from Phase 1 |
| **Hosting (Phase 2 proper)** | Vercel free tier + Supabase or Neon free tier | $0 |
| **Hosting (Phase 3+)** | JLBC infrastructure if offered, paid VPS otherwise | TBD |
| **Auth** | Google SSO restricted to `azleg.gov` (or equivalent JLBC domain) | Reuses existing identity; minimal new infra |
| **Repo visibility** | Private through Phase 3, re-evaluate going public at Phase 4 | Civic-tech open-sourcing is great, but only after the system is trustworthy |

## 10. Citation UX

### 10.1 Inline rendering

- Each sentence (or clause) that the system makes a factual claim about is **underlined**, with a numeric chip at the end of the underlined span: *"…fiscal year 2024 General Fund appropriation of $1.74B [3]"*
- The underline scope = the exact span supported by the chunk. **Multiple chips per sentence** when different parts come from different sources.
- **Three confidence states** rendered as glyphs on the chip:
  - ✓ **Verbatim** — the exact phrase appears in the source chunk
  - ≈ **Paraphrase** — the source chunk supports the claim semantically; faithfulness check passed
  - ⚠ **Ungrounded** — faithfulness check failed. **Chip and the claim it supports are stripped** from the rendered answer with an italic note: `[claim removed: no supporting source]`

### 10.2 Hover and click behavior

- **Hover the chip** → tooltip with filename, page number, fiscal year, the exact verbatim quote from the source chunk, and a "Copy citation" button that formats as `JLBC Baseline Book FY24, p. 47`.
- **Click the chip** → side panel:
  - PDF jumps to the page, scrolls the cited region into center viewport
  - Yellow rectangle overlay painted on the precise bbox(es); multiple rects for multi-region citations
  - Highlight persists until the next click
  - Breadcrumb at top: `Page 47 of FY24-baseline-book.pdf`

### 10.3 Verify mode

A toggle in the answer pane (off by default). When on, scrolling the answer auto-scrolls the PDF viewer to follow each citation as it comes into view. Synchronized scrollytelling for analysts auditing a long answer.

> **Deferred to Phase 2.** Polish feature; not in v1 scope. Decision D10.

### 10.4 Implementation notes (PDF source)

- **Citation transport (v1):** Claude (running inside the user's YouCoded session) emits `cite(chunk_id, span_start, span_end, confidence, claim_span)` as MCP tool calls against the registered Budget MCP server. The `cite` tool is a record-only operation — it returns `{ok: true}` and the budget backend reads citations from YouCoded's transcript stream as `tool_use` blocks (already parsed structurally by YouCoded's transcript-watcher). NOT Anthropic's Citations API; NOT prompt-marker JSON. Tool calls give us span-level anchoring + schema validation + a verification pass in one shape.
- **`claim_span` field carries the answer text the citation supports.** Drives the underlined region in the rendered answer — the budget UI matches `claim_span` to a substring of the assistant's message and underlines it.
- `react-pdf-highlighter-extended` wraps PDF.js and supports both text and rect highlights. Skip `react-pdf-viewer` (unmaintained since early 2023) and Adobe Embed (vendor lock-in, weak programmatic control).
- Server serves PDFs via HTTP Range requests; PDF.js loads in 64KB chunks. Render only ±2 pages around viewport per PDF.js's own guidance.

### 10.5 Non-PDF source rendering (.docx)

For chunks sourced from .docx documents, the side-panel viewer uses HTML rendering with paragraph- and cell-level highlights instead of bbox overlays. Same UX promise; different rendering primitive.

- **Render path:** Server converts the .docx to HTML on demand (Mammoth.js server-side, or a Python equivalent like `docx2html`). The HTML preserves Word's structural tagging — every `<w:p>` becomes a `<p>` with a stable `id`, every `<w:tc>` becomes a `<td>` with a stable `id`. The same stable ids are stored in `chunks.source_anchor` during ingest, so a click on a citation chip can resolve directly to a DOM element.
- **Highlighting:** The chunk's `source_anchor` JSON carries `{paragraph_id, table_cell_id?}`. The viewer scrolls to that element and applies a yellow background highlight on the matching `<p>` or `<td>`.
- **Multi-paragraph citations** = multiple chips, each opening their own anchor. Same as multi-region PDF citations.
- **Confidence chrome and verify mode** behave identically to the PDF path.
- **Stable ids are the contract.** The DOCX renderer must emit deterministic, ingest-time-equivalent ids — otherwise highlighting silently mismatches the cited paragraph. Verify by re-rendering during ingest and confirming the same id assignment.

## 11. Refusal Behavior

Three explicit cases:

1. **`refusal_no_retrieval`** — every `retrieve()` tool call on the turn returned chunks below the calibrated reranker threshold. The threshold is calibrated during Phase 1 against the eval set (start with reranker score < 0.3 as a placeholder; tune so the eval set's intended-refusal queries refuse and the rest don't). Enforced at the MCP-tool-result level: the `retrieve()` tool returns `top_score`, and the system prompt instructs Claude to refuse when no retrieval clears the threshold. Response: *"I couldn't find anything in the corpus that addresses this question. The corpus currently includes [doc types and fiscal years]. You may want to rephrase, or this may be outside what's been indexed."*
2. **`refusal_synthesis`** — retrieval found chunks but every claim the LLM tried to emit failed faithfulness check (post-generation). Response: *"I found these potentially relevant passages but couldn't confidently synthesize an answer."* Lists the top 5 chunks with citations. Analyst reads raw chunks and decides.
3. **`refusal_out_of_scope`** — the query asks for editorial judgment ("what should we do about X"). The system prompt instructs Claude to recognize this shape and decline without retrieving.

Refusal is logged but not a failure. We monitor refusal rate; we treat false confidence as the worse failure mode.

## 12. Audit Log

Every query writes one row to `queries`. Schema in §6. Used for:
- Diagnosing regressions (replay the exact retrieved chunks against a new prompt)
- Eval set seeding (Phase 3 — anonymized real queries become eval cases)
- Trust auditing (analyst can ask "show me everything I asked yesterday and the citations I got")
- Operational metrics (refusal rate, latency, faithfulness pass rate)

Audit log content is **never** used to train, fine-tune, or share with third parties. Operational only.

## 13. Evaluation

Hand-curated, version-controlled eval set at `eval/queries.yaml`. ~50 Q/A pairs at v1 launch, target ~200 by Phase 3.

```yaml
- id: q-001
  query: "What was the FY24 General Fund appropriation for ADC?"
  type: lookup
  expected_answer_contains: ["$1.74", "General Fund", "ADC"]
  expected_chunks_must_include:
    - {doc: "FY24-jlbc-approps-report.pdf", page: 47}
  expected_refusal: false

- id: q-014
  query: "How did corrections appropriations change between FY23 and FY25?"
  type: comparison
  expected_answer_contains: ["FY23", "FY25", "increase|decrease|change"]
  expected_chunks_must_include:
    - {doc: "FY23-jlbc-baseline.pdf", agency: "ADC"}
    - {doc: "FY25-jlbc-baseline.pdf", agency: "ADC"}
  expected_refusal: false

- id: q-027
  query: "What's the right tax policy for Arizona?"
  type: out-of-scope
  expected_refusal: true
```

**Curated by Destin initially.** Once trusted analysts come online in Phase 2, they help expand the set; their queries (anonymized via the audit log) seed new eval cases organically.

**Run automatically** on every PR that touches: ingest, chunking, retrieval, reranker config, query routing, LLM prompts, faithfulness verifier, or `LLMProvider` implementations. Reports:
- Per-query-type accuracy (lookup vs. comparison vs. out-of-scope)
- Faithfulness pass rate
- Refusal rate
- Citation precision (did we cite the right chunk?) and recall (did we cite *all* the right chunks?)

Eval results stored in `eval_runs` table. Regressions surface in CI.

## 14. Public-Launch Gate (Phase 4 entry criteria)

Phase 4 does not begin until **all** of the following are met:

1. Faithfulness pass rate ≥ 95% on the eval set
2. Analyst-confirmed accuracy ≥ 90% on a 50-query human-graded subset
3. Refusal rate between 5% and 35%
4. Zero "egregious failure" regressions for two consecutive eval runs (egregious = wrong dollar figure, wrong fiscal year, wrong agency, conflated programs)
5. 3+ months of continuous internal use by 5+ analysts without major incident
6. Signed-off public-readiness review documenting known limitations, data freshness, evaluation summary, and unsolved failure modes

Falsifiable. If any slips, Phase 4 stays gated. Internal use continues regardless.

## 15. Anti-Patterns Explicitly Rejected

These are codified to prevent future drift.

- **No "hallucination-free" or "grounded" marketing language.** Stanford's Lexis study is the canonical reason. Honest about limits or we don't ship.
- **No automated action on system output.** Outputs inform analysts; analysts decide. The DOGE VA contract AI is the canonical anti-pattern.
- **No summarization of truncated or sampled fiscal numbers without a verifier pass.** If a chunk got cut mid-table, we re-chunk or refuse, but never summarize partial data.
- **No silent fallback when faithfulness check fails.** Stripped citations are visible. Hidden failure erodes trust.
- **No use of corpus content for any purpose beyond answering queries.** Audit log is operational only; not a training set, not shared, not used to fine-tune.
- **No feature creep that competes with citation rigor.** FiscalNote PolicyNote is the cautionary tale — flashy summaries crowd out the core trust loop. Citations are the product. Everything else is secondary.

## 16. Open Questions (To Resolve in Phase 0 or Phase 1)

- **Tier 1 entity scope.** Phase 0 catalog will tell us which agencies are tractable; we may discover some aren't (mid-period reorganizations, sunset agencies). Resolution: Phase 0 memo.
- **AFR restated tables.** How do we represent a value that the AFR has restated across two years? Options: keep both versions and note restatement, replace older with restated, expose both via metadata. Resolution: Phase 0 finding determines difficulty; Phase 1 implementation decision.
- **Comparison query decomposition heuristics.** ~~When user says "compare X" without specifying years, do we fan out across all years? Last 3 years?~~ **Resolved 2026-05-06 (decision D7):** decomposition is Claude's job under the constrained agent pattern. The system prompt instructs Claude to require explicit fiscal years and ask the analyst rather than fan out by default. No server-side decomposer.
- **Faithfulness verifier model choice.** Self-hosted NLI model vs. another LLM call vs. structured-output classifier from the same Claude session. Resolution: Phase 1c spike.
- **Companion app framework.** Electron (matches YouCoded, larger binary) vs. Tauri (smaller, less mature for our integrations). **Deferred to Phase 2** — v1 doesn't ship a companion (decision D3).
- **JLBC SSO availability.** Whether `azleg.gov` Google Workspace SSO is technically available to our app. Resolution: ask JLBC IT before Phase 3.
- **DOCX→HTML renderer choice.** Mammoth.js (Node, runs in browser or server) vs. python-docx + custom HTML emitter. **Deferred to Phase 2** — DOCX viewer not in v1 scope (decision D10).
- **Source format coverage beyond PDF/DOCX.** If future corpus expansion brings HTML pages (e.g., legislative bill text rendered as HTML on `azleg.gov`) or XML (legislative bill tracker feeds), the format-aware router extends naturally — but we should not pre-build paths until we have a real document to ingest.
- **Cross-cut whole-table chunk stamping.** ~~Phase 1a chunk-shape D6 stamps each whole-table cross-cut chunk to a SINGLE `agency_canonical_id`~~. **Resolved 2026-05-06 (decision D2):** schema flips to `agency_canonical_ids TEXT[]`; whole-table chunks stamp ALL agencies. No re-chunking needed. Filter syntax `WHERE 'agency:adc' = ANY(agency_canonical_ids)` uses GIN index. "Primary" status is recoverable from `section_path[0]` if needed.
- **Acronym expansion for retrieval.** [Phase 1a finding 2026-05-06] Source documents use spelled-out names ("Department of Corrections") — JLBC docs and the bill DOCX both do. Acronym-form queries ("ADC", "ADOT", "GAA") don't tokenize against in-corpus text under TF-IDF. **Reframed under decision D7:** with constrained agent-pattern retrieval, acronym expansion becomes a system-prompt instruction ("expand acronyms before calling retrieve()") rather than a separate component. Test in WS8 eval; revisit only if recall is poor.
- **bd2 parser shape mismatch.** [Phase 1a finding 2026-05-06] `funds/parser.py::parse_s18_table` works on `s18.pdf` (FY27 baseline funds × agencies) but yields 0 rows on `bd2.pdf` (FY26 approps funds × agencies). Out of scope for retrieval; revisit when fund-catalog cross-source merge is needed.
- **Multi-page table reassembly across repeated headings.** [Phase 1a finding 2026-05-06] s18's title repeats on every continuation page, so 13 pages emit as 13 chunks. **Less urgent under decision D2** — each chunk now stamps to all 25 agencies, so retrieval by agency filter still surfaces all 13 chunks. Revisit if eval shows it matters.
- **Citation tool schema final field names + types.** [New, 2026-05-06] D6 sketched `cite(chunk_id, span_start, span_end, confidence, claim_span)`. Nail down before Phase 1c WS3 (system prompt + tool schema).
- **YouCoded port-9900 remote API surface.** [New, 2026-05-06] Verify a non-YouCoded client can connect, create a session, send messages, receive streamed transcripts including `tool_use` blocks. Resolution: 5-minute look at YouCoded's `remote-server.ts` before Phase 1c WS1.

## 17. References

Research informing this design (Phase 0 web research, 2026-05-04):

**PDF extraction (open-source, financial focus):**
- [MinerU 2.5 / OmniDocBench leaderboard](https://www.codesota.com/browse/computer-vision/document-parsing/omnidocbench)
- [Docling (IBM) — visual grounding docs](https://docling-project.github.io/docling/examples/visual_grounding/)
- [PaddleOCR-VL 1.5](https://huggingface.co/PaddlePaddle/PaddleOCR-VL)
- [Best Open-Source PDF-to-Markdown Tools in 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [Building a Financial RAG System Pt 5 — structure-aware chunking benchmark](https://medium.com/@steveinatorx_49018/building-a-financial-rag-system-pt-5-how-i-fixed-chunking-to-reach-90-recall-7f1158e934a9)

**Hybrid retrieval and embeddings:**
- [ParadeDB Hybrid Search in PostgreSQL](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)
- [Voyage-3-large announcement (legal & finance benchmarks)](https://blog.voyageai.com/2025/01/07/voyage-3-large/)
- [FinSage: Multi-aspect RAG for Financial Filings QA](https://arxiv.org/html/2504.14493v3)
- [ZeroEntropy: Choosing the Best Reranking Model 2026](https://zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025/)

**Citation UX and faithfulness:**
- [Hebbia Matrix product](https://www.hebbia.com/product)
- [Glean Deep-Linked Citations API](https://developers.glean.com/guides/chat/deep-linked-citations)
- [Stanford Legal RAG Hallucinations study (2024, 17–33% rate)](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)
- [Layout-Aware RAG with Evidence Pins (Sept 2025)](https://vipulmshah.medium.com/layout-aware-rag-with-evidence-pins-building-clickable-citations-for-pdfs-using-docling-neo4j-5305769759f0)
- [react-pdf-highlighter-extended](https://github.com/DanielArnould/react-pdf-highlighter-extended)
- [Anthropic Citations API](https://claude.com/blog/introducing-citations-api)

**Civic-tech precedents:**
- [Stanford RegLab STARA (closest analog)](https://reglab.github.io/stara/) — [GitHub](https://github.com/reglab/stara)
- [GAO experimental LLM — FedScoop](https://fedscoop.com/gao-in-experimentation-phase-with-ai-model-to-query-reports-inform-its-work/)
- [GRASP — municipal-budget chatbot paper](https://arxiv.org/html/2503.23299)
- [Free Law Project semantic search](https://free.law/2026/05/04/semantic-search-on-courtlistener/)

**Cautionary tales:**
- [ProPublica on DOGE's VA AI tool](https://www.propublica.org/article/inside-ai-tool-doge-veterans-affairs-contracts-sahil-lavingia)
- [FiscalNote PolicyNote release](https://fiscalnote.com/press-room/fiscalnote-unveils-policynote)
- [GovAI Coalition](https://www.sanjoseca.gov/your-government/departments-offices/information-technology/ai-reviews-algorithm-register/govai-coalition)
- [ProPublica AI principles](https://www.propublica.org/ai-principles)
