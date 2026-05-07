// Runtime configuration for the budget MCP server. Resolved once at
// module load — the MCP server is a long-running process under
// YouCoded's MCP host, so re-reading env on every call buys nothing.

const DEFAULT_BRIDGE_URL = "http://127.0.0.1:9200";

export interface Config {
  /** Base URL of the FastAPI retrieval sidecar (retrieval/api.py). */
  bridgeUrl: string;
  /** Per-call HTTP timeout (ms). Voyage rerank can take ~1s on a cold
   *  cache; we leave headroom for the slowest case the user is willing
   *  to wait synchronously. */
  bridgeTimeoutMs: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  return {
    bridgeUrl: env.RETRIEVAL_BRIDGE_URL ?? DEFAULT_BRIDGE_URL,
    bridgeTimeoutMs: Number(env.RETRIEVAL_BRIDGE_TIMEOUT_MS ?? 15000),
  };
}
