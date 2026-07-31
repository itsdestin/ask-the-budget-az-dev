// Smoke tests for the per-tool ToolBody dispatcher and the pure helpers that
// drive the per-tool views. We test the helpers directly and render the
// dispatcher to a string with representative inputs.
//
// Carried from web/tests/tool-body.test.tsx. The "primitives helpers" block is
// byte-identical. The dispatcher block was rewritten, because seven of its nine
// cases exercised views this port deletes on purpose — Bash, Read, Edit (x2),
// Grep, Glob, Write, WebFetch. Invariant 7 removed every filesystem, shell, and
// web tool from the model-callable surface, so those cases could only be kept by
// keeping views for tools that cannot be called. The cases that still MEAN
// something (raw fallback shows input + output, errors surface through
// ErrorBlock) survive, retargeted at tools that exist, and the five real tools
// each gained coverage.
//
// ONE assertion was dropped rather than retargeted: the error case used to also
// assert `toContain("Failed")`. That chip was rendered by ShellView, which is
// gone, and no surviving view emits it. Failure is still surfaced — ToolCard
// puts it on the status glyph's aria-label and the `is-failed` left border —
// but that lives on the CARD, not in ToolBody, so it is out of this file's
// reach — tool-card.test.tsx picks the coverage back up at that level.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import {
  basename,
  parentDir,
  stripCarriageReturns,
  unescapeForDisplay,
} from "../tool-views/primitives.js";
import ToolBody from "../tool-views/ToolBody.js";
import type { AssistantBlock } from "../chat-types.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

function block(overrides: Partial<ToolBlock>): ToolBlock {
  return {
    kind: "tool",
    toolUseId: "t1",
    toolName: "retrieve",
    input: {},
    status: "complete",
    ...overrides,
  } as ToolBlock;
}

describe("primitives helpers", () => {
  it("basename extracts the file name from windows-style paths", () => {
    expect(basename("C:\\Users\\foo\\bar.ts")).toBe("bar.ts");
  });

  it("basename extracts the file name from posix paths", () => {
    expect(basename("/a/b/c.ts")).toBe("c.ts");
  });

  it("parentDir returns the directory chain", () => {
    expect(parentDir("/a/b/c.ts")).toBe("a/b");
  });

  it("stripCarriageReturns collapses progress lines to final state", () => {
    const input =
      "Updating files: 10%\rUpdating files: 50%\rUpdating files: 100%\nDone.";
    expect(stripCarriageReturns(input)).toBe("Updating files: 100%\nDone.");
  });

  it("unescapeForDisplay reveals literal \\n / \\\" / \\t escapes", () => {
    expect(unescapeForDisplay("foo\\nbar")).toBe("foo\nbar");
    expect(unescapeForDisplay('say \\"hi\\"')).toBe('say "hi"');
    expect(unescapeForDisplay("a\\tb")).toBe("a\tb");
  });
});

describe("ToolBody dispatcher", () => {
  it("renders retrieve chunks with title, page and score", () => {
    const tool = block({
      toolName: "retrieve",
      input: { query: "Aviation Fund", filters: { fiscal_year: 2025 } },
      output: JSON.stringify({
        chunks: [
          {
            chunk_id: "c1",
            doc_id: "d1",
            doc_title: "JLBC Baseline Book",
            publisher: "JLBC",
            fiscal_year: 2025,
            doc_type: "jlbc-baseline",
            section_path: ["Aviation", "Fund balance"],
            page_start: 47,
            page_end: 47,
            text: "The Aviation Fund balance was $12.4 million.",
            score: 3.125,
          },
        ],
        top_score: 3.125,
        retrieval_id: "r1",
        bm25_count: 10,
        dense_count: 10,
        fused_count: 15,
      }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("JLBC Baseline Book");
    expect(html).toContain("p. 47");
    expect(html).toContain("3.125");
    expect(html).toContain("Aviation Fund balance was");
    // Filters are the most decision-shaping input the model chose.
    expect(html).toContain("fiscal_year");
  });

  it("renders retrieve's empty result honestly rather than as a blank card", () => {
    const tool = block({
      toolName: "retrieve",
      input: { query: "nothing" },
      output: JSON.stringify({
        chunks: [],
        top_score: -1e9,
        retrieval_id: "r2",
        bm25_count: 0,
        dense_count: 0,
        fused_count: 0,
      }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("No chunks returned");
  });

  it("renders cite source metadata without echoing the claim on success", () => {
    const tool = block({
      toolName: "cite",
      input: {
        chunk_id: "chunk-abc",
        confidence: "verbatim",
        quote: "$12.4 million",
        claim_span: "The Aviation Fund held $12.4 million",
      },
      output: JSON.stringify({ ok: true, citation_id: "cit-1" }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("chunk-abc");
    expect(html).toContain("Verbatim");
    expect(html).toContain("$12.4 million");
    // The claim is already underlined inline in the answer; a successful cite
    // must not repeat it here.
    expect(html).not.toContain("The Aviation Fund held");
  });

  it("shows the intended claim and the validator's preview when a cite fails", () => {
    const tool = block({
      toolName: "cite",
      input: {
        chunk_id: "chunk-abc",
        confidence: "verbatim",
        claim_span: "The Aviation Fund held $12.4 million",
      },
      output: JSON.stringify({
        ok: false,
        error: "quote not found in chunk text",
        cited_text_preview: "…the Highway Fund held $9.1 million…",
      }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("The Aviation Fund held");
    expect(html).toContain("Highway Fund held");
    expect(html).toContain("quote not found in chunk text");
  });

  it("treats an unreadable cite response as a failure, never a silent success", () => {
    // A non-JSON body has no producer today, but if one ever appears the wrong
    // answer is a green "cite recorded" card. Core Invariant 2 says citations
    // are verified, not merely emitted — an unverifiable ack is a failed one.
    const tool = block({
      toolName: "cite",
      input: {
        chunk_id: "chunk-abc",
        confidence: "verbatim",
        claim_span: "The Aviation Fund held $12.4 million",
      },
      output: "<html>502 Bad Gateway</html>",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("unreadable response");
    expect(html).toContain("Error");
    // And it shows the intended claim, the same as any other failed cite.
    expect(html).toContain("The Aviation Fund held");
  });

  it("renders list_filter_values as a scannable table", () => {
    const tool = block({
      toolName: "list_filter_values",
      input: { field: "agency" },
      output: JSON.stringify({
        field: "agency",
        values: [
          {
            canonical_id: "adot",
            chunk_count: 214,
            sample_doc_title: "ADOT FY2026 Baseline",
          },
        ],
      }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("adot");
    expect(html).toContain("214");
    expect(html).toContain("ADOT FY2026 Baseline");
  });

  it("turns a create_document token into a real download link", () => {
    // This is the UI half of the promise the system prompt makes: the tool
    // returns {download_token, filename}, and GET /api/documents/{token}
    // serves the file. If this assertion fails, the prompt is lying.
    const tool = block({
      toolName: "create_document",
      input: {
        title: "FY2027 ADOT memo",
        body_markdown: "# FY2027 ADOT\n\nBody text.",
        format: "docx",
      },
      output: JSON.stringify({
        ok: true,
        download_token: "abc123",
        filename: "FY2027-ADOT-memo.docx",
      }),
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain('href="/api/documents/abc123"');
    expect(html).toContain("FY2027-ADOT-memo.docx");
  });

  it("falls back to the raw view for cite_batch (input + output sections)", () => {
    // cite_batch has no bespoke view by design: the per-claim chips in the
    // answer are its real surface, and the header already says how many.
    const tool = block({
      toolName: "cite_batch",
      input: { citations: [{ chunk_id: "c1" }] },
      output: '{"results":[{"ok":true}]}',
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html.toLowerCase()).toContain("input");
    expect(html.toLowerCase()).toContain("output");
    expect(html).toContain("&quot;chunk_id&quot;");
  });

  it("falls back to the raw view for unknown tools", () => {
    const tool = block({
      toolName: "MysteryTool",
      input: { foo: "bar" },
      output: "ok",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html.toLowerCase()).toContain("input");
    expect(html.toLowerCase()).toContain("output");
    expect(html).toContain("&quot;foo&quot;");
    expect(html).toContain("ok");
  });

  it("surfaces tool errors via the ErrorBlock", () => {
    const tool = block({
      toolName: "retrieve",
      input: { query: "x" },
      output: "store unreachable",
      isError: true,
      status: "failed",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("Error");
    expect(html).toContain("store unreachable");
  });
});
