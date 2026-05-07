// In-process WebSocket server that mimics YouCoded's port-9900 protocol.
// Used by client + provider tests so we can exercise the full
// connect→auth→session→transcript-event flow without depending on a
// real running YouCoded.

import { createServer, type Server } from "node:http";
import { WebSocketServer, WebSocket } from "ws";

export interface MockServerOptions {
  /** When true, accept any token (default). When false, accept only
   *  tokens listed in `acceptedTokens`. */
  acceptAnyToken?: boolean;
  acceptedTokens?: string[];
}

export interface ConnectedClient {
  ws: WebSocket;
  authedToken: string;
}

/**
 * Spin up an HTTP+WS server, route /ws to a WebSocketServer, and expose
 * a tiny API so tests can drive the wire protocol — accept/reject auth,
 * respond to session:create/destroy, broadcast transcript events.
 */
export class MockYouCodedServer {
  private server: Server;
  private wss: WebSocketServer;
  private port = 0;
  private clients = new Set<ConnectedClient>();
  private nextSessionCounter = 1;
  /** session:create handler — tests can override to control SessionInfo
   *  shape or simulate failures (throw to make the request reject). */
  public onSessionCreate?: (
    payload: Record<string, unknown>,
  ) => Record<string, unknown>;
  /** session:destroy handler — returns boolean (true=success). */
  public onSessionDestroy?: (sessionId: string) => boolean;
  /** session:input handler — fire-and-forget; tests use this to
   *  simulate corresponding transcript events. */
  public onSessionInput?: (sessionId: string, text: string) => void;

  constructor(private opts: MockServerOptions = { acceptAnyToken: true }) {
    this.server = createServer();
    this.wss = new WebSocketServer({ server: this.server, path: "/ws" });
    this.wss.on("connection", (ws) => this.handleConnection(ws));
  }

  async start(): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      this.server.once("error", reject);
      this.server.listen(0, "127.0.0.1", () => {
        const addr = this.server.address();
        if (typeof addr === "object" && addr) {
          this.port = addr.port;
          resolve(`ws://127.0.0.1:${this.port}/ws`);
        } else {
          reject(new Error("server didn't bind to a port"));
        }
      });
    });
  }

  get url(): string {
    return `ws://127.0.0.1:${this.port}/ws`;
  }

  async stop(): Promise<void> {
    for (const c of this.clients) {
      try {
        c.ws.close();
      } catch {}
    }
    this.clients.clear();
    await new Promise<void>((resolve) =>
      this.wss.close(() => resolve()),
    );
    await new Promise<void>((resolve) =>
      this.server.close(() => resolve()),
    );
  }

  /** Broadcast a transcript event to all authed clients. */
  emitTranscriptEvent(event: {
    type: string;
    sessionId: string;
    uuid: string;
    timestamp: number;
    data: Record<string, unknown>;
  }): void {
    const msg = JSON.stringify({ type: "transcript:event", payload: event });
    for (const c of this.clients) c.ws.send(msg);
  }

  /** Broadcast a session:destroyed event. */
  emitSessionDestroyed(sessionId: string, exitCode?: number): void {
    const payload: Record<string, unknown> = { sessionId };
    if (exitCode !== undefined) payload.exitCode = exitCode;
    const msg = JSON.stringify({ type: "session:destroyed", payload });
    for (const c of this.clients) c.ws.send(msg);
  }

  private handleConnection(ws: WebSocket): void {
    let authed = false;
    let authedToken = "";

    ws.on("message", (raw: Buffer | string) => {
      let msg: { type?: string; id?: string; token?: string; payload?: unknown };
      try {
        msg = JSON.parse(raw.toString());
      } catch {
        return;
      }

      if (!authed) {
        if (msg.type !== "auth") {
          ws.send(
            JSON.stringify({
              type: "auth:failed",
              reason: "expected-auth",
            }),
          );
          ws.close();
          return;
        }
        const token = typeof msg.token === "string" ? msg.token : "";
        const ok =
          (this.opts.acceptAnyToken && token.length > 0) ||
          (this.opts.acceptedTokens?.includes(token) ?? false);
        if (!ok) {
          ws.send(
            JSON.stringify({
              type: "auth:failed",
              reason: "invalid-credentials",
            }),
          );
          ws.close();
          return;
        }
        authed = true;
        authedToken = token;
        this.clients.add({ ws, authedToken });
        ws.send(
          JSON.stringify({
            type: "auth:ok",
            token,
            platform: "desktop",
          }),
        );
        return;
      }

      // Authed steady state. Handlers that throw are treated as
      // "intentionally don't respond" — useful for timeout tests.
      if (msg.type === "session:create" && msg.id) {
        const payload = (msg.payload ?? {}) as Record<string, unknown>;
        let result: Record<string, unknown> | undefined;
        try {
          result = this.onSessionCreate
            ? this.onSessionCreate(payload)
            : this.defaultSessionInfo(payload);
        } catch {
          return;
        }
        ws.send(
          JSON.stringify({
            type: "session:create:response",
            id: msg.id,
            payload: result,
          }),
        );
        return;
      }

      if (msg.type === "session:destroy" && msg.id) {
        const payload = (msg.payload ?? {}) as { sessionId?: string };
        let ok: boolean;
        try {
          ok = this.onSessionDestroy
            ? this.onSessionDestroy(payload.sessionId ?? "")
            : true;
        } catch {
          return;
        }
        ws.send(
          JSON.stringify({
            type: "session:destroy:response",
            id: msg.id,
            payload: ok,
          }),
        );
        return;
      }

      if (msg.type === "session:input") {
        const payload = (msg.payload ?? {}) as {
          sessionId?: string;
          text?: string;
        };
        try {
          this.onSessionInput?.(
            payload.sessionId ?? "",
            payload.text ?? "",
          );
        } catch {}
        return;
      }
    });

    ws.on("close", () => {
      for (const c of this.clients) {
        if (c.ws === ws) {
          this.clients.delete(c);
          break;
        }
      }
    });
  }

  private defaultSessionInfo(
    payload: Record<string, unknown>,
  ): Record<string, unknown> {
    const sessionId = `sess-${this.nextSessionCounter++}`;
    return {
      id: sessionId,
      name: (payload["name"] as string) ?? "test",
      cwd: (payload["cwd"] as string) ?? "/tmp",
      permissionMode: payload["permissionMode"] ?? "normal",
      skipPermissions: Boolean(payload["skipPermissions"]),
      status: "active",
      createdAt: Date.now(),
      provider: payload["provider"] ?? "claude",
    };
  }
}
