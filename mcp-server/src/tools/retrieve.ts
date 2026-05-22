// MCP `retrieve` tool — locked schema lives in
// docs/superpowers/decisions/2026-05-06-citation-tool-schema.md.
//
// Forwards the call to the FastAPI sidecar (retrieval/api.py) and
// returns the response payload as a JSON-string `text` content block —
// that's the only structured way to hand the chunk list back through
// the MCP transport so Claude can reason over it. The system prompt
// (mcp-server/system-prompt.md) tells Claude how to consume that
// payload (parse JSON, cite by chunk_id, refuse on top_score < 0.65).

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { loadConfig, type Config } from "../config.js";
import { postJson, type Fetcher } from "../lib/bridge.js";

// Each filter dimension matches the FastAPI sidecar's RetrieveFiltersBody
// 1:1. Defining them at module scope (rather than inline inside
// inputSchema) makes them re-usable by tests + readable when the schema
// doc is referenced.
const filtersSchema = z
  .object({
    fiscal_year: z
      .array(z.number().int().min(2015).max(2030))
      .optional()
      .describe("Restrict to documents covering these fiscal years (any-of)."),
    doc_type: z
      .array(
        // The enum values below MUST match the `doc_type` values
        // actually present in the documents table. Pre-2026-05-08
        // this enum drifted from the DB:
        //
        //   - It accepted `baseline-agency` / `approps-report` /
        //     `baseline-cross-cut` / `primer` — none of which exist
        //     in the corpus, so any retrieval filtered to one
        //     returned 0 chunks (silent zero, no error).
        //   - It rejected the values that DO exist
        //     (`baseline-per-agency`, `approps-per-agency`,
        //     `s-pdf`, `bd-pdf`, `bh-pdf`, `detailed-list-pdf`,
        //     `topic-pdf`) — so when the system prompt told the
        //     model to filter on those, the call hit a zod
        //     validation error.
        //
        // The fix is to mirror the DB exactly. If a future ingest
        // adds a new doc_type, extend this enum AND `system-prompt.md`.
        // The list_filter_values MCP tool is the runtime source of
        // truth; this enum exists for input validation at the MCP
        // boundary.
        z.enum([
          "baseline-per-agency",
          "approps-per-agency",
          "s-pdf",
          "bd-pdf",
          "bh-pdf",
          "detailed-list-pdf",
          "topic-pdf",
          "afr",
          "governors-budget",
          "budget-bill",
        ]),
      )
      .optional()
      .describe("Restrict to document types (any-of)."),
    publisher: z
      .array(z.enum(["jlbc", "legislature", "governor", "agao"]))
      .optional()
      .describe("Restrict to publishers (any-of)."),
    agency_canonical_id: z
      .array(z.string())
      .optional()
      .describe(
        "Restrict to chunks tagged with these agency IDs (e.g. 'agency:adc'; any-of, GIN-indexed).",
      ),
    fund_canonical_id: z
      .array(z.string())
      .optional()
      .describe("Restrict to chunks whose primary fund matches (any-of)."),
    is_table: z
      .boolean()
      .optional()
      .describe("If true, return only tabular chunks; if false, only narrative."),
  })
  .strict();

// MCP `registerTool` takes a ZodRawShape (object literal of zod fields),
// not a wrapped z.object. Keep the shape here as a value the tests can
// reuse for direct validation.
export const retrieveInputShape = {
  query: z
    .string()
    .min(1)
    .describe(
      "Natural-language search query. Expand acronyms before calling " +
        "(e.g., 'AHCCCS' → 'Arizona Health Care Cost Containment System AHCCCS'). " +
        "Be specific; vague queries reduce recall.",
    ),
  filters: filtersSchema
    .optional()
    .describe("Optional filters to narrow the search."),
  top_k: z
    .number()
    .int()
    .min(1)
    .max(50)
    .optional()
    .describe(
      "Number of chunks to return after rerank. When `intent` is set, " +
        "the server overrides this with the intent's default top_k " +
        "(lookup→5, compare→12, analyze→18); pass top_k explicitly to " +
        "override. NOTE: the FIRST retrieve() of any session is capped " +
        "to 5 chunks regardless of this value (progressive-retrieval " +
        "discipline — see deep_dive for the opt-out). Subsequent calls " +
        "honor this field normally.",
    ),
  // Added 2026-05-20: route classifier that hints at the analysis depth
  // the user is asking for. Tunes top_k server-side and is recorded in
  // the audit log so future eval can correlate answer quality with
  // routing decisions.
  intent: z
    .enum(["lookup", "compare", "analyze"])
    .optional()
    .describe(
      "Question-depth classifier set by Claude based on the user's " +
        "question. 'lookup' = one specific fact (top_k 5, terse answer). " +
        "'compare' = side-by-side of two entities/years (top_k 12). " +
        "'analyze' = open-ended overview (top_k 18, structured answer). " +
        "Optional; omit when unsure. NOTE: the FIRST retrieve() of any " +
        "session is capped to 5 chunks regardless of intent — see " +
        "deep_dive for the opt-out. After that, intent is honored.",
    ),
  // Added 2026-05-20: opt-out for the first-call cap. Set true when the
  // analyst explicitly requested thorough/comprehensive coverage and
  // the model needs the full retrieve breadth on the very first call.
  // Default false (cap fires). On second+ calls, has no effect.
  deep_dive: z
    .boolean()
    .optional()
    .describe(
      "Set true ONLY when the analyst explicitly asked for thorough / " +
        "comprehensive / 'deep dive' coverage and you need the full " +
        "intent-resolved top_k on the very FIRST retrieve() of the " +
        "session. By default, the first retrieve() is capped to 5 " +
        "chunks so you can sample before pulling more (call retrieve() " +
        "again with a sharper query or higher top_k once you see what " +
        "the sample contains). Most questions don't need this. " +
        "Only has an effect on the first retrieve() of a session.",
    ),
};

export const retrieveInputSchema = z.object(retrieveInputShape);

export type RetrieveInput = z.infer<typeof retrieveInputSchema>;

// Return shape the FastAPI sidecar produces. Mirrors the
// citation-tool-schema.md contract verbatim.
export interface ChunkOut {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  text: string;
  score: number;
}

export interface RetrieveBridgeResponse {
  chunks: ChunkOut[];
  top_score: number;
  retrieval_id: string;
  bm25_count: number;
  dense_count: number;
  fused_count: number;
}

const TOOL_DESCRIPTION =
  "Search the Arizona budget corpus and return the most relevant chunks " +
  "for a query. Call this BEFORE answering any user question that asks " +
  "about budget content. You MAY call retrieve() multiple times per turn " +
  "(e.g. one call per side of a comparison). Use filters when the user's " +
  "question implies them (a specific fiscal year, agency, publisher, etc.). " +
  "Returns chunks with chunk_id values that you must echo back into cite() " +
  "calls — never invent a chunk_id. If `top_score` < 0.30, do NOT cite; " +
  "respond with the refusal phrase from the system prompt. " +
  "PROGRESSIVE RETRIEVAL: the FIRST retrieve() of any session is capped " +
  "at 5 chunks regardless of what you pass — sample first, expand only " +
  "if the sample isn't enough. The response carries `first_call_capped: " +
  "true` on that call so you know. To opt out (analyst explicitly asked " +
  "for thorough / comprehensive / deep-dive coverage), pass " +
  "`deep_dive: true` on the first call.";

/** Module-level state — one MCP server process per Claude Code session,
 *  so a simple boolean is enough to track "is this the first retrieve()
 *  of the session." Resets when the process restarts (i.e. on new
 *  session), which is exactly the semantics we want. */
let isFirstRetrieveCall = true;

/** How small the first retrieve() of a session is forced to be. Matches
 *  lookup's top_k so a question whose first call lands well doesn't
 *  need a follow-up. The number is tunable; named so callers /
 *  tests / observers can refer to it without re-deriving "5". */
export const FIRST_CALL_TOP_K_CAP = 5;

/** Test-only reset. Production never resets — the MCP server process
 *  is short-lived (one per session) and the natural restart on a new
 *  session is the intended trigger. Tests need this to exercise the
 *  cap independently. */
export function resetFirstCallStateForTests(): void {
  isFirstRetrieveCall = true;
}

/** Build the retrieve tool callback. `fetcher` is injected for tests
 *  so they can stub the HTTP boundary without spinning a real server. */
export function makeRetrieveHandler(
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
) {
  return async (input: RetrieveInput) => {
    // Progressive-retrieval discipline: the first retrieve() of a
    // session is capped to FIRST_CALL_TOP_K_CAP regardless of the
    // model's requested top_k or intent. This forces a small sample
    // first so the model can read it and decide whether to expand.
    // Opt-out: model sets `deep_dive: true` when the analyst
    // explicitly asked for thorough coverage. After the first call,
    // the flag flips and pass-through behavior resumes.
    const firstCallCappedNow =
      isFirstRetrieveCall && input.deep_dive !== true;
    // Flip the flag NOW (before the await) so concurrent retrieve()
    // calls in the same turn don't all see "first call" — only the
    // earliest dispatch wins the cap.
    if (isFirstRetrieveCall) isFirstRetrieveCall = false;

    const body: Record<string, unknown> = {
      query: input.query,
      filters: input.filters ?? null,
    };
    if (firstCallCappedNow) {
      // Hard override — wins over both input.top_k and intent's
      // resolved default. Forward `intent` anyway so the audit log
      // sees the model's classification, but the explicit top_k=5
      // takes precedence in the sidecar's resolution chain.
      body.top_k = FIRST_CALL_TOP_K_CAP;
      if (input.intent !== undefined) body.intent = input.intent;
    } else {
      if (input.top_k !== undefined) body.top_k = input.top_k;
      if (input.intent !== undefined) body.intent = input.intent;
    }

    let result: RetrieveBridgeResponse;
    try {
      result = await postJson<RetrieveBridgeResponse>(
        cfg,
        "/retrieve",
        body,
        fetcher,
      );
    } catch (err) {
      // Surface bridge errors as a tool error so Claude sees them
      // instead of a silent failure. `isError: true` is the MCP
      // convention for tool-side problems vs successful responses.
      return {
        content: [
          {
            type: "text" as const,
            text:
              `retrieve() failed: ${(err as Error).message}. ` +
              `Tell the user the retrieval service is unavailable.`,
          },
        ],
        isError: true,
      };
    }

    // Augment the response with the first_call_capped flag so the
    // model can tell why the result is smaller than its ask. We
    // include this signal only when the cap actually fired — second-
    // and-later calls (and first-call deep_dive opt-outs) return the
    // sidecar's response unchanged.
    const responseToModel = firstCallCappedNow
      ? { ...result, first_call_capped: true }
      : result;

    return {
      content: [
        {
          type: "text" as const,
          // The model parses this JSON. Pretty-printing aids debug
          // visibility without measurably costing tokens — chunks
          // are bounded by `top_k`.
          text: JSON.stringify(responseToModel, null, 2),
        },
      ],
    };
  };
}

export function registerRetrieveTool(
  server: McpServer,
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
): void {
  server.registerTool(
    "retrieve",
    {
      description: TOOL_DESCRIPTION,
      inputSchema: retrieveInputShape,
    },
    makeRetrieveHandler(cfg, fetcher),
  );
}
