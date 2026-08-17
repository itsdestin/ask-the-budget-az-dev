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
import { ToolGlyph } from "../tool-views/primitives.js";

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

describe("ToolGlyph", () => {
  // The shape table (`toolGlyph`, in primitives.tsx) is not exported — only
  // this component is. Render it, the same way both real callers do, rather
  // than importing the table directly.
  it("returns a distinct glyph element for each known tool", () => {
    const retrieve = renderToString(<ToolGlyph tool="retrieve" />);
    const cite = renderToString(<ToolGlyph tool="cite" />);
    expect(retrieve).not.toEqual(cite);
  });

  it("falls back for an unknown tool without throwing", () => {
    expect(() =>
      renderToString(<ToolGlyph tool="mystery_tool" />),
    ).not.toThrow();
  });

  it("gives create_document its own glyph, not the fallback square", () => {
    const created = renderToString(<ToolGlyph tool="create_document" />);
    const fallback = renderToString(<ToolGlyph tool="mystery_tool" />);
    expect(created).not.toEqual(fallback);
  });

  it("omitting label renders aria-hidden instead of an accessible name", () => {
    const html = renderToString(<ToolGlyph tool="retrieve" />);
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toContain("role=\"img\"");
  });

  it("passing label renders role=img with that name, not aria-hidden", () => {
    const html = renderToString(<ToolGlyph tool="retrieve" label="running" />);
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="running"');
    expect(html).not.toContain("aria-hidden");
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

// ===== Task 2 additions (TC15) — start =====

describe("tool glyphs", () => {
  it("gives every tool that reaches an analyst its own icon", () => {
    // `document_guide` had no case and fell through to the generic filled
    // square — and it is the tool that runs right before a memo is written.
    //
    // The fallback shape is computed here, dynamically, from an unregistered
    // tool name rather than pinned as a literal string. A hardcoded string
    // pins the OLD 12x12 fallback's exact markup; primitives.tsx's 24x24
    // rewrite changed that markup's attributes (no more inline
    // fill="currentColor" per shape, rx="2" added), so a literal copy of the
    // old string can never equal ANY current shape and the assertion below
    // would pass even with the document_guide case deleted — verified by
    // deleting it and watching the literal-string version stay green.
    const shapes = new Map<string, string>();
    for (const name of ["retrieve", "list_filter_values", "create_document", "document_guide"]) {
      const { container } = render(
        <ToolCard tool={block({ toolName: name, toolUseId: name })} />,
      );
      const svg = container.querySelector(".chat-tool-glyph")!;
      shapes.set(name, svg.innerHTML);
    }
    const { container: fallbackContainer } = render(
      <ToolCard tool={block({ toolName: "__unregistered_tool__", toolUseId: "u1" })} />,
    );
    const fallbackHtml = fallbackContainer.querySelector(".chat-tool-glyph")!.innerHTML;

    expect(new Set(shapes.values()).size, "each tool needs a distinct glyph").toBe(4);
    for (const [name, html] of shapes) {
      expect(html, `${name} must not be the fallback square`).not.toBe(fallbackHtml);
    }
  });

  it("draws the glyphs as strokes on a 24x24 grid, matching the app's own icons", () => {
    const { container } = render(<ToolCard tool={block({ toolName: "retrieve" })} />);
    const svg = container.querySelector(".chat-tool-glyph")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("fill")).toBe("none");
  });
});

// ===== Task 2 additions — end =====
