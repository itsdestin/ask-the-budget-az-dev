// Unit tests for the cite tool. Same pattern as retrieve.test.ts —
// schema validation + handler behavior with a stubbed fetcher.

import { describe, expect, it, vi } from "vitest";

import { loadConfig } from "../src/config.js";
import { citeInputSchema, makeCiteHandler } from "../src/tools/cite.js";

describe("cite input schema", () => {
  it("accepts a well-formed citation", () => {
    const parsed = citeInputSchema.parse({
      chunk_id: "test-doc::0",
      span_start: 0,
      span_end: 35,
      confidence: "verbatim",
      claim_span: "ADC's FY 2025 General Fund appropriation was $1.74B.",
    });
    expect(parsed.confidence).toBe("verbatim");
  });

  it("rejects unknown confidence values", () => {
    expect(() =>
      citeInputSchema.parse({
        chunk_id: "c",
        span_start: 0,
        span_end: 1,
        confidence: "definitely",
        claim_span: "x",
      }),
    ).toThrow();
  });

  it("rejects negative span_start", () => {
    expect(() =>
      citeInputSchema.parse({
        chunk_id: "c",
        span_start: -1,
        span_end: 5,
        confidence: "verbatim",
        claim_span: "x",
      }),
    ).toThrow();
  });

  it("rejects an empty claim_span", () => {
    expect(() =>
      citeInputSchema.parse({
        chunk_id: "c",
        span_start: 0,
        span_end: 5,
        confidence: "verbatim",
        claim_span: "",
      }),
    ).toThrow();
  });

  // Plan amendment (2026-05-20, Task 4): the 500-char schema ceiling
  // was relaxed to 2000 (server soft-clamps to 500 + flags `truncated`).
  // The schema test that locked in the 500 boundary is updated to lock
  // in the new 2000 boundary — same intent (reject pathologically long
  // claim_spans at the schema layer), new threshold.
  it("rejects an over-long claim_span (>2000 chars)", () => {
    expect(() =>
      citeInputSchema.parse({
        chunk_id: "c",
        span_start: 0,
        span_end: 5,
        confidence: "verbatim",
        claim_span: "x".repeat(2001),
      }),
    ).toThrow();
  });

  it("accepts a quote-only payload (no span_start/span_end)", () => {
    const parsed = citeInputSchema.parse({
      chunk_id: "doc::0",
      quote: "Aviation Fund balance was $123,456.",
      confidence: "verbatim",
      claim_span: "Aviation Fund balance was $123,456.",
    });
    expect(parsed.quote).toBe("Aviation Fund balance was $123,456.");
    expect(parsed.span_start).toBeUndefined();
    expect(parsed.span_end).toBeUndefined();
  });

  it("accepts an over-500-char claim_span up to the new 2000 ceiling (server will truncate to 500)", () => {
    const parsed = citeInputSchema.parse({
      chunk_id: "doc::0",
      span_start: 0,
      span_end: 5,
      confidence: "verbatim",
      claim_span: "x".repeat(750),
    });
    expect(parsed.claim_span.length).toBe(750);
  });
});

describe("cite handler", () => {
  it("forwards claim_span+confidence to the bridge alongside the span bounds", async () => {
    // The 2026-05-11 alignment-check addition: claim_span and
    // confidence are now part of the validate request so the sidecar
    // can verify the cited text actually supports the claim. If the
    // MCP server stops forwarding them, the sidecar silently falls
    // back to bounds-only validation — which is the exact failure
    // mode this fix targets.
    const fetcher = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      expect(String(url)).toMatch(/\/cite\/validate$/);
      const body = JSON.parse(opts?.body as string);
      expect(body).toEqual({
        chunk_id: "test-doc::0",
        span_start: 0,
        span_end: 35,
        claim_span: "ADC's FY 2025 General Fund appropriation was $1.74B.",
        confidence: "verbatim",
      });
      return new Response(JSON.stringify({ ok: true, chunk_text_length: 200 }), {
        status: 200,
      });
    });

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "test-doc::0",
      span_start: 0,
      span_end: 35,
      confidence: "verbatim",
      claim_span: "ADC's FY 2025 General Fund appropriation was $1.74B.",
    });

    expect(result.isError).toBeUndefined();
    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(true);
    expect(typeof decoded.citation_id).toBe("string");
    expect(decoded.citation_id.length).toBe(36); // UUID v4
  });

  it("surfaces cited_text_preview to the model on alignment failure", async () => {
    // When the sidecar rejects on alignment, it returns the actual
    // cited slice so the model knows what its span_start/span_end
    // pointed at and can pick a better one. The MCP server must
    // forward this preview field — without it the model sees only
    // "paraphrase: overlap too low" with no signal on what it
    // actually cited.
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            ok: false,
            error:
              "paraphrase cite: only 0/4 content words from the claim " +
              "appear in the cited span (ratio 0.00, threshold 0.60). " +
              "The cited span likely doesn't support this claim — pick " +
              "a different chunk or a different span within the same chunk.",
            chunk_text_length: 800,
            cited_text_preview:
              "Operating Budget composition: General Fund $342,500.",
          }),
          { status: 200 },
        ),
    );

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "c1",
      span_start: 0,
      span_end: 80,
      confidence: "paraphrase",
      claim_span: "$6,000,000 for secure ballot paper",
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(false);
    expect(decoded.error).toContain("paraphrase");
    expect(decoded.cited_text_preview).toContain("Operating Budget");
    expect(decoded.chunk_text_length).toBe(800);
  });

  it("returns ok:false on unknown chunk_id with the bridge's error", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: false, error: "unknown chunk_id" }), {
          status: 200,
        }),
    );

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "made-up",
      span_start: 0,
      span_end: 5,
      confidence: "verbatim",
      claim_span: "x",
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(false);
    expect(decoded.error).toBe("unknown chunk_id");
    expect(decoded.citation_id).toBeUndefined();
  });

  it("returns ok:false with chunk_text_length on out-of-range span", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: "span out of range",
            chunk_text_length: 50,
          }),
          { status: 200 },
        ),
    );

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "c1",
      span_start: 0,
      span_end: 100,
      confidence: "verbatim",
      claim_span: "x",
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(false);
    expect(decoded.error).toBe("span out of range");
    expect(decoded.chunk_text_length).toBe(50);
  });

  it("rejects span_end <= span_start before calling the bridge", async () => {
    const fetcher = vi.fn(async () => new Response("{}", { status: 200 }));

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "c1",
      span_start: 30,
      span_end: 30,
      confidence: "verbatim",
      claim_span: "x",
    });

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(false);
    expect(decoded.error).toBe("span out of range");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("returns isError:true on bridge transport failure", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError("ECONNREFUSED 127.0.0.1:9200");
    });

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "c1",
      span_start: 0,
      span_end: 5,
      confidence: "verbatim",
      claim_span: "x",
    });
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toMatch(/cite\(\) failed to validate/);
  });

  it("forwards a quote-based cite to the bridge with quote in the body", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      expect(String(url)).toMatch(/\/cite\/validate$/);
      const body = JSON.parse(opts?.body as string);
      expect(body.quote).toBe("Aviation Fund balance was $123,456.");
      expect(body.span_start).toBeUndefined();
      expect(body.span_end).toBeUndefined();
      return new Response(
        JSON.stringify({
          ok: true,
          chunk_text_length: 500,
          resolved_span_start: 42,
          resolved_span_end: 77,
        }),
        { status: 200 },
      );
    });

    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "doc::0",
      quote: "Aviation Fund balance was $123,456.",
      confidence: "verbatim",
      claim_span: "Aviation Fund balance was $123,456.",
    });

    expect(result.isError).toBeUndefined();
    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(true);
  });

  it("rejects locally when neither quote nor span_start/span_end is supplied", async () => {
    const fetcher = vi.fn(async () => new Response("{}"));
    const handler = makeCiteHandler(loadConfig(), fetcher);
    const result = await handler({
      chunk_id: "doc::0",
      confidence: "verbatim",
      claim_span: "x",
    } as never);
    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded.ok).toBe(false);
    expect(decoded.error).toMatch(/quote|span_start/);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
