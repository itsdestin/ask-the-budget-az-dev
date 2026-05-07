// Pure unit tests for citation extraction. Builds a synthetic
// AssistantTurn with a retrieve() then cite() pair and verifies the
// extracted Citation list mirrors the cite() inputs and resolves
// chunk metadata against the matching retrieve() result.

import { describe, expect, it } from "vitest";

import {
  extractCitations,
  formatCopyCitation,
  type Citation,
} from "../lib/citation-extract.js";
import type { AssistantTurn } from "../state/chat-types.js";

function turnWithBlocks(blocks: AssistantTurn["blocks"]): AssistantTurn {
  return {
    kind: "assistant",
    id: "t1",
    blocks,
    isComplete: true,
    timestamp: 0,
  };
}

const RETRIEVE_OUTPUT_OK = JSON.stringify({
  chunks: [
    {
      chunk_id: "doc-A:p47:s1",
      doc_id: "doc-A",
      doc_title: "JLBC Baseline Book",
      publisher: "JLBC",
      fiscal_year: 2024,
      doc_type: "jlbc-baseline-book",
      section_path: ["Aviation Fund"],
      page_start: 47,
      page_end: 47,
      bbox: [10, 20, 100, 40],
      text: "Aviation Fund balance was $123M as of June 30, 2024.",
      score: 0.91,
    },
  ],
  top_score: 0.91,
  retrieval_id: "r-1",
  bm25_count: 14,
  dense_count: 14,
  fused_count: 20,
});

describe("extractCitations", () => {
  it("returns [] for a turn with no cite() tool blocks", () => {
    const turn = turnWithBlocks([
      { kind: "text", uuid: "u1", text: "hello world" },
    ]);
    expect(extractCitations(turn)).toEqual([]);
  });

  it("pulls cite() inputs into Citation records in order", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "Aviation Fund" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "Balance was $123M." },
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 12,
          span_end: 18,
          confidence: "verbatim",
          claim_span: "$123M.",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-uuid-1" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    const c = citations[0]!;
    expect(c.index).toBe(1);
    expect(c.chunkId).toBe("doc-A:p47:s1");
    expect(c.confidence).toBe("verbatim");
    expect(c.claimSpan).toBe("$123M.");
    expect(c.citationId).toBe("cit-uuid-1");
    expect(c.resolved?.docTitle).toBe("JLBC Baseline Book");
    expect(c.resolved?.docId).toBe("doc-A");
    expect(c.resolved?.pageStart).toBe(47);
    expect(c.resolved?.fiscalYear).toBe(2024);
    expect(c.resolved?.bbox).toEqual([10, 20, 100, 40]);
  });

  it("normalizes a missing bbox to null (e.g. DOCX chunks)", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: JSON.stringify({
          chunks: [
            {
              chunk_id: "bill-A:para12",
              doc_id: "bill-A",
              doc_title: "SB1735",
              publisher: "legislature",
              fiscal_year: 2025,
              doc_type: "budget-bill",
              section_path: [],
              page_start: null,
              page_end: null,
              bbox: null,
              text: "Section 12 ...",
              score: 0.7,
            },
          ],
          top_score: 0.7,
          retrieval_id: "r-2",
          bm25_count: 1,
          dense_count: 1,
          fused_count: 1,
        }),
      },
      { kind: "text", uuid: "u1", text: "From the bill." },
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "bill-A:para12",
          span_start: 0,
          span_end: 9,
          confidence: "paraphrase",
          claim_span: "From the",
        },
        status: "complete",
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    expect(citations[0]!.resolved?.bbox).toBeNull();
    expect(citations[0]!.resolved?.docId).toBe("bill-A");
  });

  it("indexes citations sequentially across multiple cite() calls", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "Two facts." },
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 5,
          confidence: "verbatim",
          claim_span: "first",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "ci-1" }),
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 6,
          span_end: 13,
          confidence: "paraphrase",
          claim_span: "second",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "ci-2" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations.map((c) => c.index)).toEqual([1, 2]);
    expect(citations.map((c) => c.confidence)).toEqual([
      "verbatim",
      "paraphrase",
    ]);
  });

  it("recognizes mcp__ask-the-budget-az__retrieve / __cite namespaced names", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "mcp__ask-the-budget-az__retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "Balance was $123M." },
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "mcp__ask-the-budget-az__cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 7,
          confidence: "verbatim",
          claim_span: "Balance",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "ci-x" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    expect(citations[0]!.resolved?.docTitle).toBe("JLBC Baseline Book");
  });

  it("drops malformed cite() inputs (no chunk_id, no claim_span, bad span)", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: { chunk_id: "x", claim_span: "y", span_start: 0, span_end: 0 },
        status: "complete",
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: { chunk_id: "x", claim_span: "y" },
        status: "complete",
      },
      {
        kind: "tool",
        toolUseId: "c3",
        toolName: "cite",
        input: { chunk_id: "", claim_span: "y", span_start: 0, span_end: 1 },
        status: "complete",
      },
    ]);
    expect(extractCitations(turn)).toEqual([]);
  });

  it("leaves resolved undefined when no retrieve() in the turn matches the chunk_id", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "ghost-chunk",
          span_start: 0,
          span_end: 3,
          confidence: "paraphrase",
          claim_span: "abc",
        },
        status: "complete",
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    expect(citations[0]!.resolved).toBeUndefined();
  });
});

describe("formatCopyCitation", () => {
  it("formats the spec example: 'JLBC Baseline Book FY24, p. 47'", () => {
    const c: Citation = {
      index: 1,
      chunkId: "x",
      spanStart: 0,
      spanEnd: 1,
      confidence: "verbatim",
      claimSpan: "y",
      resolved: {
        docId: "doc-A",
        docTitle: "JLBC Baseline Book",
        publisher: "JLBC",
        fiscalYear: 2024,
        docType: "jlbc-baseline-book",
        pageStart: 47,
        pageEnd: 47,
        bbox: [10, 20, 100, 40],
        text: "y",
      },
    };
    expect(formatCopyCitation(c)).toBe("JLBC Baseline Book FY24, p. 47");
  });

  it("uses page range when start ≠ end", () => {
    const c: Citation = {
      index: 1,
      chunkId: "x",
      spanStart: 0,
      spanEnd: 1,
      confidence: "verbatim",
      claimSpan: "y",
      resolved: {
        docId: "doc-B",
        docTitle: "Foo",
        publisher: "AGAO",
        fiscalYear: null,
        docType: "afr",
        pageStart: 10,
        pageEnd: 12,
        bbox: null,
        text: "y",
      },
    };
    expect(formatCopyCitation(c)).toContain("pp. 10–12");
  });

  it("falls back to chunk id when no resolved metadata", () => {
    const c: Citation = {
      index: 1,
      chunkId: "loose-chunk",
      spanStart: 0,
      spanEnd: 1,
      confidence: "paraphrase",
      claimSpan: "y",
    };
    expect(formatCopyCitation(c)).toBe("chunk loose-chunk");
  });
});
