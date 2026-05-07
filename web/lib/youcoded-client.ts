// WebSocket client for YouCoded's remote API at ws://localhost:9900/ws.
//
// Owns the wire protocol: auth handshake, session lifecycle, transcript
// event subscription. Stateless about higher-level concepts (turns,
// citations, refusals) — those live in YouCodedSessionProvider.
//
// Auth strategy (per project decision 2026-05-07): read a persisted
// token from `~/.claude/.remote-tokens.json`. That file is YouCoded's
// own token store (an array of UUID strings). Every successful remote
// auth — desktop, Android, browser — adds an entry. As long as YouCoded
// has been opened remotely at least once, we have a token without
// asking the user.

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { WebSocket } from "ws";

import type {
  AuthResponse,
  CreateSessionOpts,
  SessionInfo,
  TranscriptEvent,
} from "./types.js";

const DEFAULT_URL = "ws://localhost:9900/ws";
const DEFAULT_TOKEN_PATH = join(homedir(), ".claude", ".remote-tokens.json");

export class YouCodedClientError extends Error {
  constructor(
    message: string,
    public readonly code:
      | "no_token"
      | "auth_failed"
      | "connection_failed"
      | "request_timeout"
      | "request_failed"
      | "not_connected",
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "YouCodedClientError";
  }
}

export interface YouCodedClientOptions {
  /** Override the default URL — used by tests with an in-process server. */
  url?: string;
  /** Override the default token-file path — used by tests. */
  tokenPath?: string;
  /** Inline token. When set, overrides token-file lookup. Used by env-var
   *  callers that prefer to load the token themselves (we deliberately
   *  do not read process.env in this module so the client stays
   *  consumable from non-Node-CLI hosts). */
  token?: string;
  /** Default timeout for request-response calls (ms). */
  requestTimeoutMs?: number;
  /** Constructor for the WebSocket implementation. Override for tests. */
  WebSocketCtor?: typeof WebSocket;
}

/** Per-session transcript-event listener. */
export type TranscriptEventListener = (e: TranscriptEvent) => void;

interface PendingRequest {
  resolve: (payload: unknown) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * Reads the first valid token from ~/.claude/.remote-tokens.json. Throws
 * a YouCodedClientError(no_token, ...) when the file is missing, empty,
 * not parseable, or doesn't contain any string entries.
 */
export function loadPersistedToken(
  tokenPath: string = DEFAULT_TOKEN_PATH,
): string {
  let raw: string;
  try {
    raw = readFileSync(tokenPath, "utf-8");
  } catch (err) {
    throw new YouCodedClientError(
      `couldn't read YouCoded token file at ${tokenPath}. ` +
        `Open YouCoded once and connect a remote client (e.g. via the Android app ` +
        `or browser) so a token is persisted, then retry.`,
      "no_token",
      err,
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new YouCodedClientError(
      `${tokenPath} is not valid JSON.`,
      "no_token",
      err,
    );
  }

  if (!Array.isArray(parsed)) {
    throw new YouCodedClientError(
      `${tokenPath} is not an array. Format: ["token1", "token2", ...].`,
      "no_token",
    );
  }

  const token = parsed.find(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  if (!token) {
    throw new YouCodedClientError(
      `${tokenPath} contains no usable tokens.`,
      "no_token",
    );
  }
  return token;
}

/**
 * Wire-level client for ws://localhost:9900/ws. After connect()+auth(),
 * issue request-response calls (createSession, destroySession) and
 * subscribe to per-session transcript events.
 */
export class YouCodedClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly tokenPath: string;
  private readonly explicitToken: string | undefined;
  private readonly requestTimeoutMs: number;
  private readonly WebSocketCtor: typeof WebSocket;

  /** Pending request-response calls keyed by request id. */
  private pending = new Map<string, PendingRequest>();

  /** Per-session transcript listeners. Scoped by sessionId so multiple
   *  budget conversations can multiplex over one client connection. */
  private listeners = new Map<string, Set<TranscriptEventListener>>();

  /** Listeners for session:destroyed broadcasts — the provider needs
   *  these to detect the YouCoded process exiting mid-turn. */
  private destroyListeners = new Set<
    (payload: { sessionId: string; exitCode?: number }) => void
  >();

  /** Monotonic counter for request id generation. Restarts on every
   *  client instance — there's no need for global uniqueness because
   *  ids are scoped to one in-flight pending map. */
  private nextRequestId = 1;

  constructor(opts: YouCodedClientOptions = {}) {
    this.url = opts.url ?? DEFAULT_URL;
    this.tokenPath = opts.tokenPath ?? DEFAULT_TOKEN_PATH;
    this.explicitToken = opts.token;
    this.requestTimeoutMs = opts.requestTimeoutMs ?? 5_000;
    this.WebSocketCtor = opts.WebSocketCtor ?? WebSocket;
  }

  /** Open the socket and complete the auth handshake. Resolves once the
   *  server returns `auth:ok`. Throws YouCodedClientError on any failure. */
  async connect(): Promise<void> {
    const token = this.explicitToken ?? loadPersistedToken(this.tokenPath);

    return new Promise<void>((resolve, reject) => {
      let settled = false;
      let ws: WebSocket;
      try {
        ws = new this.WebSocketCtor(this.url);
      } catch (err) {
        reject(
          new YouCodedClientError(
            `couldn't open WebSocket to ${this.url}. Is YouCoded running?`,
            "connection_failed",
            err,
          ),
        );
        return;
      }

      const finishOk = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      const finishErr = (err: Error) => {
        if (settled) return;
        settled = true;
        try {
          ws.close();
        } catch {}
        reject(err);
      };

      ws.once("open", () => {
        // Server expects the very first message to be auth.
        ws.send(JSON.stringify({ type: "auth", token }));
      });

      ws.once("error", (err: Error) => {
        finishErr(
          new YouCodedClientError(
            `WebSocket error before auth: ${err.message}. ` +
              `Is YouCoded running and reachable at ${this.url}?`,
            "connection_failed",
            err,
          ),
        );
      });

      // The server's first reply post-open is the auth verdict. Once
      // we get it, swap to the steady-state message handler.
      const authHandler = (raw: Buffer | string) => {
        let msg: AuthResponse;
        try {
          msg = JSON.parse(raw.toString()) as AuthResponse;
        } catch {
          finishErr(
            new YouCodedClientError(
              "received non-JSON auth response from server",
              "auth_failed",
            ),
          );
          return;
        }

        if (msg.type === "auth:ok") {
          ws.off("message", authHandler);
          this.ws = ws;
          this.attachSteadyState(ws);
          finishOk();
        } else if (msg.type === "auth:failed") {
          finishErr(
            new YouCodedClientError(
              `YouCoded rejected the token: ${msg.reason}. ` +
                `Re-pair via YouCoded's settings → Remote Access.`,
              "auth_failed",
            ),
          );
        } else {
          finishErr(
            new YouCodedClientError(
              `unexpected first server message: ${JSON.stringify(msg)}`,
              "auth_failed",
            ),
          );
        }
      };
      ws.on("message", authHandler);
    });
  }

  /** Attach the steady-state message router after auth succeeds. */
  private attachSteadyState(ws: WebSocket): void {
    ws.on("message", (raw: Buffer | string) => {
      let msg: { type?: string; id?: string; payload?: unknown };
      try {
        msg = JSON.parse(raw.toString());
      } catch {
        return; // ignore garbage; YouCoded should never send non-JSON
      }

      // Request-response: any `*:response` matches a pending id.
      if (msg.id && msg.type && msg.type.endsWith(":response")) {
        const pending = this.pending.get(msg.id);
        if (pending) {
          this.pending.delete(msg.id);
          clearTimeout(pending.timer);
          pending.resolve(msg.payload);
          return;
        }
      }

      // Transcript event broadcast: route by sessionId.
      if (msg.type === "transcript:event" && msg.payload) {
        const ev = msg.payload as TranscriptEvent;
        const ls = this.listeners.get(ev.sessionId);
        if (ls) for (const cb of ls) safeInvoke(cb, ev);
        return;
      }

      // Session destruction: notify global listeners.
      if (msg.type === "session:destroyed" && msg.payload) {
        const payload = msg.payload as { sessionId: string; exitCode?: number };
        for (const cb of this.destroyListeners) safeInvoke(cb, payload);
        return;
      }

      // Other broadcasts (chat:hydrate, session:created, status:data,
      // pty:output, hook:event, ...) are ignored by the budget client —
      // we get everything we need from transcript:event.
    });

    ws.on("close", (code, reason) => {
      // Reject any in-flight requests; their callers are stuck otherwise.
      for (const [, pending] of this.pending) {
        clearTimeout(pending.timer);
        pending.reject(
          new YouCodedClientError(
            `connection closed mid-request (code ${code}): ${reason.toString()}`,
            "request_failed",
          ),
        );
      }
      this.pending.clear();
      this.ws = null;
    });

    ws.on("error", () => {
      // Surfaced via close; nothing to do here that close doesn't.
    });
  }

  /** Close the connection cleanly. Subsequent calls reject. */
  async disconnect(): Promise<void> {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    return new Promise<void>((resolve) => {
      if (ws.readyState === ws.CLOSED) {
        resolve();
        return;
      }
      ws.once("close", () => resolve());
      try {
        ws.close();
      } catch {
        resolve();
      }
    });
  }

  /** Send a request-response message and await the matching response. */
  private async request<T>(
    type: string,
    payload: unknown,
  ): Promise<T> {
    const ws = this.ws;
    if (!ws || ws.readyState !== ws.OPEN) {
      throw new YouCodedClientError(
        `not connected — call connect() first`,
        "not_connected",
      );
    }
    const id = `budget-${this.nextRequestId++}`;
    const timeoutMs = this.requestTimeoutMs;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new YouCodedClientError(
            `${type} request ${id} timed out after ${timeoutMs}ms`,
            "request_timeout",
          ),
        );
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (payload) => resolve(payload as T),
        reject,
        timer,
      });
      ws.send(JSON.stringify({ type, id, payload }));
    });
  }

  /** Create a new YouCoded session. The returned SessionInfo's `id` is
   *  used as the conversationId in higher-level APIs. */
  async createSession(opts: CreateSessionOpts): Promise<SessionInfo> {
    return this.request<SessionInfo>("session:create", opts);
  }

  /** Destroy a YouCoded session. */
  async destroySession(sessionId: string): Promise<boolean> {
    return this.request<boolean>("session:destroy", { sessionId });
  }

  /** Send user text into a session's PTY. Fire-and-forget — YouCoded
   *  does not ack per-input; observed effect is the resulting
   *  `user-message` transcript event. */
  sendInput(sessionId: string, text: string): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== ws.OPEN) {
      throw new YouCodedClientError(
        `not connected — call connect() first`,
        "not_connected",
      );
    }
    ws.send(
      JSON.stringify({
        type: "session:input",
        payload: { sessionId, text },
      }),
    );
  }

  /** Subscribe to transcript events for one session. Returns an
   *  unsubscribe function. */
  onTranscriptEvent(
    sessionId: string,
    listener: TranscriptEventListener,
  ): () => void {
    let ls = this.listeners.get(sessionId);
    if (!ls) {
      ls = new Set();
      this.listeners.set(sessionId, ls);
    }
    ls.add(listener);
    return () => {
      const set = this.listeners.get(sessionId);
      if (!set) return;
      set.delete(listener);
      if (set.size === 0) this.listeners.delete(sessionId);
    };
  }

  /** Subscribe to session:destroyed broadcasts (any session). Useful
   *  for higher layers that need to abort an in-flight turn cleanly
   *  when YouCoded reports the underlying session has exited. */
  onSessionDestroyed(
    listener: (payload: { sessionId: string; exitCode?: number }) => void,
  ): () => void {
    this.destroyListeners.add(listener);
    return () => {
      this.destroyListeners.delete(listener);
    };
  }
}

function safeInvoke<T>(cb: (arg: T) => void, arg: T): void {
  try {
    cb(arg);
  } catch (err) {
    // Listeners that throw shouldn't break the message router. Log to
    // stderr only — stdout might be reserved (not in this app, but
    // matches the MCP server's discipline).
    process.stderr.write(
      `[youcoded-client] listener threw: ${(err as Error).stack ?? err}\n`,
    );
  }
}
