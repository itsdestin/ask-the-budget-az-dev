// New in Plan 4 Task 10.
//
// Task 6 removed the harness's synthetic "this answer is incomplete"
// assistant message, because system-authored first-person prose was landing
// in `_done.finalAnswer` — the audit record of what the MODEL said. The fact
// now travels as `stopReason: "max_steps"`. These tests are the other half of
// that trade: if the UI doesn't surface it, an answer that ran out of budget
// mid-thought is indistinguishable from a finished one, which is exactly the
// failure mode Core Invariant 3 exists to prevent.

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { renderToString } from "react-dom/server";

import AssistantTurnBubble from "../AssistantTurnBubble.js";
import type { AssistantTurn } from "../chat-types.js";

function turn(overrides: Partial<AssistantTurn> = {}): AssistantTurn {
  return {
    kind: "assistant",
    id: "a1",
    blocks: [
      {
        kind: "text",
        uuid: "u1",
        text: "ADOT's FY2027 operating budget is",
      },
    ],
    isComplete: true,
    timestamp: 1,
    ...overrides,
  };
}

describe("AssistantTurnBubble — max_steps notice", () => {
  it("announces an incomplete answer when the turn hit the tool-call budget", () => {
    const html = renderToString(
      <AssistantTurnBubble turn={turn({ stopReason: "max_steps" })} />,
    );
    expect(html).toContain("Incomplete answer");
    expect(html).toContain("tool-call budget");
  });

  it("renders it as a system notice, not as model prose", () => {
    // Two things make it un-mistakable for a message: role="status" (assistive
    // tech announces it as a status, not as content) and the notice class,
    // which is bordered/tinted and lives OUTSIDE .chat-bubble.
    const html = renderToString(
      <AssistantTurnBubble turn={turn({ stopReason: "max_steps" })} isLatest />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain("chat-notice");
    // The notice must not be inside the speech bubble — if it were, it would
    // read as something the assistant said.
    const noticeAt = html.indexOf("chat-notice");
    const bubbleEndsAt = html.indexOf("ADOT&#x27;s FY2027 operating budget is");
    expect(noticeAt).toBeGreaterThan(bubbleEndsAt);
  });

  it("stays silent on a normal completed turn", () => {
    const html = renderToString(
      <AssistantTurnBubble turn={turn({ stopReason: "end_turn" })} />,
    );
    expect(html).not.toContain("Incomplete answer");
    expect(html).not.toContain('role="status"');
  });

  it("stays silent while the turn is still streaming", () => {
    // stopReason can be present on a turn the reducer has not closed yet;
    // announcing "incomplete" mid-stream would be a lie that resolves itself.
    const html = renderToString(
      <AssistantTurnBubble
        turn={turn({ stopReason: "max_steps", isComplete: false })}
      />,
    );
    expect(html).not.toContain("Incomplete answer");
  });

  it("keeps the quiet one-liner for ordinary unusual stop reasons", () => {
    const html = renderToString(
      <AssistantTurnBubble turn={turn({ stopReason: "max_tokens" })} />,
    );
    expect(html).toContain("output-length limit");
    // Quiet, not a notice: max_tokens truncates the text visibly mid-sentence
    // and needs no alarm.
    expect(html).not.toContain('role="status"');
  });
});

describe("AssistantTurnBubble — tool blocks", () => {
  it("hides cite tool cards (the chip is their surface) but shows retrieve", () => {
    const html = renderToString(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { kind: "text", uuid: "u1", text: "Answer." },
            {
              kind: "tool",
              toolUseId: "t1",
              toolName: "cite",
              input: { chunk_id: "c1", confidence: "verbatim" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "t2",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "complete",
            },
          ],
        })}
      />,
    );
    expect(html).not.toContain("Cite claim");
    expect(html).toContain("Search corpus");
  });

  it("groups consecutive tool calls but leaves a lone one bare", () => {
    // blocks: text, tool, tool, text, tool  ->  one group of 2, one bare card
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { kind: "text", uuid: "u1", text: "Looking this up." },
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolB",
              toolName: "list_filter_values",
              input: { field: "agency" },
              status: "complete",
            },
            { kind: "text", uuid: "u2", text: "One more check." },
            {
              kind: "tool",
              toolUseId: "toolC",
              toolName: "retrieve",
              input: { query: "General Fund" },
              status: "complete",
            },
          ],
        })}
      />,
    );
    expect(container.querySelectorAll(".chat-tool-group")).toHaveLength(1);
    expect(
      container.querySelectorAll(
        ":not(.chat-tool-group) > .chat-tool:not(.is-inset)",
      ),
    ).toHaveLength(1);
  });

  it("keeps a run intact across an interleaved cite call (cite is invisible to grouping)", () => {
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolCite",
              toolName: "cite",
              input: { chunk_id: "c1", confidence: "verbatim" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolB",
              toolName: "retrieve",
              input: { query: "General Fund" },
              status: "complete",
            },
          ],
        })}
      />,
    );
    // retrieve, cite, retrieve -> one group of two (cite stays hidden and
    // doesn't split the run).
    expect(container.querySelectorAll(".chat-tool-group")).toHaveLength(1);
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(0);
  });
});
