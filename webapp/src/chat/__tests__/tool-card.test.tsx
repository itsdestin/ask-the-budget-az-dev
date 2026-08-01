// Carried from web/tests/tool-card.test.tsx. The two original assertions are
// unchanged; a third was added for create_document, the tool Plan 4 introduced.
//
// The ToolCard block below is new. It picks up the failure-visibility coverage
// that tool-body.test.tsx lost when ShellView (and its "Failed" chip) was
// deleted: failure is still surfaced, just one level up, on the card's status
// glyph and left border rather than inside the body.

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import ToolCard from "../ToolCard.js";
import type { AssistantBlock } from "../chat-types.js";
import { toolGlyph } from "../tool-views/primitives.js";

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

describe("toolGlyph", () => {
  it("returns a distinct glyph element for each known tool", () => {
    const retrieve = renderToString(<svg>{toolGlyph("retrieve")}</svg>);
    const cite = renderToString(<svg>{toolGlyph("cite")}</svg>);
    expect(retrieve).not.toEqual(cite);
  });

  it("falls back for an unknown tool without throwing", () => {
    expect(() =>
      renderToString(<svg>{toolGlyph("mystery_tool")}</svg>),
    ).not.toThrow();
  });

  it("gives create_document its own glyph, not the fallback square", () => {
    const created = renderToString(<svg>{toolGlyph("create_document")}</svg>);
    const fallback = renderToString(<svg>{toolGlyph("mystery_tool")}</svg>);
    expect(created).not.toEqual(fallback);
  });
});

describe("ToolCard status", () => {
  it("marks a failed tool on both the glyph label and the card", () => {
    const html = renderToString(<ToolCard tool={block({ status: "failed" })} />);
    expect(html).toContain('aria-label="failed"');
    expect(html).toContain("is-failed");
  });

  it("does not mark a complete tool as failed", () => {
    const html = renderToString(
      <ToolCard tool={block({ status: "complete" })} />,
    );
    expect(html).toContain('aria-label="complete"');
    expect(html).not.toContain("is-failed");
  });

  it("pulses only while a tool is running", () => {
    const running = renderToString(
      <ToolCard tool={block({ status: "running" })} />,
    );
    expect(running).toContain('aria-label="running"');
    expect(running).toContain("chat-pulse");
    const done = renderToString(<ToolCard tool={block({})} />);
    expect(done).not.toContain("chat-pulse");
  });

  it("shows the friendly label and header summary, collapsed by default", () => {
    const html = renderToString(<ToolCard tool={block({})} />);
    expect(html).toContain("Search corpus");
    expect(html).toContain("Aviation Fund");
    // Collapsed: the body is not rendered until the header is clicked.
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("chat-tool-body");
  });

  it("renders as a compact row: chevron toggle, neutral glyph, danger only on failure", () => {
    const completeTool = block({ status: "complete" });
    const failedTool = block({ status: "failed" });
    const { container, rerender } = render(<ToolCard tool={completeTool} />);
    expect(container.querySelector(".chat-tool-chevron")).not.toBeNull();
    expect(container.querySelector(".chat-tool")!.className).not.toContain(
      "is-failed",
    );
    rerender(<ToolCard tool={failedTool} />);
    expect(container.querySelector(".chat-tool")!.className).toContain(
      "is-failed",
    );
  });

  it("inGroup renders the inset variant", () => {
    const completeTool = block({ status: "complete" });
    const { container } = render(<ToolCard tool={completeTool} inGroup />);
    expect(container.querySelector(".chat-tool")!.className).toContain(
      "is-inset",
    );
  });
});
