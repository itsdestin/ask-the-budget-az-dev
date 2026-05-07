// Integration tests for YouCodedSessionProvider against a mock YouCoded
// server. Exercises the full multi-turn flow:
//
//   start → sendTurn → (assistant text + retrieve + cite + Bash) →
//   turn-complete → end
//
// The test that mixes retrieve+cite with a generic Bash tool is the
// canonical regression for "all tool types pass through" — the user's
// directive that drove this WS's expanded scope.

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { ProviderEvent } from "../lib/types.js";
import { YouCodedSessionProvider } from "../lib/youcoded-session-provider.js";
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
  server.onSessionCreate = undefined;
  server.onSessionDestroy = undefined;
  server.onSessionInput = undefined;
});

function makeProvider() {
  return new YouCodedSessionProvider({
    url: serverUrl,
    token: "test-token",
  });
}

describe("YouCodedSessionProvider", () => {
  it("startConversation creates a session and returns its id", async () => {
    server.onSessionCreate = (payload) => ({
      id: "conv-1",
      name: payload["name"] ?? "x",
      cwd: payload["cwd"] ?? "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation({
      cwd: "/tmp/budget",
    });
    expect(conversationId).toBe("conv-1");
    await provider.disconnect();
  });

  it("sendTurn streams every event type to onEvent — including a generic Bash tool", async () => {
    // Wire setup: mock server that tags conv-X for the test's session.
    server.onSessionCreate = () => ({
      id: "conv-X",
      name: "test",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation();

    // When the provider sends user input, the mock server emits a full
    // turn worth of transcript events: user-message, retrieve tool_use,
    // retrieve tool_result, Bash tool_use, Bash tool_result, cite
    // tool_use, cite tool_result, assistant-text, turn-complete.
    server.onSessionInput = (sessionId, _text) => {
      // Schedule events on the next tick so the provider's listener
      // is registered before they fire.
      setImmediate(() => {
        const emit = (
          type: string,
          data: Record<string, unknown>,
          uuid: string,
        ) =>
          server.emitTranscriptEvent({
            type,
            sessionId,
            uuid,
            timestamp: Date.now(),
            data,
          });

        emit("user-message", { text: "Aviation Fund balance?" }, "u-user");
        emit(
          "tool-use",
          {
            toolUseId: "tu-1",
            toolName: "retrieve",
            toolInput: { query: "Aviation Fund balance" },
          },
          "u-1",
        );
        emit(
          "tool-result",
          {
            toolUseId: "tu-1",
            toolResult: JSON.stringify({
              chunks: [
                { chunk_id: "jlbc-baseline-fy2027-s18-0010", score: 0.9 },
                { chunk_id: "jlbc-baseline-fy2027-s18-0011", score: 0.7 },
              ],
              top_score: 0.9,
              retrieval_id: "ret-1",
            }),
          },
          "u-2",
        );
        emit(
          "tool-use",
          {
            toolUseId: "tu-2",
            toolName: "Bash",
            toolInput: { command: "ls /tmp", description: "list" },
          },
          "u-3",
        );
        emit(
          "tool-result",
          { toolUseId: "tu-2", toolResult: "file1\nfile2", isError: false },
          "u-4",
        );
        emit(
          "tool-use",
          {
            toolUseId: "tu-3",
            toolName: "cite",
            toolInput: {
              chunk_id: "jlbc-baseline-fy2027-s18-0010",
              span_start: 0,
              span_end: 25,
              confidence: "verbatim",
              claim_span: "Aviation Fund balance was $123,456.",
            },
          },
          "u-5",
        );
        emit(
          "tool-result",
          {
            toolUseId: "tu-3",
            toolResult: JSON.stringify({ ok: true, citation_id: "cit-1" }),
          },
          "u-6",
        );
        emit(
          "assistant-text",
          { text: "Aviation Fund balance was $123,456.", model: "claude-opus-4-7" },
          "u-text",
        );
        emit(
          "turn-complete",
          {
            stopReason: "end_turn",
            model: "claude-opus-4-7",
            anthropicRequestId: "req_1",
            usage: {
              inputTokens: 100,
              outputTokens: 20,
              cacheReadTokens: 0,
              cacheCreationTokens: 0,
            },
          },
          "u-end",
        );
      });
    };

    const events: ProviderEvent[] = [];
    const result = await provider.sendTurn({
      conversationId,
      userMessage: "Aviation Fund balance?",
      onEvent: (e) => events.push(e),
    });

    // Every event surfaced — generic and budget tools alike.
    const types = events.map((e) => e.type);
    expect(types).toContain("user_message");
    expect(types).toContain("tool_use"); // retrieve, Bash, AND cite
    expect(types).toContain("tool_result");
    expect(types).toContain("assistant_text_delta");
    expect(types).toContain("turn_complete");

    const toolUses = events.filter((e) => e.type === "tool_use");
    const toolNames = toolUses.map(
      (e) => (e as { toolName: string }).toolName,
    );
    expect(toolNames).toEqual(["retrieve", "Bash", "cite"]);

    // Result accumulator: final answer, citations, retrieved chunk ids,
    // tool call summary.
    expect(result.finalAnswer).toBe("Aviation Fund balance was $123,456.");
    expect(result.stopReason).toBe("end_turn");
    expect(result.citations).toHaveLength(1);
    expect(result.citations[0]).toMatchObject({
      chunkId: "jlbc-baseline-fy2027-s18-0010",
      confidence: "verbatim",
    });
    expect(result.retrievedChunkIds).toEqual([
      "jlbc-baseline-fy2027-s18-0010",
      "jlbc-baseline-fy2027-s18-0011",
    ]);
    // toolCalls preserves order and includes ALL tool types (not just retrieve/cite).
    expect(result.toolCalls.map((t) => t.toolName)).toEqual([
      "retrieve",
      "Bash",
      "cite",
    ]);
    // Each call has its output backfilled from the matching tool-result.
    expect(result.toolCalls[1]?.output).toBe("file1\nfile2");
    expect(result.toolCalls[1]?.isError).toBe(false);

    await provider.endConversation(conversationId);
    await provider.disconnect();
  });

  it("dedups assistant_text_delta by uuid (avoids growing-message double-render)", async () => {
    server.onSessionCreate = () => ({
      id: "conv-Y",
      name: "test",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation();

    server.onSessionInput = (sessionId) => {
      setImmediate(() => {
        // Two assistant-text events with the same uuid (Claude rewriting
        // a growing message) — the *latest* should win for finalAnswer
        // but only ONE assistant_text_delta event should reach onEvent.
        const emit = (data: Record<string, unknown>, uuid: string) =>
          server.emitTranscriptEvent({
            type: "assistant-text",
            sessionId,
            uuid,
            timestamp: Date.now(),
            data,
          });
        emit({ text: "Aviation" }, "uuid-A");
        emit({ text: "Aviation Fund" }, "uuid-A");
        emit({ text: "Aviation Fund balance was $123,456." }, "uuid-A");
        server.emitTranscriptEvent({
          type: "turn-complete",
          sessionId,
          uuid: "uuid-end",
          timestamp: Date.now(),
          data: { stopReason: "end_turn" },
        });
      });
    };

    const deltas: ProviderEvent[] = [];
    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: (e) => {
        if (e.type === "assistant_text_delta") deltas.push(e);
      },
    });
    expect(deltas).toHaveLength(1);
    // But finalAnswer captures the LAST text the uuid had — the
    // accumulator updates regardless of dedup.
    expect(result.finalAnswer).toBe(
      "Aviation Fund balance was $123,456.",
    );

    await provider.disconnect();
  });

  it("session_died stop reason fires when the underlying session is destroyed mid-turn", async () => {
    server.onSessionCreate = () => ({
      id: "conv-Z",
      name: "test",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation();

    server.onSessionInput = (sessionId) => {
      setImmediate(() => {
        // No turn events; just kill the session.
        server.emitSessionDestroyed(sessionId, 1);
      });
    };

    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: () => {},
    });
    expect(result.stopReason).toBe("session_died");
    await provider.disconnect();
  });

  it("AbortSignal short-circuits the turn", async () => {
    server.onSessionCreate = () => ({
      id: "conv-A",
      name: "test",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation();
    const ctrl = new AbortController();
    setImmediate(() => ctrl.abort());

    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: () => {},
      signal: ctrl.signal,
    });
    expect(result.stopReason).toBe("aborted");
    await provider.disconnect();
  });

  it("sendTurn rejects for unknown conversationId", async () => {
    const provider = makeProvider();
    await expect(
      provider.sendTurn({
        conversationId: "never-started",
        userMessage: "x",
        onEvent: () => {},
      }),
    ).rejects.toThrow(/unknown conversationId/);
    await provider.disconnect();
  });

  it("drops malformed cite() inputs but doesn't fail the turn", async () => {
    server.onSessionCreate = () => ({
      id: "conv-B",
      name: "test",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const { conversationId } = await provider.startConversation();

    server.onSessionInput = (sessionId) => {
      setImmediate(() => {
        // First cite is missing required fields; second is well-formed.
        server.emitTranscriptEvent({
          type: "tool-use",
          sessionId,
          uuid: "u1",
          timestamp: 1,
          data: {
            toolUseId: "tu1",
            toolName: "cite",
            toolInput: { chunk_id: "x" }, // missing span_start, span_end, ...
          },
        });
        server.emitTranscriptEvent({
          type: "tool-use",
          sessionId,
          uuid: "u2",
          timestamp: 2,
          data: {
            toolUseId: "tu2",
            toolName: "cite",
            toolInput: {
              chunk_id: "good",
              span_start: 0,
              span_end: 5,
              confidence: "paraphrase",
              claim_span: "x",
            },
          },
        });
        server.emitTranscriptEvent({
          type: "turn-complete",
          sessionId,
          uuid: "u3",
          timestamp: 3,
          data: { stopReason: "end_turn" },
        });
      });
    };

    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: () => {},
    });
    expect(result.citations).toHaveLength(1);
    expect(result.citations[0]?.chunkId).toBe("good");
    await provider.disconnect();
  });
});
