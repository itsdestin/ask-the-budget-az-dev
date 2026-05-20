// MCP `cite` tool — locked schema lives in
// docs/superpowers/decisions/2026-05-06-citation-tool-schema.md.
//
// Records that a specific span of an assistant claim is supported by
// a chunk. Validation happens server-side in the FastAPI sidecar
// (chunk_id existence + span bounds); the tool returns the validation
// verdict to the model so it can self-correct on hallucinated chunk_ids.

import { randomUUID } from "node:crypto";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { loadConfig, type Config } from "../config.js";
import { postJson, type Fetcher } from "../lib/bridge.js";

export const citeInputShape = {
  chunk_id: z
    .string()
    .min(1)
    .describe(
      "Primary key into the chunks table. Must equal a value returned " +
        "from retrieve() in this conversation. Format: '<doc_id>::<chunk_index>'. " +
        "Do NOT invent ids.",
    ),
  // span_start/span_end are NOW optional — pass either (span_start,
  // span_end) or `quote`, not both. When both are present, the offsets
  // win and `quote` is ignored (back-compat). The schema can't enforce
  // "exactly one of" so the handler also validates this at runtime.
  span_start: z
    .number()
    .int()
    .min(0)
    .optional()
    .describe(
      "Character offset (inclusive) into chunk.text where the supporting " +
        "span begins. Use 0 to cite from the start of the chunk. " +
        "OPTIONAL — prefer `quote` for new code; both paths produce the " +
        "same validation downstream.",
    ),
  span_end: z
    .number()
    .int()
    .min(1)
    .optional()
    .describe(
      "Character offset (exclusive) into chunk.text where the supporting " +
        "span ends. OPTIONAL — see span_start.",
    ),
  // The preferred path post-2026-05-20: paste the exact substring of
  // chunk.text you want to cite. The server scans chunk.text for the
  // quote and derives offsets. This avoids the Bash-script workaround
  // past sessions resorted to when offsets were hard to compute.
  quote: z
    .string()
    .min(1)
    .optional()
    .describe(
      "The exact substring of chunk.text that supports the claim. " +
        "The server scans chunk.text for this string and derives " +
        "span_start/span_end. If multiple occurrences exist, the first " +
        "is used. Prefer this over span_start/span_end for new code.",
    ),
  confidence: z
    .enum(["verbatim", "paraphrase"])
    .describe(
      "'verbatim' = the claim is a direct quote from chunk.text in this " +
        "span (allowing minor formatting normalization). 'paraphrase' = the " +
        "claim restates the span's content in different words.",
    ),
  // Relaxed from max(500) to max(2000) — the SERVER soft-clamps to 500
  // and flags `truncated: true` rather than rejecting outright. Past
  // sessions had 7 cite calls rejected at the 500-char boundary; the
  // truncate-don't-reject approach keeps the citation alive (just with
  // a shorter chip-attachment string).
  claim_span: z
    .string()
    .min(1)
    .max(2000)
    .describe(
      "The literal substring of your just-emitted answer that this citation " +
        "supports. Should be a complete clause or sentence. The server " +
        "truncates to 500 chars (with truncated:true) and the UI uses the " +
        "truncated string to attach the citation chip.",
    ),
};

export const citeInputSchema = z.object(citeInputShape);
export type CiteInput = z.infer<typeof citeInputSchema>;

interface CiteValidateResponse {
  ok: boolean;
  error?: string;
  chunk_text_length?: number;
  // When validation fails for an alignment reason, the sidecar echoes
  // back the first ~500 chars of chunk.text[span_start:span_end]. We
  // surface this to the model so it can SEE what its span actually
  // contained and pick a better one on retry.
  cited_text_preview?: string;
  // Phase 1c dogfood-hardening (2026-05-20): Task 5 (sidecar) echoes these back when /cite/validate derives offsets from a quote. Optional here; handler doesn't consume them.
  resolved_span_start?: number;
  resolved_span_end?: number;
}

const TOOL_DESCRIPTION =
  "Record that the immediately preceding assistant claim is supported by " +
  "a specific span of a retrieved chunk. Call once per distinct claim. " +
  "Do NOT invent chunk_ids — only use ids returned from a prior retrieve() " +
  "call. The tool validates chunk_id, span bounds, span breadth, and " +
  "alignment of the cited text with claim_span. Returns ok:false with a " +
  "descriptive error (and the actual cited-span preview on alignment " +
  "failures) so you can self-correct by picking a different span or a " +
  "different chunk.";

interface CiteSuccess {
  ok: true;
  citation_id: string;
}

interface CiteFailure {
  ok: false;
  error: string;
  chunk_text_length?: number;
  cited_text_preview?: string;
}

export type CiteResult = CiteSuccess | CiteFailure;

export function makeCiteHandler(
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
) {
  return async (input: CiteInput) => {
    // Locally validate that the caller supplied either (span_start,
    // span_end) OR quote. The schema can't enforce "exactly one of"
    // declaratively, so we catch it here before a wasted HTTP call.
    const hasOffsets =
      typeof input.span_start === "number" && typeof input.span_end === "number";
    const hasQuote = typeof input.quote === "string" && input.quote.length > 0;
    if (!hasOffsets && !hasQuote) {
      const result: CiteResult = {
        ok: false,
        error:
          "cite() requires either (span_start, span_end) OR quote. " +
          "Pass the exact quoted substring of chunk.text as `quote` and " +
          "the server will derive the offsets.",
      };
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(result) },
        ],
      };
    }
    // Same span-inverted check as before, only applied when offsets
    // were supplied. (Skipped for quote-only — the server derives the
    // offsets so they can't be inverted there.)
    if (hasOffsets && input.span_end! <= input.span_start!) {
      const result: CiteResult = {
        ok: false,
        error: "span out of range",
      };
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(result) },
        ],
      };
    }

    let validate: CiteValidateResponse;
    try {
      // Build the body. When BOTH offsets and quote are provided, we
      // prefer the offsets (back-compat) and DROP the quote — that
      // matches the brief's Item 2 disposition rule.
      const body: Record<string, unknown> = {
        chunk_id: input.chunk_id,
        claim_span: input.claim_span,
        confidence: input.confidence,
      };
      if (hasOffsets) {
        body.span_start = input.span_start;
        body.span_end = input.span_end;
      } else if (hasQuote) {
        body.quote = input.quote;
      }
      validate = await postJson<CiteValidateResponse>(
        cfg,
        "/cite/validate",
        body,
        fetcher,
      );
    } catch (err) {
      return {
        content: [
          {
            type: "text" as const,
            text:
              `cite() failed to validate: ${(err as Error).message}. ` +
              `Try the citation again or skip the claim.`,
          },
        ],
        isError: true,
      };
    }

    let result: CiteResult;
    if (validate.ok) {
      result = { ok: true, citation_id: randomUUID() };
    } else {
      result = {
        ok: false,
        error: validate.error ?? "validation failed",
        ...(validate.chunk_text_length !== undefined
          ? { chunk_text_length: validate.chunk_text_length }
          : {}),
        ...(validate.cited_text_preview !== undefined
          ? { cited_text_preview: validate.cited_text_preview }
          : {}),
      };
    }

    return {
      content: [
        { type: "text" as const, text: JSON.stringify(result) },
      ],
    };
  };
}

export function registerCiteTool(
  server: McpServer,
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
): void {
  server.registerTool(
    "cite",
    {
      description: TOOL_DESCRIPTION,
      inputSchema: citeInputShape,
    },
    makeCiteHandler(cfg, fetcher),
  );
}
