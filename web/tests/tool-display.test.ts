// Tests for the friendly tool-label + summary helper that drives
// the ToolCard header. Keeping this independent of React lets us
// pin the user-visible naming contract without spinning up a render.

import { describe, expect, it } from "vitest";

import { toolDisplayLabel, toolHeaderSummary } from "../lib/tool-display";

describe("toolDisplayLabel", () => {
  it("renames Budget MCP tools to human-readable labels", () => {
    expect(toolDisplayLabel("mcp__ask-the-budget-az__retrieve")).toBe(
      "Search corpus",
    );
    expect(toolDisplayLabel("mcp__ask-the-budget-az__cite")).toBe("Cite claim");
    expect(toolDisplayLabel("mcp__ask-the-budget-az__list_filter_values")).toBe(
      "Browse filters",
    );
    // Bare names (after MCP host stripping) work too.
    expect(toolDisplayLabel("retrieve")).toBe("Search corpus");
    expect(toolDisplayLabel("cite")).toBe("Cite claim");
  });

  it("renames Claude Code core tools", () => {
    expect(toolDisplayLabel("Bash")).toBe("Shell");
    expect(toolDisplayLabel("Read")).toBe("Read file");
    expect(toolDisplayLabel("Grep")).toBe("Search files");
    expect(toolDisplayLabel("Glob")).toBe("Find files");
    expect(toolDisplayLabel("WebFetch")).toBe("Fetch URL");
    expect(toolDisplayLabel("WebSearch")).toBe("Web search");
    expect(toolDisplayLabel("ToolSearch")).toBe("Look up tool");
  });

  it("falls back to the bare name for unknown tools", () => {
    // We don't crash on unrecognized names; we strip the MCP prefix
    // (if any) and pass through. Better than showing raw mcp__…__name
    // for tools we haven't specialized yet.
    expect(toolDisplayLabel("mcp__other-server__some_tool")).toBe("some_tool");
    expect(toolDisplayLabel("SomethingNew")).toBe("SomethingNew");
  });
});

describe("toolHeaderSummary", () => {
  it("returns the query for retrieve", () => {
    expect(
      toolHeaderSummary("retrieve", { query: "Aviation Fund balance" }),
    ).toBe("Aviation Fund balance");
    // MCP-namespaced form normalizes the same way.
    expect(
      toolHeaderSummary("mcp__ask-the-budget-az__retrieve", {
        query: "Aviation Fund balance",
      }),
    ).toBe("Aviation Fund balance");
  });

  it("returns the confidence (NOT claim_span) for cite", () => {
    // Critical: the claim_span is already underlined inline in the
    // chat answer. Repeating it in the tool-card header is redundant
    // noise. The header shows confidence only; expanded body shows
    // chunk metadata.
    const summary = toolHeaderSummary("cite", {
      confidence: "verbatim",
      claim_span: "$4,677,100 in FY 2025 for the operating budget",
    });
    expect(summary).toBe("verbatim");
    expect(summary).not.toContain("$4,677,100");
  });

  it("returns the field name for list_filter_values", () => {
    expect(
      toolHeaderSummary("list_filter_values", { field: "agency" }),
    ).toBe("agency");
  });

  it("returns the basename (not full path) for file tools", () => {
    // Long absolute paths push the rest of the header off-screen;
    // the expanded body still has the full path via PathHeader.
    expect(
      toolHeaderSummary("Read", {
        file_path: "/c/Users/desti/ask-the-budget-az-dev/web/components/ChatThread.tsx",
      }),
    ).toBe("ChatThread.tsx");
    expect(
      toolHeaderSummary("Edit", {
        file_path: "C:\\Users\\desti\\foo\\bar.ts",
      }),
    ).toBe("bar.ts");
  });

  it("returns hostname for WebFetch URLs", () => {
    expect(
      toolHeaderSummary("WebFetch", {
        url: "https://www.azleg.gov/budget/2027",
      }),
    ).toBe("www.azleg.gov");
  });

  it("returns todo count for TodoWrite", () => {
    expect(
      toolHeaderSummary("TodoWrite", {
        todos: [{ task: "a" }, { task: "b" }, { task: "c" }],
      }),
    ).toBe("3 todos");
    expect(toolHeaderSummary("TodoWrite", { todos: [{ task: "a" }] })).toBe(
      "1 todo",
    );
  });

  it("falls back to first string value for unknown tools", () => {
    expect(
      toolHeaderSummary("UnknownTool", { arg1: "hello", arg2: 42 }),
    ).toBe("hello");
  });

  it("returns null when there's no useful summary", () => {
    expect(toolHeaderSummary("retrieve", {})).toBeNull();
    expect(toolHeaderSummary("cite", { chunk_id: "x" })).toBeNull(); // no confidence
  });
});
