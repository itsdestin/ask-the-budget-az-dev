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

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  coalesceActionLabels,
  FILTER_FIELD_NAMES,
  toolActionLabel,
  toolDisplayLabel,
  toolHeaderSentence,
  toolHeaderSummary,
} from "../tool-display.js";
import { FIELD_LABEL } from "../tool-views/ListFilterValuesView.js";

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

describe("toolActionLabel", () => {
  it("names what happened, in the tense the run is actually in", () => {
    expect(toolActionLabel("retrieve", "past")).toBe("Searched");
    expect(toolActionLabel("retrieve", "present")).toBe("Searching");
    expect(toolActionLabel("create_document", "past")).toBe("Wrote a document");
    expect(toolActionLabel("create_document", "present")).toBe(
      "Writing a document",
    );
    expect(toolActionLabel("list_filter_values", "past")).toBe(
      "Browsed filters",
    );
    expect(toolActionLabel("document_guide", "past")).toBe(
      "Checked the style guide",
    );
  });

  it("never leaks a raw snake_case tool name for a registered tool", () => {
    // Same guard as toolDisplayLabel's, for the same reason: `document_guide`
    // reached the UI unlabelled once. Asserting the whole registered set means
    // the next tool added to harness/tools.py fails HERE rather than in front
    // of an analyst.
    const registered = [
      "retrieve",
      "cite",
      "cite_batch",
      "list_filter_values",
      "create_document",
      "document_guide",
    ];
    for (const name of registered) {
      for (const tense of ["past", "present"] as const) {
        expect(toolActionLabel(name, tense)).not.toBe(name);
        expect(toolActionLabel(name, tense)).not.toContain("_");
      }
    }
  });

  it("falls back to the bare name for an unknown tool", () => {
    expect(toolActionLabel("some_future_tool", "past")).toBe("some_future_tool");
  });
});

describe("coalesceActionLabels", () => {
  const t = (toolName: string) => ({ toolName });

  it("collapses an adjacent same-label run into a count", () => {
    expect(
      coalesceActionLabels([t("retrieve"), t("retrieve")], "past"),
    ).toBe("Searched ×2");
  });

  it("keeps only the first phrase capitalised", () => {
    // "Searched ×3, wrote a document" reads as one sentence fragment.
    // "Searched ×3, Wrote a document" reads as two headings jammed together.
    expect(
      coalesceActionLabels(
        [t("retrieve"), t("retrieve"), t("retrieve"), t("create_document")],
        "past",
      ),
    ).toBe("Searched ×3, wrote a document");
  });

  it("does not merge non-adjacent same-label runs", () => {
    // Order is the model's actual sequence of work; collapsing across a gap
    // would claim it did three searches back to back when it did not.
    expect(
      coalesceActionLabels(
        [t("retrieve"), t("create_document"), t("retrieve")],
        "past",
      ),
    ).toBe("Searched, wrote a document, searched");
  });

  it("carries the tense through to every phrase", () => {
    expect(
      coalesceActionLabels([t("retrieve"), t("create_document")], "present"),
    ).toBe("Searching, writing a document");
  });

  it("returns an empty string for an empty run", () => {
    expect(coalesceActionLabels([], "past")).toBe("");
  });
});

describe("toolHeaderSentence", () => {
  const search = (query: string) => ({ toolName: "retrieve", input: { query } });

  it("reads as a sentence for a single search", () => {
    const s = toolHeaderSentence([search("State Aviation Fund balance FY2025")], "past");
    expect(s.verb).toBe("Searched");
    expect(s.rest).toBe(' for “State Aviation Fund balance FY2025”');
  });

  it("keeps the first query visible however many searches ran", () => {
    // The rejected alternative led with the count, which pushes the one
    // informative part of the row toward the ellipsis.
    const s = toolHeaderSentence(
      [search("State Aviation Fund balance FY2025"), search("b"), search("c")],
      "past",
    );
    expect(s.verb).toBe("Searched");
    expect(s.rest).toBe(' for “State Aviation Fund balance FY2025” and 2 more');
  });

  it("uses the present participle while a call is in flight", () => {
    const s = toolHeaderSentence([search("aviation fund")], "present");
    expect(s.verb).toBe("Searching");
    expect(s.rest).toBe(' for “aviation fund”…');
  });

  it("names each tool with its own preposition", () => {
    expect(
      toolHeaderSentence([{ toolName: "create_document", input: { title: "AHCCCS FY24-26" } }], "past"),
    ).toEqual({ verb: "Wrote", rest: ' the document “AHCCCS FY24-26”' });
    expect(
      toolHeaderSentence([{ toolName: "document_guide", input: { report_type: "research-memo" } }], "past"),
    ).toEqual({ verb: "Checked", rest: " the house style for a research memo" });
    expect(
      toolHeaderSentence([{ toolName: "list_filter_values", input: { field: "agency" } }], "past"),
    ).toEqual({ verb: "Checked", rest: " which agencies the corpus covers" });
  });

  it("appends a second kind of work rather than dropping the query", () => {
    const s = toolHeaderSentence(
      [search("AHCCCS General Fund FY2026"), search("b"), search("c"),
       { toolName: "create_document", input: { title: "Memo" } }],
      "past",
    );
    expect(s.rest).toBe(' for “AHCCCS General Fund FY2026” and 2 more, then wrote a document');
  });

  it("never leaks a raw field name or a corpus name", () => {
    const s = toolHeaderSentence(
      [{ toolName: "list_filter_values", input: { field: "agency" } }],
      "past",
    );
    const whole = s.verb + s.rest;
    expect(whole).not.toMatch(/canonical_id|doc_type|Budget Documents|Fiscal Notes/);
  });

  it("keeps the count for retrieve when the leading call has no query", () => {
    // Regression guard for the "and N more" count silently vanishing when the
    // leading call's summary is empty. retrieve's no-summary branch was
    // always correct; pinned here so it can't be broken while fixing the two
    // branches below.
    const s = toolHeaderSentence(
      [{ toolName: "retrieve", input: {} }, { toolName: "retrieve", input: {} }],
      "past",
    );
    expect(s.verb).toBe("Searched");
    expect(s.rest).toBe(" and 1 more");
  });

  it("keeps the count for create_document when the leading call has no title", () => {
    // The no-summary fallback used to omit ${more} entirely, so a run of two
    // untitled create_document calls rendered as "Wrote a document" — a
    // silent undercount of real work.
    const s = toolHeaderSentence(
      [
        { toolName: "create_document", input: {} },
        { toolName: "create_document", input: {} },
      ],
      "past",
    );
    expect(s.verb).toBe("Wrote");
    expect(s.rest).toBe(" a document and 1 more");
  });

  it("keeps the count for document_guide across multiple calls", () => {
    // document_guide's branch never interpolated ${more} at all, so two
    // calls rendered identically to one: "Checked the house style for a
    // document".
    const s = toolHeaderSentence(
      [
        { toolName: "document_guide", input: {} },
        { toolName: "document_guide", input: {} },
      ],
      "past",
    );
    expect(s.verb).toBe("Checked");
    expect(s.rest).toBe(" the house style for a document and 1 more");
  });

  it("keeps the count for list_filter_values across multiple calls", () => {
    // The last branch that never interpolated ${more}: three filter checks
    // rendered identically to one, silently undercounting real work. 3433779
    // fixed create_document and document_guide and missed this one, and its
    // three regression tests skipped it.
    const s = toolHeaderSentence(
      [
        { toolName: "list_filter_values", input: { field: "agency" } },
        { toolName: "list_filter_values", input: { field: "fund" } },
        { toolName: "list_filter_values", input: { field: "doc_type" } },
      ],
      "past",
    );
    expect(s.verb).toBe("Checked");
    expect(s.rest).toBe(" which agencies the corpus covers and 2 more");
  });

  it("degrades legibly for an unregistered tool", () => {
    const s = toolHeaderSentence([{ toolName: "some_future_tool", input: { thing: "x" } }], "past");
    expect(s.verb).toBe("some_future_tool");
    expect(s.rest).toContain("x");
  });

  it("returns an empty sentence for an empty run", () => {
    expect(toolHeaderSentence([], "past")).toEqual({ verb: "", rest: "" });
  });
});

describe("filter-field copy tables — no drift from harness/tools.py", () => {
  // 🔴 THE GUARD THIS DISPATCH EXISTS FOR. Both copy tables were keyed on
  // `retrieve`'s FILTER vocabulary (`agency_canonical_id`, `fiscal_year`) —
  // values `list_filter_values` can never emit — and neither had `fund`. So
  // the real input "agency" hit both defaults: the header read "Checked which
  // values the corpus covers" (TC14 requires "agencies") and the body read
  // "What the corpus covers" (TC21 requires "Agencies the corpus covers").
  //
  // It shipped green through three reviews because every fixture pinned the
  // impossible input too. A test that supplies its own vocabulary cannot
  // catch a vocabulary mismatch, so this one reads the vocabulary from
  // harness/tools.py — the file that defines and enforces it. Same approach
  // as tool-body.test.tsx's DOC_TYPE_NAMES registry check.
  const toolsPy = readFileSync(resolve(process.cwd(), "../harness/tools.py"), "utf-8");

  // The schema enum the model is constrained by.
  const schemaBlock = toolsPy.slice(toolsPy.indexOf("_LIST_FILTER_VALUES_SCHEMA"));
  const schemaEnum = [
    ...(schemaBlock.match(/"enum":\s*\[([^\]]*)\]/)?.[1] ?? "").matchAll(/"([^"]+)"/g),
  ].map((m) => m[1]!);

  // The runtime check that actually raises, in _list_filter_values.
  const runtimeEnum = [
    ...(toolsPy.match(/if field not in \(([^)]*)\)/)?.[1] ?? "").matchAll(/"([^"]+)"/g),
  ].map((m) => m[1]!);

  const sorted = (xs: string[]) => [...xs].sort();

  it("extracted a sane field list from harness/tools.py (extraction sanity check)", () => {
    // Without this, a regex that silently matched nothing would make every
    // assertion below vacuously true — the shape that let the original defect
    // through.
    expect(schemaEnum).toContain("agency");
    expect(schemaEnum.length).toBe(4);
    expect(sorted(runtimeEnum)).toEqual(sorted(schemaEnum));
  });

  it("tool-display.ts's header table names exactly the tool's fields", () => {
    expect(sorted(Object.keys(FILTER_FIELD_NAMES))).toEqual(sorted(schemaEnum));
  });

  it("the view's body-label table names exactly the tool's fields", () => {
    expect(sorted(Object.keys(FIELD_LABEL))).toEqual(sorted(schemaEnum));
  });

  it("no accepted field falls through to either table's default", () => {
    // The key-set assertions above would still pass if a table were keyed
    // correctly and consulted wrongly, so this checks the rendered output.
    for (const field of schemaEnum) {
      const s = toolHeaderSentence([{ toolName: "list_filter_values", input: { field } }], "past");
      expect(s.rest, `header falls through to "values" for field "${field}"`)
        .not.toContain("which values the corpus covers");
      expect(FIELD_LABEL[field], `no body label for field "${field}"`).toBeTruthy();
    }
  });
});
