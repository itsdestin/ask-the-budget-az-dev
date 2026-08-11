// H5 as amended: the viewer checks at click time whether the citation's
// source still resolves, and treats two shapes as unresolvable.
import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import PdfViewer from "../PdfViewer";
import {
  CitationBusProvider,
  useCitationBus,
} from "../../chat/citation-context";
import type { Citation } from "../../chat/citation-extract";

function citation(over: Partial<Citation> = {}): Citation {
  return {
    index: 1,
    chunkId: "chunk-1",
    spanStart: 0,
    spanEnd: 5,
    confidence: "verbatim",
    claimSpan: "hello",
    resolved: {
      docId: "doc-A",
      docTitle: "Budget Report",
      publisher: "JLBC",
      fiscalYear: 2024,
      docType: "report",
      pageStart: 47,
      pageEnd: 47,
      bbox: [10, 20, 100, 40],
      text: "hello world",
    },
    ...over,
  };
}

function mountWithBus(c: Citation) {
  function Driver() {
    const bus = useCitationBus();
    useEffect(() => {
      bus.select(c);
    }, [bus, c]);
    return <PdfViewer corpus="budget" />;
  }
  return render(
    <CitationBusProvider>
      <Driver />
    </CitationBusProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PdfViewer stale-citation detection (H5)", () => {
  it("404 → unresolvable 'gone'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/api/chunks/")) {
          return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );
    const { container } = mountWithBus(citation());
    await waitFor(() => {
      expect(container.textContent).toContain("Source no longer available");
    });
    // Does NOT render the loaded PDF
    expect(container.querySelector("canvas")).toBeNull();
    expect(container.textContent).toContain("chunk-1");
  });

  it("200 but the stored quote is gone → unresolvable 'moved'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/api/chunks/")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              chunk_id: "chunk-1",
              doc_id: "doc-A",
              page: 47,
              bbox: null,
              text: "the passage has completely changed",
              source_format: "pdf",
              pdf_unavailable_reason: null,
            }),
          };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );
    const { container } = mountWithBus(citation());
    await waitFor(() => {
      expect(container.textContent).toContain("Source no longer available");
    });
    expect(container.textContent).toContain("updated since the citation");
  });

  it("200 and the quote is present → today's behaviour, unchanged", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/api/chunks/")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              chunk_id: "chunk-1",
              doc_id: "doc-A",
              page: 47,
              bbox: [10, 20, 100, 40],
              text: "hello world",
              source_format: "pdf",
              pdf_unavailable_reason: null,
            }),
          };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );
    const { container } = mountWithBus(citation());
    // The loaded state should render — NOT the stale state
    await waitFor(() => {
      expect(container.textContent).toContain("Budget Report");
    });
    expect(container.textContent).not.toContain("Source no longer available");
  });

  it("nothing is fetched until a citation is selected", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <CitationBusProvider>
        <PdfViewer corpus="budget" />
      </CitationBusProvider>,
    );
    expect(screen.getByText("Click a citation to see its source.")).toBeInTheDocument();
    // No chunk fetch should have happened yet
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/chunks/"),
      expect.anything(),
    );
  });

  it("a 503 is NOT reported as a stale citation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown) => {
        const u = String(_url);
        if (u.includes("/api/chunks/")) {
          return { ok: false, status: 503, json: async () => ({ detail: "share offline" }) };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );
    const { container } = mountWithBus(citation());
    // Wait a moment to ensure no stale state renders
    await new Promise((r) => setTimeout(r, 100));
    expect(container.textContent).not.toContain("Source no longer available");
    // The loaded state should still be showing (the original render)
    expect(container.textContent).toContain("Budget Report");
  });
});
