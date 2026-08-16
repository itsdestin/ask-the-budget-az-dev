// ToolGroup collapses a run of consecutive tool calls into one row. Fixtures
// mirror tool-card.test.tsx's `block()` helper.
//
// fireEvent, not userEvent — this webapp has no @testing-library/user-event
// dependency; every other test file in the suite drives clicks via fireEvent
// (see citation-chip.test.tsx / citation-bus.test.tsx).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

// ---------------------------------------------------------------------------
// FINAL REVIEW — IMPORTANT 3: a failed group must not redden its successful
// children
// ---------------------------------------------------------------------------
//
// The rule was written as a DESCENDANT selector
// (`.chat-tool-group.is-failed .chat-tool-label`), so expanding a group in
// which ONE call failed painted the labels of every SUCCESSFUL child red too.
// That is the mirror image of the failed-citation-hover bug fixed elsewhere on
// this branch — there a failure was dressed as a success, here a success is
// dressed as a failure — and it misinforms the analyst about which call
// actually failed.
//
// jsdom applies no stylesheet, so this cannot be asserted with
// getComputedStyle. Instead it reads the real selector out of app.css and asks
// each rendered label whether it MATCHES — which is precisely the question the
// browser's cascade would ask, with no reimplementation of the cascade.

/** The selector app.css uses to paint a failed group's label text red. */
function failedGroupLabelSelector(): string {
  const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf-8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const match = css.match(
    /(\.chat-tool-group\.is-failed[^{}]*?\.chat-tool-label)\s*\{[^}]*color:\s*var\(--chat-danger\)/,
  );
  expect(
    match,
    "app.css must still tint a failed group's own label — this test would be vacuous otherwise",
  ).not.toBeNull();
  return match![1].trim();
}

describe("ToolGroup danger scoping", () => {
  it("tints only its own header row, never a successful child's label", () => {
    const selector = failedGroupLabelSelector();
    const { container } = render(
      // Mixed run: the first call succeeded, the second failed. The group is
      // is-failed (one failure is a failure), but only ONE row really failed.
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /2 tool calls/ }));

    const group = container.querySelector(".chat-tool-group.is-failed")!;
    expect(group, "a run containing a failure marks the group").not.toBeNull();

    const groupLabel = group.querySelector(
      ".chat-tool-head > .chat-tool-label",
    )!;
    expect(
      groupLabel.matches(selector),
      "the group's own summary label keeps the danger tint",
    ).toBe(true);

    const childLabels = [
      ...container.querySelectorAll(".chat-tool-group-body .chat-tool-label"),
    ];
    expect(childLabels.length).toBeGreaterThan(0);
    for (const label of childLabels) {
      const row = label.closest(".chat-tool")!;
      if (row.classList.contains("is-failed")) continue;
      expect(
        label.matches(selector),
        "a SUCCESSFUL child row's label must carry no danger colour",
      ).toBe(false);
    }
  });
});
