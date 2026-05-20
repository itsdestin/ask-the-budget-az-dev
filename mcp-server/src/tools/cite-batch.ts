// MCP `cite_batch` tool — added 2026-05-20.
//
// Why this exists: the original `cite(chunk_id, ..., claim_span)` tool
// requires one tool_use → one tool_result round-trip per citation. A
// typical analyze-shaped answer carries 15-25 distinct claims; serial
// round-trips burn 45-75s of LLM-turn cycle time just registering
// citations. The model already wants to emit all citations after the
// answer is written; giving it a tool that takes them as a single
// call collapses those round-trips into one.
//
// Contract:
//   - Input is an array of citation objects, each matching the same
//     shape as the single `cite` tool (chunk_id, claim_span,
//     confidence, plus either quote OR span_start+span_end).
//   - The handler dispatches to the sidecar's /cite/validate_batch
//     endpoint, which does ONE bulk DB fetch for all unique chunks
//     and validates each in-memory.
//   - Response is a parallel array of per-citation results: each entry
//     is {ok: true, citation_id: <uuid>} on success, or
//     {ok: false, error: ..., cited_text_preview?: ...} on failure.
//     Order matches the input.
//   - Empty input is allowed (returns {citations: []}) — the model
//     may legitimately call cite_batch with zero items if it changed
//     its mind during answer composition.
//
// The single-citation `cite` tool stays registered for back-compat;
// the system prompt steers the model toward cite_batch when emitting
// more than one citation.

import { randomUUID } from "node:crypto";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { loadConfig, type Config } from "../config.js";
import { postJson, type Fetcher } from "../lib/bridge.js";

/** A single citation entry inside a cite_batch input. Mirrors the
 *  single-cite tool's shape — kept narrow so the model doesn't have
 *  to learn a second mental model for cites. */
const citeBatchItemSchema = z
  .object({
    chunk_id: z
      .string()
      .min(1)
      .describe(
        "Primary key into the chunks table. Must equal a value returned " +
          "from retrieve() in this conversation. Do NOT invent ids.",
      ),
    span_start: z
      .number()
      .int()
      .min(0)
      .optional()
      .describe(
        "Optional — prefer `quote`. Character offset (inclusive) into " +
          "chunk.text where the supporting span begins.",
      ),
    span_end: z
      .number()
      .int()
      .min(1)
      .optional()
      .describe(
        "Optional — prefer `quote`. Character offset (exclusive) where " +
          "the supporting span ends.",
      ),
    quote: z
      .string()
      .min(1)
      .optional()
      .describe(
        "PREFERRED. The exact substring of chunk.text that supports the " +
          "claim. Server scans chunk.text for this string and derives " +
          "span_start/span_end. If multiple occurrences exist, the first " +
          "is used.",
      ),
    confidence: z
      .enum(["verbatim", "paraphrase"])
      .describe(
        "'verbatim' = the claim is a direct quote (allowing minor " +
          "formatting normalization). 'paraphrase' = the claim restates " +
          "the cited span's content in different words.",
      ),
    claim_span: z
      .string()
      .min(1)
      .max(2000)
      .describe(
        "The literal substring of your just-emitted answer that this " +
          "citation supports. The UI does substring search to attach the " +
          "chip; type it back exactly. Server soft-clamps to 500 chars.",
      ),
  })
  .describe("One citation in the batch.");

export const citeBatchInputShape = {
  citations: z
    .array(citeBatchItemSchema)
    .max(50)
    .describe(
      "Array of citations to register. Each entry has the same shape as " +
        "the single cite() tool's input. Order is preserved in the " +
        "response. Max 50 per batch (no real model should exceed this; " +
        "the cap is a defensive guard against runaway tool calls). " +
        "Empty array is allowed and returns an empty response.",
    ),
};

export const citeBatchInputSchema = z.object(citeBatchInputShape);
export type CiteBatchInput = z.infer<typeof citeBatchInputSchema>;
type CiteBatchItem = z.infer<typeof citeBatchItemSchema>;

/** Wire shape of /cite/validate_batch on the sidecar side. Mirrors
 *  retrieval/api.py's CiteValidateBatchResponse. The Node-side handler
 *  remaps to model-facing CiteBatchResult entries (replacing the
 *  per-cite "ok:true" with a minted citation_id). */
interface SidecarCiteResponse {
  ok: boolean;
  error?: string;
  chunk_text_length?: number;
  cited_text_preview?: string;
  resolved_span_start?: number;
  resolved_span_end?: number;
  truncated?: boolean;
}

interface SidecarBatchResponse {
  citations: SidecarCiteResponse[];
}

interface CiteBatchItemSuccess {
  ok: true;
  citation_id: string;
  // Same passthrough as the single-cite tool: the sidecar derives
  // these from the quote (or echoes them from the explicit offset
  // path). The web UI uses them to drive its PDF text-layer search.
  // Threaded through here because the model's tool_result is the only
  // channel the UI reads.
  resolved_span_start?: number;
  resolved_span_end?: number;
}

interface CiteBatchItemFailure {
  ok: false;
  error: string;
  chunk_text_length?: number;
  cited_text_preview?: string;
}

type CiteBatchItemResult = CiteBatchItemSuccess | CiteBatchItemFailure;

interface CiteBatchResult {
  citations: CiteBatchItemResult[];
}

const TOOL_DESCRIPTION =
  "Register MULTIPLE citations at once. Use this instead of calling " +
  "cite() N times when your answer cites more than one claim — the " +
  "round-trip cost is one batch call instead of N serial cite() calls, " +
  "which is dramatically faster for analyze-shaped answers. Input is " +
  "an array of citation entries with the same shape as cite(); response " +
  "is a parallel array of per-citation results in the same order. " +
  "Order matters: the i-th result corresponds to the i-th input. Empty " +
  "array is allowed.";

/** Local pre-validation of one batch item. Catches the
 *  "neither offsets nor quote supplied" case before the HTTP call. */
function localValidateItem(item: CiteBatchItem): CiteBatchItemResult | null {
  const hasOffsets =
    typeof item.span_start === "number" && typeof item.span_end === "number";
  const hasQuote = typeof item.quote === "string" && item.quote.length > 0;
  if (!hasOffsets && !hasQuote) {
    return {
      ok: false,
      error:
        "cite() requires either (span_start, span_end) OR quote. Pass " +
        "the exact quoted substring of chunk.text as `quote` and the " +
        "server will derive the offsets.",
    };
  }
  if (hasOffsets && item.span_end! <= item.span_start!) {
    return { ok: false, error: "span out of range" };
  }
  return null;
}

/** Build the body the sidecar expects: drop UI-only fields if any
 *  creep in, prefer offsets over quote when both supplied (back-compat
 *  with the single-cite tool's disposition rule). */
function toSidecarBody(item: CiteBatchItem): Record<string, unknown> {
  const hasOffsets =
    typeof item.span_start === "number" && typeof item.span_end === "number";
  const hasQuote = typeof item.quote === "string" && item.quote.length > 0;
  const body: Record<string, unknown> = {
    chunk_id: item.chunk_id,
    claim_span: item.claim_span,
    confidence: item.confidence,
  };
  if (hasOffsets) {
    body.span_start = item.span_start;
    body.span_end = item.span_end;
  } else if (hasQuote) {
    body.quote = item.quote;
  }
  return body;
}

export function makeCiteBatchHandler(
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
) {
  return async (input: CiteBatchInput) => {
    if (input.citations.length === 0) {
      const result: CiteBatchResult = { citations: [] };
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(result) },
        ],
      };
    }

    // Pre-validate every item locally. Collect (index → localResult)
    // for items that failed pre-validation so we can stitch them back
    // into the response in the correct slots. The remaining items go
    // to the sidecar; their slots get filled from the sidecar response.
    const localResults: Map<number, CiteBatchItemResult> = new Map();
    const toForward: CiteBatchItem[] = [];
    const forwardIndices: number[] = [];
    for (let i = 0; i < input.citations.length; i++) {
      const item = input.citations[i]!;
      const localFail = localValidateItem(item);
      if (localFail) {
        localResults.set(i, localFail);
      } else {
        toForward.push(item);
        forwardIndices.push(i);
      }
    }

    // Sidecar batch validation for the items that passed local checks.
    let sidecarResp: SidecarBatchResponse = { citations: [] };
    if (toForward.length > 0) {
      try {
        sidecarResp = await postJson<SidecarBatchResponse>(
          cfg,
          "/cite/validate_batch",
          { citations: toForward.map(toSidecarBody) },
          fetcher,
        );
      } catch (err) {
        // Whole batch transport failure — surface once. The model will
        // either retry or abandon the citations. We do NOT split the
        // batch into singletons on transport error; the bridge layer
        // already retried once.
        return {
          content: [
            {
              type: "text" as const,
              text:
                `cite_batch() failed to validate: ${(err as Error).message}. ` +
                `Try the batch again or skip the claims.`,
            },
          ],
          isError: true,
        };
      }
    }

    // Stitch sidecar responses back into the per-input slots.
    const out: CiteBatchItemResult[] = new Array(input.citations.length);
    for (let k = 0; k < forwardIndices.length; k++) {
      const slot = forwardIndices[k]!;
      const sc = sidecarResp.citations[k];
      if (!sc) {
        // Shouldn't happen — sidecar guarantees order + length — but
        // defensively fail closed on the affected slot.
        out[slot] = {
          ok: false,
          error: "sidecar returned fewer responses than requested",
        };
        continue;
      }
      if (sc.ok) {
        out[slot] = {
          ok: true,
          citation_id: randomUUID(),
          // Pass through sidecar-derived offsets so the UI can find
          // the cited text in the PDF text layer. Without these, the
          // PdfPage falls back to a sentinel (0, claim_span.length)
          // range that doesn't actually point at the cited text and
          // shows the "couldn't pinpoint" badge.
          ...(sc.resolved_span_start !== undefined
            ? { resolved_span_start: sc.resolved_span_start }
            : {}),
          ...(sc.resolved_span_end !== undefined
            ? { resolved_span_end: sc.resolved_span_end }
            : {}),
        };
      } else {
        out[slot] = {
          ok: false,
          error: sc.error ?? "validation failed",
          ...(sc.chunk_text_length !== undefined
            ? { chunk_text_length: sc.chunk_text_length }
            : {}),
          ...(sc.cited_text_preview !== undefined
            ? { cited_text_preview: sc.cited_text_preview }
            : {}),
        };
      }
    }
    // Fill the local-fail slots.
    for (const [slot, localResult] of localResults.entries()) {
      out[slot] = localResult;
    }

    const result: CiteBatchResult = { citations: out };
    return {
      content: [
        { type: "text" as const, text: JSON.stringify(result) },
      ],
    };
  };
}

export function registerCiteBatchTool(
  server: McpServer,
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
): void {
  server.registerTool(
    "cite_batch",
    {
      description: TOOL_DESCRIPTION,
      inputSchema: citeBatchInputShape,
    },
    makeCiteBatchHandler(cfg, fetcher),
  );
}
