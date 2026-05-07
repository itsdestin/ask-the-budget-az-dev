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
  span_start: z
    .number()
    .int()
    .min(0)
    .describe(
      "Character offset (inclusive) into chunk.text where the supporting " +
        "span begins. Use 0 to cite from the start of the chunk.",
    ),
  span_end: z
    .number()
    .int()
    .min(1)
    .describe(
      "Character offset (exclusive) into chunk.text where the supporting " +
        "span ends. Must be > span_start and ≤ chunk text length.",
    ),
  confidence: z
    .enum(["verbatim", "paraphrase"])
    .describe(
      "'verbatim' = the claim is a direct quote from chunk.text in this " +
        "span (allowing minor formatting normalization). 'paraphrase' = the " +
        "claim restates the span's content in different words. The post- " +
        "generation faithfulness verifier uses exact-match for verbatim and " +
        "NLI for paraphrase.",
    ),
  claim_span: z
    .string()
    .min(1)
    .max(500)
    .describe(
      "The literal substring of your just-emitted answer that this citation " +
        "supports. Should be a complete clause or sentence; max ~500 chars. " +
        "The UI uses this string to attach the citation chip to the right text.",
    ),
};

export const citeInputSchema = z.object(citeInputShape);
export type CiteInput = z.infer<typeof citeInputSchema>;

interface CiteValidateResponse {
  ok: boolean;
  error?: string;
  chunk_text_length?: number;
}

const TOOL_DESCRIPTION =
  "Record that the immediately preceding assistant claim is supported by " +
  "a specific span of a retrieved chunk. Call once per distinct claim. " +
  "Do NOT invent chunk_ids — only use ids returned from a prior retrieve() " +
  "call. The tool validates chunk_id and span bounds against the database " +
  "and returns ok:false if either is wrong, so you can self-correct.";

interface CiteSuccess {
  ok: true;
  citation_id: string;
}

interface CiteFailure {
  ok: false;
  error: string;
  chunk_text_length?: number;
}

export type CiteResult = CiteSuccess | CiteFailure;

export function makeCiteHandler(
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
) {
  return async (input: CiteInput) => {
    // span_end > span_start is enforced here in addition to the
    // sidecar's check — duplicating the constraint catches the case
    // before a network call and keeps the error message structurally
    // identical regardless of which layer noticed first.
    if (input.span_end <= input.span_start) {
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
      validate = await postJson<CiteValidateResponse>(
        cfg,
        "/cite/validate",
        {
          chunk_id: input.chunk_id,
          span_start: input.span_start,
          span_end: input.span_end,
        },
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
      // Server-generated UUID; the audit log writer (Phase 1c WS5)
      // links the cite() row to its retrieve() call by retrieval_id
      // and stores citation_id for end-to-end traceability.
      result = { ok: true, citation_id: randomUUID() };
    } else {
      result = {
        ok: false,
        error: validate.error ?? "validation failed",
        ...(validate.chunk_text_length !== undefined
          ? { chunk_text_length: validate.chunk_text_length }
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
