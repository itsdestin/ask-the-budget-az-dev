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

// ---------------------------------------------------------------------------
// System-prompt materialization
//
// Without this, Claude spawns at the budget app's source-code cwd and
// reads the developer-facing CLAUDE.md, treating itself as a "help me
// build the budget tool" assistant rather than the budget tool's
// retrieve/cite-constrained backend. The materialization tests pin
// down the per-conversation tempdir mechanism documented in
// `docs/superpowers/investigations/2026-05-06-youcoded-remote-api-verification.md`.

describe("YouCodedSessionProvider — system prompt materialization", () => {
  let promptDir: string;
  let promptPath: string;
  let contextPath: string;
  let runtimeRoot: string;
  let nextSession = 0;

  beforeAll(async () => {
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    promptDir = await fs.mkdtemp(path.join(os.tmpdir(), "budget-test-src-"));
    promptPath = path.join(promptDir, "system-prompt.md");
    contextPath = path.join(promptDir, "system-prompt-context.md");
    await fs.writeFile(promptPath, "# Budget agent rules\nUse retrieve().\n");
    await fs.writeFile(contextPath, "# Glossary\nADC = Department of Corrections.\n");
  });

  afterAll(async () => {
    const fs = await import("node:fs/promises");
    await fs.rm(promptDir, { recursive: true, force: true });
  });

  beforeAll(async () => {
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    runtimeRoot = await fs.mkdtemp(path.join(os.tmpdir(), "budget-test-rt-"));
  });

  afterAll(async () => {
    const fs = await import("node:fs/promises");
    await fs.rm(runtimeRoot, { recursive: true, force: true });
  });

  function makeMaterializingProvider() {
    return new YouCodedSessionProvider({
      url: serverUrl,
      token: "test-token",
      systemPromptPath: promptPath,
      systemPromptContextPath: contextPath,
      runtimeDirRoot: runtimeRoot,
    });
  }

  it("materializes CLAUDE.md + data/system-prompt-context.md into a per-conversation runtime dir, and passes that as cwd", async () => {
    let createPayloadCwd: string | undefined;
    server.onSessionCreate = (payload) => {
      createPayloadCwd = payload["cwd"] as string;
      return {
        id: `mat-conv-${++nextSession}`,
        name: "x",
        cwd: createPayloadCwd ?? "/tmp",
        permissionMode: "normal",
        skipPermissions: true,
        status: "active",
        createdAt: 1000,
        provider: "claude",
      };
    };

    const provider = makeMaterializingProvider();
    const { conversationId } = await provider.startConversation();
    expect(typeof createPayloadCwd).toBe("string");
    // The cwd YouCoded sees should be a fresh subdir of runtimeRoot,
    // not the budget app's source tree.
    expect(createPayloadCwd!.startsWith(runtimeRoot)).toBe(true);

    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const claudeMd = await fs.readFile(
      path.join(createPayloadCwd!, "CLAUDE.md"),
      "utf8",
    );
    expect(claudeMd).toContain("Budget agent rules");
    const contextMd = await fs.readFile(
      path.join(createPayloadCwd!, "data", "system-prompt-context.md"),
      "utf8",
    );
    expect(contextMd).toContain("ADC = Department of Corrections");

    // endConversation cleans up.
    await provider.endConversation(conversationId);
    let exists = true;
    try {
      await fs.access(createPayloadCwd!);
    } catch {
      exists = false;
    }
    expect(exists).toBe(false);
    await provider.disconnect();
  });

  it("respects an explicit opts.cwd override (no materialization)", async () => {
    let createPayloadCwd: string | undefined;
    server.onSessionCreate = (payload) => {
      createPayloadCwd = payload["cwd"] as string;
      return {
        id: `mat-conv-${++nextSession}`,
        name: "x",
        cwd: createPayloadCwd ?? "/tmp",
        permissionMode: "normal",
        skipPermissions: true,
        status: "active",
        createdAt: 1000,
        provider: "claude",
      };
    };

    const provider = makeMaterializingProvider();
    await provider.startConversation({ cwd: "/explicit/dir" });
    expect(createPayloadCwd).toBe("/explicit/dir");
    await provider.disconnect();
  });

  it("gives concurrent conversations distinct runtime dirs", async () => {
    const cwds: string[] = [];
    server.onSessionCreate = (payload) => {
      cwds.push(payload["cwd"] as string);
      return {
        id: `mat-conv-${++nextSession}`,
        name: "x",
        cwd: (payload["cwd"] as string) ?? "/tmp",
        permissionMode: "normal",
        skipPermissions: true,
        status: "active",
        createdAt: 1000,
        provider: "claude",
      };
    };

    const provider = makeMaterializingProvider();
    const [a, b] = await Promise.all([
      provider.startConversation(),
      provider.startConversation(),
    ]);
    expect(a.conversationId).not.toBe(b.conversationId);
    expect(cwds.length).toBe(2);
    expect(cwds[0]).not.toBe(cwds[1]);
    await provider.disconnect();
  });

  it("writes .mcp.json with alwaysLoad:true and a per-session .claude/settings.json deny list", async () => {
    // Stage a synthetic global ~/.claude.json the loader can read.
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    const globalCfgDir = await fs.mkdtemp(
      path.join(os.tmpdir(), "budget-globalcfg-"),
    );
    const globalCfgPath = path.join(globalCfgDir, "config.json");
    await fs.writeFile(
      globalCfgPath,
      JSON.stringify({
        mcpServers: {
          "ask-the-budget-az": {
            command: "/test/node",
            args: ["/test/mcp/dist/index.js"],
            env: { RETRIEVAL_BRIDGE_URL: "http://127.0.0.1:9200" },
          },
        },
      }),
      "utf8",
    );

    let createPayloadCwd: string | undefined;
    server.onSessionCreate = (payload) => {
      createPayloadCwd = payload["cwd"] as string;
      return {
        id: `mat-conv-${++nextSession}`,
        name: "x",
        cwd: createPayloadCwd ?? "/tmp",
        permissionMode: "normal",
        skipPermissions: true,
        status: "active",
        createdAt: 1000,
        provider: "claude",
      };
    };

    const provider = new YouCodedSessionProvider({
      url: serverUrl,
      token: "test-token",
      systemPromptPath: promptPath,
      systemPromptContextPath: contextPath,
      runtimeDirRoot: runtimeRoot,
      globalMcpConfigPath: globalCfgPath,
    });

    await provider.startConversation();
    expect(typeof createPayloadCwd).toBe("string");

    // .mcp.json should declare the budget server eagerly loaded.
    const mcpJsonRaw = await fs.readFile(
      path.join(createPayloadCwd!, ".mcp.json"),
      "utf8",
    );
    const mcpJson = JSON.parse(mcpJsonRaw);
    expect(mcpJson.mcpServers["ask-the-budget-az"]).toMatchObject({
      command: "/test/node",
      args: ["/test/mcp/dist/index.js"],
      env: { RETRIEVAL_BRIDGE_URL: "http://127.0.0.1:9200" },
      alwaysLoad: true,
    });

    // .claude/settings.json should allow Bash + Read + the three
    // budget MCP tools (D5: general tools stay enabled) and deny the
    // tools past sessions never used legitimately.
    const settingsRaw = await fs.readFile(
      path.join(createPayloadCwd!, ".claude", "settings.json"),
      "utf8",
    );
    const settings = JSON.parse(settingsRaw);
    expect(settings.permissions.allow).toEqual(
      expect.arrayContaining([
        "Bash",
        "Read",
        "mcp__ask-the-budget-az__retrieve",
        "mcp__ask-the-budget-az__cite",
        "mcp__ask-the-budget-az__cite_batch",
        "mcp__ask-the-budget-az__list_filter_values",
      ]),
    );
    expect(settings.permissions.deny).toEqual(
      expect.arrayContaining([
        "Grep",
        "Write",
        "Edit",
        "WebFetch",
        "WebSearch",
      ]),
    );
    // ToolSearch is NOT in either list — alwaysLoad eliminates need
    // for it and denying could break lazy-loading for anything we
    // haven't eager-loaded.
    expect(settings.permissions.allow).not.toContain("ToolSearch");
    expect(settings.permissions.deny).not.toContain("ToolSearch");

    await provider.disconnect();
    await fs.rm(globalCfgDir, { recursive: true, force: true });
  });

  it("throws a clear error when the budget MCP server isn't in the global config", async () => {
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");
    const globalCfgDir = await fs.mkdtemp(
      path.join(os.tmpdir(), "budget-globalcfg-empty-"),
    );
    const globalCfgPath = path.join(globalCfgDir, "config.json");
    await fs.writeFile(globalCfgPath, JSON.stringify({}), "utf8");

    server.onSessionCreate = () => ({
      id: "should-never-reach",
      name: "x",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = new YouCodedSessionProvider({
      url: serverUrl,
      token: "test-token",
      systemPromptPath: promptPath,
      systemPromptContextPath: contextPath,
      runtimeDirRoot: runtimeRoot,
      globalMcpConfigPath: globalCfgPath,
    });

    await expect(provider.startConversation()).rejects.toThrow(
      /Budget MCP server isn't registered/,
    );

    await provider.disconnect();
    await fs.rm(globalCfgDir, { recursive: true, force: true });
  });
});

// ---------------------------------------------------------------------------
// Tool-result redirect inlining
//
// When `retrieve()` returns a chunks blob bigger than Claude Code's
// per-tool-result token budget (observed live: ~88K characters for 20
// chunks), CC writes the real payload to a sidecar `tool-results/*.txt`
// and gives the caller a redirect message instead. Without inlining,
// every cite() call's chunk_id fails to resolve against the empty
// chunks map and the side-panel shows "Couldn't open source PDF" for
// every citation.

describe("YouCodedSessionProvider — tool-result redirect inlining", () => {
  it("follows the 'Output has been saved to <path>' redirect and returns chunk ids from the sidecar", async () => {
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");

    // Stage a sidecar file in the exact shape Claude Code writes:
    // a JSON array of { type: 'text', text: <stringified payload> } parts.
    const sidecarDir = await fs.mkdtemp(
      path.join(os.tmpdir(), "budget-redirect-test-"),
    );
    const sidecarFile = path.join(
      sidecarDir,
      "mcp-ask-the-budget-az-retrieve-12345.txt",
    );
    const realPayload = JSON.stringify({
      chunks: [
        {
          chunk_id: "jlbc-baseline-fy2027-s18-0010",
          doc_id: "jlbc-baseline-fy2027-s18",
          page_start: 11,
        },
        {
          chunk_id: "jlbc-baseline-fy2027-s18-0011",
          doc_id: "jlbc-baseline-fy2027-s18",
          page_start: 12,
        },
      ],
      top_score: 0.62,
      retrieval_id: "ret-redirect",
    });
    await fs.writeFile(
      sidecarFile,
      JSON.stringify([{ type: "text", text: realPayload }]),
    );

    server.onSessionCreate = () => ({
      id: "redirect-conv",
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

        emit(
          "tool-use",
          {
            toolUseId: "tu-redirect",
            toolName: "retrieve",
            toolInput: { query: "aviation" },
          },
          "u-1",
        );
        // The redirect message Claude Code writes when the real
        // payload exceeds the per-tool token budget. Note the
        // `.txt\b` boundary the inliner regex relies on.
        const redirectMsg =
          `Error: result (88,629 characters) exceeds maximum allowed tokens. ` +
          `Output has been saved to ${sidecarFile}.\n` +
          `Format: JSON array...`;
        emit(
          "tool-result",
          {
            toolUseId: "tu-redirect",
            toolResult: redirectMsg,
            isError: false,
          },
          "u-2",
        );
        emit(
          "assistant-text",
          { text: "ok", model: "claude-opus-4-7" },
          "u-text",
        );
        emit(
          "turn-complete",
          {
            stopReason: "end_turn",
            model: "claude-opus-4-7",
            anthropicRequestId: "req_redirect",
            usage: {
              inputTokens: 1,
              outputTokens: 1,
              cacheReadTokens: 0,
              cacheCreationTokens: 0,
            },
          },
          "u-end",
        );
      });
    };

    const seenToolResults: string[] = [];
    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: (e) => {
        if (e.type === "tool_result" && typeof e.output === "string") {
          seenToolResults.push(e.output);
        }
      },
    });

    // The forwarded tool_result event got the inlined chunks, not
    // the redirect message — so client-side citation extraction
    // can build the resolved-chunk map.
    expect(seenToolResults).toHaveLength(1);
    expect(seenToolResults[0]).not.toContain("Output has been saved to");
    expect(seenToolResults[0]).toContain("jlbc-baseline-fy2027-s18-0010");

    // Server-side accumulator picked up both chunk ids — the audit
    // log will record them.
    expect(result.retrievedChunkIds).toEqual([
      "jlbc-baseline-fy2027-s18-0010",
      "jlbc-baseline-fy2027-s18-0011",
    ]);

    await provider.disconnect();
    await fs.rm(sidecarDir, { recursive: true, force: true });
  });

  it("also handles the <persisted-output> 'Full output saved to:' format with a .json sidecar", async () => {
    const fs = await import("node:fs/promises");
    const os = await import("node:os");
    const path = await import("node:path");

    const sidecarDir = await fs.mkdtemp(
      path.join(os.tmpdir(), "budget-redirect-test2-"),
    );
    const sidecarFile = path.join(
      sidecarDir,
      "toolu_01UJBFU2T313QH1RrFp69nkQ.json",
    );
    const realPayload = JSON.stringify({
      chunks: [
        {
          chunk_id: "jlbc-baseline-fy2027-s18-0008",
          doc_id: "jlbc-baseline-fy2027-s18",
          page_start: 9,
        },
      ],
      top_score: 0.55,
      retrieval_id: "ret-2",
    });
    await fs.writeFile(
      sidecarFile,
      JSON.stringify([{ type: "text", text: realPayload }]),
    );

    server.onSessionCreate = () => ({
      id: "redirect-conv-2",
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

        emit(
          "tool-use",
          {
            toolUseId: "tu-redirect2",
            toolName: "retrieve",
            toolInput: { query: "border security" },
          },
          "u-1",
        );
        // Format B exactly as observed in transcripts:
        const redirectMsg =
          `<persisted-output>\n` +
          `Output too large (67.3KB). Full output saved to: ${sidecarFile}\n\n` +
          `Preview (first 2KB):\n[\n  {\n    "type": "text",\n    "text": "..."\n  }\n]`;
        emit(
          "tool-result",
          {
            toolUseId: "tu-redirect2",
            toolResult: redirectMsg,
            isError: false,
          },
          "u-2",
        );
        emit("assistant-text", { text: "ok" }, "u-text");
        emit(
          "turn-complete",
          {
            stopReason: "end_turn",
            model: "claude-opus-4-7",
            anthropicRequestId: "req_redirect2",
            usage: {
              inputTokens: 1,
              outputTokens: 1,
              cacheReadTokens: 0,
              cacheCreationTokens: 0,
            },
          },
          "u-end",
        );
      });
    };

    const seenToolResults: string[] = [];
    const result = await provider.sendTurn({
      conversationId,
      userMessage: "x",
      onEvent: (e) => {
        if (e.type === "tool_result" && typeof e.output === "string") {
          seenToolResults.push(e.output);
        }
      },
    });

    expect(seenToolResults).toHaveLength(1);
    expect(seenToolResults[0]).not.toContain("Full output saved to");
    expect(seenToolResults[0]).toContain("jlbc-baseline-fy2027-s18-0008");
    expect(result.retrievedChunkIds).toEqual([
      "jlbc-baseline-fy2027-s18-0008",
    ]);

    await provider.disconnect();
    await fs.rm(sidecarDir, { recursive: true, force: true });
  });
});

// ---------------------------------------------------------------------------
// Sidecar /health probe (Decision Q1)
//
// startConversation runs a 2-second probe of the retrieval sidecar's
// /health endpoint and returns the result inline so the UI can render
// a banner BEFORE the user types a question. No event plumbing — the
// probe outcome is just a field on the return value.

describe("YouCodedSessionProvider — sidecar health probe", () => {
  it("startConversation returns health.ok=false when the probe fails", async () => {
    server.onSessionCreate = () => ({
      id: "probe-conv-1",
      name: "x",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    // Point the probe at a port nothing's listening on so the fetch
    // fails fast (ECONNREFUSED) within the 2s timeout.
    const prev = process.env.RETRIEVAL_BRIDGE_URL;
    process.env.RETRIEVAL_BRIDGE_URL = "http://127.0.0.1:1";

    const result = await provider.startConversation();

    expect(result.conversationId).toBe("probe-conv-1");
    expect(result.health.ok).toBe(false);
    expect(typeof result.health.reason).toBe("string");
    expect(result.health.reason!.length).toBeGreaterThan(0);

    if (prev === undefined) delete process.env.RETRIEVAL_BRIDGE_URL;
    else process.env.RETRIEVAL_BRIDGE_URL = prev;
    await provider.disconnect();
  });

  it("startConversation returns health.ok=true when the sidecar responds 200", async () => {
    // Spin a tiny test HTTP server that answers /health with 200.
    const http = await import("node:http");
    const healthServer = http.createServer((_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ status: "ok" }));
    });
    await new Promise<void>((resolve) => healthServer.listen(0, resolve));
    const port = (healthServer.address() as { port: number }).port;

    server.onSessionCreate = () => ({
      id: "probe-conv-2",
      name: "x",
      cwd: "/tmp",
      permissionMode: "normal",
      skipPermissions: true,
      status: "active",
      createdAt: 1000,
      provider: "claude",
    });

    const provider = makeProvider();
    const prev = process.env.RETRIEVAL_BRIDGE_URL;
    process.env.RETRIEVAL_BRIDGE_URL = `http://127.0.0.1:${port}`;

    const result = await provider.startConversation();
    expect(result.health.ok).toBe(true);
    expect(result.health.reason).toBeUndefined();

    if (prev === undefined) delete process.env.RETRIEVAL_BRIDGE_URL;
    else process.env.RETRIEVAL_BRIDGE_URL = prev;
    await provider.disconnect();
    await new Promise<void>((resolve) => healthServer.close(() => resolve()));
  });
});
