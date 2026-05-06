# Phase 1c — Companion + Synthesis + UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the LLM synthesis layer + faithfulness verifier + web UI on top of Phase 1b's retrieval API, producing a working end-to-end product on Destin's machine. By the end of Phase 1c, Destin can type a question into a browser, get an answer with citation chips, click a chip, and see the source PDF page with the cited region highlighted. This is "Phase 1 — Working prototype" complete per spec §7.

**Inputs from Phase 1b:**
- `retrieve(RetrievalRequest) -> RetrievalResult` retrieval API at `retrieval/pipeline.py`
- Postgres with all chunks + embeddings + indexes
- Eval set at `eval/queries.yaml` with ~30 queries
- Refusal threshold locked
- `data/system-prompt-context.md` from Phase 1a (writing draft + Gov glossary)
- `phase-1b-complete` git tag

**Scope this plan:**
- LLM provider abstraction (`LLMProvider` interface) + `LocalCompanionProvider` implementation
- Companion app (lifts from YouCoded's PTY/wrapper infra)
- Tool-call citation emission (`cite(chunk_id, span_start, span_end, confidence)`)
- NLI/judge faithfulness verifier
- Next.js web UI (search bar, answer pane, citation chips)
- PDF.js + react-pdf-highlighter-extended viewer
- DOCX → HTML on-demand renderer with stable paragraph IDs
- Audit log writes (the `queries` table populated)
- Eval expansion to ~50 queries
- End-to-end smoke test on Destin's machine

**Out of scope (deferred to Phase 2):**
- Companion app distribution to other analysts
- Public web deployment (Vercel + Supabase)
- AnthropicAPIProvider (uses single shared org account)
- SelfHostedLLMProvider (open-weight model)
- Tier 2 entity resolution (program-level)
- Larger eval set expansion (Phase 3)

**Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│ Browser (localhost:3000)                                │
│  Next.js SPA: search bar, answer pane, PDF viewer       │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS / API routes
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Web server (Next.js, localhost:3000)                    │
│  Routes:                                                │
│   POST /api/query → calls retrieve() + synthesize()    │
│   GET  /api/pdf/:doc_id → HTTP range serving            │
│   GET  /api/docx/:doc_id → on-demand HTML render        │
│  Faithfulness verifier (post-synthesis)                 │
│  Audit log writer                                       │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────┴───────────┐
              ▼                        ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│ Postgres                  │  │ Companion app            │
│ (Phase 1b — chunks etc.)  │  │ (localhost:9100)         │
│                           │  │  • Wraps Claude Code     │
│                           │  │  • WebSocket transport   │
│                           │  │  • System tray UI only   │
└──────────────────────────┘  └──────────────────────────┘
```

**Tech Stack:**
- Web app: Next.js 14 (App Router) + React 18 + TypeScript
- PDF viewer: `pdfjs-dist` + `react-pdf-highlighter-extended`
- DOCX → HTML: `mammoth.js` (Node, server-side render)
- Companion: lifts from YouCoded's existing PTY/wrapper infrastructure (`youcoded/desktop/src/main/pty-worker.js` + claude-code wrapper). Initial implementation: a small Node.js process exposing a localhost WebSocket; can later become an Electron app for distribution.
- Faithfulness verifier: NLI model self-hosted (e.g., `sentence-transformers/cross-encoder-nli-deberta-v3-base`) OR an LLM judge call — decision in Workstream 3.
- Python for retrieval (re-used from 1b); Node for web + companion (different runtime). Web server calls retrieval via subprocess or HTTP-bridge — see Workstream 6.

**Source spec:** `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` — §4 (architecture), §4.2 (provider abstraction), §5 (data flow), §10 (citation UX), §11 (refusal), §12 (audit log).

---

## File structure

Files created during Phase 1c:

| Path | Purpose | Tracked? |
|---|---|---|
| `companion/server.js` | Localhost WebSocket server wrapping Claude Code | ✓ |
| `companion/synthesize.js` | Builds the synthesis prompt + tool definitions | ✓ |
| `companion/claude-wrapper.js` | YouCoded-style claude-code wrapper (lifted) | ✓ |
| `companion/package.json` | Companion app deps | ✓ |
| `companion/README.md` | Companion app setup + run instructions | ✓ |
| `web/` | Next.js app root | ✓ |
| `web/package.json` | Web deps | ✓ |
| `web/app/page.tsx` | Single-page UI (search, answer, viewer) | ✓ |
| `web/app/api/query/route.ts` | POST /api/query handler | ✓ |
| `web/app/api/pdf/[doc_id]/route.ts` | PDF range-serving | ✓ |
| `web/app/api/docx/[doc_id]/route.ts` | DOCX → HTML | ✓ |
| `web/components/SearchBar.tsx` | Query input | ✓ |
| `web/components/AnswerPane.tsx` | Renders answer with citation chips | ✓ |
| `web/components/CitationChip.tsx` | Underlined-span chip with hover/click | ✓ |
| `web/components/PdfViewer.tsx` | PDF.js + react-pdf-highlighter wrapper | ✓ |
| `web/components/DocxViewer.tsx` | HTML viewer with paragraph-id highlight | ✓ |
| `web/components/RefusalBanner.tsx` | Three refusal cases per spec §11 | ✓ |
| `web/components/VerifyModeToggle.tsx` | Spec §10.3 toggle | ✓ |
| `web/lib/retrieval-bridge.ts` | Calls Python retrieval (subprocess or HTTP) | ✓ |
| `web/lib/llm-provider.ts` | `LLMProvider` interface + `LocalCompanionProvider` | ✓ |
| `web/lib/faithfulness.ts` | NLI/judge verifier | ✓ |
| `web/lib/citation-merge.ts` | Merges multi-chunk citations into one rendered span | ✓ |
| `web/lib/audit-log.ts` | Writes to `queries` table | ✓ |
| `web/tests/...` | Component + integration tests (Playwright for E2E) | ✓ |
| `eval/queries-expanded.yaml` | ~50-query eval set (1b's 30 + 20 added) | ✓ |
| `eval/run_e2e_eval.py` | Runs full retrieval + synthesis + faithfulness, scores against expected_answer_contains | ✓ |

Files modified:
- `pyproject.toml` — add `fastapi>=0.110` + `uvicorn` if we choose HTTP-bridge for retrieval
- `.gitignore` — add `web/.next/`, `web/node_modules/`, `companion/node_modules/`

Secrets:
- `.env.local` — `ANTHROPIC_OAUTH_TOKEN` (read by companion via Claude Code's existing auth flow), `DATABASE_URL` (web → Postgres for audit log), `RETRIEVAL_BRIDGE_URL` (web → retrieval).

---

## Workstream 1 — LLM Provider abstraction

**Goal:** Define the `LLMProvider` TypeScript interface and the `LocalCompanionProvider` implementation. Per spec §4.2 — this separation lets us swap providers in later phases without touching retrieval or UI.

### Task 1.1: Provider interface

**Files:**
- Create: `web/lib/llm-provider.ts`
- Create: `web/tests/test_llm_provider.ts`

- [ ] **Step 1: Write the interface (matches spec §4.2)**

```ts
export interface LLMProvider {
  synthesize(args: {
    query: string;
    chunks: Chunk[];
    queryType: "lookup" | "comparison" | "synthesis";
  }): Promise<{
    answer: string;
    citations: Citation[];
    refusal?: RefusalReason;
  }>;
}

export type Citation = {
  chunkId: string;
  spanStart: number;   // char offset in answer
  spanEnd: number;
  confidence: number;  // model's self-reported [0..1]
};

export type RefusalReason =
  | { type: "no_retrieval" }
  | { type: "synthesis"; chunks_shown: string[] }
  | { type: "out_of_scope" };
```

- [ ] **Step 2: Failing test — mock provider returns expected shape**

```ts
test("mock provider returns valid LLMProvider shape", async () => {
  const mock: LLMProvider = {
    synthesize: async () => ({
      answer: "test",
      citations: [{ chunkId: "c1", spanStart: 0, spanEnd: 4, confidence: 0.9 }],
    }),
  };
  const result = await mock.synthesize({ query: "q", chunks: [], queryType: "lookup" });
  expect(result.citations[0].chunkId).toBe("c1");
});
```

### Task 1.2: LocalCompanionProvider

**Files:**
- Update: `web/lib/llm-provider.ts`

- [ ] **Step 1: Implement against companion WebSocket**

```ts
export class LocalCompanionProvider implements LLMProvider {
  constructor(private url = "ws://localhost:9100") {}

  async synthesize(args) {
    const ws = new WebSocket(this.url);
    return new Promise((resolve, reject) => {
      ws.onopen = () => ws.send(JSON.stringify({ type: "synthesize", payload: args }));
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === "synthesize:result") resolve(data.payload);
        if (data.type === "synthesize:error") reject(new Error(data.payload.message));
      };
      ws.onerror = (err) => reject(err);
    });
  }
}
```

- [ ] **Step 2: Failing test against a stub companion server**

Spin up a tiny Node WebSocket server in the test that replies with a canned `synthesize:result`; assert client decodes correctly.

---

## Workstream 2 — Companion app

**Goal:** Lift the Claude-Code-wrapping infrastructure from YouCoded into a small standalone Node app. Exposes a localhost WebSocket; receives `(query, chunks, queryType)`; runs Claude Code with a structured prompt; emits answer + tool-call citations.

This is the most YouCoded-coupled workstream — the wrapper, PTY setup, and Pro/Max-OAuth flow already exist there. We're not building from scratch; we're vendoring (or borrowing) and trimming.

### Task 2.1: Lift the wrapper from YouCoded

**Files:**
- Create: `companion/claude-wrapper.js`
- Create: `companion/server.js`
- Create: `companion/package.json`

- [ ] **Step 1: Identify YouCoded source files to lift**

Read `youcoded/desktop/src/main/pty-worker.js` and `youcoded/app/src/main/assets/claude-wrapper.js` (Android version for reference). The desktop pty-worker.js is the closer match — it's already a Node process that spawns Claude Code as a child PTY.

- [ ] **Step 2: Copy + trim**

Copy `pty-worker.js` to `companion/claude-wrapper.js`. Strip everything that's YouCoded-app-specific (terminal UI plumbing, session strip metadata, tool routing). Keep: PTY spawn, OAuth-token plumbing, stdout streaming.

- [ ] **Step 3: Wrap as a WebSocket server**

`companion/server.js`:

```js
const WebSocket = require("ws");
const { spawnClaudeCode, sendQuery } = require("./claude-wrapper");

const wss = new WebSocket.Server({ port: 9100 });
wss.on("connection", (ws) => {
  ws.on("message", async (raw) => {
    const msg = JSON.parse(raw);
    if (msg.type === "synthesize") {
      try {
        const result = await synthesize(msg.payload);
        ws.send(JSON.stringify({ type: "synthesize:result", payload: result, id: msg.id }));
      } catch (err) {
        ws.send(JSON.stringify({ type: "synthesize:error", payload: { message: err.message }, id: msg.id }));
      }
    }
  });
});
```

- [ ] **Step 4: Run instructions in `companion/README.md`**

```bash
cd companion
npm install
node server.js  # listens on ws://localhost:9100
```

Document: requires Claude Code installed + Pro/Max OAuth completed via `claude /login`. Reuses the YouCoded auth approach — companion doesn't manage its own credentials.

### Task 2.2: Synthesis prompt + tool definitions

**Files:**
- Create: `companion/synthesize.js`
- Create: `companion/tests/test_synthesize.js`

- [ ] **Step 1: Build the prompt**

```js
function buildSystemPrompt(domainPrimer) {
  return [
    "You are an Arizona state budget analyst's assistant.",
    "You answer fiscal questions by citing exact source chunks.",
    "",
    "**Hard rules:**",
    "- Every factual claim must be supported by a `cite()` tool call.",
    "- Use the `cite()` tool with the chunk_id and the span (start, end) in your answer text where the supported claim appears.",
    "- If the chunks don't support a claim, do not make it. Refuse with `refuse(reason)` if you can't answer faithfully.",
    "- Be terse. Analysts know the domain; no over-explanation.",
    "",
    "**Domain reference:**",
    domainPrimer,
  ].join("\n");
}

function buildUserMessage(query, chunks, queryType) {
  return [
    `Query type: ${queryType}`,
    `Query: ${query}`,
    "",
    "Available chunks:",
    chunks.map((c, i) => `[${i}] chunk_id=${c.chunkId}\n${c.text}`).join("\n\n"),
    "",
    "Provide an answer using only what the chunks support. Emit `cite()` calls for each supported claim.",
  ].join("\n");
}
```

- [ ] **Step 2: Define the `cite` and `refuse` tools**

Claude tool-use format:

```js
const tools = [
  {
    name: "cite",
    description: "Anchor a claim to a source chunk. Call once per factual claim.",
    input_schema: {
      type: "object",
      properties: {
        chunk_id: { type: "string" },
        span_start: { type: "integer", description: "Char offset in the answer where the claim begins" },
        span_end: { type: "integer", description: "Char offset where the claim ends" },
        confidence: { type: "number", description: "0..1 self-reported confidence in the citation" },
      },
      required: ["chunk_id", "span_start", "span_end", "confidence"],
    },
  },
  {
    name: "refuse",
    description: "Decline to answer when chunks don't support a confident answer.",
    input_schema: {
      type: "object",
      properties: {
        reason: { type: "string", enum: ["synthesis", "out_of_scope"] },
        explanation: { type: "string" },
      },
      required: ["reason"],
    },
  },
];
```

- [ ] **Step 3: Parse the response**

Claude's tool-use response interleaves text blocks and tool-use blocks. Walk the assistant's content array; collect text into the `answer`; collect `cite` tool uses into `citations`; if `refuse` was called, return a refusal.

- [ ] **Step 4: Failing test — mock Claude response → structured output**

Synthetic Claude API response with two text blocks + three `cite` calls; verify the parser produces correct `(answer, citations)` tuple.

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

## Workstream 4 — Web UI

**Goal:** Single Next.js page with search bar, answer pane, side-panel viewer, citation chips. Implements spec §10 citation UX.

### Task 4.1: Next.js scaffold + layout

**Files:**
- Create: `web/app/page.tsx`
- Create: `web/app/layout.tsx`

- [ ] **Step 1: Scaffold Next.js 14 App Router project**

```bash
npx create-next-app@latest web --typescript --app --tailwind --no-src-dir
```

- [ ] **Step 2: Two-column layout**

Left column: search bar + answer pane. Right column: PDF/DOCX viewer. Resizable divider via `react-resizable-panels` or CSS grid.

### Task 4.2: SearchBar + AnswerPane

**Files:**
- Create: `web/components/SearchBar.tsx`
- Create: `web/components/AnswerPane.tsx`

- [ ] **Step 1: SearchBar — text input + submit**

Posts to `/api/query`. Streams the answer (Vercel AI SDK pattern) so chips appear as the LLM emits them.

- [ ] **Step 2: AnswerPane — renders answer with chips**

Walks the (answer, citations) tuple. Each citation underlines the span and renders a numbered chip at the end of the underlined span. Chips show one of three glyphs per spec §10.1: ✓ verbatim, ≈ paraphrase, ⚠ ungrounded (the last is rendered as `[claim removed]` rather than as a chip after Workstream 3 stripping).

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

**Files:**
- Create: `web/components/DocxViewer.tsx`
- Create: `web/app/api/docx/[doc_id]/route.ts`

- [ ] **Step 1: Server-side mammoth.js render**

```ts
// web/app/api/docx/[doc_id]/route.ts
import mammoth from "mammoth";
export async function GET(req, { params }) {
  const docxPath = await resolveDocPath(params.doc_id);
  const result = await mammoth.convertToHtml({ path: docxPath }, {
    transformDocument: addStableIds,  // see Step 2
  });
  return new Response(result.value, { headers: { "content-type": "text/html" } });
}
```

- [ ] **Step 2: Stable paragraph ID transform**

Per spec §10.5: every `<w:p>` becomes `<p id="...">` with the same `w14:paraId` value Phase 1a captured in `chunks.source_anchor.paragraph_id`. Mammoth's transform API lets us inject ids during render. **This is the contract that makes citation→highlight work for DOCX.**

- [ ] **Step 3: DocxViewer component**

Loads the HTML via fetch, sets `dangerouslySetInnerHTML`. On `citation:select(chunkId)`, looks up `chunks.source_anchor.paragraph_id`, scrolls to `#<paragraph_id>`, paints a yellow background highlight. Multi-paragraph chunks get multiple highlights.

- [ ] **Step 4: Stable-id contract test**

Re-rendering the same DOCX twice must produce the same paragraph ids. Run mammoth twice on `samples/raw-docx/budget-bill-sb1735-2025.docx`; assert identical id sets. Otherwise highlighting silently mismatches the cited paragraph.

### Task 4.6: Refusal banner + verify mode toggle

**Files:**
- Create: `web/components/RefusalBanner.tsx`
- Create: `web/components/VerifyModeToggle.tsx`

- [ ] **Step 1: RefusalBanner — three cases per spec §11**

`refusal_no_retrieval`, `refusal_synthesis`, `refusal_out_of_scope`. Each renders the spec's exact copy plus, for `synthesis` and `out_of_scope`, the top 5 chunks for the analyst to read directly.

- [ ] **Step 2: VerifyModeToggle per spec §10.3**

Off by default. When on: scrolling the answer pane scrolls the viewer to the chunk corresponding to the citation that just came into view. Implement via IntersectionObserver on chip elements.

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
    sub_queries: retrieval.sub_queries,
    retrieved_chunk_ids: retrieval.chunks.map(c => c.chunkId),
    reranker_scores: retrieval.reranker_scores,
    chunks_sent_to_llm: retrieval.chunks.map(c => c.chunkId),
    llm_provider: "local-companion",
    llm_response_raw: synthResult.answer,
    citations_emitted: synthResult.citations,
    faithfulness_verdicts: verified.verdicts,
    final_answer_rendered: verified.cleanedAnswer,
    refusal_type: synthResult.refusal?.type ?? null,
    latency_ms: Date.now() - start,
  });
  return NextResponse.json({ answer: verified.cleanedAnswer, citations: verified.citations, refusal: synthResult.refusal });
}
```

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

**Goal:** Expand Phase 1b's ~30-query eval set to ~50, run end-to-end (retrieval + synthesis + faithfulness), measure full-system metrics.

### Task 7.1: Expand eval set

**Files:**
- Update/Create: `eval/queries-expanded.yaml`

- [ ] **Step 1: Add 20 more queries**

Targeted at gaps from Phase 1b's eval results. Cover:
- Cross-publisher comparisons (Gov rec vs. enacted)
- Year-over-year comparisons (multi-year fan-out)
- Bills-anchored questions ("show me the legal text appropriating $X to Y")
- Fund-level questions answered by s18/bd2 cross-cuts
- AFR audited-vs-enacted comparisons
- Out-of-scope refusal cases (3 of them: editorial, hypothetical, beyond-corpus)
- Synthesis cases ("summarize the major fiscal pressures in FY 2025")

Each query: `expected_answer_contains: list[str]` (substring matches in the rendered answer) + `expected_citations_must_include: list[chunk-shape constraint]` + `expected_refusal: bool`.

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

- [ ] **Step 1: Bring whole stack up via `scripts/dev.sh`**

Postgres + retrieval sidecar + companion server + Next.js. Open `localhost:3000`. Run a handful of queries by hand, confirm:
- Citation chips render with right glyphs
- Click → PDF jumps + highlights bbox
- DOCX click → paragraph highlights
- Refusal banners render the right copy
- Verify mode synchronizes answer scrolling with viewer

Document any rough edges in `docs/known-issues-phase-1.md` for Phase 2 polish.

---

## Deferred decisions (explicit non-goals)

These are explicit non-goals for Phase 1 — captured for Phase 2+ planning:

- **Companion app distribution.** Phase 2: ship a packaged Electron/Tauri build for the 2-3 trusted analyst rollout. Phase 1's companion is a Node script Destin runs locally.
- **Multi-tenant deployment.** Phase 2: free-tier Vercel + Supabase. Phase 1 is single-machine.
- **Auth.** Phase 2: Google SSO restricted to azleg.gov. Phase 1: localhost, no auth needed.
- **Eval expansion to 200 queries.** Phase 3.
- **AnthropicAPIProvider / SelfHostedLLMProvider.** Phase 3 / 4.
- **Tier 2 entity resolution.** Phase 3 — programs and sub-programs canonicalization. Phase 1's per-agency outline trees give us partial coverage; Phase 3 fills in the rest using real query log analysis.
- **AFR restated-table handling decision.** Spec §16 open question. Phase 2 decision.
- **Public-launch metrics gate.** Spec §14. Phase 4.
- **Comparison query fan-out heuristics for "compare X" without explicit years.** Spec §16 open question. Phase 1 refuses without explicit years; Phase 2 picks heuristic from real query patterns.

## What "Phase 1 done" means (full Phase 1 across 1a + 1b + 1c)

By the end of Phase 1c (and therefore Phase 1):

- Destin can type a question into a localhost browser and get an answer with citation chips
- Click a chip → the source PDF page opens with the cited region highlighted
- DOCX-source citations open the on-demand HTML render with paragraph highlight
- Faithfulness verifier strips ungrounded claims with a visible note
- Refusal cases render the right banner copy + raw chunks
- Audit log accumulates one row per query
- Eval set passes the Phase 1 bar (§7.3 above)
- The whole stack starts with one command (`scripts/dev.sh`)
- `phase-1-complete` tag created

Phase 2 takes this and builds: companion app distribution, free-tier deployment, 2-3 trusted-analyst onboarding.

## Pointer to the conversation

The Phase 1 split decision (1a → ingest+chunk, 1b → store+retrieve, 1c → synthesize+UI), the Order C ingest priority, the retrieval-bridge Option B (FastAPI sidecar), and the faithfulness-verifier-Option-A default were settled during the 2026-05-06 cleanup pass.
