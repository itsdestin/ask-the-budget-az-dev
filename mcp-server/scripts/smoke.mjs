#!/usr/bin/env node
// Smoke test: drive the built MCP server's retrieve + cite handlers
// against a live FastAPI sidecar at $RETRIEVAL_BRIDGE_URL. Used during
// Phase 1c WS1 development — not part of the test suite (depends on
// the sidecar + Postgres + Voyage being up).
//
// Usage:
//   node scripts/smoke.mjs

import { loadConfig } from "../dist/config.js";
import { makeRetrieveHandler } from "../dist/tools/retrieve.js";
import { makeCiteHandler } from "../dist/tools/cite.js";

const cfg = loadConfig();
process.stdout.write(`bridge: ${cfg.bridgeUrl}\n`);

const retrieve = makeRetrieveHandler(cfg);
const cite = makeCiteHandler(cfg);

const r = await retrieve({ query: "Aviation Fund balance", top_k: 5 });
if (r.isError) {
  process.stderr.write(`retrieve failed: ${r.content[0].text}\n`);
  process.exit(1);
}
const payload = JSON.parse(r.content[0].text);
process.stdout.write(
  `retrieve: ${payload.chunks.length} chunks, top_score ${payload.top_score.toFixed(3)}, retrieval_id ${payload.retrieval_id}\n`,
);

if (payload.chunks.length === 0) {
  process.stderr.write("no chunks returned — corpus may be empty\n");
  process.exit(2);
}

const top = payload.chunks[0];
process.stdout.write(
  `top chunk: ${top.chunk_id} (${top.doc_title}) page ${top.page_start}\n`,
);

// Try a valid cite + an invalid one to confirm both branches.
const goodCite = await cite({
  chunk_id: top.chunk_id,
  span_start: 0,
  span_end: Math.min(20, top.text.length),
  confidence: "verbatim",
  claim_span: top.text.slice(0, Math.min(20, top.text.length)),
});
process.stdout.write(`cite (valid): ${goodCite.content[0].text}\n`);

const badCite = await cite({
  chunk_id: "made-up-chunk-id",
  span_start: 0,
  span_end: 5,
  confidence: "verbatim",
  claim_span: "x",
});
process.stdout.write(`cite (invalid): ${badCite.content[0].text}\n`);
