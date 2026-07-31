# Phase 1c — Synthesis + UI Implementation Plan

> **STATUS: CLOSED — superseded by Standalone consolidation Plans 1–4 (see STATUS.md).** The MCP-server/sidecar/Next.js stack this plan shipped is retired; synthesis is now the in-process `harness/` OpenRouter loop.
>
> Original per-workstream status (2026-05-07):
>
> | WS | Status | Landed in |
> |---|---|---|
> | WS1 — Budget MCP server (`mcp-server/`) | ✓ shipped | `c81cc4c` / `c240bbe` (merge) |
> | WS6 — FastAPI retrieval bridge (`retrieval/api.py`, bundled with WS1) | ✓ shipped | same commit as WS1 |
> | WS2 — `LLMProvider` + `YouCodedSessionProvider` (`web/lib/`) | ✓ shipped | `6eaea46` / `77f3f45` (merge) |
> | WS4a — Next.js scaffold + chat skeleton + theme tokens (`web/app/`, `web/components/`, `web/state/`) | ✓ shipped | `83c0d72` / `f66fb68` (merge) |
> | WS4b — Per-tool ToolBody views + CitationChip + RefusalBanner | ✓ shipped | `e1dda9d` / `d9cef10` / `3d4812b` (merge) |
> | WS4c — PdfViewer + `/api/pdf` range serving + click-chip-to-jump | ✓ shipped | `4a1ddec` / `e0ceb58` / `501583e` (merge) |
> | WS3 — Faithfulness verifier | not started — needs spike (§3.1) | — |
> | WS5 — Audit-log writes to `conversations` / `messages` / `queries` | not started — schema exists, no writer yet | — |
> | WS7 — Eval expansion + end-to-end validation | blocked on volume corpus | — |
>
> Test status: 109/109 vitest in `web/`, 345/345 pytest (42 skipped on live-DB/Voyage gates) in repo root.
>
> **What works end-to-end today:** Run the FastAPI sidecar, register the Budget MCP server with YouCoded, restart YouCoded, then `cd web && npm run dev`. Type a question; you'll see streaming assistant text, per-tool ToolBody views (Bash terminal-style, Edit/Write diffs, Read with cat-n parser, Grep grouped-by-file, retrieve chunk previews, cite citation cards, generic raw fallback), citation chips with hover tooltip + click-to-bus, multi-turn follow-ups, and (after first chip click) a side-panel **PDF viewer** that renders the cited page via pdfjs-dist + canvas with a yellow bbox highlight on the cited region. Refusal banners are wired component-side but not auto-rendered (props-driven only). **Faithfulness verification, refusal auto-detection, and audit-log persistence are NOT wired** — that's the WS3 / WS5 work.
>
> The unchecked checkbox items below (`- [ ]`) under WS1, WS2, WS4 are NOT pending — they shipped. Treat the WS3 / WS5 / WS7 sections as the live work queue.

> **REFRAMED 2026-05-06.** This plan was rewritten in-place to reflect the architectural reframe captured in `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`. Key changes from the original plan:
> 1. **No standalone companion app for v1.** Replaced by piggybacking on a running YouCoded instance (decision D3). WS2 (Companion app) is **deleted**; WS1 (LLMProvider) becomes "implement `YouCodedSessionProvider`."
> 2. **Custom budget tools live in a Budget MCP server** (decision D6) registered in YouCoded's MCP config. New WS introduced for it.
> 3. **Constrained agent-pattern retrieval** (decision D7). The synthesis prompt requires Claude to call `retrieve()` before answering; comparison decomposition happens in Claude's reasoning, not server-side.
> 4. **Multi-turn chat** is the UX (decision D4). The web UI is a chat thread (not search-bar + answer-pane).
> 5. **DOCX viewer + verify-mode toggle deferred to Phase 2** (decision D10).
> 6. **Eval expansion target is 30 → 35** (was 30 → 50). Full 50 follows Phase 1.5 backfill.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the synthesis + citation rendering + web UI on top of Phase 1b's retrieval API, producing a working multi-turn chat-style end-to-end product on Destin's machine that depends on a running YouCoded instance. By the end of Phase 1c, Destin can type a question into a budget-app browser tab, get a cited answer, ask follow-ups in the same conversation, click citation chips, and see the source PDF page with the cited region highlighted. This is "Phase 1 — Working prototype" complete per spec §7.

**Inputs from Phase 1b:**
- `retrieve(RetrievalRequest) -> RetrievalResult` Python entry point at `retrieval/pipeline.py`
- `REFUSAL_RERANKER_THRESHOLD` constant (calibrated)
- Postgres with all chunks + embeddings + indexes (post-volume-ingest)
- Eval set at `eval/queries.yaml` with ~30 queries
- `data/system-prompt-context.md` from Phase 1a (writing draft + Gov glossary)
- `phase-1b-complete` git tag

**Hard external dependency:**
- A YouCoded installation on the same machine, running and reachable at `ws://localhost:9900`. v1 fails fast with a "please open YouCoded" notice if absent.

**Scope this plan:**
- `LLMProvider` interface + `YouCodedSessionProvider` implementation (talks to localhost:9900)
- **Budget MCP server** — Node process registered in YouCoded's MCP config; exposes `retrieve(query, filters)` and `cite(...)` tools
- Synthesis system prompt (loaded by the MCP server) — instructs Claude on tool use, refusal thresholds, citation format, acronym expansion
- NLI/judge faithfulness verifier (post-streaming)
- Next.js multi-turn chat UI (conversation thread with citation chips)
- PDF.js + react-pdf-highlighter-extended viewer with bbox highlight
- Audit log writes (`conversations`, `messages`, `queries` tables populated)
- Eval expansion to ~35 queries; end-to-end smoke test

**Out of scope (deferred to Phase 2):**
- Standalone companion app (so the budget app can run without YouCoded)
- DOCX HTML renderer / `DocxViewer` component
- Verify-mode toggle (synchronized scrolling)
- Public web deployment (Vercel + Supabase)
- `AnthropicAPIProvider` and `SelfHostedLLMProvider`
- Tier 2 entity resolution (program-level)
- Larger eval set expansion (Phase 3)

**Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│ Browser (localhost:3000)                                │
│  Next.js SPA: chat thread, citation chips, PDF viewer   │
│  (DOCX viewer + verify-mode deferred to Phase 2)        │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS / API routes (SSE for streaming)
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Budget web server (Next.js, localhost:3000)            │
│  Routes:                                                │
│   POST /api/conversations → start a new conversation    │
│   POST /api/conversations/:id/messages → send turn      │
│   GET  /api/pdf/:doc_id → HTTP range serving            │
│  YouCodedSessionProvider (talks to ws://localhost:9900)│
│  Faithfulness verifier (post-streaming)                 │
│  Audit log writer (conversations, messages, queries)    │
└────────────┬─────────────────────┬─────────────────────┘
             │                     │
             │ ws://localhost:9900 │ Postgres
             │                     ▼
             ▼              ┌──────────────────────────┐
┌──────────────────────────┐│ Postgres                  │
│                           │  │  • Wraps Claude Code     │
│                           │  │  • chunks, conversations,│
│                           │  │    messages, queries     │
└──────────────────────────┘  └──────────────────────────┘
                ▲
                │ MCP (stdio / JSON-RPC)
                │
┌──────────────────────────────────────────────────────────┐
│ Running YouCoded instance (must be open on the machine)  │
│  Claude Code session per conversation                    │
│  Pro/Max OAuth (existing)                                │
│  Transcript-watcher (parses tool_use blocks)             │
│  MCP host (loads Budget MCP server)                      │
└──────────────────────────┬───────────────────────────────┘
                           │ stdio MCP
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Budget MCP server (Node, registered in YouCoded)        │
│  Tools:                                                  │
│   retrieve(query, filters) → {chunks, top_score}         │
│   cite(chunk_id, span_start, span_end, conf, claim_span) │
│  Imports retrieval/pipeline.py via subprocess or HTTP    │
└──────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- Web app: Next.js 14 (App Router) + React 18 + TypeScript
- PDF viewer: `pdfjs-dist` + `react-pdf-highlighter-extended`
- ~~DOCX → HTML: `mammoth.js`~~ — deferred to Phase 2
- Budget MCP server: Node 20+, `@modelcontextprotocol/sdk` for the tool framing. Single process, ~few hundred lines. Reference shape: `wecoded-marketplace/spotify-services` plugin.
- Faithfulness verifier: NLI model self-hosted (e.g., `sentence-transformers/cross-encoder-nli-deberta-v3-base`) OR an LLM judge call — decision in Workstream 3.
- Python for retrieval (re-used from 1b); Node for web + MCP server (different runtime). MCP server calls retrieval via subprocess or HTTP-bridge — see Workstream 6.

**Source spec:** `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` (post-2026-05-06 reframe) — §4 (architecture), §4.2 (provider abstraction), §5 (multi-turn data flow), §10 (citation UX), §11 (refusal), §12 (audit log).

**Source decisions:** `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md` — D3 (YouCoded piggyback), D4 (multi-turn), D5 (Claude keeps general tools), D6 (MCP server), D7 (constrained agent pattern), D10 (UI scope), D11 (provider seam).

---

## File structure

Files created during Phase 1c:

| Path | Purpose | Tracked? |
|---|---|---|
| `mcp-server/index.ts` | Budget MCP server entry point — registers `retrieve` and `cite` tools | ✓ |
| `mcp-server/tools/retrieve.ts` | Wraps `retrieval/pipeline.py::retrieve()` (subprocess or HTTP) | ✓ |
| `mcp-server/tools/cite.ts` | Records cite calls; returns ack | ✓ |
| `mcp-server/system-prompt.md` | System prompt loaded into the MCP server config (constrained agent rules) | ✓ |
| `mcp-server/package.json` | MCP server deps (`@modelcontextprotocol/sdk`) | ✓ |
| `mcp-server/README.md` | Setup: register with YouCoded's MCP config | ✓ |
| `web/` | Next.js app root | ✓ |
| `web/package.json` | Web deps | ✓ |
| `web/app/page.tsx` | Multi-turn chat UI (thread view) | ✓ |
| `web/app/api/conversations/route.ts` | POST /api/conversations — start a new conversation (calls `LLMProvider.startConversation`) | ✓ |
| `web/app/api/conversations/[id]/messages/route.ts` | POST /api/conversations/:id/messages — relay user turn, stream events back | ✓ |
| `web/app/api/pdf/[doc_id]/route.ts` | PDF range-serving | ✓ |
| `web/components/ChatThread.tsx` | Renders the conversation as message bubbles | ✓ |
| `web/components/MessageInput.tsx` | Bottom-of-thread input (replaces SearchBar) | ✓ |
| `web/components/CitationChip.tsx` | Underlined-span chip with hover/click | ✓ |
| `web/components/PdfViewer.tsx` | PDF.js + react-pdf-highlighter wrapper | ✓ |
| `web/components/RefusalBanner.tsx` | Three refusal cases per spec §11 | ✓ |
| `web/lib/llm-provider.ts` | `LLMProvider` interface + `YouCodedSessionProvider` | ✓ |
| `web/lib/youcoded-client.ts` | WebSocket client for `ws://localhost:9900` | ✓ |
| `web/lib/transcript-parser.ts` | Parses YouCoded's transcript stream for `tool_use` blocks | ✓ |
| `web/lib/faithfulness.ts` | NLI/judge verifier | ✓ |
| `web/lib/citation-merge.ts` | Merges multi-chunk citations into one rendered span | ✓ |
| `web/lib/audit-log.ts` | Writes to `conversations`, `messages`, `queries` tables | ✓ |
| `web/tests/...` | Component + integration tests (Playwright for E2E) | ✓ |
| `eval/queries-expanded.yaml` | ~35-query eval set (1b's 30 + 5 added for end-to-end) | ✓ |
| `eval/run_e2e_eval.py` | Runs full retrieval + synthesis + faithfulness, scores against expected_answer_contains | ✓ |

Files NOT created (deferred to Phase 2):
- `companion/*` — standalone companion app (D3)
- `web/components/DocxViewer.tsx` (D10)
- `web/components/VerifyModeToggle.tsx` (D10)
- `web/app/api/docx/[doc_id]/route.ts` (D10)

Files modified:
- `pyproject.toml` — add `fastapi>=0.110` + `uvicorn` if we choose HTTP-bridge for retrieval
- `.gitignore` — add `web/.next/`, `web/node_modules/`, `mcp-server/node_modules/`

Secrets:
- `.env.local` — `ANTHROPIC_OAUTH_TOKEN` (read by companion via Claude Code's existing auth flow), `DATABASE_URL` (web → Postgres for audit log), `RETRIEVAL_BRIDGE_URL` (web → retrieval).

---

## Workstream 1 — Budget MCP server

**Goal:** Build the small Node process that registers `retrieve` and `cite` tools with the user's running YouCoded instance. Once registered, any Claude session in YouCoded can use these tools — including the budget app's own conversations and any normal YouCoded chat the user opens (D6).

This replaces the original Phase 1c WS1 ("LLM Provider abstraction" — moved to WS2 in this reframe) AND WS2 ("Companion app" — deleted under D3, deferred to Phase 2).

### Task 1.1: MCP server scaffold

**Files:**
- Create: `mcp-server/package.json`
- Create: `mcp-server/index.ts`
- Create: `mcp-server/README.md`

- [ ] **Step 1: Bootstrap the MCP project**

`mcp-server/package.json` depends on `@modelcontextprotocol/sdk`. Reference: `wecoded-marketplace/spotify-services` plugin in your YouCoded ecosystem — same shape (Node MCP server, two tools, registered in YouCoded's MCP config).

`mcp-server/index.ts` minimal scaffold:

```ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { retrieveTool } from "./tools/retrieve";
import { citeTool } from "./tools/cite";

const server = new Server(
  { name: "ask-the-budget-az", version: "0.1.0" },
  { capabilities: { tools: {} } },
);

server.registerTool(retrieveTool);
server.registerTool(citeTool);

await server.connect(new StdioServerTransport());
```

- [ ] **Step 2: README on registering with YouCoded**

Two-line setup: add an entry to `~/.claude/.../mcp_servers.json` (or whichever YouCoded MCP config the user is on) pointing at `mcp-server/index.ts`. Document the exact config path; verify in YouCoded that the tools show up in `/mcp`.

### Task 1.2: `retrieve` tool

**Files:**
- Create: `mcp-server/tools/retrieve.ts`
- Create: `mcp-server/tests/test_retrieve.ts`

- [ ] **Step 1: Failing test — tool definition + filter shape**

```ts
test("retrieve tool schema validates filter shape", () => {
  const valid = { query: "Aviation Fund", filters: { fiscal_year: [2027] } };
  expect(retrieveTool.inputSchema.parse(valid)).toEqual(valid);
  const invalid = { query: "x", filters: { fiscal_year: "2027" } }; // wrong type
  expect(() => retrieveTool.inputSchema.parse(invalid)).toThrow();
});
```

- [ ] **Step 2: Implement against `retrieval/pipeline.py`**

Two paths:
- **Subprocess (simpler):** spawn `python -m retrieval.cli` with the query/filters as JSON on stdin; read JSON response on stdout. Cold-start cost per call, but dead simple.
- **HTTP bridge (better):** stand up `fastapi + uvicorn` server (`retrieval/server.py`) that imports `retrieve()` once and serves HTTP. MCP tool POSTs to it. Faster (no Python startup per call); needs a process to manage.

Recommend HTTP bridge — Phase 1b WS6 already builds the Python pipeline; wrapping it in a FastAPI server is ~30 lines.

```ts
export const retrieveTool = {
  name: "retrieve",
  description: "Retrieve relevant chunks from the AZ budget corpus...",
  inputSchema: z.object({
    query: z.string(),
    filters: z.object({
      fiscal_year: z.array(z.number()).optional(),
      doc_type: z.array(z.string()).optional(),
      publisher: z.array(z.string()).optional(),
      agency_canonical_id: z.array(z.string()).optional(),
      fund_canonical_id: z.array(z.string()).optional(),
      is_table: z.boolean().optional(),
    }).optional(),
  }),
  async handler({ query, filters }) {
    const result = await fetch(`${RETRIEVAL_URL}/retrieve`, {
      method: "POST",
      body: JSON.stringify({ query, ...filters }),
    }).then(r => r.json());
    return {
      content: [{ type: "text", text: JSON.stringify(result) }],
    };
  },
};
```

The MCP `content` shape is what Claude sees — so the chunks come back as text it can read. Each chunk includes its `chunk_id`, `text`, page/bbox, agency stamps, etc.

### Task 1.3: `cite` tool

**Files:**
- Create: `mcp-server/tools/cite.ts`
- Create: `mcp-server/tests/test_cite.ts`

- [ ] **Step 1: Schema + ack-only handler**

```ts
export const citeTool = {
  name: "cite",
  description: "Record a citation supporting a claim in your answer...",
  inputSchema: z.object({
    chunk_id: z.string(),
    span_start: z.number().int().nonnegative(),
    span_end: z.number().int().positive(),
    confidence: z.enum(["verbatim", "paraphrase"]),
    claim_span: z.string().min(1),
  }),
  async handler(args) {
    // Record-only: the budget web server reads cite() calls from YouCoded's
    // transcript stream as tool_use blocks. The MCP server doesn't need to
    // do anything except ack; faithfulness verification happens in the
    // budget web server post-streaming.
    return { content: [{ type: "text", text: "ok" }] };
  },
};
```

- [ ] **Step 2: Validate `chunk_id` exists**

Tool handler queries Postgres to confirm `chunk_id` is real before returning ok. Hallucinated chunk_ids fail loudly here (Claude sees the error in the tool result and can self-correct).

### Task 1.4: System prompt

**Files:**
- Create: `mcp-server/system-prompt.md`

The system prompt is loaded into the Claude session that uses these tools. It's the linchpin of the constrained agent pattern (D7).

- [ ] **Step 1: Draft the system prompt**

Should cover:
- **Domain primer** — load `data/system-prompt-context.md` from Phase 1a (writing draft + Gov glossary + acronyms)
- **Constrained agent rules**:
  - "You MUST call `retrieve()` at least once before answering any user question about the budget corpus."
  - "If `retrieve()` returns chunks with `top_score < 0.3`, refuse: 'I couldn't find anything in the corpus that addresses this question. The corpus currently includes [doc types and fiscal years].'"
  - "When the user asks a comparison question (between two FYs, between Gov and JLBC), call `retrieve()` once per side."
  - "Expand acronyms before calling `retrieve()`: ADC → 'Department of Corrections'; ADOT → 'Department of Transportation'; etc."
  - "When the user asks an editorial/policy question ('what should we do', 'what's the right policy'), refuse with `refusal_out_of_scope`."
- **Citation rules**:
  - "Every factual claim in your answer must be supported by a `cite()` tool call."
  - "`claim_span` must be the verbatim text of the claim as you wrote it in your answer."
  - "Use `confidence: 'verbatim'` when the chunk text contains the claim word-for-word; otherwise `'paraphrase'`."
- **Refusal copy** — three refusal types from spec §11

- [ ] **Step 2: Document how the system prompt loads**

YouCoded's MCP config (or per-conversation system prompt) needs to include this. Document the exact mechanism — likely a YouCoded skill or per-session prompt prefix.

### Task 1.5: Integration smoke test

**Files:**
- Create: `mcp-server/tests/test_integration.ts`

- [ ] **Step 1: Open a YouCoded session with the MCP server registered**

Spin up YouCoded (or use the running instance). Start a chat. Send a test query like "What's the balance of the Aviation Fund?"

- [ ] **Step 2: Verify Claude calls `retrieve()` then `cite()`**

Watch the YouCoded transcript for the tool_use blocks. Confirm `retrieve` is called with reasonable args, returns chunks, and `cite` is emitted for the claim. Manual smoke test; no automation yet.

---

## Workstream 2 — `LLMProvider` interface + `YouCodedSessionProvider`

**Goal:** Define the TypeScript `LLMProvider` interface (preserved as a seam per D11) and ship the v1 implementation: `YouCodedSessionProvider`, which talks to a running YouCoded instance over `ws://localhost:9900`. This replaces what was originally split across the old WS1 + WS2 (provider abstraction + standalone companion). The standalone companion is **deferred to Phase 2** under D3.

### Task 2.1: Provider interface

**Files:**
- Create: `web/lib/llm-provider.ts`
- Create: `web/tests/test_llm_provider.ts`

- [ ] **Step 1: Write the multi-turn interface (matches reframed spec §4.2)**

```ts
export interface LLMProvider {
  startConversation(): Promise<{ conversationId: string }>;

  sendTurn(args: {
    conversationId: string;
    userMessage: string;
    onEvent: (e: ProviderEvent) => void;
  }): Promise<{
    finalAnswer: string;
    citations: Citation[];
    retrievedChunkIds: string[];
    refusal?: RefusalReason;
  }>;

  endConversation(id: string): Promise<void>;
}

export type ProviderEvent =
  | { type: "assistant_text_delta"; text: string }
  | { type: "tool_use"; tool: "retrieve" | "cite"; input: unknown }
  | { type: "tool_result"; output: unknown }
  | { type: "attention"; state: "ok" | "stuck" | "error" }
  | { type: "done" };

export type Citation = {
  chunkId: string;
  spanStart: number;
  spanEnd: number;
  confidence: "verbatim" | "paraphrase";
  claimSpan: string;
};

export type RefusalReason =
  | { type: "no_retrieval" }
  | { type: "synthesis"; chunks_shown: string[] }
  | { type: "out_of_scope" };
```

- [ ] **Step 2: Failing test — mock provider returns expected shape**

```ts
test("mock provider matches multi-turn LLMProvider interface", async () => {
  const events: ProviderEvent[] = [];
  const mock: LLMProvider = {
    startConversation: async () => ({ conversationId: "c1" }),
    sendTurn: async ({ onEvent }) => {
      onEvent({ type: "assistant_text_delta", text: "hi" });
      onEvent({ type: "done" });
      return { finalAnswer: "hi", citations: [], retrievedChunkIds: [] };
    },
    endConversation: async () => {},
  };
  const { conversationId } = await mock.startConversation();
  const r = await mock.sendTurn({ conversationId, userMessage: "q", onEvent: (e) => events.push(e) });
  expect(r.finalAnswer).toBe("hi");
});
```

### Task 2.2: `YouCodedSessionProvider`

**Files:**
- Create: `web/lib/youcoded-client.ts`
- Create: `web/lib/transcript-parser.ts`
- Update: `web/lib/llm-provider.ts`

- [ ] **Step 1: Verify YouCoded port-9900 surface**

Spec §16 open question: confirm a non-YouCoded client can connect, create a session, send messages, receive streamed transcripts including `tool_use` blocks. Read `youcoded/desktop/src/main/remote-server.ts` to identify the message types. Write a 30-line probe script that connects, opens a session, sends "hello", and prints transcript events.

If the surface is sufficient: proceed.
If gaps exist (e.g. no way to send `system_prompt` per-session, no way to load an MCP server only for this session): file as known limitations and either work around or open YouCoded changes — these need to be done in YouCoded's repo (the budget app doesn't fork YouCoded per D9).

- [ ] **Step 2: Implement the WebSocket client**

`web/lib/youcoded-client.ts` — typed wrapper around YouCoded's port-9900 protocol. Handles auth (probably bearer token from YouCoded's pairing flow), session lifecycle, message send, transcript event subscription.

- [ ] **Step 3: Implement transcript-parser**

`web/lib/transcript-parser.ts` — consumes YouCoded's transcript stream, emits typed `ProviderEvent`s. Looks at each transcript event:
- `assistant-text-delta` events → `{ type: "assistant_text_delta", text }`
- `tool_use` blocks where tool name is `retrieve` or `cite` → `{ type: "tool_use", ... }`
- `tool_result` blocks → `{ type: "tool_result", ... }`
- attention-state changes → `{ type: "attention", state }`
- end-of-turn → `{ type: "done" }`

YouCoded's `transcript-watcher.ts` already does the heavy lifting (parsing JSONL, attention classification, etc.) — the budget client just needs to consume the events YouCoded emits over port 9900.

- [ ] **Step 4: Wire into `YouCodedSessionProvider`**

```ts
export class YouCodedSessionProvider implements LLMProvider {
  constructor(private url = "ws://localhost:9900") {}

  async startConversation() {
    const client = await connectToYouCoded(this.url);
    const session = await client.createSession({ /* TBD: how to attach the budget MCP system prompt */ });
    return { conversationId: session.id };
  }

  async sendTurn({ conversationId, userMessage, onEvent }) {
    const events = await sendMessageAndStream(conversationId, userMessage);
    const citations: Citation[] = [];
    const retrievedChunkIds: string[] = [];
    let finalAnswer = "";
    for await (const e of events) {
      onEvent(e);
      if (e.type === "assistant_text_delta") finalAnswer += e.text;
      if (e.type === "tool_use" && e.tool === "cite") citations.push(parseCite(e.input));
      if (e.type === "tool_use" && e.tool === "retrieve") {
        // chunks come back via the corresponding tool_result
      }
      if (e.type === "tool_result" && /* corresponds to retrieve */) {
        retrievedChunkIds.push(...extractChunkIds(e.output));
      }
    }
    return { finalAnswer, citations, retrievedChunkIds };
  }

  async endConversation(id: string) {
    // no-op for v1; the YouCoded session lives on
  }
}
```

- [ ] **Step 5: Detect missing YouCoded gracefully**

If `ws://localhost:9900` doesn't connect, the budget web server returns a 503 to the browser with a payload like `{ error: "youcoded_not_running" }`. The chat UI shows a banner: *"YouCoded must be running to use the budget app. Open YouCoded and refresh."* Don't crash; don't auto-retry forever; do offer a refresh button.

---

## Workstream 3 — Faithfulness verifier

**Goal:** Per-citation entailment check after the LLM emits its answer. Failed citations get stripped along with the claim text they support, replaced with `[claim removed: no supporting source]` per spec §10.1.

### Task 3.1: Choose verifier strategy

**Files:**
- Create: `docs/superpowers/investigations/2026-MM-DD-faithfulness-spike.md`

Spec §16 lists this as an open question: "Self-hosted NLI model vs. another LLM call vs. structured-output classifier from the same Claude session."

- [ ] **Step 1: Spike each option on 10 sample (claim, chunk) pairs**

Hand-pick 10 (claim_text, chunk_text) pairs — 5 truly-entailed, 5 paraphrase-or-fabricated. Score with:

  **Option A — self-hosted NLI:** `cross-encoder/nli-deberta-v3-base` (or similar). Local CPU/GPU, no API cost, ~50ms latency.
  **Option B — Anthropic LLM judge:** A second Claude call: "Does this chunk entail this claim? Answer ENTAILS or NOT_ENTAILS plus a one-sentence reason." ~500ms + cost.
  **Option C — structured-output from same session:** Add a `verify(claim, chunk_id)` tool to the synthesis call; model self-grades its citations. Risk: model has incentive to mark its own citations as good.

Score on accuracy (matches manual ground truth) + latency + cost. Write findings memo.

- [ ] **Step 2: Pick + document**

Default to **Option A** unless its accuracy on the spike is unacceptably worse than B. The reason: (1) deterministic, no API dependency, (2) cheap enough to run on every citation, (3) Option C is structurally weak (verifier and synthesizer are the same model). Option B is reasonable if (A) underperforms but adds latency + cost.

### Task 3.2: Implement the chosen verifier

**Files:**
- Create: `web/lib/faithfulness.ts`
- Create: `web/tests/test_faithfulness.ts`

- [ ] **Step 1: Failing test — entailment + non-entailment**

```ts
test("entailed claim passes verifier", async () => {
  const result = await verify({
    claim: "ADC's FY 2025 General Fund appropriation was $1.74B.",
    chunk: { text: "Department of Corrections — FY 2025 — General Fund — $1,740,000,000 ..." },
  });
  expect(result.passed).toBe(true);
  expect(result.score).toBeGreaterThan(0.7);
});

test("paraphrased-but-incorrect claim fails verifier", async () => {
  const result = await verify({
    claim: "ADC's FY 2025 General Fund appropriation was $5B.",
    chunk: { text: "Department of Corrections — FY 2025 — General Fund — $1,740,000,000 ..." },
  });
  expect(result.passed).toBe(false);
});
```

- [ ] **Step 2: Implement**

If Option A: spawn the NLI model in a Python sidecar (since Node ML support is weaker), call via HTTP. If Option B: Anthropic API call. If Option C: implemented as a tool in Workstream 2.

- [ ] **Step 3: Verify-and-strip pipeline**

```ts
async function verifyAnswer(answer: string, citations: Citation[], chunks: Chunk[]) {
  const verdicts = await Promise.all(citations.map(c => verify({ claim: answer.slice(c.spanStart, c.spanEnd), chunk: lookup(chunks, c.chunkId) })));
  const surviving = citations.filter((_, i) => verdicts[i].passed);
  const stripped = citations.filter((_, i) => !verdicts[i].passed);
  let cleanedAnswer = answer;
  // Strip in reverse char order so offsets stay valid
  for (const c of stripped.sort((a, b) => b.spanStart - a.spanStart)) {
    cleanedAnswer = cleanedAnswer.slice(0, c.spanStart) + "[claim removed: no supporting source]" + cleanedAnswer.slice(c.spanEnd);
  }
  return { cleanedAnswer, citations: surviving, stripped };
}
```

- [ ] **Step 4: Failing test — answer-stripping preserves remaining citation offsets**

After stripping, the surviving citations' span_start/end must still line up with their text in the cleaned answer. Test that.

---

## Workstream 4 — Web UI (multi-turn chat)

**Goal:** Next.js multi-turn chat UI with citation chips, side-panel PDF viewer, refusal banners. Implements spec §10 citation UX in a chat-thread shape rather than search-bar+answer-pane (D4).

### Task 4.1: Next.js scaffold + chat layout

**Files:**
- Create: `web/app/page.tsx`
- Create: `web/app/layout.tsx`

- [ ] **Step 1: Scaffold Next.js 14 App Router project**

```bash
npx create-next-app@latest web --typescript --app --tailwind --no-src-dir
```

- [ ] **Step 2: Two-column layout**

Left column: chat thread (scrolling messages) + bottom-anchored message input. Right column: PDF viewer. Resizable divider via `react-resizable-panels` or CSS grid.

### Task 4.2: ChatThread + MessageInput

**Files:**
- Create: `web/components/ChatThread.tsx`
- Create: `web/components/MessageInput.tsx`

- [ ] **Step 1: MessageInput — text input + submit**

Submit posts to `/api/conversations/:id/messages`. Streams events back via SSE; chat thread appends as text and tool calls arrive.

- [ ] **Step 2: ChatThread — render multi-turn conversation**

Renders the conversation as a sequence of message bubbles (user + assistant). Each assistant message contains the synthesized answer with citation chips inline. Tool calls (retrieve, cite) can render as collapsible breadcrumbs ("Searched: 'Aviation Fund balance' (FY 2027) → 14 results") so the analyst can audit the agent's reasoning.

Walks the (answer, citations) tuple per assistant message. Each citation underlines the span and renders a numbered chip at the end of the underlined span. Chips show one of three glyphs per spec §10.1: ✓ verbatim, ≈ paraphrase, ⚠ ungrounded (the last is rendered as `[claim removed]` rather than as a chip after Workstream 3 stripping).

### Task 4.3: CitationChip — hover + click

**Files:**
- Create: `web/components/CitationChip.tsx`
- Create: `web/components/CitationTooltip.tsx`

- [ ] **Step 1: Hover tooltip per spec §10.2**

Tooltip content: filename + page number + fiscal year + verbatim quote from chunk + "Copy citation" button. Format string for copy: `JLBC Baseline Book FY24, p. 47`.

- [ ] **Step 2: Click handler**

Emits a global event (Zustand store or simple event bus): `citation:select(chunkId, citation)`. Viewers (PdfViewer, DocxViewer) subscribe and scroll to + highlight the cited region.

### Task 4.4: PdfViewer

**Files:**
- Create: `web/components/PdfViewer.tsx`

- [ ] **Step 1: Mount react-pdf-highlighter-extended**

```tsx
import { PdfHighlighter, PdfLoader } from "react-pdf-highlighter-extended";

<PdfLoader url={`/api/pdf/${docId}`}>
  {(pdfDocument) => (
    <PdfHighlighter
      pdfDocument={pdfDocument}
      highlights={highlights}
      onScrollChange={() => {}}
    />
  )}
</PdfLoader>
```

- [ ] **Step 2: Convert chunk citation → highlight**

Chunk `bbox` is `[x1, y1, x2, y2]` in PDF points (per cross-doc-relationships §4). `react-pdf-highlighter-extended` accepts highlights as `{ position: { boundingRect: { x1, y1, x2, y2, width, height }, rects: [...], pageNumber } }`. Convert.

For tabular chunks, the chunk bbox is the whole table; the LLM's `cite()` call returns a `row_label` in the `confidence` blob (extension to spec — see Task 4.6). Use it to derive the row's bbox via PDF text-search (PDF.js exposes a `getTextContent()` API per page; find the row label, build a tighter rect around just that row).

- [ ] **Step 3: HTTP range-request via /api/pdf**

```ts
// web/app/api/pdf/[doc_id]/route.ts
export async function GET(req: Request, { params }: { params: { doc_id: string } }) {
  const range = req.headers.get("range");
  const path = await resolveDocPath(params.doc_id);
  return serveFileWithRangeSupport(path, range);
}
```

PDF.js loads in 64KB chunks; the route must support `Range` headers.

### Task 4.5: DocxViewer

> **Deferred to Phase 2 under D10.** v1 has only one DOCX in the slice (the SB 1735 bill) and the cost of building the server-side mammoth render + stable-id contract isn't worth it for a single doc. When DOCX-source citations are clicked in v1, fall back to: open the underlying file via the OS default DOCX handler, OR show a "DOCX viewer coming in Phase 2; here's the verbatim cited text" panel. The chunks themselves are still retrievable; only the in-app rendering is deferred.

The original Task 4.5 detail is preserved here for Phase 2 reference:
- Server-side mammoth.js render with stable paragraph IDs (`web14:paraId` → DOM `id`)
- Re-rendering must produce identical id sets (contract test)
- Citation click → scroll + highlight by `paragraph_id` from `chunks.source_anchor`

### Task 4.6: Refusal banner

**Files:**
- Create: `web/components/RefusalBanner.tsx`

- [ ] **Step 1: RefusalBanner — three cases per spec §11**

`refusal_no_retrieval`, `refusal_synthesis`, `refusal_out_of_scope`. Each renders the spec's exact copy plus, for `synthesis` and `out_of_scope`, the top 5 chunks for the analyst to read directly.

> **Verify-mode toggle deferred to Phase 2 under D10.** Polish feature; not needed for v1 dogfood.

---

## Workstream 5 — Audit log

**Goal:** Every query writes one row to the `queries` table per spec §12. Used for debugging, eval-set seeding, trust auditing.

### Task 5.1: Write audit row on every query

**Files:**
- Create: `web/lib/audit-log.ts`
- Update: `web/app/api/query/route.ts`

- [ ] **Step 1: Implement `writeQueryRow(queryRow)`**

Inserts into `queries` table (schema from spec §6 + Phase 1b 0001 migration). Fields: raw_query, classified_type, sub_queries (JSON), retrieved_chunk_ids, reranker_scores, chunks_sent_to_llm, llm_provider, llm_response_raw, citations_emitted, faithfulness_verdicts, final_answer_rendered, refusal_type, latency_ms.

- [ ] **Step 2: Wire into /api/query**

```ts
export async function POST(req) {
  const start = Date.now();
  const { query } = await req.json();
  const retrieval = await callRetrieval(query);
  const synthResult = await provider.synthesize({ query, chunks: retrieval.chunks, queryType: retrieval.classified_type });
  const verified = await verifyAnswer(synthResult.answer, synthResult.citations, retrieval.chunks);
  await writeQueryRow({
    raw_query: query,
    classified_type: retrieval.classified_type,
    retrieve_calls: retrieveCalls,    // list of {query, filters, returned_chunk_ids, reranker_scores, top_score}
    cite_calls: synthResult.citations,
    faithfulness_verdicts: verified.verdicts,
    refusal_type: synthResult.refusal?.type ?? null,
    latency_ms: Date.now() - start,
  });
  // Plus: append assistant message to messages table; FK queries.message_id to it.
  return NextResponse.json({ answer: verified.cleanedAnswer, citations: verified.citations, refusal: synthResult.refusal });
}
```

> **Note 2026-05-06:** schema reframed under D4 — `queries` is per-assistant-turn FK'd to `messages`, with `retrieve_calls` and `cite_calls` JSONB columns. Audit log writer also writes to `conversations` (on first turn) and `messages` (every turn).

- [ ] **Step 3: Audit log NEVER trains anything**

Per spec §12: "Audit log content is never used to train, fine-tune, or share with third parties." No code path should export this table outside of the analyst's own machine. Add a comment in the route file citing the invariant.

---

## Workstream 6 — Retrieval bridge (Python ↔ Node)

**Goal:** Node web server needs to call the Python retrieval pipeline from Phase 1b. Two reasonable shapes; pick one.

### Task 6.1: Pick the bridge shape

**Files:**
- Create: `docs/retrieval-bridge-decision.md`

- [ ] **Step 1: Compare two options**

  **Option A — Python subprocess on each query.** Simple. Cold-start overhead per query (~1s for the imports + DB connection). No long-running process to manage.

  **Option B — Python FastAPI sidecar on localhost.** Run `uvicorn retrieval.api:app` alongside Node web server. Web server makes HTTP calls. Persistent connection pool. ~10ms latency vs 1s cold-start. One more process to manage in dev.

- [ ] **Step 2: Default to Option B**

Decision: Option B because retrieval is in the user-facing latency budget. Trade-off: dev-loop adds one more `uvicorn` invocation; document in `companion/README.md` and a top-level dev script that starts everything together.

### Task 6.2: Implement Option B

**Files:**
- Create: `retrieval/api.py` (FastAPI sidecar)
- Create: `web/lib/retrieval-bridge.ts`

- [ ] **Step 1: FastAPI app**

```python
from fastapi import FastAPI
from retrieval.pipeline import retrieve, RetrievalRequest

app = FastAPI()

@app.post("/retrieve")
def http_retrieve(req: RetrievalRequest):
    return retrieve(req)

# uvicorn retrieval.api:app --host localhost --port 9200
```

- [ ] **Step 2: Node client**

```ts
export async function callRetrieval(query: string): Promise<RetrievalResult> {
  const res = await fetch(`${process.env.RETRIEVAL_BRIDGE_URL}/retrieve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
  });
  return res.json();
}
```

- [ ] **Step 3: Top-level dev script**

`scripts/dev.sh` (bash) or `scripts/dev.ps1` (PowerShell) that starts: Postgres (Docker), retrieval sidecar, companion server, Next.js dev server. One command to bring the whole stack up locally.

---

## Workstream 7 — Eval expansion + end-to-end validation

**Goal:** Expand Phase 1b's ~30-query eval set to ~35 (D10 tightened from the original "to ~50" target — full 50 follows Phase 1.5 backfill), run end-to-end (retrieval-via-MCP + synthesis-via-YouCoded-session + faithfulness), measure full-system metrics.

### Task 7.1: Expand eval set

**Files:**
- Update/Create: `eval/queries-expanded.yaml`

- [ ] **Step 1: Add 5 more queries (target ~35 total)**

Targeted at multi-turn flows + cross-publisher integration that single-shot Phase 1b eval can't measure. Cover:
- A multi-turn conversation: turn 1 = lookup, turn 2 = follow-up that requires anaphora resolution (e.g. "what about FY24?" referring back to turn 1's agency).
- Cross-publisher comparison (Gov rec vs. enacted) — exercises Claude calling `retrieve()` twice with different `publisher` filters.
- A bills-anchored question that resolves to a specific paragraph in the SB 1735 DOCX.
- A synthesis case ("summarize the major fiscal pressures in FY 2025").
- An out-of-scope query that should hit `refusal_out_of_scope` via the system prompt's policy-question rule.

Each query: `expected_answer_contains: list[str]` (substring matches in the rendered answer) + `expected_citations_must_include: list[chunk-shape constraint]` + `expected_refusal: bool` + (for multi-turn) `turns: list[{query, expected_answer_contains, ...}]`.

### Task 7.2: End-to-end eval runner

**Files:**
- Create: `eval/run_e2e_eval.py`

- [ ] **Step 1: Run each query through the full stack**

For each query: POST `/api/query` with the query text → receive `{answer, citations, refusal}`. Compare against expected. Per-query: pass / fail with reason (retrieval miss / faithfulness strip / classifier miscall / unexpected refusal).

- [ ] **Step 2: Compute spec §13 metrics**

- Per-query-type accuracy (lookup / comparison / synthesis / out-of-scope)
- Faithfulness pass rate
- Refusal rate (correct refusals / total)
- Citation precision (cited the right chunk?) and recall (cited all the right chunks?)
- End-to-end latency p50, p95

- [ ] **Step 3: Persist results in `eval_runs`**

Insert one row per `run_eval` invocation. Schema already in 1b's 0001 migration.

### Task 7.3: Phase 1 done bar

**Files:**
- Create: `docs/superpowers/investigations/2026-MM-DD-phase-1-launch-readiness.md`

- [ ] **Step 1: Run end-to-end eval; report**

Pass bar for Phase 1 done (per spec §7 — "End-to-end working but only on Destin's machine"):

- Retrieval recall@20 ≥ 80% on lookup queries (already the 1b bar — verify it still holds)
- Faithfulness pass rate ≥ 80% (relaxed vs. spec §14's Phase 4 gate of ≥ 95%)
- Refusal rate within [5%, 50%] (wider band than Phase 4's [5%, 35%])
- Zero citations rendering past faithfulness check that point at the wrong chunk on a 5-query manual spot check
- End-to-end latency p95 ≤ 8s (Pro/Max LLM call dominates; if higher, profile + optimize)

If pass bar is met, Phase 1 is done. Tag `phase-1-complete`.

If bar isn't met, the failure mode usually points at the workstream to revisit:
- Retrieval recall low → 1b chunk-shape or retrieval issue
- Faithfulness pass low → verifier model swap (option A → B) or prompt tuning in companion
- Citations point at wrong chunk → tool-call parsing bug in companion or chip-rendering bug in UI
- High latency → retrieval bridge cold start, big-table chunk size, or Pro/Max throttling

### Task 7.4: Smoke test on Destin's machine

- [ ] **Step 1: Bring whole stack up**

Required running processes: YouCoded (with Budget MCP server registered) + Postgres (Docker) + retrieval FastAPI sidecar + Next.js dev server. A `scripts/dev.sh` (or `.ps1`) starts everything except YouCoded itself (which Destin runs). Open `localhost:3000`. Run a handful of queries by hand, confirm:
- Conversation thread accepts user messages and renders streaming assistant responses
- Tool calls (retrieve, cite) visible as breadcrumbs in the assistant message
- Citation chips render with right glyphs (✓ / ≈)
- Click → PDF jumps + highlights bbox
- DOCX-source citations show "viewer coming in Phase 2" panel (per D10 deferral)
- Refusal banners render the right copy
- Follow-up turns work — anaphora resolves correctly via Claude's session context
- Closing/reopening YouCoded breaks the budget app cleanly with the "please open YouCoded" banner

Document any rough edges in `docs/known-issues-phase-1.md` for Phase 2 polish.

---

## Deferred decisions (explicit non-goals)

These are explicit non-goals for Phase 1 — captured for Phase 2+ planning:

- **Standalone companion app.** Phase 2: ship a packaged companion (lifts YouCoded's PTY/wrapper + WebSocket layer) so the budget app can run without YouCoded installed. Phase 1 hard-depends on YouCoded.
- **DOCX HTML viewer + verify-mode toggle.** Phase 2 polish (D10).
- **Multi-tenant deployment.** Phase 2: free-tier Vercel + Supabase. Phase 1 is single-machine.
- **Auth.** Phase 2: Google SSO restricted to azleg.gov. Phase 1: localhost, no auth needed (relies on YouCoded's existing OAuth for Claude).
- **Eval expansion to 50 (and eventually 200).** Phase 1.5 / Phase 3.
- **AnthropicAPIProvider / SelfHostedLLMProvider.** Phase 3 / 4.
- **Tier 2 entity resolution.** Phase 3 — programs and sub-programs canonicalization. Phase 1's per-agency outline trees give us partial coverage.
- **AFR restated-table handling decision.** Spec §16 open question. Phase 2 decision.
- **Public-launch metrics gate.** Spec §14. Phase 4.

## What "Phase 1 done" means (full Phase 1 across 1a + 1b + 1c)

By the end of Phase 1c (and therefore Phase 1):

- A running YouCoded instance has the Budget MCP server registered with `retrieve` + `cite` tools
- Destin can open `localhost:3000` and have a multi-turn budget chat
- Claude calls `retrieve()` per turn (constrained agent rule); citations come back as `cite()` tool calls
- Citation chips render with right glyphs; click → source PDF page with cited region highlighted
- Multi-turn follow-ups work (anaphora resolved via Claude's session context)
- Faithfulness verifier strips ungrounded claims with a visible note
- Refusal cases render the right banner copy + raw chunks
- Audit log accumulates rows in `conversations`, `messages`, `queries`
- Eval set (~35 queries) passes the Phase 1 bar (§7.3 above)
- The budget stack starts with one command (`scripts/dev.sh`); YouCoded is a manual prerequisite documented in the README
- `phase-1-complete` tag created

Phase 2 takes this and builds: standalone companion (so the app can run without YouCoded), DOCX HTML viewer, verify-mode, free-tier deployment, 2-3 trusted-analyst onboarding.

## Pointer to the conversation

The Phase 1 split decision (1a → ingest+chunk, 1b → store+retrieve, 1c → synthesize+UI), the Order C ingest priority, the retrieval-bridge Option B (FastAPI sidecar), and the faithfulness-verifier-Option-A default were settled during the 2026-05-06 cleanup pass.
