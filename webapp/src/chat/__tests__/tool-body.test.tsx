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

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { render, screen } from "@testing-library/react";

import {
  basename,
  ErrorBlock,
  parentDir,
  stripCarriageReturns,
  unescapeForDisplay,
} from "../tool-views/primitives.js";
import ToolBody from "../tool-views/ToolBody.js";
import { downloadUrl } from "../tool-views/CreateDocumentView.js";
import { DOC_TYPE_NAMES } from "../tool-views/RetrieveView.js";
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

describe("downloadUrl", () => {
  it("builds the same-origin path the documents route serves", () => {
    expect(downloadUrl("abc123")).toBe("/api/documents/abc123");
  });

  it("percent-encodes anything that would change the URL's shape", () => {
    // The token is server-generated randomness today, so none of these can
    // occur — but it reaches us over the wire, and a value that crosses a
    // trust boundary gets encoded on principle, not on inspection. A raw "/"
    // would silently address a different route; "#" would truncate the path
    // at the fragment; a space would produce an invalid URL.
    expect(downloadUrl("a/b")).toBe("/api/documents/a%2Fb");
    expect(downloadUrl("a#b")).toBe("/api/documents/a%23b");
    expect(downloadUrl("a b")).toBe("/api/documents/a%20b");
    expect(downloadUrl("../../etc/passwd")).toBe(
      "/api/documents/..%2F..%2Fetc%2Fpasswd",
    );
  });
});

describe("ToolBody dispatcher", () => {
  // RETARGETED (Part 2, Task 3). This used to assert `3.125` and the literal
  // `fiscal_year` were on the page. Both are now deliberately gone — the score
  // is a raw cross-encoder logit that reads as a confidence next to a dollar
  // figure, and a field name tells the analyst about our database rather than
  // their question. The assertions were inverted rather than deleted, so the
  // removal stays pinned instead of merely stopping being checked.
  it("renders retrieve passages with title and page, and never the score", () => {
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
    expect(html).not.toContain("3.125");
    expect(html).toContain("Aviation Fund balance was");
    // Filters are the most decision-shaping input the model chose — said in
    // English now, never as the field name.
    expect(html).not.toContain("fiscal_year");
    expect(html).toContain("FY 2025");
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
    // RETARGETED (Part 2, Task 3): was "No chunks returned (top_score below
    // the refusal threshold or no matches)". "chunk" is not the analyst's
    // word, and naming the threshold explained our machinery instead of the
    // result. The honesty this test exists for is unchanged — an empty search
    // still says so rather than rendering a blank card.
    expect(html).toContain("Found nothing");
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

  it("renders list_filter_values as readable names, not a code/count table", () => {
    // UPDATED for TC20/TC21 (2026-08-16): the view used to print the raw
    // canonical_id and chunk_count as a table — database plumbing, not
    // something an analyst can act on. It now shows only the value's
    // readable name, taken from sample_doc_title.
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
    expect(html).toContain("ADOT FY2026 Baseline");
    expect(html).not.toContain("214");
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

  it("still shows the pending state while create_document is running", () => {
    // No output yet is the one case where "waiting" is the truth.
    const tool = block({
      toolName: "create_document",
      input: { title: "Memo", body_markdown: "Body." },
      status: "running",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("Waiting for the file");
  });

  it("never leaves create_document waiting forever on an unreadable response", () => {
    // The bad outcome here is not a wrong error message, it's a card that sits
    // on "Waiting for the file to be written…" indefinitely: no link, no
    // failure, nothing to act on. Output that arrived but can't be read is a
    // failure, and has to look like one.
    const tool = block({
      toolName: "create_document",
      input: { title: "Memo", body_markdown: "Body." },
      output: "<html>502 Bad Gateway</html>",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("unreadable response");
    expect(html).toContain("Error");
    expect(html).not.toContain("Waiting for the file");
  });

  it("treats a create_document ack with no ok field as a failure", () => {
    // Valid JSON, wrong shape — parses fine, tells us nothing.
    const tool = block({
      toolName: "create_document",
      input: { title: "Memo", body_markdown: "Body." },
      output: '{"detail":"internal server error"}',
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("unreadable response");
    expect(html).not.toContain("Waiting for the file");
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

  it("long errors collapse behind a Show-more instead of a nested scrollbar", () => {
    // Was: a 192px-tall .chat-error-body with its own overflow:auto, scrolling
    // INSIDE the thread's own scroller. Now ErrorBlock renders through the
    // same CollapsibleBlock every other tool body uses, so a long error
    // collapses behind a button instead of a second nested scrollbar.
    const longError = Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n");
    render(<ErrorBlock error={longError} />);
    expect(screen.getByRole("button", { name: /Show 20 more lines/ })).toBeInTheDocument();
  });

  it("renders with the danger variant so a tool error never looks like ordinary output", () => {
    // Pins the class CollapsibleBlock's variant="danger" adds. Without this,
    // a future edit that drops the danger variant would make ErrorBlock
    // render as plain output — Core Invariant 3 territory — and every other
    // test here would still pass, since none of them check the tint.
    const html = renderToString(<ErrorBlock error="store unreachable" />);
    expect(html).toContain("is-danger");
  });
});

// ===== Task 2 additions (TC15, TC20, TC21) — start =====

describe("DocumentGuideView", () => {
  const guideTool = (overrides = {}) =>
    ({
      kind: "tool",
      toolUseId: "g1",
      toolName: "document_guide",
      input: { report_type: "research-memo" },
      status: "complete",
      output: JSON.stringify({
        report_type: "research-memo",
        guide:
          "## Numbers\n\nRound to one decimal place in the document body.\n\n## Shape\n\nIssue, background, analysis, options.",
      }),
      ...overrides,
    }) as ToolBlock;

  it("renders the guide as readable text, not raw JSON", () => {
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toContain("Round to one decimal place");
    // The raw payload's own punctuation must not survive to the screen.
    expect(container.textContent).not.toContain('"report_type"');
    expect(container.textContent).not.toContain("\\n");
  });

  it("names the report type in plain English", () => {
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toContain("research memo");
    expect(container.textContent).not.toContain("research-memo");
  });

  it("names the guidance as advice", () => {
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toMatch(/advice/i);
  });

  it("states that nothing checks the finished document against the guidance", () => {
    // This is the half that matters: the design deliberately never rewrites
    // the model's numbers, because that would mean editing figures an
    // analyst is about to send under their own name. A card that showed
    // house rules without saying so would imply a check that does not
    // exist. Pinned separately from the "advice" wording above so a rewrite
    // that keeps the word "advice" but drops this clause cannot pass.
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toMatch(/nothing checks|not enforced/i);
  });
});

describe("ListFilterValuesView — names, not codes", () => {
  const filterTool = () =>
    ({
      kind: "tool",
      toolUseId: "f1",
      toolName: "list_filter_values",
      input: { field: "agency_canonical_id" },
      status: "complete",
      output: JSON.stringify({
        field: "agency_canonical_id",
        values: [
          { canonical_id: "agency:ahcccs", chunk_count: 4812, sample_doc_title: "AHCCCS — FY 2026 Baseline" },
          { canonical_id: "agency:ade", chunk_count: 3109, sample_doc_title: "Education, Department of — FY 2026 Baseline" },
        ],
      }),
      ...{},
    }) as ToolBlock;

  it("shows no field codes, no slugs and no chunk counts", () => {
    const { container } = render(<ToolBody tool={filterTool()} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("agency_canonical_id");
    expect(text).not.toContain("agency:ahcccs");
    // Unformatted, not "4,812": {v.chunk_count} rendered raw would produce
    // "4812" with no thousands separator, and a comma-formatted assertion
    // never catches that — verified by mutation (see the report).
    expect(text).not.toContain("4812");
    expect(text).not.toMatch(/chunk/i);
  });

  it("shows the agencies themselves", () => {
    const { container } = render(<ToolBody tool={filterTool()} />);
    expect(container.textContent).toContain("AHCCCS");
  });

  it("does not de-duplicate two catalog ids that share a display name", () => {
    // Two catalog ids resolving to the same displayed name — e.g. two rows
    // both reading "Child Safety" — are a real, recorded corpus defect
    // (duplicate agency ids; see STATUS.md's "Corpus identity" sections).
    // Collapsing them here would hide the exact symptom that makes the
    // defect visible, so this must render TWO rows, not one.
    const tool = {
      kind: "tool",
      toolUseId: "f2",
      toolName: "list_filter_values",
      input: { field: "agency_canonical_id" },
      status: "complete",
      output: JSON.stringify({
        field: "agency_canonical_id",
        values: [
          { canonical_id: "agency:cs", chunk_count: 520, sample_doc_title: "Child Safety — FY 2026 Baseline" },
          { canonical_id: "agency:dcs", chunk_count: 1595, sample_doc_title: "Child Safety — FY 2026 Baseline" },
        ],
      }),
    } as ToolBlock;
    const { container } = render(<ToolBody tool={tool} />);
    const chips = container.querySelectorAll(".chat-chip");
    expect(chips).toHaveLength(2);
    expect(Array.from(chips).map((c) => c.textContent)).toEqual([
      "Child Safety",
      "Child Safety",
    ]);
  });
});

// ===== Task 2 additions — end =====
describe("RetrieveView — grouped by document", () => {
  const chunk = (over: Record<string, unknown> = {}) => ({
    chunk_id: "c1", doc_id: "agao-afr-fy2025",
    doc_title: "FY 2025 Annual Financial Report",
    publisher: "agao", fiscal_year: 2025, doc_type: "afr",
    section_path: ["Note 1. — Summary", "Note 3. — Statement of Expenditures"],
    page_start: 162, page_end: null,
    text: "Note 1. — Summary > Note 3. — Statement of Expenditures\nSTATE OF ARIZONA\nFund balance, June 30 2025 … 60,092,781.04",
    score: 1.26, ...over,
  });
  const retrieveTool = (chunks: unknown[]) =>
    ({
      kind: "tool", toolUseId: "r1", toolName: "retrieve",
      input: { query: "Aviation Fund", filters: { doc_type: "afr", fiscal_year: 2025 } },
      status: "complete",
      output: JSON.stringify({
        chunks, top_score: 1.26, retrieval_id: "x",
        bm25_count: 131, dense_count: 100, fused_count: 20,
      }),
    }) as ToolBlock;

  it("shows one block per DOCUMENT, not one per passage", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([
        chunk({ chunk_id: "a", page_start: 162 }),
        chunk({ chunk_id: "b", page_start: 163 }),
        chunk({ chunk_id: "c", page_start: 164 }),
        chunk({ chunk_id: "d", doc_id: "jlbc-baseline-fy2026-tra",
                doc_title: "FY 2026 Baseline — Transportation", publisher: "jlbc",
                fiscal_year: 2026, page_start: 4, section_path: ["Aviation Fund"],
                text: "The Aviation Fund receives revenue from the aircraft licence tax." }),
      ])} />,
    );
    expect(container.querySelectorAll(".chat-doc-group")).toHaveLength(2);
    // Three passages from one document must not print its title three times.
    const titles = [...container.querySelectorAll(".chat-doc-head")]
      .map((n) => n.textContent ?? "")
      .filter((t) => t.includes("Annual Financial Report"));
    expect(titles).toHaveLength(1);
  });

  it("lists every page of a document it grouped", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([
        chunk({ chunk_id: "a", page_start: 162 }),
        chunk({ chunk_id: "b", page_start: 163 }),
      ])} />,
    );
    const pages = container.querySelector(".chat-doc-pages")!.textContent ?? "";
    expect(pages).toContain("162");
    expect(pages).toContain("163");
  });

  it("shows no score, no rank number and no pipeline counters", () => {
    // A raw cross-encoder logit beside a dollar figure invites reading it as a
    // confidence. Budget Documents removed its relevance number for the same
    // reason; order carries the ranking.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/score/i);
    expect(text).not.toMatch(/bm25|dense|fused/i);
    expect(text).not.toMatch(/#1/);
    expect(text).not.toMatch(/chunk/i);
    expect(text).not.toContain("1.26");
  });

  it("does not print the section heading twice", () => {
    // The stored passage text BEGINS with its own heading, and the view also
    // renders that heading, so ~3 lines of every result were the line above it
    // repeated.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const text = container.textContent ?? "";
    const first = text.indexOf("Note 3. — Statement of Expenditures");
    expect(first).toBeGreaterThanOrEqual(0);
    expect(
      text.indexOf("Note 3. — Statement of Expenditures", first + 1),
      "the heading must appear once, not once as a breadcrumb and again inside the passage",
    ).toBe(-1);
  });

  it("reduces the breadcrumb to the leaf heading, not the full ancestor chain", () => {
    // TC18, verbatim: "The breadcrumb itself reduces to the leaf heading;
    // the full ancestor path is noise at this size." The fixture's
    // section_path carries two entries -- the ancestor ("Note 1. — Summary")
    // must not appear in the breadcrumb, and the leaf ("Note 3. — Statement
    // of Expenditures") must.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const path = container.querySelector(".chat-doc-path")!.textContent ?? "";
    expect(path).not.toContain("Note 1");
    expect(path).not.toContain("Summary");
    expect(path).toBe("Note 3. — Statement of Expenditures");
  });

  it("describes the filters in English, in the summary sentence", () => {
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const summary = container.querySelector(".chat-search-summary")!.textContent ?? "";
    expect(summary).not.toContain("doc_type");
    expect(summary).not.toContain("fiscal_year");
    expect(summary).toMatch(/2025/);
  });

  it("translates a filtered doc_type code to its display name, in the summary sentence", () => {
    // Pins that DOC_TYPE_NAMES actually drives the sentence, not just that a
    // map with this shape exists somewhere. `describeFilters` must be doing
    // real work here: `retrieveTool` filters on doc_type "afr", and a
    // passthrough (`docTypeName = (t) => t`) would print "afr" instead of
    // this phrase.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const summary = container.querySelector(".chat-search-summary")!.textContent ?? "";
    expect(summary).toContain(DOC_TYPE_NAMES.afr);
    expect(summary).not.toMatch(/\bafr\b/);
  });

  it("renders an agency or fund filter as an uppercased word, never the raw slug", () => {
    // A slug is a code ("agency:ahcccs"), not a name -- the prefix must be
    // gone and the remainder must read as a word, not a lowercase database
    // value.
    const tool = {
      kind: "tool", toolUseId: "r1", toolName: "retrieve",
      input: {
        query: "AHCCCS spending",
        filters: { agency_canonical_id: "agency:ahcccs", fund_canonical_id: "fund:2005" },
      },
      status: "complete",
      output: JSON.stringify({
        chunks: [chunk()], top_score: 1.26, retrieval_id: "x",
        bm25_count: 1, dense_count: 1, fused_count: 1,
      }),
    } as unknown as ToolBlock;
    const { container } = render(<ToolBody tool={tool} />);
    const summary = container.querySelector(".chat-search-summary")!.textContent ?? "";
    expect(summary).toContain("AHCCCS");
    expect(summary).toContain("2005");
    expect(summary).not.toContain("agency:");
    expect(summary).not.toContain("fund:");
    expect(summary).not.toContain("ahcccs");
  });

  it("says plainly what it found", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([chunk({ chunk_id: "a" }), chunk({ chunk_id: "b", page_start: 163 })])} />,
    );
    expect(container.querySelector(".chat-search-summary")!.textContent)
      .toMatch(/2 passages.*1 document/);
  });

  it("says so when it found nothing", () => {
    const { container } = render(<ToolBody tool={retrieveTool([])} />);
    expect(container.textContent).toMatch(/nothing|no passages/i);
    expect(container.textContent).not.toMatch(/threshold|refusal/i);
  });
});

describe("DOC_TYPE_NAMES — no drift from the registry", () => {
  // The map is a second copy of data/document-types.yaml, a shape that has
  // shipped real bugs twice in this repo: harness/tools.py's _DOC_TYPES
  // silently drifted to 11 entries against a registry of 15, and Upload.tsx
  // hand-maintained a doc_type→publisher map that defeated the registry's
  // own acceptance test. Same extraction approach as
  // webapp/src/pages/Upload.test.tsx's "holds no hardcoded doc_type strings
  // of its own" -- a regex over the raw YAML, no parser dependency needed.
  const registry = readFileSync(
    resolve(process.cwd(), "../data/document-types.yaml"),
    "utf-8",
  );
  const registrySlugs = [...registry.matchAll(/-\s*key:\s*(\S+)/g)].map((m) => m[1]);

  it("extracted a sane number of keys from the registry (extraction sanity check)", () => {
    // If this regex silently matched nothing, every assertion below would be
    // vacuously true.
    expect(registrySlugs.length).toBeGreaterThanOrEqual(15);
    expect(registrySlugs).toContain("afr");
  });

  it("every DOC_TYPE_NAMES key names a real registry type", () => {
    // Deliberately one-directional: the map is display-only, and a NEW
    // registry type appearing with no friendly label yet must not fail this
    // suite -- it degrades legibly to its own code. What must never happen is
    // this map naming a type that does not exist.
    for (const key of Object.keys(DOC_TYPE_NAMES)) {
      expect(registrySlugs, `DOC_TYPE_NAMES has "${key}", which is not in the registry`)
        .toContain(key);
    }
  });
});
