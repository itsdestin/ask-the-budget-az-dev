// Tests for the friendly tool-label + summary helper that drives the ToolCard
// header. Keeping this independent of React lets us pin the user-visible
// naming contract without spinning up a render.
//
// Carried from web/tests/tool-display.test.ts. Two describe-blocks' worth of
// assertions were REMOVED rather than translated, and the removal is the
// point of the change, not collateral:
//
//   - "renames Claude Code core tools" (Bash/Read/Grep/Glob/WebFetch/
//     WebSearch/ToolSearch) and the Read/Edit/WebFetch/TodoWrite summary
//     cases. Plan 4's Invariant 7 removed the entire filesystem/shell/web
//     surface; harness/tools.py exposes five tools and none of those names
//     can reach the UI. A test asserting a friendly label for `Bash` would be
//     pinning a capability the system deliberately does not have.
//   - the `mcp__…` prefix-stripping cases. There is no MCP server, so no code
//     path produces a prefixed name.
//
// Every surviving assertion is unchanged in SUBSTANCE — same inputs, same
// expected values, no matcher weakened — but several were reflowed by the
// formatter when their surrounding block shrank, so this file is not
// byte-identical to the original and shouldn't be diffed as if it were.
// create_document and cite_batch have new coverage.

import { describe, expect, it } from "vitest";

import { toolDisplayLabel, toolHeaderSummary } from "../tool-display.js";

describe("toolDisplayLabel", () => {
  it("renames the budget tools to human-readable labels", () => {
    expect(toolDisplayLabel("retrieve")).toBe("Search corpus");
    expect(toolDisplayLabel("cite")).toBe("Cite claim");
    expect(toolDisplayLabel("cite_batch")).toBe("Cite claims");
    expect(toolDisplayLabel("list_filter_values")).toBe("Browse filters");
    expect(toolDisplayLabel("create_document")).toBe("Write document");
    expect(toolDisplayLabel("document_guide")).toBe("Check style guide");
  });

  it("never leaks a raw snake_case tool name for a registered tool", () => {
    // The generic fallback returns the bare name, which is a legible
    // degradation for a tool nobody has labelled yet — and a defect for one
    // that ships. `document_guide` reached the UI unlabelled once; this
    // asserts the whole registered set, so the next tool added to
    // harness/tools.py fails here rather than in front of an analyst.
    const registered = [
      "retrieve",
      "cite",
      "cite_batch",
      "list_filter_values",
      "create_document",
      "document_guide",
    ];
    for (const name of registered) {
      expect(toolDisplayLabel(name)).not.toBe(name);
      expect(toolDisplayLabel(name)).not.toContain("_");
    }
  });

  it("falls back to the bare name for unknown tools", () => {
    // We don't crash on unrecognized names; we pass them through. Better than
    // a blank header for a tool a future task adds before it adds a label.
    expect(toolDisplayLabel("SomethingNew")).toBe("SomethingNew");
  });
});

describe("toolHeaderSummary", () => {
  it("returns the query for retrieve", () => {
    expect(
      toolHeaderSummary("retrieve", { query: "Aviation Fund balance" }),
    ).toBe("Aviation Fund balance");
  });

  it("returns the confidence (NOT claim_span) for cite", () => {
    // Critical: the claim_span is already underlined inline in the chat
    // answer. Repeating it in the tool-card header is redundant noise. The
    // header shows confidence only; the expanded body shows chunk metadata.
    const summary = toolHeaderSummary("cite", {
      confidence: "verbatim",
      claim_span: "$4,677,100 in FY 2025 for the operating budget",
    });
    expect(summary).toBe("verbatim");
    expect(summary).not.toContain("$4,677,100");
  });

  it("returns the citation count for cite_batch", () => {
    expect(
      toolHeaderSummary("cite_batch", { citations: [{}, {}, {}] }),
    ).toBe("3 citations");
    expect(toolHeaderSummary("cite_batch", { citations: [{}] })).toBe(
      "1 citation",
    );
  });

  it("returns the field name for list_filter_values", () => {
    expect(toolHeaderSummary("list_filter_values", { field: "agency" })).toBe(
      "agency",
    );
  });

  it("returns the title (NOT the body) for create_document", () => {
    // body_markdown is a whole memo; the header is one truncated line.
    const summary = toolHeaderSummary("create_document", {
      title: "FY2027 ADOT operating budget",
      body_markdown: "# FY2027 ADOT\n\nA long memo body…",
    });
    expect(summary).toBe("FY2027 ADOT operating budget");
    expect(summary).not.toContain("long memo body");
  });

  it("returns the report type for document_guide", () => {
    expect(
      toolHeaderSummary("document_guide", { report_type: "comparison" }),
    ).toBe("comparison");
  });

  it("summarizes document_guide with nothing when no type was asked for", () => {
    // The tool defaults to research-memo server-side, but the header reports
    // what the model SENT. Printing "research-memo" here would show a choice
    // the model never made.
    expect(toolHeaderSummary("document_guide", {})).toBeNull();
  });

  it("falls back to first string value for unknown tools", () => {
    expect(toolHeaderSummary("UnknownTool", { arg1: "hello", arg2: 42 })).toBe(
      "hello",
    );
  });

  it("returns null when there's no useful summary", () => {
    expect(toolHeaderSummary("retrieve", {})).toBeNull();
    expect(toolHeaderSummary("cite", { chunk_id: "x" })).toBeNull(); // no confidence
  });
});
