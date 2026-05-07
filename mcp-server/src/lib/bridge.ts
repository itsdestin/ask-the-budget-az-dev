// HTTP client for the FastAPI retrieval sidecar (retrieval/api.py).
// Shared by both tools so the timeout/error-shape contract lives in
// exactly one place.

import type { Config } from "../config.js";

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

export type Fetcher = typeof fetch;

/** Posts JSON to `${cfg.bridgeUrl}${path}`, decodes JSON response, throws
 *  BridgeError on non-2xx or transport failure. The `fetcher` parameter
 *  is dependency-injected so tests can stub it. */
export async function postJson<T>(
  cfg: Config,
  path: string,
  body: unknown,
  fetcher: Fetcher = fetch,
): Promise<T> {
  const url = `${cfg.bridgeUrl.replace(/\/$/, "")}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), cfg.bridgeTimeoutMs);

  try {
    const resp = await fetcher(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!resp.ok) {
      // Read the body for the error message but cap it — pydantic
      // validation errors can be verbose and we don't want a huge
      // string round-tripped to the model.
      const text = (await resp.text()).slice(0, 500);
      throw new BridgeError(
        `bridge ${resp.status} on ${path}: ${text}`,
        resp.status,
        text,
      );
    }

    return (await resp.json()) as T;
  } catch (err) {
    if (err instanceof BridgeError) throw err;
    if (err instanceof Error && err.name === "AbortError") {
      throw new BridgeError(
        `bridge timeout after ${cfg.bridgeTimeoutMs}ms on ${path}`,
      );
    }
    throw new BridgeError(
      `bridge transport error on ${path}: ${(err as Error).message}`,
    );
  } finally {
    clearTimeout(timer);
  }
}

/** GET helper used only by /health probes during dev. */
export async function getJson<T>(
  cfg: Config,
  path: string,
  fetcher: Fetcher = fetch,
): Promise<T> {
  const url = `${cfg.bridgeUrl.replace(/\/$/, "")}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), cfg.bridgeTimeoutMs);
  try {
    const resp = await fetcher(url, { signal: controller.signal });
    if (!resp.ok) {
      throw new BridgeError(`bridge ${resp.status} on ${path}`, resp.status);
    }
    return (await resp.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}
