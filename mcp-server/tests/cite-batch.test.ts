// Unit tests for the cite_batch tool. Same pattern as cite.test.ts —
// schema validation + handler behavior with a stubbed fetcher. The
// handler is the interesting bit: it pre-validates each item, forwards
// only the survivors to the sidecar's /cite/validate_batch endpoint,
// and stitches sidecar responses back into the original slots.

import { describe, expect, it, vi } from "vitest";

import { loadConfig } from "../src/config.js";
import {
  citeBatchInputSchema,
  makeCiteBatchHandler,
} from "../src/tools/cite-batch.js";

describe("cite_batch input schema", () => {
  it("accepts an empty citations array", () => {
    const parsed = citeBatchInputSchema.parse({ citations: [] });
    expect(parsed.citations).toEqual([]);
  });

  it("accepts a batch of quote-based citations", () => {
    const parsed = citeBatchInputSchema.parse({
      citations: [
        {
          chunk_id: "doc::0",
          quote: "Aviation Fund balance",
          confidence: "verbatim",
          claim_span: "Aviation Fund balance",
        },
        {
          chunk_id: "doc::1",
          quote: "$123 million for ADC",
          confidence: "paraphrase",
          claim_span: "ADC received $123M",
        },
      ],
    });
    expect(parsed.citations).toHaveLength(2);
    expect(parsed.citations[0]!.quote).toBe("Aviation Fund balance");
  });

  it("accepts a mixed batch of quote-based and offset-based citations", () => {
    const parsed = citeBatchInputSchema.parse({
      citations: [
        {
          chunk_id: "c1",
          quote: "x",
          confidence: "verbatim",
          claim_span: "y",
        },
        {
          chunk_id: "c2",
          span_start: 0,
          span_end: 10,
          confidence: "verbatim",
          claim_span: "z",
        },
      ],
    });
    expect(parsed.citations[0]!.quote).toBeDefined();
    expect(parsed.citations[1]!.span_start).toBe(0);
  });

  it("rejects an over-large batch (>50 citations)", () => {
    // Defensive cap — no real model should exceed this. Catches a
    // runaway-tool-call regression early.
    const big = Array.from({ length: 51 }, () => ({
      chunk_id: "c",
      quote: "x",
      confidence: "verbatim" as const,
      claim_span: "y",
    }));
    expect(() => citeBatchInputSchema.parse({ citations: big })).toThrow();
  });

  it("rejects an unknown confidence value in any item", () => {
    expect(() =>
      citeBatchInputSchema.parse({
        citations: [
          {
            chunk_id: "c",
            quote: "x",
            confidence: "uncertain",
            claim_span: "y",
          },
        ],
      }),
    ).toThrow();
  });
});

describe("cite_batch handler", () => {
  it("returns an empty citations array immediately when input is empty", async () => {
    // Empty input must NOT hit the sidecar — short-circuit at the
    // handler. Catches accidental empty-array round-trips.
    const fetcher = vi.fn(async () => new Response("{}"));
    const handler = makeCiteBatchHandler(loadConfig(), fetcher);
    const result = await handler({ citations: [] });
    expect(fetcher).not.toHaveBeenCalled();
    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded).toEqual({ citations: [] });
  });

  it("forwards a multi-citation batch to the sidecar in one HTTP call", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      expect(String(url)).toMatch(/\/cite\/validate_batch$/);
      const body = JSON.parse(opts?.body as string);
      // The handler should forward the array — and ONLY for items that
      // passed local pre-validation.
      expect(body.citations).toHaveLength(2);
      expect(body.citations[0].chunk_id).toBe("doc-A:0");
      expect(body.citations[0].quote).toBe("first quote");
      expect(body.citations[1].chunk_id).toBe("doc-B:0");
      return new Response(
        JSON.stringify({
          citations: [
            { ok: true },
            { ok: true },
          ],
        }),
        { status: 200 },
      );
    });

    const handler = makeCiteBatchHandler(loadConfig(), fetcher);
    const result = await handler({
      citations: [
        {
          chunk_id: "doc-A:0",
          quote: "first quote",
          confidence: "verbatim",
          claim_span: "first claim",
        },
        {
          chunk_id: "doc-B:0",
          quote: "second quote",
          confidence: "paraphrase",
          claim_span: "second claim",
        },
      ],
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.citations).toHaveLength(2);
    expect(decoded.citations[0].ok).toBe(true);
    expect(decoded.citations[1].ok).toBe(true);
    // Successful entries get unique minted citation_ids.
    expect(decoded.citations[0].citation_id).toBeDefined();
    expect(decoded.citations[1].citation_id).toBeDefined();
    expect(decoded.citations[0].citation_id).not.toBe(
      decoded.citations[1].citation_id,
    );
  });

  it("stitches local pre-validation failures back into the correct slot", async () => {
    // Item 1 has neither quote nor offsets → fails local pre-validation
    // (never reaches the sidecar). Items 0 and 2 are valid and go to the
    // sidecar. The handler must put each result back in its original
    // position so the model sees a parallel array.
    const fetcher = vi.fn(async (_url: RequestInfo | URL, opts?: RequestInit) => {
      const body = JSON.parse(opts?.body as string);
      // Sidecar should only see 2 forwarded items (slots 0 and 2).
      expect(body.citations).toHaveLength(2);
      expect(body.citations[0].chunk_id).toBe("doc-A:0");
      expect(body.citations[1].chunk_id).toBe("doc-C:0");
      return new Response(
        JSON.stringify({
          citations: [{ ok: true }, { ok: true }],
        }),
        { status: 200 },
      );
    });

    const handler = makeCiteBatchHandler(loadConfig(), fetcher);
    const result = await handler({
      citations: [
        {
          chunk_id: "doc-A:0",
          quote: "valid first",
          confidence: "verbatim",
          claim_span: "x",
        },
        // Missing both quote AND span_start/span_end.
        {
          chunk_id: "doc-B:0",
          confidence: "verbatim",
          claim_span: "y",
        } as never,
        {
          chunk_id: "doc-C:0",
          quote: "valid third",
          confidence: "verbatim",
          claim_span: "z",
        },
      ],
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.citations).toHaveLength(3);
    expect(decoded.citations[0].ok).toBe(true);
    expect(decoded.citations[1].ok).toBe(false);
    expect(decoded.citations[1].error).toMatch(/quote|span_start/);
    expect(decoded.citations[2].ok).toBe(true);
  });

  it("preserves order of sidecar responses (i-th result for i-th input)", async () => {
    // The model relies on slot-correspondence to know which result
    // belongs to which input. The sidecar contract is order-preserving;
    // the handler must not reorder. Mixed ok/fail confirms both paths.
    const fetcher = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          citations: [
            { ok: true },
            { ok: false, error: "quote not found in chunk.text" },
            { ok: true },
          ],
        }),
        { status: 200 },
      );
    });

    const handler = makeCiteBatchHandler(loadConfig(), fetcher);
    const result = await handler({
      citations: [
        { chunk_id: "a", quote: "q1", confidence: "verbatim", claim_span: "x" },
        { chunk_id: "b", quote: "q2", confidence: "verbatim", claim_span: "y" },
        { chunk_id: "c", quote: "q3", confidence: "verbatim", claim_span: "z" },
      ],
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.citations[0].ok).toBe(true);
    expect(decoded.citations[1].ok).toBe(false);
    expect(decoded.citations[1].error).toContain("quote not found");
    expect(decoded.citations[2].ok).toBe(true);
  });

  it("surfaces a single transport-failure error for the whole batch", async () => {
    // Bridge transport error on the batch endpoint must not be retried
    // by the handler (the bridge layer already retries once). Returns
    // isError:true so Claude Code surfaces it as a tool failure
    // instead of misinterpreting the body as per-cite results.
    const fetcher = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const handler = makeCiteBatchHandler(loadConfig(), fetcher);
    const result = await handler({
      citations: [
        { chunk_id: "a", quote: "q", confidence: "verbatim", claim_span: "x" },
      ],
    });
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toMatch(/cite_batch\(\) failed/);
  });
});
