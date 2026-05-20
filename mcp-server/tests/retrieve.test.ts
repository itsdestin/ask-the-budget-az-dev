// Unit tests for the retrieve tool. Exercise schema validation +
// handler behavior with a stubbed fetcher so no real HTTP / Postgres /
// Voyage call is made — these run in any environment.

import { describe, expect, it, vi } from "vitest";

import { loadConfig } from "../src/config.js";
import {
  makeRetrieveHandler,
  retrieveInputSchema,
  type RetrieveBridgeResponse,
} from "../src/tools/retrieve.js";

// ---------------------------------------------------------------------------
// Schema validation
// ---------------------------------------------------------------------------

describe("retrieve input schema", () => {
  it("accepts a minimal query-only payload", () => {
    const parsed = retrieveInputSchema.parse({ query: "Aviation Fund" });
    expect(parsed.query).toBe("Aviation Fund");
  });

  it("accepts the full filter set", () => {
    const parsed = retrieveInputSchema.parse({
      query: "balance",
      filters: {
        fiscal_year: [2027],
        doc_type: ["baseline-per-agency"],
        publisher: ["jlbc"],
        agency_canonical_id: ["agency:adc"],
        fund_canonical_id: ["fund:aviation"],
        is_table: true,
      },
      top_k: 10,
    });
    expect(parsed.filters?.fiscal_year).toEqual([2027]);
    expect(parsed.top_k).toBe(10);
  });

  it("accepts every doc_type value present in the corpus", () => {
    // Regression: pre-2026-05-08 the enum drifted from the DB and
    // rejected the values that actually exist in the documents
    // table. This test pins the enum to the canonical list so a
    // future ingest doesn't silently break filtering again.
    const allDocTypes = [
      "baseline-per-agency",
      "approps-per-agency",
      "s-pdf",
      "bd-pdf",
      "bh-pdf",
      "detailed-list-pdf",
      "topic-pdf",
      "afr",
      "governors-budget",
      "budget-bill",
    ];
    for (const dt of allDocTypes) {
      expect(() =>
        retrieveInputSchema.parse({
          query: "x",
          filters: { doc_type: [dt] },
        }),
      ).not.toThrow();
    }
  });

  it("rejects doc_type values that DON'T exist in the corpus", () => {
    // Pre-2026-05-08 these would have been accepted (and produced
    // silent zero-result retrievals). Pin the rejection so the
    // enum can't drift back.
    const invalidDocTypes = [
      "baseline-agency",      // missing the "per-"
      "approps-report",        // wrong shape entirely
      "baseline-cross-cut",    // legacy name
      "primer",                // doesn't exist in DB
    ];
    for (const dt of invalidDocTypes) {
      expect(() =>
        retrieveInputSchema.parse({
          query: "x",
          filters: { doc_type: [dt] },
        }),
      ).toThrow();
    }
  });

  it("rejects fiscal_year with the wrong primitive type", () => {
    expect(() =>
      retrieveInputSchema.parse({
        query: "x",
        filters: { fiscal_year: "2027" },
      }),
    ).toThrow();
  });

  it("rejects an empty query string", () => {
    expect(() => retrieveInputSchema.parse({ query: "" })).toThrow();
  });

  it("rejects unknown publisher values", () => {
    expect(() =>
      retrieveInputSchema.parse({
        query: "x",
        filters: { publisher: ["acme"] },
      }),
    ).toThrow();
  });

  it("rejects unknown filter keys (strict)", () => {
    expect(() =>
      retrieveInputSchema.parse({
        query: "x",
        filters: { mystery: ["foo"] },
      }),
    ).toThrow();
  });

  it("rejects fiscal_year out of bounds", () => {
    expect(() =>
      retrieveInputSchema.parse({
        query: "x",
        filters: { fiscal_year: [1900] },
      }),
    ).toThrow();
  });

  it("accepts an intent value", () => {
    for (const intent of ["lookup", "compare", "analyze"]) {
      const parsed = retrieveInputSchema.parse({
        query: "x",
        intent,
      });
      expect(parsed.intent).toBe(intent);
    }
  });

  it("rejects an unknown intent value", () => {
    expect(() =>
      retrieveInputSchema.parse({ query: "x", intent: "random" }),
    ).toThrow();
  });

  it("accepts a payload without intent (back-compat)", () => {
    const parsed = retrieveInputSchema.parse({ query: "x" });
    expect(parsed.intent).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Handler behavior — fetcher mocked
// ---------------------------------------------------------------------------

const fakeBridgeResponse: RetrieveBridgeResponse = {
  chunks: [
    {
      chunk_id: "test-doc::0",
      doc_id: "test-doc",
      doc_title: "Doc",
      publisher: "jlbc",
      fiscal_year: 2027,
      doc_type: "baseline-cross-cut",
      section_path: ["AHCCCS"],
      page_start: 47,
      page_end: 47,
      text: "Aviation Fund balance was $123,456.",
      score: 0.91,
    },
  ],
  top_score: 0.91,
  retrieval_id: "00000000-0000-0000-0000-000000000001",
  bm25_count: 12,
  dense_count: 8,
  fused_count: 4,
};

function makeFakeFetch(
  response: unknown,
  init: { ok?: boolean; status?: number; bodyText?: string } = {},
): typeof fetch {
  return vi.fn(async (_url: RequestInfo | URL, _opts?: RequestInit) => {
    return new Response(
      init.bodyText ?? JSON.stringify(response),
      {
        status: init.status ?? 200,
        headers: { "content-type": "application/json" },
      },
    );
  });
}

describe("retrieve handler", () => {
  it("forwards query+filters+top_k to the bridge and returns the JSON payload", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      // Confirm the URL points at /retrieve and the body shape is right.
      expect(String(url)).toMatch(/\/retrieve$/);
      expect(opts?.method).toBe("POST");
      const body = JSON.parse(opts?.body as string);
      expect(body.query).toBe("Aviation Fund");
      expect(body.filters).toEqual({ fiscal_year: [2027] });
      expect(body.top_k).toBe(10);
      return new Response(JSON.stringify(fakeBridgeResponse), { status: 200 });
    });

    const handler = makeRetrieveHandler(loadConfig(), fetcher);
    const result = await handler({
      query: "Aviation Fund",
      filters: { fiscal_year: [2027] },
      top_k: 10,
    });

    expect(result.isError).toBeUndefined();
    expect(result.content).toHaveLength(1);
    expect(result.content[0]!.type).toBe("text");

    const decoded = JSON.parse(result.content[0]!.text as string);
    expect(decoded).toEqual(fakeBridgeResponse);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("omits top_k from the request body when caller omits it (sidecar default wins)", async () => {
    // Updated 2026-05-20 (Task 9): the Node handler used to default
    // top_k to 20 client-side, but that shadowed the sidecar's new
    // default of 15 (Task 8 / Decision Q2). The contract is now: if
    // the caller passes neither top_k nor intent, the body has no
    // top_k field and the sidecar uses DEFAULT_PIPELINE_TOP_K.
    const fetcher = vi.fn(async (_u: RequestInfo | URL, opts?: RequestInit) => {
      const body = JSON.parse(opts?.body as string);
      expect(body.filters).toBeNull();
      expect(body.top_k).toBeUndefined();
      expect(body.intent).toBeUndefined();
      return new Response(JSON.stringify(fakeBridgeResponse), { status: 200 });
    });

    const handler = makeRetrieveHandler(loadConfig(), fetcher);
    await handler({ query: "x" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("returns isError:true with a readable message on bridge HTTP error", async () => {
    const fetcher = makeFakeFetch(undefined, {
      status: 500,
      bodyText: "internal server error",
    });
    const handler = makeRetrieveHandler(loadConfig(), fetcher);
    const result = await handler({ query: "x" });
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toMatch(/retrieve\(\) failed/);
    expect(result.content[0]!.text).toMatch(/500/);
  });

  it("returns isError:true with a transport-error message when fetch throws", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError("ECONNREFUSED 127.0.0.1:9200");
    });
    const handler = makeRetrieveHandler(loadConfig(), fetcher);
    const result = await handler({ query: "x" });
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toMatch(/transport error/);
  });
});
