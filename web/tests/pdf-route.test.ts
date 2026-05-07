// Tests for the /api/pdf/[doc_id] Range-aware streamer. The pure
// `parseRangeHeader` helper covers the spec branches; the GET
// handler is exercised with a temp file + a stubbed `fetch` so we
// can confirm Range requests produce 206 + the right Content-Range
// header without spinning up the FastAPI sidecar.

import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { GET, parseRangeHeader } from "../app/api/pdf/[doc_id]/route";

const TEST_BYTES = Buffer.alloc(1024, 0x41); // "AAAA…" — 1KB stand-in for a PDF.
let tmpFile: string;

beforeAll(async () => {
  // The route uses fs.stat / createReadStream against an absolute path,
  // so the smoke tests need a real file on disk. tmpdir() is wiped on
  // afterAll; nothing leaves the runner.
  tmpFile = path.join(os.tmpdir(), `budget-pdf-${process.pid}.bin`);
  await fs.writeFile(tmpFile, TEST_BYTES);
});

afterAll(async () => {
  await fs.rm(tmpFile, { force: true });
});

function makeFetchMock(body: unknown, status = 200) {
  // Returns a fetch() implementation that echoes the same response
  // for every call — fine for these tests since each test only
  // reaches `/docs/{doc_id}` once.
  return vi.fn(async () => {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
}

function ctxFor(docId: string) {
  return { params: Promise.resolve({ doc_id: docId }) };
}

describe("parseRangeHeader", () => {
  const SIZE = 1000;

  it("returns null when no header is present", () => {
    expect(parseRangeHeader(null, SIZE)).toBeNull();
  });

  it("rejects non-bytes range units", () => {
    expect(parseRangeHeader("octets=0-9", SIZE)).toBeNull();
  });

  it("parses a closed range (bytes=0-99)", () => {
    expect(parseRangeHeader("bytes=0-99", SIZE)).toEqual({
      start: 0,
      end: 99,
    });
  });

  it("parses an open-ended range (bytes=500-)", () => {
    expect(parseRangeHeader("bytes=500-", SIZE)).toEqual({
      start: 500,
      end: 999,
    });
  });

  it("parses a suffix range (bytes=-200 → last 200 bytes)", () => {
    expect(parseRangeHeader("bytes=-200", SIZE)).toEqual({
      start: 800,
      end: 999,
    });
  });

  it("clamps an overshooting end to size-1", () => {
    // PDF.js sometimes asks for ranges past EOF; clamping is more
    // forgiving than 416 and matches what production HTTP servers do.
    expect(parseRangeHeader("bytes=100-9999", SIZE)).toEqual({
      start: 100,
      end: 999,
    });
  });

  it("rejects a start past EOF", () => {
    expect(parseRangeHeader("bytes=2000-2099", SIZE)).toBeNull();
  });

  it("rejects an inverted range (end < start)", () => {
    expect(parseRangeHeader("bytes=500-100", SIZE)).toBeNull();
  });
});

describe("GET /api/pdf/[doc_id]", () => {
  const ORIG_FETCH = globalThis.fetch;
  afterAll(() => {
    globalThis.fetch = ORIG_FETCH;
  });

  it("returns 404 when the sidecar reports doc not found", async () => {
    globalThis.fetch = makeFetchMock({ detail: "doc_id not found" }, 404);
    const req = new Request("http://localhost/api/pdf/ghost");
    const res = await GET(req, ctxFor("ghost"));
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("doc_not_found");
  });

  it("returns 502 when the sidecar is unreachable / errors", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const req = new Request("http://localhost/api/pdf/x");
    const res = await GET(req, ctxFor("x"));
    expect(res.status).toBe(502);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("retrieval_bridge_unreachable");
  });

  it("returns 415 for non-PDF source formats (DOCX bills)", async () => {
    globalThis.fetch = makeFetchMock({
      doc_id: "bill-A",
      title: "SB1234",
      publisher: "legislature",
      doc_type: "budget-bill",
      fiscal_year: 2025,
      source_format: "docx",
      source_blob_path: tmpFile,
    });
    const req = new Request("http://localhost/api/pdf/bill-A");
    const res = await GET(req, ctxFor("bill-A"));
    expect(res.status).toBe(415);
    const body = (await res.json()) as { source_format: string };
    expect(body.source_format).toBe("docx");
  });

  it("returns 500 when the source file is missing on disk", async () => {
    globalThis.fetch = makeFetchMock({
      doc_id: "d1",
      title: "Foo",
      publisher: "jlbc",
      doc_type: "baseline-cross-cut",
      fiscal_year: 2024,
      source_format: "pdf",
      source_blob_path: path.join(os.tmpdir(), "this-does-not-exist.pdf"),
    });
    const req = new Request("http://localhost/api/pdf/d1");
    const res = await GET(req, ctxFor("d1"));
    expect(res.status).toBe(500);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("source_blob_missing");
  });

  it("streams full body with 200 + Accept-Ranges when no Range header", async () => {
    globalThis.fetch = makeFetchMock({
      doc_id: "d1",
      title: "Foo",
      publisher: "jlbc",
      doc_type: "baseline-cross-cut",
      fiscal_year: 2024,
      source_format: "pdf",
      source_blob_path: tmpFile,
    });
    const req = new Request("http://localhost/api/pdf/d1");
    const res = await GET(req, ctxFor("d1"));
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("application/pdf");
    expect(res.headers.get("Accept-Ranges")).toBe("bytes");
    expect(res.headers.get("Content-Length")).toBe(String(TEST_BYTES.length));
    const buf = Buffer.from(await res.arrayBuffer());
    expect(buf.length).toBe(TEST_BYTES.length);
  });

  it("streams the requested range with 206 + Content-Range when Range present", async () => {
    globalThis.fetch = makeFetchMock({
      doc_id: "d1",
      title: "Foo",
      publisher: "jlbc",
      doc_type: "baseline-cross-cut",
      fiscal_year: 2024,
      source_format: "pdf",
      source_blob_path: tmpFile,
    });
    const req = new Request("http://localhost/api/pdf/d1", {
      headers: { range: "bytes=100-199" },
    });
    const res = await GET(req, ctxFor("d1"));
    expect(res.status).toBe(206);
    expect(res.headers.get("Content-Length")).toBe("100");
    expect(res.headers.get("Content-Range")).toBe(
      `bytes 100-199/${TEST_BYTES.length}`,
    );
    const buf = Buffer.from(await res.arrayBuffer());
    expect(buf.length).toBe(100);
    expect(buf[0]).toBe(0x41);
  });
});
