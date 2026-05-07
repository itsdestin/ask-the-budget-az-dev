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

  it("rejects an over-long claim_span (>500 chars)", () => {
    expect(() =>
      citeInputSchema.parse({
        chunk_id: "c",
        span_start: 0,
        span_end: 5,
        confidence: "verbatim",
        claim_span: "x".repeat(501),
      }),
    ).toThrow();
  });
});

describe("cite handler", () => {
  it("returns ok:true with a citation_id when the bridge validates", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      expect(String(url)).toMatch(/\/cite\/validate$/);
      const body = JSON.parse(opts?.body as string);
      expect(body).toEqual({
        chunk_id: "test-doc::0",
        span_start: 0,
        span_end: 35,
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
});
