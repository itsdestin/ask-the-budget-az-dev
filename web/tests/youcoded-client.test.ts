// Tests for YouCodedClient. Uses an in-process mock WS server so the
// real wire protocol (auth, request-response, transcript broadcast) is
// exercised end-to-end without requiring a running YouCoded.

import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import {
  YouCodedClient,
  YouCodedClientError,
  loadPersistedToken,
} from "../lib/youcoded-client.js";
import { MockYouCodedServer } from "./helpers/mock-youcoded-server.js";

let server: MockYouCodedServer;
let serverUrl: string;

beforeAll(async () => {
  server = new MockYouCodedServer();
  serverUrl = await server.start();
});

afterAll(async () => {
  await server.stop();
});

afterEach(() => {
  // Reset overrides between tests so they don't leak.
  server.onSessionCreate = undefined;
  server.onSessionDestroy = undefined;
  server.onSessionInput = undefined;
});

// ---------------------------------------------------------------------------
// loadPersistedToken
// ---------------------------------------------------------------------------

describe("loadPersistedToken", () => {
  it("returns the first usable token from the JSON array", () => {
    const dir = mkdtempSync(join(tmpdir(), "budget-token-"));
    const path = join(dir, ".remote-tokens.json");
    writeFileSync(path, JSON.stringify(["abc-123", "def-456"]));
    try {
      expect(loadPersistedToken(path)).toBe("abc-123");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("throws no_token when the file is missing", () => {
    expect(() =>
      loadPersistedToken("/no/such/path/.remote-tokens.json"),
    ).toThrow(YouCodedClientError);
    try {
      loadPersistedToken("/no/such/path/.remote-tokens.json");
    } catch (err) {
      expect((err as YouCodedClientError).code).toBe("no_token");
    }
  });

  it("throws no_token when the file is not JSON", () => {
    const dir = mkdtempSync(join(tmpdir(), "budget-token-"));
    const path = join(dir, ".remote-tokens.json");
    writeFileSync(path, "not json");
    try {
      expect(() => loadPersistedToken(path)).toThrow(/not valid JSON/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("throws no_token when the array is empty", () => {
    const dir = mkdtempSync(join(tmpdir(), "budget-token-"));
    const path = join(dir, ".remote-tokens.json");
    writeFileSync(path, "[]");
    try {
      expect(() => loadPersistedToken(path)).toThrow(/no usable tokens/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("throws no_token when the JSON is not an array", () => {
    const dir = mkdtempSync(join(tmpdir(), "budget-token-"));
    const path = join(dir, ".remote-tokens.json");
    writeFileSync(path, JSON.stringify({ token: "abc" }));
    try {
      expect(() => loadPersistedToken(path)).toThrow(/is not an array/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// connect / auth
// ---------------------------------------------------------------------------

describe("YouCodedClient connect", () => {
  it("authenticates with the supplied token", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      token: "test-token",
    });
    await client.connect();
    await client.disconnect();
  });

  it("throws auth_failed when the server rejects the token", async () => {
    // Spin a separate mock server that only accepts one specific token.
    const strictServer = new MockYouCodedServer({
      acceptAnyToken: false,
      acceptedTokens: ["good-token"],
    });
    const url = await strictServer.start();
    try {
      const client = new YouCodedClient({ url, token: "bad-token" });
      await expect(client.connect()).rejects.toMatchObject({
        code: "auth_failed",
      });
    } finally {
      await strictServer.stop();
    }
  });

  it("throws connection_failed when the server isn't reachable", async () => {
    const client = new YouCodedClient({
      url: "ws://127.0.0.1:1/ws", // port 1 is reliably unreachable
      token: "x",
    });
    await expect(client.connect()).rejects.toMatchObject({
      code: "connection_failed",
    });
  });

  it("throws no_token when no token is supplied and no file exists", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      tokenPath: "/no/such/path/.remote-tokens.json",
    });
    await expect(client.connect()).rejects.toMatchObject({
      code: "no_token",
    });
  });
});

// ---------------------------------------------------------------------------
// session lifecycle
// ---------------------------------------------------------------------------

describe("YouCodedClient session lifecycle", () => {
  it("createSession returns the SessionInfo from the server", async () => {
    server.onSessionCreate = (payload) => ({
      id: "sess-test",
      name: payload["name"] ?? "x",
      cwd: payload["cwd"] ?? "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();
    const info = await client.createSession({
      name: "Budget chat",
      cwd: "/tmp/budget",
      skipPermissions: true,
    });
    expect(info.id).toBe("sess-test");
    expect(info.name).toBe("Budget chat");
    expect(info.cwd).toBe("/tmp/budget");
    await client.disconnect();
  });

  it("destroySession returns the boolean result", async () => {
    let received = "";
    server.onSessionDestroy = (sessionId) => {
      received = sessionId;
      return true;
    };

    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();
    const ok = await client.destroySession("sess-99");
    expect(ok).toBe(true);
    expect(received).toBe("sess-99");
    await client.disconnect();
  });

  it("sendInput is fire-and-forget", async () => {
    let captured: { sessionId: string; text: string } | null = null;
    server.onSessionInput = (sessionId, text) => {
      captured = { sessionId, text };
    };

    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();
    client.sendInput("sess-1", "hello world");
    // Give the round-trip a moment.
    await new Promise((r) => setTimeout(r, 50));
    expect(captured).toEqual({ sessionId: "sess-1", text: "hello world" });
    await client.disconnect();
  });

  it("sendInput throws when not connected", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    expect(() => client.sendInput("s1", "x")).toThrow(/not connected/);
  });

  it("createSession rejects with request_timeout when the server doesn't respond", async () => {
    server.onSessionCreate = () => {
      // Throwing inside the mock just means no response is sent — the
      // promise will time out client-side.
      throw new Error("simulated unresponsive server");
    };

    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
      requestTimeoutMs: 200,
    });
    await client.connect();
    await expect(
      client.createSession({ name: "x", cwd: "/tmp" }),
    ).rejects.toMatchObject({ code: "request_timeout" });
    await client.disconnect();
  });
});

// ---------------------------------------------------------------------------
// transcript event subscription
// ---------------------------------------------------------------------------

describe("YouCodedClient transcript subscriptions", () => {
  it("routes transcript events to the matching sessionId listener", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();

    const events: string[] = [];
    const unsubscribe = client.onTranscriptEvent("sess-A", (e) => {
      events.push(`${e.type}:${e.data.text ?? ""}`);
    });

    server.emitTranscriptEvent({
      type: "user-message",
      sessionId: "sess-A",
      uuid: "u1",
      timestamp: 1,
      data: { text: "hello" },
    });
    server.emitTranscriptEvent({
      type: "assistant-text",
      sessionId: "sess-B", // different session — should NOT be received
      uuid: "u2",
      timestamp: 2,
      data: { text: "world" },
    });
    server.emitTranscriptEvent({
      type: "tool-use",
      sessionId: "sess-A",
      uuid: "u3",
      timestamp: 3,
      data: { toolUseId: "tu1", toolName: "Bash" },
    });

    await new Promise((r) => setTimeout(r, 50));
    expect(events).toEqual(["user-message:hello", "tool-use:"]);

    unsubscribe();
    server.emitTranscriptEvent({
      type: "user-message",
      sessionId: "sess-A",
      uuid: "u4",
      timestamp: 4,
      data: { text: "after-unsubscribe" },
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(events).toEqual(["user-message:hello", "tool-use:"]); // unchanged

    await client.disconnect();
  });

  it("multiple listeners on one session each receive events", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();

    let countA = 0;
    let countB = 0;
    client.onTranscriptEvent("sess-X", () => {
      countA++;
    });
    client.onTranscriptEvent("sess-X", () => {
      countB++;
    });
    server.emitTranscriptEvent({
      type: "thinking",
      sessionId: "sess-X",
      uuid: "u1",
      timestamp: 1,
      data: {},
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(countA).toBe(1);
    expect(countB).toBe(1);
    await client.disconnect();
  });

  it("session:destroyed broadcasts reach destroyListeners", async () => {
    const client = new YouCodedClient({
      url: serverUrl,
      token: "test",
    });
    await client.connect();

    const seen: { sessionId: string; exitCode?: number }[] = [];
    client.onSessionDestroyed((p) => seen.push(p));

    server.emitSessionDestroyed("sess-1", 0);
    server.emitSessionDestroyed("sess-2");
    await new Promise((r) => setTimeout(r, 50));
    expect(seen).toEqual([
      { sessionId: "sess-1", exitCode: 0 },
      { sessionId: "sess-2" },
    ]);
    await client.disconnect();
  });
});
