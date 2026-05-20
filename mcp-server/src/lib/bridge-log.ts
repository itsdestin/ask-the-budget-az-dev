// JSONL writer for per-call bridge diagnostics. The MCP server is a
// long-running subprocess; we don't have an audit-log table yet (Phase
// 1c WS5), so logging to a JSONL file under the conversation's session
// dir is the cheapest way to get visibility into transport errors and
// timeouts. Records are append-only and one line each; readers
// (humans, future audit-log writer) can `cat` or `jq` them.

import { promises as fs } from "node:fs";
import { dirname } from "node:path";

export interface BridgeLogRecord {
  timestamp: string;          // ISO 8601
  endpoint: string;           // e.g. "/retrieve", "/cite/validate"
  durationMs: number;         // wall-clock from request start to response/error
  outcome: "ok" | "transport_error" | "timeout" | "http_4xx" | "http_5xx";
  httpStatus: number | null;  // null for transport_error / timeout
  errorCategory: string | null; // free-form when outcome != "ok"; e.g. "ECONNREFUSED"
  retrievalId?: string;       // when the response carried one
}

/** Append a single JSONL record to `path`. Errors are caught and
 *  silently dropped — we never want diagnostics to break a real
 *  request. The caller never awaits a non-fulfilled promise. */
export async function logBridgeCall(
  rec: BridgeLogRecord,
  path: string,
): Promise<void> {
  try {
    // Best-effort mkdir of the parent dir. Cheap when it already exists.
    await fs.mkdir(dirname(path), { recursive: true });
    await fs.appendFile(path, JSON.stringify(rec) + "\n", "utf8");
  } catch {
    // Swallow — diagnostics must never break production requests.
  }
}
