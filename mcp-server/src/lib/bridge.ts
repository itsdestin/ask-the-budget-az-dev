// HTTP client for the FastAPI retrieval sidecar (retrieval/api.py).
// Shared by both tools so the timeout/error-shape contract lives in
// exactly one place.
//
// Connection-pool note (2026-05-08): the MCP server is a long-running
// subprocess of Claude Code. Node's built-in fetch (undici) maintains
// a global keep-alive connection pool. If the sidecar process restarts
// (re-deploy, crash, dev iteration), existing pooled connections become
// dead — undici still hands them out, the request writes to a closed
// FD, and every retrieve hangs until the AbortController fires.
// Symptom: "bridge timeout after 15000ms" with ZERO request landing in
// the sidecar log.
//
// We DO NOT try to fix this client-side: the userland `undici` package
// is a different version than Node's built-in, and passing one's Agent
// as `dispatcher` to the other's fetch fails with "invalid
// onRequestStart". Workaround: kill the MCP subprocesses after a
// sidecar restart. In production the sidecar doesn't restart, so the
// pool stays consistent and this isn't a problem. The retry-once-on-
// transport-error logic below handles transient network blips.

import { homedir } from "node:os";
import { join } from "node:path";

import type { Config } from "../config.js";
import { logBridgeCall, type BridgeLogRecord } from "./bridge-log.js";

export class BridgeError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly bodyText?: string,
  ) {
    super(message);
    this.name = "BridgeError";
  }
}

/** Where bridge-call records are appended. Default: under the user's
 *  ~/.claude/ask-the-budget-az dir; overridable via env so an
 *  operator can redirect logs without rebuilding. */
function bridgeLogPath(): string {
  return (
    process.env.BUDGET_BRIDGE_LOG_PATH ??
    join(homedir(), ".claude", "ask-the-budget-az", "bridge.log")
  );
}

export type Fetcher = typeof fetch;

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  fetcher: Fetcher,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetcher(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Posts JSON to `${cfg.bridgeUrl}${path}`, decodes JSON response, throws
 *  BridgeError on non-2xx or transport failure. The `fetcher` parameter
 *  is dependency-injected so tests can stub it.
 *
 *  Retries ONCE on transport error (fetch threw before getting a
 *  response): handles transient localhost blips and gives a dead
 *  pooled connection a chance to fail-and-recycle. Does NOT retry on
 *  non-2xx responses (those are deterministic — the sidecar told us
 *  no) and does NOT retry on AbortError (the timeout is already the
 *  upper bound). */
export async function postJson<T>(
  cfg: Config,
  path: string,
  body: unknown,
  fetcher: Fetcher = fetch,
): Promise<T> {
  const url = `${cfg.bridgeUrl.replace(/\/$/, "")}${path}`;
  const init: RequestInit = {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };

  const started = Date.now();
  let lastErr: Error | null = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const resp = await fetchWithTimeout(
        url,
        init,
        cfg.bridgeTimeoutMs,
        fetcher,
      );
      if (!resp.ok) {
        const text = (await resp.text()).slice(0, 500);
        // Log the http-error outcome before throwing.
        const outcome: BridgeLogRecord["outcome"] =
          resp.status >= 500 ? "http_5xx" : "http_4xx";
        void logBridgeCall(
          {
            timestamp: new Date().toISOString(),
            endpoint: path,
            durationMs: Date.now() - started,
            outcome,
            httpStatus: resp.status,
            errorCategory: text.slice(0, 80),
          },
          bridgeLogPath(),
        );
        throw new BridgeError(
          `bridge ${resp.status} on ${path}: ${text}`,
          resp.status,
          text,
        );
      }
      const json = (await resp.json()) as T;
      // Look for a retrieval_id without typing the generic — best-effort.
      const retrievalId =
        (json as { retrieval_id?: unknown })?.retrieval_id;
      void logBridgeCall(
        {
          timestamp: new Date().toISOString(),
          endpoint: path,
          durationMs: Date.now() - started,
          outcome: "ok",
          httpStatus: resp.status,
          errorCategory: null,
          retrievalId:
            typeof retrievalId === "string" ? retrievalId : undefined,
        },
        bridgeLogPath(),
      );
      return json;
    } catch (err) {
      if (err instanceof BridgeError) throw err;
      if (err instanceof Error && err.name === "AbortError") {
        void logBridgeCall(
          {
            timestamp: new Date().toISOString(),
            endpoint: path,
            durationMs: Date.now() - started,
            outcome: "timeout",
            httpStatus: null,
            errorCategory: `timeout_${cfg.bridgeTimeoutMs}ms`,
          },
          bridgeLogPath(),
        );
        throw new BridgeError(
          `bridge timeout after ${cfg.bridgeTimeoutMs}ms on ${path}`,
        );
      }
      lastErr = err as Error;
      // Loop body falls through to next attempt; transient transport
      // errors are retried once.
    }
  }
  // Both attempts failed at the transport layer (fetch threw before
  // getting a response). Log the transport_error outcome.
  void logBridgeCall(
    {
      timestamp: new Date().toISOString(),
      endpoint: path,
      durationMs: Date.now() - started,
      outcome: "transport_error",
      httpStatus: null,
      errorCategory: lastErr?.message?.slice(0, 80) ?? "unknown",
    },
    bridgeLogPath(),
  );
  throw new BridgeError(
    `bridge transport error on ${path}: ${lastErr?.message ?? "unknown"}`,
  );
}

/** GET helper used only by /health probes during dev. */
export async function getJson<T>(
  cfg: Config,
  path: string,
  fetcher: Fetcher = fetch,
): Promise<T> {
  const url = `${cfg.bridgeUrl.replace(/\/$/, "")}${path}`;
  const resp = await fetchWithTimeout(
    url,
    { method: "GET" },
    cfg.bridgeTimeoutMs,
    fetcher,
  );
  if (!resp.ok) {
    throw new BridgeError(`bridge ${resp.status} on ${path}`, resp.status);
  }
  return (await resp.json()) as T;
}
