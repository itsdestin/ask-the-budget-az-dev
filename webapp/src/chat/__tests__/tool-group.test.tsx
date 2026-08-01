// ToolGroup collapses a run of consecutive tool calls into one row. Fixtures
// mirror tool-card.test.tsx's `block()` helper.
//
// fireEvent, not userEvent — this webapp has no @testing-library/user-event
// dependency; every other test file in the suite drives clicks via fireEvent
// (see citation-chip.test.tsx / citation-bus.test.tsx).

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ToolGroup from "../ToolGroup.js";
import type { AssistantBlock } from "../chat-types.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

function block(overrides: Partial<ToolBlock>): ToolBlock {
  return {
    kind: "tool",
    toolUseId: "t1",
    toolName: "retrieve",
    input: { query: "Aviation Fund" },
    status: "complete",
    ...overrides,
  } as ToolBlock;
}

const retrieveComplete = block({ toolUseId: "t1", toolName: "retrieve" });
const retrieveComplete2 = block({ toolUseId: "t2", toolName: "retrieve" });
const listFiltersComplete = block({
  toolUseId: "t3",
  toolName: "list_filter_values",
  input: { field: "agency" },
});
const retrieveRunning = block({
  toolUseId: "t4",
  toolName: "retrieve",
  status: "running",
});
const retrieveFailed = block({
  toolUseId: "t5",
  toolName: "retrieve",
  status: "failed",
});

describe("ToolGroup", () => {
  it("coalesces names and states into one summary row", () => {
    render(
      <ToolGroup
        tools={[retrieveComplete, retrieveComplete2, listFiltersComplete]}
      />,
    );
    const head = screen.getByRole("button", { name: /3 tool calls/ });
    expect(head).toHaveTextContent("Search corpus ×2, Browse filters");
    expect(head).toHaveTextContent("all complete");
  });

  it("reports running and failed counts while in flight", () => {
    render(<ToolGroup tools={[retrieveRunning, retrieveFailed]} />);
    const head = screen.getByRole("button", { name: /2 tool calls/ });
    expect(head).toHaveTextContent("1 failed");
  });

  it("expands to inset child rows", () => {
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /2 tool calls/ }));
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(2);
  });
});
