import { describe, expect, it } from "vitest";
import { rehydrateTurns } from "../history-rehydrate.js";

const TS = "2026-08-02T10:00:00+00:00";

describe("rehydrateTurns", () => {
  it("a plain user/assistant pair round-trips to two turns", () => {
    const turns = rehydrateTurns(
      [
        { role: "user", content: "what did ADC spend?" },
        { role: "assistant", content: "ADC spent $1.2 billion." },
      ],
      TS,
    );
    expect(turns).toHaveLength(2);
    expect(turns[0].kind).toBe("user");
    expect(turns[1].kind).toBe("assistant");
    if (turns[0].kind === "user") expect(turns[0].text).toBe("what did ADC spend?");
    if (turns[1].kind === "assistant") {
      expect(turns[1].blocks).toHaveLength(1);
      expect(turns[1].blocks[0].kind).toBe("text");
    }
  });

  it("an assistant turn with tool_calls + replies produces text and tool blocks in arrival order", () => {
    const turns = rehydrateTurns(
      [
        { role: "user", content: "q" },
        {
          role: "assistant",
          content: "Let me search.",
          tool_calls: [
            {
              id: "call_1",
              type: "function",
              function: { name: "retrieve", arguments: '{"query": "ADC"}' },
            },
          ],
        },
        { role: "tool", tool_call_id: "call_1", content: '{"chunks": []}' },
        { role: "assistant", content: "ADC spent $1.2 billion." },
      ],
      TS,
    );
    expect(turns).toHaveLength(2);
    if (turns[1].kind === "assistant") {
      const blocks = turns[1].blocks;
      // text → tool → text in arrival order
      expect(blocks).toHaveLength(3);
      expect(blocks[0].kind).toBe("text");
      expect(blocks[1].kind).toBe("tool");
      expect(blocks[2].kind).toBe("text");
      if (blocks[1].kind === "tool") {
        expect(blocks[1].toolName).toBe("retrieve");
        expect(blocks[1].toolUseId).toBe("call_1");
        expect(blocks[1].status).toBe("complete");
        expect(blocks[1].output).toBe('{"chunks": []}');
      }
    }
  });

  it("arguments that is not valid JSON yields input: {} and does not throw", () => {
    expect(() =>
      rehydrateTurns(
        [
          { role: "user", content: "q" },
          {
            role: "assistant",
            content: "",
            tool_calls: [
              {
                id: "c1",
                type: "function",
                function: { name: "retrieve", arguments: '{"query": br' },
              },
            ],
          },
          { role: "tool", tool_call_id: "c1", content: "result" },
        ],
        TS,
      ),
    ).not.toThrow();
    const turns = rehydrateTurns(
      [
        { role: "user", content: "q" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "c1",
              type: "function",
              function: { name: "retrieve", arguments: '{"query": br' },
            },
          ],
        },
        { role: "tool", tool_call_id: "c1", content: "result" },
      ],
      TS,
    );
    if (turns[1].kind === "assistant") {
      const block = turns[1].blocks[0];
      if (block.kind === "tool") {
        expect(block.input).toEqual({});
      }
    }
  });

  it("a tool call with no matching reply still renders (status failed)", () => {
    const turns = rehydrateTurns(
      [
        { role: "user", content: "q" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "orphan",
              type: "function",
              function: { name: "retrieve", arguments: "{}" },
            },
          ],
        },
      ],
      TS,
    );
    if (turns[1].kind === "assistant") {
      const block = turns[1].blocks[0];
      if (block.kind === "tool") {
        expect(block.status).toBe("failed");
      }
    }
  });

  it("an unknown role is skipped rather than rendered", () => {
    const turns = rehydrateTurns(
      [
        { role: "system", content: "you are a budget analyst" },
        { role: "user", content: "q" },
        { role: "assistant", content: "a" },
      ],
      TS,
    );
    expect(turns).toHaveLength(2);
    expect(turns.every((t) => t.kind === "user" || t.kind === "assistant")).toBe(true);
  });

  it("returns [] on an empty list", () => {
    expect(rehydrateTurns([])).toEqual([]);
  });

  it("restores the annotation from the final assistant message (Handoff Issue 1)", () => {
    const annotation = {
      figures: [
        { text: "$1,391,157,700", start: 0, end: 15, index: 1, verdict: "linked",
          primary: { chunk_id: "c1", doc_id: "d1", page_start: 3 } },
      ],
    };
    const turns = rehydrateTurns(
      [
        { role: "user", content: "what did ADC spend?" },
        {
          role: "assistant",
          content: "Let me search.",
          tool_calls: [
            { id: "call_1", type: "function",
              function: { name: "retrieve", arguments: '{"query": "ADC"}' } },
          ],
        },
        { role: "tool", tool_call_id: "call_1", content: '{"chunks": []}' },
        { role: "assistant", content: "ADC spent $1,391,157,700.", annotation },
      ],
      TS,
    );
    expect(turns).toHaveLength(2);
    const last = turns[turns.length - 1];
    if (last.kind === "assistant") {
      expect(last.annotation).toEqual(annotation);
    }
  });

  it("leaves annotation undefined when no assistant message carries it", () => {
    const turns = rehydrateTurns(
      [
        { role: "user", content: "q" },
        { role: "assistant", content: "answer" },
      ],
      TS,
    );
    const last = turns[turns.length - 1];
    if (last.kind === "assistant") {
      expect(last.annotation).toBeUndefined();
    }
  });

  it("takes the annotation from a tool-calling turn's answer, not its narration", () => {
    // The server attaches the annotation to the FINAL assistant message (the
    // answer). Narration messages before it carry none.
    const turns = rehydrateTurns(
      [
        { role: "user", content: "q" },
        { role: "assistant", content: "Let me search." },
        { role: "tool", tool_call_id: "call_9", content: "{}" },
        { role: "assistant", content: "The answer.", annotation: { figures: [{ text: "x" }] } },
      ],
      TS,
    );
    const last = turns[turns.length - 1];
    if (last.kind === "assistant") {
      expect(last.annotation).toEqual({ figures: [{ text: "x" }] });
    }
  });

  it("timestamps are fabricated from createdAt", () => {
    const ts = "2026-08-02T10:00:00+00:00";
    const turns = rehydrateTurns(
      [{ role: "user", content: "q" }],
      ts,
    );
    const expected = Date.parse(ts);
    if (turns[0].kind === "user") {
      expect(turns[0].timestamp).toBe(expected);
    }
  });
});
