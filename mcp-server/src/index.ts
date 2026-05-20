#!/usr/bin/env node
// Budget MCP server — registered with a running YouCoded instance via
// ~/.claude.json. Exposes two tools to any Claude session:
//
//   - retrieve(query, filters?, top_k?)  → chunks + top_score + retrieval_id
//   - cite(chunk_id, span_start, span_end, confidence, claim_span) → ok / error
//
// Both forward to the FastAPI retrieval sidecar (retrieval/api.py) at
// $RETRIEVAL_BRIDGE_URL (default http://127.0.0.1:9200). The system
// prompt that constrains how Claude uses these tools lives in
// mcp-server/system-prompt.md and is loaded into the budget-app's
// working-directory CLAUDE.md (per the YouCoded API verification
// memo's "system prompt via cwd CLAUDE.md" approach).

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { loadConfig } from "./config.js";
import { registerCiteTool } from "./tools/cite.js";
import { registerCiteBatchTool } from "./tools/cite-batch.js";
import { registerListFilterValuesTool } from "./tools/list-filter-values.js";
import { registerRetrieveTool } from "./tools/retrieve.js";

async function main(): Promise<void> {
  const cfg = loadConfig();

  const server = new McpServer({
    name: "ask-the-budget-az",
    version: "0.1.0",
  });

  registerRetrieveTool(server, cfg);
  registerCiteTool(server, cfg);
  // cite_batch (2026-05-20): registers N citations in one round-trip.
  // System prompt steers the model toward this for multi-citation
  // answers; single-citation answers still use cite().
  registerCiteBatchTool(server, cfg);
  registerListFilterValuesTool(server, cfg);

  // stdio transport: YouCoded's MCP host launches us as a subprocess
  // and frames JSON-RPC over stdin/stdout. No HTTP listener here.
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  // Errors here are unrecoverable — log to stderr and exit so YouCoded
  // can surface the failure to the user. stdout is reserved for the
  // MCP transport, so log nothing on it.
  process.stderr.write(
    `[budget-mcp-server] fatal: ${(err as Error).stack ?? err}\n`,
  );
  process.exit(1);
});
