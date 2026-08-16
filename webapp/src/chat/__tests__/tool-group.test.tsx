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
const retrieveFailed = block({
  toolUseId: "t5",
  toolName: "retrieve",
  status: "failed",
});
const retrieveRunning = block({
  toolUseId: "t4",
  toolName: "retrieve",
  status: "running",
});

describe("ToolGroup", () => {
  it("coalesces a multi-call run into one past-tense summary row", () => {
    render(
      <ToolGroup
        tools={[retrieveComplete, retrieveComplete2, listFiltersComplete]}
      />,
    );
    const head = screen.getByRole("button", {
      name: /Searched ×2, browsed filters/,
    });
    expect(head).toHaveTextContent("Searched ×2, browsed filters");
  });

  it("renders a run of ONE, carrying that call's own summary", () => {
    render(<ToolGroup tools={[retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searched/ });
    expect(head).toHaveTextContent("Searched");
    // The query is the single most useful thing on the row and the bare
    // ToolCard this replaced showed it. Losing it would be a regression.
    expect(head).toHaveTextContent("Aviation Fund");
  });

  it("expands a run of ONE straight to that call's body — one click, not two", () => {
    // The bare ToolCard this replaced opened its body on a single click.
    // Wrapping the sole call in a child row would silently make every source
    // check a two-click operation, and every count-based assertion would
    // still pass.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(screen.getByRole("button", { name: /Searched/ }));
    expect(container.querySelector(".chat-tool-body")).not.toBeNull();
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(0);
  });

  it("expands a multi-call run to inset child rows", () => {
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Searched, browsed filters/ }),
    );
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(2);
  });

  it("puts every expansion inside one capped container", () => {
    // TC8's cap is a single CSS rule on this element. If a future edit renders
    // the body outside it, the cap silently stops applying and a 15-passage
    // expansion buries the answer again.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Searched, browsed filters/ }),
    );
    const expansion = container.querySelector(".chat-tool-group-expansion")!;
    expect(expansion, "the expansion must have its capped wrapper").not.toBeNull();
    expect(expansion.querySelector(".chat-tool-group-body")).not.toBeNull();
  });
});

describe("ToolGroup tense and progress", () => {
  it("uses the present participle while any call is still in flight", () => {
    // "Searched" over a call that has not finished is a false statement about
    // a live process (TC4).
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searching/ });
    expect(head).toHaveTextContent("Searching ×2");
    expect(head).not.toHaveTextContent("Searched");
  });

  it("reports progress while a multi-call run is in flight", () => {
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    expect(
      screen.getByRole("button", { name: /Searching/ }),
    ).toHaveTextContent("1 of 2 done");
  });

  it("shows NO detail line once a multi-call run has settled", () => {
    // "all complete" is deleted, not kept. Asserting it while suppressing
    // "1 failed" would make the card claim a clean run it cannot vouch for;
    // silence claims nothing (TC3).
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveComplete2]} />,
    );
    expect(container.querySelector(".chat-tool-summary")).toBeNull();
    expect(container.textContent).not.toContain("all complete");
  });

  it("still shows the query on a settled run of one", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    expect(container.querySelector(".chat-tool-summary")).not.toBeNull();
  });

  it("wraps a single call's expansion in the capped container too", () => {
    // The height cap is one CSS rule on .chat-tool-group-expansion. Dropping
    // the wrapper only in the n = 1 branch would pass every other test here,
    // including the one-click test, which looks for .chat-tool-body and not
    // for what contains it.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(screen.getByRole("button", { name: /Searched/ }));
    const expansion = container.querySelector(".chat-tool-group-expansion")!;
    expect(expansion).not.toBeNull();
    expect(expansion.querySelector(".chat-tool-body")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2026-08-16 — TC9. The collapsed card carries NO failure signal at all.
//
// This INVERTS what this file used to assert. The old tests pinned a red group
// header and a "1 failed" count, and carefully scoped the tint so it could not
// reach a successful child. All of that is gone, because the signal is not
// actionable: the model retries a failed call itself, so a red row usually
// marks a transient step in work that then succeeded, and alarming an analyst
// about a self-correcting event spends the trust every other warning needs.
//
// DEMOTED, NOT DELETED — the second test below is the half that matters. A
// suppression that also drops the call on the floor would satisfy the first
// test perfectly and destroy the audit trail, which is the direction this is
// most at risk of drifting in.
// ---------------------------------------------------------------------------

describe("ToolGroup failure handling", () => {
  it("looks identical to an all-successful run when collapsed", () => {
    const { container: withFailure } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    const head = withFailure.querySelector(".chat-tool-head")!;

    expect(withFailure.querySelector(".is-failed")).toBeNull();
    expect(withFailure.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
  });

  it("still records the failure inside the expansion", () => {
    // The audit trail is intact for anyone who opens the card; it simply stops
    // shouting at people who did not ask.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);

    const failedRows = container.querySelectorAll(
      ".chat-tool-group-body .chat-tool.is-failed",
    );
    expect(
      failedRows,
      "the failed call must still be visible once expanded",
    ).toHaveLength(1);
    expect(
      container.querySelectorAll(".chat-tool-group-body .chat-tool"),
    ).toHaveLength(2);
  });
});
