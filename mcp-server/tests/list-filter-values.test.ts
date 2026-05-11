// Unit tests for the list_filter_values tool. Stubbed fetcher; no
// real HTTP / Postgres calls.

import { describe, expect, it, vi } from "vitest";

import { loadConfig } from "../src/config.js";
import {
  listFilterValuesInputSchema,
  makeListFilterValuesHandler,
} from "../src/tools/list-filter-values.js";

describe("list_filter_values input schema", () => {
  it.each(["agency", "doc_type", "publisher", "fund"])(
    "accepts field=%s",
    (field) => {
      expect(() =>
        listFilterValuesInputSchema.parse({ field }),
      ).not.toThrow();
    },
  );

  it("rejects unknown field values", () => {
    expect(() =>
      listFilterValuesInputSchema.parse({ field: "chunk_id" }),
    ).toThrow();
  });

  it("rejects missing field", () => {
    expect(() => listFilterValuesInputSchema.parse({})).toThrow();
  });
});

describe("list_filter_values handler", () => {
  it("forwards field to /list_values and returns the JSON payload", async () => {
    const cfg = loadConfig();
    const fetcher = vi.fn(
      async (
        url: string,
        init?: { method?: string; body?: string },
      ): Promise<Response> => {
        expect(url.endsWith("/list_values")).toBe(true);
        expect(init?.method).toBe("POST");
        expect(JSON.parse(init?.body ?? "{}")).toEqual({
          field: "agency",
        });
        const body = JSON.stringify({
          field: "agency",
          values: [
            {
              canonical_id: "agency:axs",
              chunk_count: 351,
              sample_doc_title: "JLBC Baseline FY2027 — AHCCCS",
            },
            {
              canonical_id: "agency:tre",
              chunk_count: 239,
              sample_doc_title: "JLBC Baseline FY2027 — Treasurer",
            },
          ],
        });
        return new Response(body, {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      },
    );
    const handler = makeListFilterValuesHandler(cfg, fetcher as never);
    const result = await handler({ field: "agency" });
    expect(result.isError).toBeFalsy();
    const text = result.content[0]!.text;
    const parsed = JSON.parse(text);
    expect(parsed.field).toBe("agency");
    expect(parsed.values).toHaveLength(2);
    expect(parsed.values[0].canonical_id).toBe("agency:axs");
    expect(parsed.values[0].sample_doc_title).toContain("AHCCCS");
  });

  it("surfaces bridge errors as MCP tool errors", async () => {
    const cfg = loadConfig();
    const fetcher = vi.fn(
      async (): Promise<Response> => {
        throw new Error("ECONNREFUSED");
      },
    );
    const handler = makeListFilterValuesHandler(cfg, fetcher as never);
    const result = await handler({ field: "agency" });
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toContain("ECONNREFUSED");
  });
});
