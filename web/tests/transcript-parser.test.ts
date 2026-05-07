// Unit tests for parseTranscriptEvent. Pure functions, no I/O — every
// transcript-event type round-trips through to its corresponding
// ProviderEvent shape.

import { describe, expect, it } from "vitest";

import {
  parseTranscriptEvent,
  type ParserContext,
} from "../lib/transcript-parser.js";
import type { TranscriptEvent } from "../lib/types.js";

function ev(
  type: TranscriptEvent["type"],
  data: TranscriptEvent["data"] = {},
  uuid = "u1",
): TranscriptEvent {
  return { type, sessionId: "s1", uuid, timestamp: 1000, data };
}

describe("parseTranscriptEvent", () => {
  it("translates user-message", () => {
    const out = parseTranscriptEvent(ev("user-message", { text: "hi" }));
    expect(out).toEqual({
      type: "user_message",
      text: "hi",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("translates user-interrupt with kind", () => {
    expect(
      parseTranscriptEvent(ev("user-interrupt", { kind: "tool-use" })),
    ).toEqual({
      type: "user_interrupt",
      kind: "tool-use",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("user-interrupt defaults kind to 'plain' when missing", () => {
    expect(parseTranscriptEvent(ev("user-interrupt", {}))).toEqual({
      type: "user_interrupt",
      kind: "plain",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("translates assistant-text including model", () => {
    expect(
      parseTranscriptEvent(
        ev("assistant-text", { text: "answer", model: "claude-opus-4-7" }),
      ),
    ).toEqual({
      type: "assistant_text_delta",
      text: "answer",
      model: "claude-opus-4-7",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("dedups repeated assistant-text uuids when ctx is provided", () => {
    const ctx: ParserContext = { seenAssistantTextUuids: new Set() };
    const first = parseTranscriptEvent(
      ev("assistant-text", { text: "ab" }, "u1"),
      ctx,
    );
    const second = parseTranscriptEvent(
      ev("assistant-text", { text: "abcd" }, "u1"),
      ctx,
    );
    const third = parseTranscriptEvent(
      ev("assistant-text", { text: "x" }, "u2"),
      ctx,
    );
    expect(first?.type).toBe("assistant_text_delta");
    expect(second).toBeNull();
    expect(third?.type).toBe("assistant_text_delta");
  });

  it("does NOT dedup when ctx omits seenAssistantTextUuids", () => {
    // Useful for one-shot translations where the caller wants every
    // event rendered (e.g. transcript replay tests).
    const a = parseTranscriptEvent(
      ev("assistant-text", { text: "ab" }, "u1"),
    );
    const b = parseTranscriptEvent(
      ev("assistant-text", { text: "abcd" }, "u1"),
    );
    expect(a?.type).toBe("assistant_text_delta");
    expect(b?.type).toBe("assistant_text_delta");
  });

  it("collapses 'thinking' and 'assistant-thinking' to assistant_thinking", () => {
    const a = parseTranscriptEvent(ev("thinking"));
    const b = parseTranscriptEvent(ev("assistant-thinking"));
    expect(a).toEqual({
      type: "assistant_thinking",
      uuid: "u1",
      timestamp: 1000,
    });
    expect(b).toEqual({
      type: "assistant_thinking",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("translates a generic tool-use (Bash) — not just retrieve/cite", () => {
    expect(
      parseTranscriptEvent(
        ev("tool-use", {
          toolUseId: "tu_1",
          toolName: "Bash",
          toolInput: { command: "ls -la", description: "list files" },
        }),
      ),
    ).toEqual({
      type: "tool_use",
      toolUseId: "tu_1",
      toolName: "Bash",
      input: { command: "ls -la", description: "list files" },
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("translates a tool-use with empty input to {}", () => {
    expect(
      parseTranscriptEvent(
        ev("tool-use", { toolUseId: "tu_1", toolName: "TaskList" }),
      ),
    ).toMatchObject({
      type: "tool_use",
      input: {},
    });
  });

  it("translates tool-result with isError + structuredPatch carried through", () => {
    const out = parseTranscriptEvent(
      ev("tool-result", {
        toolUseId: "tu_1",
        toolResult: "diff applied",
        isError: false,
        structuredPatch: [
          {
            oldStart: 1,
            oldLines: 1,
            newStart: 1,
            newLines: 1,
            lines: [" context", "-old", "+new"],
          },
        ],
      }),
    );
    expect(out).toMatchObject({
      type: "tool_result",
      toolUseId: "tu_1",
      output: "diff applied",
      isError: false,
    });
    expect(
      (out as { structuredPatch?: unknown[] }).structuredPatch,
    ).toHaveLength(1);
  });

  it("omits optional fields on tool-result when absent (clean shape)", () => {
    const out = parseTranscriptEvent(
      ev("tool-result", { toolUseId: "tu_1", toolResult: "ok" }),
    );
    expect(out).toEqual({
      type: "tool_result",
      toolUseId: "tu_1",
      output: "ok",
      uuid: "u1",
      timestamp: 1000,
    });
    expect("isError" in (out as object)).toBe(false);
    expect("structuredPatch" in (out as object)).toBe(false);
  });

  it("translates turn-complete with full metadata", () => {
    expect(
      parseTranscriptEvent(
        ev("turn-complete", {
          stopReason: "end_turn",
          model: "claude-opus-4-7",
          anthropicRequestId: "req_abc",
          usage: {
            inputTokens: 1000,
            outputTokens: 200,
            cacheReadTokens: 50,
            cacheCreationTokens: 0,
          },
        }),
      ),
    ).toEqual({
      type: "turn_complete",
      stopReason: "end_turn",
      model: "claude-opus-4-7",
      anthropicRequestId: "req_abc",
      usage: {
        inputTokens: 1000,
        outputTokens: 200,
        cacheReadTokens: 50,
        cacheCreationTokens: 0,
      },
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("turn-complete defaults stopReason to 'end_turn' when missing", () => {
    expect(parseTranscriptEvent(ev("turn-complete", {}))).toEqual({
      type: "turn_complete",
      stopReason: "end_turn",
      uuid: "u1",
      timestamp: 1000,
    });
  });

  it("translates compact-summary", () => {
    expect(parseTranscriptEvent(ev("compact-summary"))).toEqual({
      type: "compact_summary",
      uuid: "u1",
      timestamp: 1000,
    });
  });
});
