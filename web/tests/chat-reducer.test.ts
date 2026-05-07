// Pure unit tests for the chat reducer + ProviderEvent translator.
// No DOM, no React — just state in / state out.

import { describe, expect, it } from "vitest";

import type { ProviderEvent } from "../lib/types.js";
import {
  chatActionFromProviderEvent,
  chatReducer,
} from "../state/chat-reducer.js";
import {
  initialChatState,
  type AssistantTurn,
  type ChatAction,
  type ChatState,
  type UserTurn,
} from "../state/chat-types.js";

function reduce(state: ChatState, ...actions: ChatAction[]): ChatState {
  return actions.reduce((s, a) => chatReducer(s, a), state);
}

const T = 1_700_000_000_000;

describe("chatReducer — conversation lifecycle", () => {
  it("CONVERSATION_STARTED sets the id and clears state", () => {
    const out = chatReducer(
      { ...initialChatState, error: "old error" },
      { type: "CONVERSATION_STARTED", conversationId: "conv-1" },
    );
    expect(out.conversationId).toBe("conv-1");
    expect(out.turns).toEqual([]);
    expect(out.error).toBeNull();
  });

  it("USER_PROMPT appends a pending user entry and flips isThinking", () => {
    const out = chatReducer(initialChatState, {
      type: "USER_PROMPT",
      text: "Aviation Fund balance?",
      clientUuid: "c1",
      timestamp: T,
    });
    expect(out.turns).toHaveLength(1);
    expect(out.turns[0]).toMatchObject({
      kind: "user",
      text: "Aviation Fund balance?",
      pending: true,
      id: "c1",
    });
    expect(out.isThinking).toBe(true);
  });

  it("USER_MESSAGE_CONFIRMED clears the pending flag on the matching entry", () => {
    let s = chatReducer(initialChatState, {
      type: "USER_PROMPT",
      text: "hi",
      clientUuid: "c1",
      timestamp: T,
    });
    s = chatReducer(s, {
      type: "USER_MESSAGE_CONFIRMED",
      uuid: "transcript-uuid",
      text: "hi",
      timestamp: T + 1,
    });
    expect(s.turns).toHaveLength(1);
    const u = s.turns[0] as UserTurn;
    expect(u.pending).toBe(false);
    expect(u.id).toBe("c1"); // we keep the optimistic id for React keying
  });

  it("USER_MESSAGE_CONFIRMED appends when no pending match exists", () => {
    const s = chatReducer(initialChatState, {
      type: "USER_MESSAGE_CONFIRMED",
      uuid: "u1",
      text: "from terminal",
      timestamp: T,
    });
    expect(s.turns).toEqual([
      {
        kind: "user",
        id: "u1",
        text: "from terminal",
        pending: false,
        timestamp: T,
      },
    ]);
  });
});

describe("chatReducer — assistant text", () => {
  it("ASSISTANT_TEXT opens an assistant turn with one text block", () => {
    const s = reduce(initialChatState, {
      type: "ASSISTANT_TEXT",
      uuid: "u-text",
      text: "Hello",
      model: "claude-opus-4-7",
      timestamp: T,
    });
    expect(s.turns).toHaveLength(1);
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.kind).toBe("assistant");
    expect(turn.id).toBe("u-text"); // seeded from the first block uuid
    expect(turn.model).toBe("claude-opus-4-7");
    expect(turn.blocks).toEqual([
      { kind: "text", uuid: "u-text", text: "Hello", model: "claude-opus-4-7" },
    ]);
    expect(turn.isComplete).toBe(false);
  });

  it("ASSISTANT_TEXT with same uuid replaces text in place (growing message)", () => {
    const s = reduce(
      initialChatState,
      {
        type: "ASSISTANT_TEXT",
        uuid: "u1",
        text: "Hel",
        timestamp: T,
      },
      { type: "ASSISTANT_TEXT", uuid: "u1", text: "Hello", timestamp: T + 1 },
      {
        type: "ASSISTANT_TEXT",
        uuid: "u1",
        text: "Hello world",
        timestamp: T + 2,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.blocks).toHaveLength(1);
    expect(turn.blocks[0]).toMatchObject({
      kind: "text",
      uuid: "u1",
      text: "Hello world",
    });
  });

  it("ASSISTANT_TEXT with different uuid appends a new block", () => {
    const s = reduce(
      initialChatState,
      { type: "ASSISTANT_TEXT", uuid: "u1", text: "First", timestamp: T },
      {
        type: "ASSISTANT_TEXT",
        uuid: "u2",
        text: "Second",
        timestamp: T + 1,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.blocks).toHaveLength(2);
    expect(turn.blocks.map((b) => (b.kind === "text" ? b.text : ""))).toEqual([
      "First",
      "Second",
    ]);
  });
});

describe("chatReducer — tool blocks", () => {
  it("TOOL_USE appends a running block; TOOL_RESULT marks it complete", () => {
    const s = reduce(
      initialChatState,
      {
        type: "TOOL_USE",
        toolUseId: "tu-1",
        toolName: "Bash",
        input: { command: "ls" },
        uuid: "u1",
        timestamp: T,
      },
      {
        type: "TOOL_RESULT",
        toolUseId: "tu-1",
        output: "file1\nfile2",
        isError: false,
        uuid: "u2",
        timestamp: T + 1,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.blocks).toHaveLength(1);
    expect(turn.blocks[0]).toMatchObject({
      kind: "tool",
      toolUseId: "tu-1",
      toolName: "Bash",
      status: "complete",
      output: "file1\nfile2",
      isError: false,
    });
  });

  it("TOOL_RESULT with isError marks the block failed", () => {
    const s = reduce(
      initialChatState,
      {
        type: "TOOL_USE",
        toolUseId: "tu-1",
        toolName: "Bash",
        input: {},
        uuid: "u1",
        timestamp: T,
      },
      {
        type: "TOOL_RESULT",
        toolUseId: "tu-1",
        output: "command not found: snek",
        isError: true,
        uuid: "u2",
        timestamp: T + 1,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    const tool = turn.blocks[0];
    expect(tool?.kind).toBe("tool");
    expect((tool as { status: string }).status).toBe("failed");
  });

  it("interleaved text and tool blocks preserve arrival order", () => {
    const s = reduce(
      initialChatState,
      {
        type: "ASSISTANT_TEXT",
        uuid: "t1",
        text: "Looking up the fund balance.",
        timestamp: T,
      },
      {
        type: "TOOL_USE",
        toolUseId: "tu-r",
        toolName: "retrieve",
        input: { query: "Aviation Fund balance" },
        uuid: "u1",
        timestamp: T + 1,
      },
      {
        type: "TOOL_RESULT",
        toolUseId: "tu-r",
        output: "{}",
        uuid: "u2",
        timestamp: T + 2,
      },
      {
        type: "TOOL_USE",
        toolUseId: "tu-c",
        toolName: "cite",
        input: {},
        uuid: "u3",
        timestamp: T + 3,
      },
      {
        type: "TOOL_RESULT",
        toolUseId: "tu-c",
        output: "{}",
        uuid: "u4",
        timestamp: T + 4,
      },
      {
        type: "ASSISTANT_TEXT",
        uuid: "t2",
        text: "Aviation Fund balance was $123,456.",
        timestamp: T + 5,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.blocks.map((b) => b.kind)).toEqual([
      "text",
      "tool",
      "tool",
      "text",
    ]);
    expect(turn.blocks.map((b) => (b.kind === "tool" ? b.toolName : b.text)))
      .toEqual([
        "Looking up the fund balance.",
        "retrieve",
        "cite",
        "Aviation Fund balance was $123,456.",
      ]);
  });

  it("doesn't double-add a TOOL_USE with the same toolUseId", () => {
    const s = reduce(
      initialChatState,
      {
        type: "TOOL_USE",
        toolUseId: "tu-1",
        toolName: "Bash",
        input: {},
        uuid: "u1",
        timestamp: T,
      },
      {
        type: "TOOL_USE",
        toolUseId: "tu-1",
        toolName: "Bash",
        input: {},
        uuid: "u2",
        timestamp: T + 1,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.blocks).toHaveLength(1);
  });
});

describe("chatReducer — turn lifecycle", () => {
  it("TURN_COMPLETE attaches metadata and clears isThinking", () => {
    const s = reduce(
      initialChatState,
      { type: "ASSISTANT_TEXT", uuid: "u1", text: "ok", timestamp: T },
      {
        type: "TURN_COMPLETE",
        stopReason: "end_turn",
        model: "claude-opus-4-7",
        anthropicRequestId: "req_abc",
        usage: {
          inputTokens: 100,
          outputTokens: 20,
          cacheReadTokens: 0,
          cacheCreationTokens: 0,
        },
        uuid: "u2",
        timestamp: T + 1,
      },
    );
    const turn = s.turns[0] as AssistantTurn;
    expect(turn.isComplete).toBe(true);
    expect(turn.stopReason).toBe("end_turn");
    expect(turn.model).toBe("claude-opus-4-7");
    expect(turn.anthropicRequestId).toBe("req_abc");
    expect(turn.usage?.inputTokens).toBe(100);
    expect(s.isThinking).toBe(false);
  });

  it("TURN_ERROR fails any running tools and surfaces an error message", () => {
    const s = reduce(
      initialChatState,
      {
        type: "TOOL_USE",
        toolUseId: "tu-1",
        toolName: "Bash",
        input: {},
        uuid: "u1",
        timestamp: T,
      },
      { type: "TURN_ERROR", message: "Lost connection to YouCoded" },
    );
    const turn = s.turns[0] as AssistantTurn;
    const tool = turn.blocks[0];
    expect((tool as { status: string }).status).toBe("failed");
    expect(turn.isComplete).toBe(true);
    expect(s.isThinking).toBe(false);
    expect(s.error).toBe("Lost connection to YouCoded");
  });

  it("CLEAR_ERROR clears the error", () => {
    const s = chatReducer(
      { ...initialChatState, error: "x" },
      { type: "CLEAR_ERROR" },
    );
    expect(s.error).toBeNull();
  });
});

describe("chatActionFromProviderEvent", () => {
  it("translates every ProviderEvent type", () => {
    const make = (e: ProviderEvent) => chatActionFromProviderEvent(e);
    expect(
      make({ type: "user_message", text: "hi", uuid: "u1", timestamp: T }),
    ).toMatchObject({ type: "USER_MESSAGE_CONFIRMED" });
    expect(
      make({
        type: "user_interrupt",
        kind: "plain",
        uuid: "u1",
        timestamp: T,
      }),
    ).toMatchObject({ type: "TURN_ERROR" });
    expect(
      make({
        type: "assistant_text_delta",
        text: "x",
        uuid: "u1",
        timestamp: T,
      }),
    ).toMatchObject({ type: "ASSISTANT_TEXT" });
    expect(
      make({ type: "assistant_thinking", uuid: "u1", timestamp: T }),
    ).toMatchObject({ type: "ASSISTANT_THINKING" });
    expect(
      make({
        type: "tool_use",
        toolUseId: "x",
        toolName: "Bash",
        input: {},
        uuid: "u1",
        timestamp: T,
      }),
    ).toMatchObject({ type: "TOOL_USE" });
    expect(
      make({
        type: "tool_result",
        toolUseId: "x",
        output: "ok",
        uuid: "u1",
        timestamp: T,
      }),
    ).toMatchObject({ type: "TOOL_RESULT" });
    expect(
      make({
        type: "turn_complete",
        stopReason: "end_turn",
        uuid: "u1",
        timestamp: T,
      }),
    ).toMatchObject({ type: "TURN_COMPLETE" });
    expect(
      make({ type: "compact_summary", uuid: "u1", timestamp: T }),
    ).toBeNull();
  });
});
