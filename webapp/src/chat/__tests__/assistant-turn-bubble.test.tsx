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
import { fireEvent, render, screen } from "@testing-library/react";
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
            // FINAL REVIEW — MINOR 3. `cite_batch` is the other half of TC7's
            // suppression and was untested. PAST_ACTION maps both names to
            // "Cited", so the existing assertion below covers it with no new
            // one: suppress only `cite` and this block leaks that word.
            {
              kind: "tool",
              toolUseId: "t1b",
              toolName: "cite_batch",
              input: { citations: [{ chunk_id: "c2" }] },
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
    // "Cite claim" is ToolCard's label and only renders inside an OPENED
    // expansion (see the comment below) — renderToString here renders the
    // card closed, so this assertion is true whether or not cite suppression
    // works at all. Verified by mutation: with `!isCiteToolBlock(block)`
    // changed to `true` in AssistantTurnBubble.tsx, this line stayed green.
    // Kept anyway because it is still a correct (if inert) statement.
    expect(html).not.toContain("Cite claim");
    // The load-bearing check: a suppressed `cite` block never reaches
    // ToolGroup, so its collapsed header never carries the past-tense action
    // label "Cited" (tool-display.ts's PAST_ACTION["cite"]). Under the
    // same mutation above, this assertion goes red — proven by running it.
    expect(html).not.toContain("Cited");
    // Task 5 removed the bare-ToolCard special case for a lone tool call, so
    // a single retrieve now renders through ToolGroup's collapsed header —
    // action label + the call's own summary — rather than ToolCard's
    // "Search corpus" label, which only appears inside the (here, unopened)
    // expansion.
    expect(html).toContain("Searched");
    expect(html).toContain("Aviation Fund");
  });

  it("attaches each run of tool calls to the bubble that FOLLOWS it", () => {
    // blocks: text, tool, tool, text, tool
    //   -> bubble u1 with no card (nothing preceded it)
    //   -> bubble u2 carrying the run of 2
    //   -> a standalone card for the trailing call, which has no bubble after it
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

    const bubbles = [...container.querySelectorAll(".chat-bubble")];
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0]!.querySelector(".chat-tool-group")).toBeNull();
    expect(bubbles[1]!.querySelector(".chat-tool-group")).not.toBeNull();

    // TC6 — the trailing run has nowhere to nest and must still be visible.
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(1);
  });

  it("never hoists a run to the top of the turn", () => {
    // Two rounds of work. Reading order is the whole point of TC1: the card
    // sits above the text it produced, not above text that came before it.
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "FY2025" },
              status: "complete",
            },
            { kind: "text", uuid: "u1", text: "The FY 2025 figure." },
            {
              kind: "tool",
              toolUseId: "toolB",
              toolName: "retrieve",
              input: { query: "FY2024" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolC",
              toolName: "retrieve",
              input: { query: "FY2024 detail" },
              status: "complete",
            },
            { kind: "text", uuid: "u2", text: "And the year before." },
          ],
        })}
      />,
    );

    const bubbles = [...container.querySelectorAll(".chat-bubble")];
    expect(bubbles).toHaveLength(2);
    // One card in each bubble — not two in the first and none in the second.
    for (const bubble of bubbles) {
      expect(bubble.querySelectorAll(".chat-tool-group")).toHaveLength(1);
    }
    // Which bubble got WHICH run is the property under test, so the two
    // assertions have to tell them apart. Bubble 0's run is one search and
    // bubble 1's is two, and only a multi-call run says "and N more" — so this
    // fails if the runs are swapped, if both land in one bubble, or if the
    // second bubble's run is dropped.
    //
    // Updated 2026-08-16 from `Searched ×2`, the Part 1 header format, which
    // Part 2 (TC13) replaced with a sentence. No lane owned this file, so the
    // merge is where it surfaced.
    expect(bubbles[0]!.textContent).toContain("Searched for");
    expect(bubbles[0]!.textContent).not.toContain("and 1 more");
    expect(bubbles[1]!.textContent).toContain("and 1 more");
    // Nothing floats between or above the bubbles.
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(0);
  });

  it("renders a run standalone while no answer text exists yet", () => {
    // Mid-search: there is no text block to nest inside, and withholding the
    // card would leave the analyst watching a blank screen through a
    // multi-second search (TC6).
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "running",
            },
          ],
        })}
      />,
    );
    expect(container.querySelectorAll(".chat-bubble")).toHaveLength(0);
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(1);
    expect(container.textContent).toContain("Searching");
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

// 2026-08-22 — closes the STATUS.md open item: a card expanded mid-search
// used to snap shut the instant the answer arrived, because TC1 moves the
// SAME run from a `.chat-turn` child (standalone, TC6) to a `.chat-bubble`
// child once text exists. The parent element genuinely changes, so React
// unmounts/remounts ToolGroup and its local `useState(false)` resets. See
// docs/superpowers/specs/2026-08-22-tool-card-open-state-design.md.
describe("AssistantTurnBubble — open state survives the move into the bubble", () => {
  it("keeps an expanded card open when the answer arrives and the card moves into the bubble", () => {
    const running = {
      kind: "tool",
      toolUseId: "toolA",
      toolName: "retrieve",
      input: { query: "Aviation Fund" },
      status: "running",
    } as const;
    const { container, rerender } = render(
      <AssistantTurnBubble turn={turn({ isComplete: false, blocks: [running] })} />,
    );
    // The real header sentence for a running single-tool retrieve run, read
    // from tool-display.ts::toolHeaderSentence — verb "Searching", rest
    // ` for “Aviation Fund”…` — rather than a guessed /Searching/ pattern.
    fireEvent.click(screen.getByRole("button", { name: /Searching for “Aviation Fund”…/ }));
    expect(container.querySelector(".chat-tool-group-expansion")).not.toBeNull();

    rerender(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { ...running, status: "complete" },
            { kind: "text", uuid: "u1", text: "The Aviation Fund total is…" },
          ],
        })}
      />,
    );
    const moved = container.querySelector(".chat-bubble .chat-tool-group");
    expect(moved).not.toBeNull(); // it DID move (TC1 intact)
    expect(moved!.querySelector(".chat-tool-group-expansion")).not.toBeNull(); // FAILS today — the move resets `open`
  });

  it("keeps an expanded in-group ToolCard open across the same move (n>=2)", () => {
    const runningA = {
      kind: "tool",
      toolUseId: "toolA",
      toolName: "retrieve",
      input: { query: "Aviation Fund" },
      status: "running",
    } as const;
    const toolB = {
      kind: "tool",
      toolUseId: "toolB",
      toolName: "list_filter_values",
      input: { field: "agency" },
      status: "complete",
    } as const;
    const { container, rerender } = render(
      <AssistantTurnBubble
        turn={turn({ isComplete: false, blocks: [runningA, toolB] })}
      />,
    );
    // Open the group first — the n>=2 branch only renders child ToolCards
    // once the group itself is expanded.
    fireEvent.click(screen.getByRole("button", { name: /Searching for “Aviation Fund”/ }));
    // Then open the first child ToolCard inside the expansion.
    const childHeaders = container.querySelectorAll(
      ".chat-tool-group-body > .chat-tool > .chat-tool-head",
    );
    expect(childHeaders).toHaveLength(2);
    fireEvent.click(childHeaders[0]!);
    expect(
      container.querySelectorAll(".chat-tool-group-body > .chat-tool")[0]!
        .querySelector(".chat-tool-body"),
    ).not.toBeNull();

    rerender(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { ...runningA, status: "complete" },
            toolB,
            { kind: "text", uuid: "u1", text: "Both checks are done." },
          ],
        })}
      />,
    );
    const movedGroup = container.querySelector(".chat-bubble .chat-tool-group");
    expect(movedGroup).not.toBeNull();
    // The group itself is still expanded…
    expect(movedGroup!.querySelector(".chat-tool-group-expansion")).not.toBeNull();
    // …and the first child ToolCard is still expanded too.
    const movedChildren = movedGroup!.querySelectorAll(
      ".chat-tool-group-body > .chat-tool",
    );
    expect(movedChildren).toHaveLength(2);
    expect(movedChildren[0]!.querySelector(".chat-tool-body")).not.toBeNull();
  });

  it("still toggles closed on click after the move", () => {
    const running = {
      kind: "tool",
      toolUseId: "toolA",
      toolName: "retrieve",
      input: { query: "Aviation Fund" },
      status: "running",
    } as const;
    const { container, rerender } = render(
      <AssistantTurnBubble turn={turn({ isComplete: false, blocks: [running] })} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Searching for “Aviation Fund”…/ }));
    expect(container.querySelector(".chat-tool-group-expansion")).not.toBeNull();

    rerender(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { ...running, status: "complete" },
            { kind: "text", uuid: "u1", text: "The Aviation Fund total is…" },
          ],
        })}
      />,
    );
    const movedHeader = container.querySelector(
      ".chat-bubble .chat-tool-group .chat-tool-head",
    )!;
    // It survived the move (open) — clicking it again must still close it;
    // the hoisted state must remain a live toggle, not a one-way sticky flag.
    fireEvent.click(movedHeader);
    expect(
      container.querySelector(".chat-bubble .chat-tool-group-expansion"),
    ).toBeNull();
  });
});
