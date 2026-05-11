// MCP `list_filter_values` tool — discovery for the canonical_ids that
// actually exist in the corpus.
//
// Why this exists: the model can't see the database, so the only way it
// knows what `agency_canonical_id` values are valid is by reading the
// system prompt's catalog. That catalog goes stale (new ingest adds
// agencies; canonical_ids drift) and inevitably mis-spells less common
// agencies. A wrong slug returns 0 chunks silently — `retrieve()`
// reports `bm25_count: 0, dense_count: 0` and the model thinks the
// corpus genuinely lacks the answer. Direct evidence (2026-05-08
// audit): "agency:trs" for Treasurer (real: "agency:tre") burned 10
// retrieves and produced 0 cites in one session;
// "agency:gov:arizona-health-care-cost-containment-system" for AHCCCS
// (real: "agency:axs") was wrong even in the system prompt itself.
//
// This tool calls the FastAPI sidecar's `/list_values` endpoint to
// enumerate the canonical_ids actually present in the corpus, with
// counts and a sample doc title so opaque slugs (axs, tre) are still
// recognizable. The model uses it once when it sees an unfamiliar
// agency or fund name; the system prompt instructs it to do so.

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { loadConfig, type Config } from "../config.js";
import { postJson, type Fetcher } from "../lib/bridge.js";

export const listFilterValuesInputShape = {
  field: z
    .enum(["agency", "doc_type", "publisher", "fund"])
    .describe(
      "Which filter dimension to enumerate. " +
        "Returns all canonical_ids in the corpus with chunk counts and " +
        "a sample document title so slugs like `agency:axs` (AHCCCS) " +
        "or `agency:tre` (Treasurer) are recognizable.",
    ),
};

export const listFilterValuesInputSchema = z.object(
  listFilterValuesInputShape,
);

export type ListFilterValuesInput = z.infer<typeof listFilterValuesInputSchema>;

interface FilterValueOut {
  canonical_id: string;
  chunk_count: number;
  sample_doc_title?: string | null;
}

interface ListValuesBridgeResponse {
  field: string;
  values: FilterValueOut[];
}

const TOOL_DESCRIPTION =
  "Enumerate the canonical_id values actually present in the budget " +
  "corpus for a given filter dimension (agency, doc_type, publisher, " +
  "fund). USE THIS BEFORE retrieve() when you're not sure of the " +
  "canonical_id for an agency or fund a user mentioned — wrong " +
  "canonical_ids cause silent zero-result filters. Returns a list of " +
  "{canonical_id, chunk_count, sample_doc_title} entries sorted by " +
  "chunk_count desc. Cheap to call; one round trip; results are " +
  "stable within the conversation.";

export function makeListFilterValuesHandler(
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
) {
  return async (input: ListFilterValuesInput) => {
    let result: ListValuesBridgeResponse;
    try {
      result = await postJson<ListValuesBridgeResponse>(
        cfg,
        "/list_values",
        { field: input.field },
        fetcher,
      );
    } catch (err) {
      return {
        content: [
          {
            type: "text" as const,
            text:
              `list_filter_values() failed: ${(err as Error).message}. ` +
              `Tell the user the retrieval service is unavailable.`,
          },
        ],
        isError: true,
      };
    }

    return {
      content: [
        {
          type: "text" as const,
          // Pretty-printed: the catalog is short (138 agencies max,
          // ~100 funds, 10 doc_types, 4 publishers) so token cost is
          // bounded and human-readable formatting helps the model
          // pattern-match agency names → slugs.
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  };
}

export function registerListFilterValuesTool(
  server: McpServer,
  cfg: Config = loadConfig(),
  fetcher: Fetcher = fetch,
): void {
  server.registerTool(
    "list_filter_values",
    {
      description: TOOL_DESCRIPTION,
      inputSchema: listFilterValuesInputShape,
    },
    makeListFilterValuesHandler(cfg, fetcher),
  );
}
