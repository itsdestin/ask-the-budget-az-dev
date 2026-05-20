// Pure unit tests for citation extraction. Builds a synthetic
// AssistantTurn with a retrieve() then cite() pair and verifies the
// extracted Citation list mirrors the cite() inputs and resolves
// chunk metadata against the matching retrieve() result.

import { describe, expect, it } from "vitest";

import {
  buildConversationResolvedChunkMap,
  extractCitations,
  extractInlineCiteTags,
  extractKeyFact,
  findNormalizedMatch,
  formatCopyCitation,
  injectCiteSentinels,
  normalizeForMatch,
  planCitationPlacements,
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

  it("uses ack-provided resolved offsets over input sentinel for quote-only cite()", () => {
    // Regression test for the "Citation is on this page — exact text
    // couldn't be pinpointed" cluster the user reported 2026-05-20.
    // Quote-only cites have no span_start/span_end on the input, so
    // the extractor previously fell back to a (0, claim_span.length)
    // sentinel — pointing the PDF text-layer search at the FIRST
    // chunk_text chars instead of the cited quote. Fix: the cite tool
    // now passes the sidecar's resolved_span_start/end through on
    // success; the extractor reads those and uses them as the
    // Citation's spanStart/spanEnd.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
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
          quote: "balance was $123M as of June 30, 2024",
          confidence: "verbatim",
          claim_span: "$123M.",
        },
        status: "complete",
        output: JSON.stringify({
          ok: true,
          citation_id: "cit-uuid-resolved",
          // Sidecar-derived offsets. With these, spanStart/spanEnd
          // point at the actual quote position in chunk.text — NOT
          // the (0, 6) sentinel that would result from claim_span
          // length alone.
          resolved_span_start: 14,
          resolved_span_end: 52,
        }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    const c = citations[0]!;
    expect(c.citationId).toBe("cit-uuid-resolved");
    expect(c.spanStart).toBe(14);
    expect(c.spanEnd).toBe(52);
  });

  it("threads resolved offsets through cite_batch entries too", () => {
    // Same regression, batched path. Each entry's resolved offsets
    // come back in cite_batch's response.citations[i] alongside the
    // citation_id.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "First. Second." },
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "cite_batch",
        input: {
          citations: [
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q1 text",
              confidence: "verbatim",
              claim_span: "First.",
            },
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q2 text",
              confidence: "verbatim",
              claim_span: "Second.",
            },
          ],
        },
        status: "complete",
        output: JSON.stringify({
          citations: [
            {
              ok: true,
              citation_id: "cb-cit-1",
              resolved_span_start: 5,
              resolved_span_end: 25,
            },
            {
              ok: true,
              citation_id: "cb-cit-2",
              resolved_span_start: 100,
              resolved_span_end: 130,
            },
          ],
        }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(2);
    expect(citations[0]!.spanStart).toBe(5);
    expect(citations[0]!.spanEnd).toBe(25);
    expect(citations[1]!.spanStart).toBe(100);
    expect(citations[1]!.spanEnd).toBe(130);
  });

  it("accepts quote-only cite() calls (no offsets) — Task 4 quote path", () => {
    // Regression test for the citation-chip drop observed 2026-05-20:
    // the model now uses the additive `quote` field instead of computing
    // span_start/span_end. The extractor must NOT silently drop these
    // citations; chip attachment uses claim_span (substring search in
    // the answer text), so the (0, claimSpan.length) sentinel is fine.
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
          // No span_start/span_end — only `quote`.
          quote: "Aviation Fund balance was $123,456,789.",
          confidence: "verbatim",
          claim_span: "$123M.",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-uuid-2" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    const c = citations[0]!;
    expect(c.chunkId).toBe("doc-A:p47:s1");
    expect(c.claimSpan).toBe("$123M.");
    expect(c.citationId).toBe("cit-uuid-2");
    // Sentinel offsets cover the full claim_span — the actual PDF
    // highlight relies on the resolved range the sidecar derives, not
    // these. The chip-attachment substring search uses claimSpan.
    expect(c.spanStart).toBe(0);
    expect(c.spanEnd).toBeGreaterThan(0);
  });

  it("drops cite() calls that supply neither offsets nor quote", () => {
    // Belt-and-suspenders: the MCP handler rejects these before the
    // HTTP call (Task 4), but if a malformed cite() somehow lands in
    // the transcript the extractor still drops it.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "Some claim." },
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          // No span_start, no span_end, no quote — malformed.
          confidence: "verbatim",
          claim_span: "Some claim.",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "no offsets or quote" }),
      },
    ]);
    expect(extractCitations(turn)).toEqual([]);
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

  it("extracts failureReason from a cite() that returned ok:false", () => {
    // The 2026-05-12 red-X chip change: when the cite tool reports
    // an alignment / bounds rejection, the renderer needs to
    // surface a failed-chip UI variant. parseCiteAck must thread
    // the server's error string through to citation.failureReason.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "paraphrase",
          claim_span: "the claim that didn't validate",
        },
        status: "complete",
        output: JSON.stringify({
          ok: false,
          error: "paraphrase cite: only 1/8 content words appear...",
          chunk_text_length: 200,
          cited_text_preview: "Unrelated section content",
        }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    const c = citations[0]!;
    expect(c.citationId).toBeUndefined();
    expect(c.failureReason).toContain("paraphrase cite");
    expect(c.failureReason).toContain("1/8");
  });

  it("collapses retry chips when the model re-tries a failed cite and succeeds", () => {
    // The 2026-05-12 UX fix: when the model emits ✗ for a claim
    // (e.g. verbatim alignment failed) then retries with the same
    // claim_span and a corrected approach (e.g. paraphrase) that
    // succeeds, the renderer should show ONLY the successful chip.
    // The failed attempt is internal-state noise the user
    // shouldn't see in the final answer.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "verbatim",
          claim_span: "$4,677,100 in FY 2025",
        },
        status: "complete",
        output: JSON.stringify({
          ok: false,
          error: "verbatim cite: only 5/10 content words appear...",
        }),
      },
      // Retry with same claim, this time succeeds as paraphrase.
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 80,
          confidence: "paraphrase",
          claim_span: "$4,677,100 in FY 2025",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-uuid-1" }),
      },
    ]);
    const citations = extractCitations(turn);
    // Only one chip in the user-visible list — the successful retry.
    expect(citations).toHaveLength(1);
    expect(citations[0]!.citationId).toBe("cit-uuid-1");
    expect(citations[0]!.failureReason).toBeUndefined();
    // Re-indexed 1-based.
    expect(citations[0]!.index).toBe(1);
  });

  it("keeps the LAST failed cite when all attempts for a claim failed", () => {
    // If the model retries and never recovers, the user still sees
    // the failed chip (red X) so they know the claim is uncited.
    // Latest attempt wins because it represents the model's final
    // judgment of the claim.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "verbatim",
          claim_span: "uncitable claim text",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "first attempt failed" }),
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 80,
          confidence: "paraphrase",
          claim_span: "uncitable claim text",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "second attempt failed" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    expect(citations[0]!.failureReason).toContain("second attempt failed");
  });

  it("collapses retry chain where claim_span shape changes (table-row → $X → bare X)", () => {
    // The 2026-05-12 audit's most user-visible failure: the model
    // first emits the full markdown table row as claim_span (which
    // fails alignment because it includes doc metadata), retries
    // with just the dollar amount ($131,582,200), then retries with
    // the bare number (131,582,200). All three reference the same
    // chunk. Without substring-chain dedup, the cell renders 3
    // chips (✗ ✗ ✓) — but they're all attempts at the same claim.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "ema-0000",
          span_start: 0,
          span_end: 250,
          confidence: "paraphrase",
          claim_span:
            "| FY 2023 Actual | JLBC FY25 Approps Report | $131,582,200 |",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "overlap below threshold" }),
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "ema-0000",
          span_start: 240,
          span_end: 260,
          confidence: "verbatim",
          claim_span: "$131,582,200",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "still below threshold" }),
      },
      {
        kind: "tool",
        toolUseId: "c3",
        toolName: "cite",
        input: {
          chunk_id: "ema-0000",
          span_start: 240,
          span_end: 260,
          confidence: "verbatim",
          claim_span: "131,582,200",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-uuid-final" }),
      },
    ]);
    const citations = extractCitations(turn);
    // Only the successful retry survives — the three forms chain
    // together as substrings under the same chunk_id.
    expect(citations).toHaveLength(1);
    expect(citations[0]!.citationId).toBe("cit-uuid-final");
  });

  it("collapses retries when the model rewrites claim_span entirely (no substring overlap)", () => {
    // The 2026-05-20 dogfood case: the model failed 4 cites against the
    // same budget-bill chunk with table-row claim_spans like
    //   "FY 2024-25 | $17,337.2M | Includes $962.8M beginning balance"
    // then retried with completely rewritten prose claim_spans like
    //   "State general fund revenue for fiscal year 2024-2025, including
    //    a beginning balance of..."
    // Neither string contains the other — substring dedup misses them
    // entirely. FIFO pairing on same-chunk_id FAIL → OK in emission
    // order is what catches them. User saw 8 chips (4 red ✗ + 4 green
    // ✓); expected 4 chips (the 4 OKs replacing the 4 FAILs).
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "f1",
        toolName: "cite",
        input: {
          chunk_id: "bill-A",
          quote: "irrelevant for this test",
          confidence: "verbatim",
          claim_span: "FY 2024-25 | $17,337.2M | beginning balance",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "overlap below threshold" }),
      },
      {
        kind: "tool",
        toolUseId: "f2",
        toolName: "cite",
        input: {
          chunk_id: "bill-A",
          quote: "irrelevant",
          confidence: "verbatim",
          claim_span: "FY 2025-26 | $17,777.1M | Enacted",
        },
        status: "complete",
        output: JSON.stringify({ ok: false, error: "overlap below threshold" }),
      },
      {
        kind: "tool",
        toolUseId: "ok1",
        toolName: "cite",
        input: {
          chunk_id: "bill-A",
          quote: "irrelevant",
          confidence: "verbatim",
          claim_span:
            "State general fund revenue for fiscal year 2024-2025, including a beginning balance",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-fy2425" }),
      },
      {
        kind: "tool",
        toolUseId: "ok2",
        toolName: "cite",
        input: {
          chunk_id: "bill-A",
          quote: "irrelevant",
          confidence: "verbatim",
          claim_span:
            "State general fund revenue for fiscal year 2025-2026, including onetime revenues",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-fy2526" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(2);
    expect(citations.map((c) => c.citationId)).toEqual([
      "cit-fy2425",
      "cit-fy2526",
    ]);
  });

  it("does NOT collapse same-chunk cites with non-overlapping claims", () => {
    // Two distinct facts cited to the same chunk must stay separate.
    // The substring check only chains cites that contain each other.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A",
          span_start: 0,
          span_end: 30,
          confidence: "verbatim",
          claim_span: "revenue was up 5 percent",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-1" }),
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "doc-A",
          span_start: 40,
          span_end: 70,
          confidence: "verbatim",
          claim_span: "spending grew 3 percent",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-2" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(2);
  });

  it("preserves separate chips for distinct claim_spans", () => {
    // Dedup must only collapse repeats of the SAME claim; distinct
    // claims (even if to the same chunk) stay as separate chips.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "verbatim",
          claim_span: "first distinct claim",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-1" }),
      },
      {
        kind: "tool",
        toolUseId: "c2",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 60,
          span_end: 100,
          confidence: "verbatim",
          claim_span: "second distinct claim",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-2" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(2);
    expect(citations[0]!.index).toBe(1);
    expect(citations[1]!.index).toBe(2);
  });

  it("humanizes the claim_span-too-big MCP schema rejection", () => {
    // The 2026-05-12 screenshot fix: instead of showing the raw
    // zod-error blob ("MCP error -32602 ... too_big ... 500 ..."),
    // surface a one-sentence explanation a non-developer can read.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "paraphrase",
          claim_span: "a claim that was too long",
        },
        status: "complete",
        output:
          'MCP error -32602: Input validation error: Invalid arguments for tool cite: [\n' +
          '  {\n    "origin": "string",\n    "code": "too_big",\n    "maximum": 500,\n' +
          '    "inclusive": true,\n    "path": [\n      "claim_span"\n    ],\n' +
          '    "message": "Too big: expected string to have <=500 characters"\n  }\n]',
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    const reason = citations[0]!.failureReason!;
    expect(reason).toContain("too long");
    expect(reason).toContain("500");
    // No raw error scaffolding leaking through.
    expect(reason).not.toContain("MCP error");
    expect(reason).not.toContain("too_big");
    expect(reason).not.toContain("origin");
  });

  it("falls back gracefully when an MCP error has no zod payload", () => {
    // Some MCP errors don't carry a parseable "Invalid arguments
    // for tool" payload (e.g., transport-level rejections). The
    // humanizer leaves those alone rather than producing a
    // misleading paraphrase; the chip still renders as failed.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 50,
          confidence: "paraphrase",
          claim_span: "x".repeat(50),
        },
        status: "complete",
        output:
          "MCP error -32603: Internal error: subprocess timed out",
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(1);
    // Raw text preserved because we can't parse a payload from it.
    expect(citations[0]!.failureReason).toContain("Internal error");
    expect(citations[0]!.citationId).toBeUndefined();
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

describe("buildConversationResolvedChunkMap + cross-turn citation resolution", () => {
  it("merges retrieve() results across turns; later turns overwrite duplicates", () => {
    const turn1 = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "t1-r1",
        toolName: "retrieve",
        input: { query: "aviation" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
    ]);
    // Second turn re-retrieves the same chunk_id with updated text;
    // map should reflect the newer metadata.
    const updated = JSON.stringify({
      chunks: [
        {
          chunk_id: "doc-A:p47:s1",
          doc_id: "doc-A",
          doc_title: "JLBC Baseline Book",
          publisher: "JLBC",
          fiscal_year: 2024,
          doc_type: "jlbc-baseline-book",
          section_path: ["Aviation Fund"],
          page_start: 99,
          page_end: 99,
          bbox: [99, 99, 199, 199],
          text: "UPDATED TEXT",
          score: 0.92,
        },
      ],
      top_score: 0.92,
      retrieval_id: "r-2",
      bm25_count: 1,
      dense_count: 1,
      fused_count: 1,
    });
    const turn2 = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "t2-r1",
        toolName: "retrieve",
        input: { query: "aviation" },
        status: "complete",
        output: updated,
      },
    ]);
    const map = buildConversationResolvedChunkMap([turn1, turn2]);
    expect(map.size).toBe(1);
    const m = map.get("doc-A:p47:s1");
    expect(m?.pageStart).toBe(99);
    expect(m?.text).toBe("UPDATED TEXT");
  });

  it("normalizeForMatch collapses whitespace, folds smart-quotes / dashes / NFKC, lowercases", () => {
    // Multiple kinds of whitespace + smart quotes + en-dash + NFKC ligature.
    const input = "  The  \"quote\" is  here–yesﬁne.";
    const { normalized, indexMap } = normalizeForMatch(input);
    // Single leading space (from runs collapsed), then text. Final
    // form should be deterministic across browsers.
    expect(normalized).toBe(' the "quote" is here-yesfine.');
    // indexMap is parallel to `normalized`; every entry must be a
    // valid index into `input`.
    expect(indexMap.length).toBe(normalized.length);
    for (const i of indexMap) {
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThan(input.length);
    }
  });

  it("findNormalizedMatch survives whitespace, smart-quote, and trailing-punctuation drift", () => {
    const haystack =
      "The Aviation Fund balance was “$123 million” as of June 30, 2024.";
    // Drift: straight quotes; collapsed whitespace; trailing period.
    const needle = '"$123 million"';
    const m = findNormalizedMatch(haystack, needle);
    expect(m).not.toBeNull();
    const matched = haystack.slice(m!.start, m!.end);
    // Must include the smart-quotes from the original — we're
    // returning indices into the original text, not the normalized.
    expect(matched).toContain("$123 million");
  });

  it("findNormalizedMatch returns null when the substring genuinely isn't present", () => {
    expect(findNormalizedMatch("abc", "xyz")).toBeNull();
  });

  it("findNormalizedMatch tolerates extra whitespace runs in either input", () => {
    const haystack = "fiscal     year   2026 baseline";
    const needle = "fiscal year 2026";
    const m = findNormalizedMatch(haystack, needle);
    expect(m).not.toBeNull();
    const matched = haystack.slice(m!.start, m!.end);
    expect(matched).toMatch(/fiscal\s+year\s+2026/);
  });

  it("normalizeForMatch strips markdown bold/italic/code so claim_span matches rendered text", () => {
    // The dominant Opus failure mode (2026-05-07 audit): claim_span
    // values arrive with markdown formatting tokens (`**`, `_`, etc.)
    // but the rendered DOM has the tokens stripped.
    const claimSpanWithMarkdown = "about **$501.9 million** of settlements";
    const renderedAnswer = "about $501.9 million of settlements";
    const m = findNormalizedMatch(renderedAnswer, claimSpanWithMarkdown);
    expect(m).not.toBeNull();
    expect(renderedAnswer.slice(m!.start, m!.end)).toBe(
      "about $501.9 million of settlements",
    );
  });

  it("normalizeForMatch strips italic markers _ and *", () => {
    expect(
      findNormalizedMatch("the value is critical", "the value is _critical_"),
    ).not.toBeNull();
    expect(
      findNormalizedMatch("FY 2026 number", "FY *2026* number"),
    ).not.toBeNull();
  });

  it("normalizeForMatch strips backticks around inline code", () => {
    expect(
      findNormalizedMatch("section A.R.S. § 35-142 governs", "`A.R.S. § 35-142`"),
    ).not.toBeNull();
  });

  it("normalizeForMatch unwraps markdown links to label-only", () => {
    // [SB1735](url) → SB1735 in normalized form, so a rendered text
    // containing "SB1735" matches the bracketed claim_span.
    expect(
      findNormalizedMatch(
        "the bill SB1735 passed",
        "[SB1735](https://example.com)",
      ),
    ).not.toBeNull();
  });

  it("normalizeForMatch treats table pipes as whitespace", () => {
    // claim_span: a whole markdown table row.
    const row = "| **FY 2023** | **$6,200,000** | One-time |";
    // Rendered table: cells separated by spaces in the DOM text content.
    const rendered = "FY 2023 $6,200,000 One-time";
    expect(findNormalizedMatch(rendered, row)).not.toBeNull();
  });

  it("normalizeForMatch collapses both accounting-negative paren conventions", () => {
    // Two equivalent forms appear in budget docs:
    //   `$(10,000,000)` — MinerU's dollar-first markdown shape
    //   `($10,000,000)` — pdfjs text-layer paren-first shape
    // Both denote a decrease. Collapsing both means a claim that
    // normalizes to `$10,000,000` matches either accounting form.
    expect(normalizeForMatch("$(10,000,000)").normalized).toBe("$10,000,000");
    expect(normalizeForMatch("($10,000,000)").normalized).toBe("$10,000,000");
    // After backslash strip + paren collapse, the chunk-side shape
    // matches the PDF-side shape symmetrically.
    expect(normalizeForMatch("\\$(3,500,000)").normalized).toBe("$3,500,000");
    // Legitimate parens — like `(Item 9 of Section 116)` — must NOT
    // be collapsed, because the depth counter only opens when we
    // see `(` IMMEDIATELY followed by `$` or `$(` immediately
    // followed by a digit.
    expect(normalizeForMatch("(Item 9 of Section 116)").normalized)
      .toBe("(item 9 of section 116)");
    expect(normalizeForMatch("decrease (Item 116)").normalized)
      .toBe("decrease (item 116)");
  });

  it("normalizeForMatch strips CommonMark backslash escapes", () => {
    // MinerU and other ingest pipelines emit `\$` to prevent `$…$`
    // from rendering as math. The PDF text layer has the UNESCAPED
    // form, so without stripping here, findNormalizedMatch fails to
    // anchor the chunk text to the PDF and PdfPage falls back to the
    // coarse chunk bbox. This was the 2026-05-11 cite-#14 case.
    // The 2026-05-12 update added accounting-paren collapse on top
    // of backslash strip, so `\$(X)` now normalizes to bare `$X`.
    const { normalized } = normalizeForMatch("\\$(10,000,000)");
    expect(normalized).toBe("$10,000,000");
    // Cross-format match works: chunk-text "$(X)" (dollar-first
    // accounting) against PDF-text "($X)" (paren-first accounting)
    // both normalize to "$X".
    const chunkText = "decrease of \\$(10,000,000) from the Fund";
    const pdfText = "decrease of ($10,000,000) from the Fund";
    expect(findNormalizedMatch(pdfText, chunkText)).not.toBeNull();
    // All CommonMark-escapable punctuation gets stripped. The leading
    // space is from the existing whitespace-collapse logic emitting
    // when the first chars (`\*` then bare `*`) get stripped — `\*`
    // strips the backslash, and the bare `*` is then treated as an
    // italic marker. Same for `_`. Net result: the asterisk/underscore
    // pair collapses to a single space, then the rest follows.
    expect(normalizeForMatch("\\* \\_ \\[ \\] \\( \\) \\# \\!").normalized)
      .toBe(" [ ] ( ) # !");
  });
});

describe("planCitationPlacements + injectCiteSentinels", () => {
  it("anchors a paragraph claim to its source line", () => {
    const content = [
      "First paragraph not cited.",
      "",
      "The State Aviation Fund got $2,587,400 for FY 2026.",
    ].join("\n");
    const placements = planCitationPlacements(content, [
      { claimSpan: "$2,587,400 for FY 2026" },
    ]);
    expect(placements).toEqual([{ citationIndex: 0, lineIndex: 2 }]);
    const augmented = injectCiteSentinels(content, placements);
    // Sentinel ends up after the matched line, not at end of content.
    expect(augmented).toBe(
      [
        "First paragraph not cited.",
        "",
        "The State Aviation Fund got $2,587,400 for FY 2026. {{cite:0}}",
      ].join("\n"),
    );
  });

  it("anchors a table-row claim to the matching row", () => {
    const content = [
      "| Year | Amount | Notes |",
      "|------|--------|-------|",
      "| **FY 2023** | **$6,200,000** | One-time |",
      "| **FY 2024** | **$12,200,000** | Carry-forward |",
    ].join("\n");
    // Opus often emits the whole row as claim_span with markdown
    // pipes and bold markers — both must be stripped during matching.
    const placements = planCitationPlacements(content, [
      { claimSpan: "| **FY 2023** | **$6,200,000** | One-time |" },
    ]);
    expect(placements[0]?.lineIndex).toBe(2);
    const augmented = injectCiteSentinels(content, placements);
    // Chip lands INSIDE the last cell of the matched row — between
    // the last cell's content and the row-closing `|`. The GFM
    // table parser eats anything after the row-closing `|`, so an
    // appended sentinel disappears; injecting before the `|` puts
    // the sentinel inside the final `<td>` where it renders as a
    // chip. The 2026-05-12 invisible-cites #1-6 issue was this case.
    expect(augmented.split("\n")[2]).toBe(
      "| **FY 2023** | **$6,200,000** | One-time {{cite:0}} |",
    );
  });

  it("injects multiple sentinels inside the last cell for table-row claims", () => {
    // Two cites both anchored to the same table row must BOTH land
    // inside the last cell; the GFM parser would eat them otherwise.
    const content = [
      "| Year | Amount |",
      "|------|--------|",
      "| FY 2023 | $6,200,000 |",
    ].join("\n");
    const placements = planCitationPlacements(content, [
      { claimSpan: "| FY 2023 | $6,200,000 |" },
      { claimSpan: "| FY 2023 | $6,200,000 |" },
    ]);
    const augmented = injectCiteSentinels(content, placements);
    expect(augmented.split("\n")[2]).toBe(
      "| FY 2023 | $6,200,000 {{cite:0}} {{cite:1}} |",
    );
  });

  it("appends unmatched citations to the end of content", () => {
    const content = "Just a single line.";
    const placements = planCitationPlacements(content, [
      { claimSpan: "no such phrase" },
    ]);
    expect(placements[0]?.lineIndex).toBe(-1);
    const augmented = injectCiteSentinels(content, placements);
    expect(augmented).toBe("Just a single line.\n\n{{cite:0}}");
  });

  it("groups multiple citations on the same line in original order", () => {
    const content = "alpha beta gamma";
    const placements = planCitationPlacements(content, [
      { claimSpan: "gamma" },
      { claimSpan: "alpha" },
    ]);
    // Both anchor to line 0; injection preserves the citation array
    // order (cite 0 before cite 1) in the sentinel sequence.
    const augmented = injectCiteSentinels(content, placements);
    expect(augmented).toBe("alpha beta gamma {{cite:0}} {{cite:1}}");
  });
});

describe("extractInlineCiteTags HTML-entity decoding", () => {
  it("decodes &quot;, &amp;, &lt;, &gt;, &apos;, &#39; in attribute values", () => {
    const text = `Claude said <cite chunk_id="c-1" claim_span="he asked &quot;why&quot;? &amp; left">he asked "why"? &amp; left</cite>.`;
    const { strippedText, citations } = extractInlineCiteTags(text);
    expect(citations).toHaveLength(1);
    // claim_span should arrive with literal quotes + ampersand,
    // matching what's actually rendered in the answer text.
    expect(citations[0]!.claimSpan).toBe('he asked "why"? & left');
    // Stripped text keeps the inner content (decoded by the renderer
    // when the markdown layer sees it, but inner is left as-is here).
    expect(strippedText).toContain("he asked");
  });

  it("falls back to inner text when claim_span attr is missing", () => {
    const text = `Hello <cite chunk_id="c-2">world</cite>.`;
    const { citations } = extractInlineCiteTags(text);
    expect(citations).toHaveLength(1);
    expect(citations[0]!.claimSpan).toBe("world");
    expect(citations[0]!.chunkId).toBe("c-2");
  });

  it("emits no citation when neither attr nor inner text is present", () => {
    expect(extractInlineCiteTags("plain text").citations).toEqual([]);
  });
});

describe("buildConversationResolvedChunkMap + cross-turn citation resolution (cont.)", () => {
  it("extractCitations falls back to additionalResolved for chunks not in this turn", () => {
    // Turn 1 retrieves the chunk, but no cite. Turn 2 cites it
    // without re-retrieving. Without the fallback the citation
    // would render with `resolved=undefined` and the PdfViewer
    // can't open the source PDF.
    const turn1 = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "t1-r1",
        toolName: "retrieve",
        input: { query: "aviation" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
    ]);
    const turn2 = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "t2-c1",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          span_start: 0,
          span_end: 10,
          confidence: "verbatim",
          claim_span: "Aviation",
        },
        status: "complete",
      },
    ]);
    const conversationMap = buildConversationResolvedChunkMap([turn1, turn2]);
    const turn2OnlyCitations = extractCitations(turn2);
    expect(turn2OnlyCitations[0]?.resolved).toBeUndefined();

    const turn2WithFallback = extractCitations(turn2, conversationMap);
    expect(turn2WithFallback[0]?.resolved?.docId).toBe("doc-A");
    expect(turn2WithFallback[0]?.resolved?.pageStart).toBe(47);
  });
});

describe("extractCitations — cite_batch tool (2026-05-20)", () => {
  // cite_batch is the batched-citation tool: one tool_use block carries
  // N citations in input.citations and N parallel results in
  // output.citations. Downstream rendering should see N Citation
  // records, indistinguishable from the model having emitted N
  // separate cite() blocks.

  it("expands one cite_batch block into N Citation records", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "First claim. Second claim." },
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "cite_batch",
        input: {
          citations: [
            {
              chunk_id: "doc-A:p47:s1",
              quote: "first source quote",
              confidence: "verbatim",
              claim_span: "First claim.",
            },
            {
              chunk_id: "doc-A:p47:s1",
              quote: "second source quote",
              confidence: "paraphrase",
              claim_span: "Second claim.",
            },
          ],
        },
        status: "complete",
        output: JSON.stringify({
          citations: [
            { ok: true, citation_id: "cit-1" },
            { ok: true, citation_id: "cit-2" },
          ],
        }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(2);
    expect(citations[0]!.claimSpan).toBe("First claim.");
    expect(citations[0]!.citationId).toBe("cit-1");
    expect(citations[1]!.claimSpan).toBe("Second claim.");
    expect(citations[1]!.citationId).toBe("cit-2");
    // Indexes 1-based across the whole batch.
    expect(citations[0]!.index).toBe(1);
    expect(citations[1]!.index).toBe(2);
    // Chunk metadata resolves the same way as single-cite blocks.
    expect(citations[0]!.resolved?.docTitle).toBe("JLBC Baseline Book");
  });

  it("pairs cite_batch input items with their matching ack by index (mixed ok/fail)", () => {
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "A claim. Another claim. Third claim." },
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "mcp__ask-the-budget-az__cite_batch",
        input: {
          citations: [
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q1",
              confidence: "verbatim",
              claim_span: "A claim.",
            },
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q2",
              confidence: "verbatim",
              claim_span: "Another claim.",
            },
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q3",
              confidence: "verbatim",
              claim_span: "Third claim.",
            },
          ],
        },
        status: "complete",
        output: JSON.stringify({
          citations: [
            { ok: true, citation_id: "cit-A" },
            { ok: false, error: "quote not found in chunk.text" },
            { ok: true, citation_id: "cit-C" },
          ],
        }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(3);
    expect(citations[0]!.citationId).toBe("cit-A");
    expect(citations[1]!.citationId).toBeUndefined();
    expect(citations[1]!.failureReason).toContain("quote not found");
    expect(citations[2]!.citationId).toBe("cit-C");
  });

  it("treats a malformed cite_batch input.citations field as no citations", () => {
    // Defensive: a bug in the model's output (citations is a string,
    // an object, missing entirely) shouldn't crash the renderer.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "cite_batch",
        input: {
          // Should be an array; rendering should drop the whole block.
          citations: "this isn't an array",
        },
        status: "complete",
        output: JSON.stringify({ citations: [] }),
      },
    ]);
    expect(extractCitations(turn)).toEqual([]);
  });

  it("handles cite_batch + plain cite() in the same turn", () => {
    // Belt-and-suspenders: if the model mixes both tool shapes within a
    // single turn (e.g. one cite_batch covering most claims plus one
    // standalone cite() afterward), the extractor produces a combined
    // ordered list with correct dedup behavior.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "r1",
        toolName: "retrieve",
        input: { query: "x" },
        status: "complete",
        output: RETRIEVE_OUTPUT_OK,
      },
      { kind: "text", uuid: "u1", text: "Claim one. Claim two. Claim three." },
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "cite_batch",
        input: {
          citations: [
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q1",
              confidence: "verbatim",
              claim_span: "Claim one.",
            },
            {
              chunk_id: "doc-A:p47:s1",
              quote: "q2",
              confidence: "verbatim",
              claim_span: "Claim two.",
            },
          ],
        },
        status: "complete",
        output: JSON.stringify({
          citations: [
            { ok: true, citation_id: "cit-1" },
            { ok: true, citation_id: "cit-2" },
          ],
        }),
      },
      {
        kind: "tool",
        toolUseId: "c3",
        toolName: "cite",
        input: {
          chunk_id: "doc-A:p47:s1",
          quote: "q3",
          confidence: "verbatim",
          claim_span: "Claim three.",
        },
        status: "complete",
        output: JSON.stringify({ ok: true, citation_id: "cit-3" }),
      },
    ]);
    const citations = extractCitations(turn);
    expect(citations).toHaveLength(3);
    expect(citations.map((c) => c.citationId)).toEqual([
      "cit-1",
      "cit-2",
      "cit-3",
    ]);
  });

  it("treats an entire failed batch ack (MCP error) as one failure on slot 0", () => {
    // The batch transport-failed at the MCP layer (e.g. schema rejection).
    // We can't pin the failure to a specific slot — surface as a single
    // failed chip on slot 0 so the user sees the error rather than
    // silent disappearance. The fact that we lose specificity here is
    // an accepted limitation; the alternative (drop all citations
    // silently) is worse.
    const turn = turnWithBlocks([
      {
        kind: "tool",
        toolUseId: "cb1",
        toolName: "cite_batch",
        input: {
          citations: [
            {
              chunk_id: "doc-A",
              quote: "q1",
              confidence: "verbatim",
              claim_span: "first claim",
            },
            {
              chunk_id: "doc-A",
              quote: "q2",
              confidence: "verbatim",
              claim_span: "second claim",
            },
          ],
        },
        status: "complete",
        output: "MCP error -32602: batch too large",
      },
    ]);
    const citations = extractCitations(turn);
    // Two input items → two Citation records. Slot 0 carries the batch
    // failure reason; slot 1 is in-flight (no ack). After dedup, both
    // remain (they have different claimSpans on the same chunk —
    // neither's claim_span is a substring of the other).
    expect(citations.length).toBeGreaterThanOrEqual(1);
    expect(citations[0]!.failureReason).toBeDefined();
  });
});

describe("extractKeyFact", () => {
  it("returns the longest currency token in claim_span", () => {
    expect(extractKeyFact("$3,300,000 for the Dark Sky Discovery Center"))
      .toBe("$3,300,000");
  });

  it("picks the longest of multiple currency tokens", () => {
    expect(extractKeyFact("Up from $5M to $123,456,789 in FY 2027"))
      .toBe("$123,456,789");
  });

  it("returns a percentage when no currency is present", () => {
    expect(extractKeyFact("an increase of 12.5% over the prior year"))
      .toBe("12.5%");
  });

  it("returns null when the claim has no currency or percentage", () => {
    expect(extractKeyFact("Aviation Fund growth in FY 2027")).toBeNull();
  });

  it("returns null for bare years and small integers (too noisy)", () => {
    expect(extractKeyFact("Section 9 of HB 2729 in 2027")).toBeNull();
  });

  it("matches '5 million' / '$5M' shorthand forms", () => {
    expect(extractKeyFact("about $5 million in carry-forward"))
      .toBe("$5 million");
    expect(extractKeyFact("about $5M in carry-forward")).toBe("$5M");
  });
});
