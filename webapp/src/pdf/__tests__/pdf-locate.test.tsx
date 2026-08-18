// Spec L2/L3/L4: the viewer consumes the server-side locate endpoint and
// the load-failure surface is a recoverable panel, not a red dead end.
//
// Measured 2026-08-18 on a live run: 44% of correctly linked figures
// rendered as "couldn't pinpoint" because the client text-layer chain
// searched inside a first-paragraph-only bbox, on a first-paragraph-only
// page, with un-swapped accounting parens. The locate endpoint (PyMuPDF on
// the real page) is the ground truth that fixes all three; these tests pin
// that the viewer TRUSTS it when it answers and IGNORES it when it doesn't.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HighlightRect, HighlightStrategy, ResolveArgs } from "../highlight-strategy";

vi.mock("pdfjs-dist", () => {
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({
      width: 612 * scale,
      height: 792 * scale,
      scale,
      // Identity for the serverRects path: the rects arrive in PDF
      // points and the component converts them through this.
      convertToViewportRectangle: (r: number[]) => r,
    }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }),
    getTextContent: async () => ({ items: [] }),
  };
  let loads = 0;
  const failNext = { value: false };
  return {
    GlobalWorkerOptions: {} as { workerPort?: unknown },
    getDocument: () => {
      loads += 1;
      if (failNext.value) {
        failNext.value = false; // one-shot: the retry must succeed
        return { promise: Promise.reject(new Error("Invalid PDF structure")) };
      }
      return { promise: Promise.resolve({ getPage: async () => page }) };
    },
    __test: {
      loadCount: () => loads,
      failNextLoad: () => {
        failNext.value = true;
      },
    },
  };
});

class FakeWorker {}
vi.stubGlobal("Worker", FakeWorker);

let pdfjsTest: {
  __test: { loadCount: () => number; failNextLoad: () => void };
};

function spyStrategy(result: HighlightRect[]) {
  const calls: ResolveArgs[] = [];
  const strategy: HighlightStrategy = {
    async resolve(args) {
      calls.push(args);
      return result;
    },
  };
  return { strategy, calls };
}

let PdfPage: typeof import("../PdfPage").default;

beforeEach(async () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    {} as unknown as CanvasRenderingContext2D,
  );
  PdfPage = (await import("../PdfPage")).default;
  pdfjsTest = (await import("pdfjs-dist")) as unknown as typeof pdfjsTest;
});

describe("PdfPage serverRects (spec L3)", () => {
  it("draws the server's rects and skips the text-layer strategy", async () => {
    const { strategy, calls } = spyStrategy([
      { left: 1, top: 1, width: 50, height: 10 },
    ]);
    const view = render(
      <PdfPage
        docId="doc-server"
        pageNumber={3}
        bbox={[0, 0, 900, 250]}
        searchTexts={["9,999"]}
        serverRects={[
          [390, 680, 560, 710],
          [80, 100, 300, 130],
        ]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() =>
      expect(view.container.querySelectorAll(".pdf-highlight").length).toBe(2),
    );
    // The server answer IS the ground truth — the client search must not
    // run at all, or it could overpaint/replace the located value.
    expect(calls.length).toBe(0);
    // No honest-miss badge alongside a located highlight.
    expect(view.container.textContent).not.toContain("couldn’t be pinpointed");
    const [first] = Array.from(
      view.container.querySelectorAll<HTMLElement>(".pdf-highlight"),
    );
    expect(first!.style.left).toBe("390px");
    expect(first!.style.top).toBe("680px");
  });

  it("falls through to the strategy when the server found nothing", async () => {
    const { strategy, calls } = spyStrategy([]);
    render(
      <PdfPage
        docId="doc-none"
        pageNumber={3}
        bbox={null}
        searchTexts={["42,424,242"]}
        serverRects={[]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() => expect(calls.length).toBe(1));
  });
});

describe("PdfPage load-failure panel (spec L4)", () => {
  it("leads with Open document and Retry instead of a red overlay", async () => {
    pdfjsTest.__test.failNextLoad();
    const view = render(
      <PdfPage
        docId="doc-broken"
        pageNumber={12}
        bbox={null}
        searchTexts={["1,234,567"]}
        containerWidth={612}
      />,
    );
    await waitFor(() =>
      expect(view.container.textContent).toContain("Couldn’t open this page"),
    );
    // The raw file link is always accurate — it is the document itself.
    const open = view.container.querySelector("a.pdf-open-original");
    expect(open).not.toBeNull();
    expect(open!.getAttribute("href")).toContain("/api/pdf/doc-broken#page=12");
    // The verbatim passage promise: the cited text below is still the source.
    expect(view.container.textContent).toContain("verbatim passage");
    // The raw error survives only as a small detail line under the
    // plain-language panel — it is no longer the surface itself.
    expect(view.container.textContent).toContain("page 12: Invalid PDF structure");
    expect(view.container.querySelector(".pdf-load-failed-detail")).not.toBeNull();
  });

  it("Retry re-runs the load", async () => {
    pdfjsTest.__test.failNextLoad();
    const view = render(
      <PdfPage
        docId="doc-retry"
        pageNumber={4}
        bbox={null}
        searchTexts={["1,234,567"]}
        containerWidth={612}
      />,
    );
    await waitFor(() =>
      expect(view.container.textContent).toContain("Couldn’t open this page"),
    );
    const before = pdfjsTest.__test.loadCount();
    fireEvent.click(view.container.querySelector(".pdf-retry-btn")!);
    await waitFor(() => expect(pdfjsTest.__test.loadCount()).toBeGreaterThan(before));
    // Second attempt succeeds (failNext was one-shot): the panel clears.
    await waitFor(() =>
      expect(view.container.textContent).not.toContain("Couldn’t open this page"),
    );
  });
});

// ---------------------------------------------------------------------------
// PdfViewer wiring: locate + fetched text ride the click-time check
// ---------------------------------------------------------------------------

import PdfViewer from "../PdfViewer";
import {
  CitationBusProvider,
  useCitationBus,
  type CitationBus,
} from "../../chat/citation-context";
import type { Citation } from "../../chat/citation-extract";

/** A figure chip's citation: the annotation carries locators but NO chunk
 *  body (by design), and sourceText is the value as the source renders it. */
function figureCitation(): Citation {
  return {
    index: 1,
    chunkId: "jlbc-baseline-fy2024-ade-0087",
    spanStart: 0,
    spanEnd: 9,
    confidence: "verbatim",
    claimSpan: "$200.2M",
    sourceText: "200,168,100",
    resolved: {
      docId: "jlbc-baseline-fy2024-ade",
      docTitle: "ADE Baseline",
      publisher: "jlbc",
      fiscalYear: 2024,
      docType: "baseline-per-agency",
      pageStart: 17,
      pageEnd: 17,
      bbox: [76, 272, 446, 334],
      text: "",
    },
  };
}

function mountViewerWithFetch(routes: Record<string, unknown | { status: number }>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [prefix, body] of Object.entries(routes)) {
      if (url.includes(prefix)) {
        if (typeof body === "object" && body !== null && "status" in body) {
          return new Response(JSON.stringify({ detail: "boom" }), {
            status: (body as { status: number }).status,
          });
        }
        return new Response(JSON.stringify(body), { status: 200 });
      }
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);

  let bus: CitationBus | null = null;
  function BusProbe() {
    bus = useCitationBus();
    return null;
  }
  const view = render(
    <CitationBusProvider>
      <BusProbe />
      <PdfViewer />
    </CitationBusProvider>,
  );
  return {
    view,
    fetchMock,
    select: (c: Citation) => act(() => bus!.select(c)),
  };
}

describe("PdfViewer locate consumption (spec L2/L3)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal("Worker", FakeWorker);
  });

  it("shows the locate endpoint's page and hydrates the cited-text panel", async () => {
    const { view, select, fetchMock } = mountViewerWithFetch({
      "/api/chunks/jlbc-baseline-fy2024-ade-0087?": {
        chunk_id: "jlbc-baseline-fy2024-ade-0087",
        doc_id: "jlbc-baseline-fy2024-ade",
        page: 17,
        bbox: [76, 272, 446, 334],
        text: "FY 2023 Supplemental … An increase of $200,000,000 … 200,168,100 carried.",
        source_anchor: null,
        source_format: "pdf",
        pdf_unavailable_reason: null,
      },
      "/locate": {
        chunk_id: "jlbc-baseline-fy2024-ade-0087",
        page: 17,
        rects: [[218, 362, 268, 375]],
        basis: "scan",
      },
    });
    select(figureCitation());

    // The breadcrumb renders the LOCATE page (here equal; the wrong-page
    // case is pinned at the SourceView level by serverPage winning).
    await waitFor(() =>
      expect(view.container.textContent).toContain("ADE Baseline"),
    );
    // The click-time check asked for locate with the source rendering.
    await waitFor(() =>
      expect(
        Array.from(fetchMock.mock.calls).some(([u]) =>
          String(u).includes("/locate") && String(u).includes("200%2C168%2C100"),
        ),
      ).toBe(true),
    );
    // The cited-text panel is hydrated from the fetched chunk body even
    // though the figure chip's annotation carried no text.
    await waitFor(() =>
      expect(view.container.textContent).toContain("FY 2023 Supplemental"),
    );
  });

  it("a locate failure leaves the existing chain intact", async () => {
    const { view, select } = mountViewerWithFetch({
      "/api/chunks/jlbc-baseline-fy2024-ade-0087?": {
        chunk_id: "jlbc-baseline-fy2024-ade-0087",
        doc_id: "jlbc-baseline-fy2024-ade",
        page: 17,
        bbox: null,
        text: "some passage text",
        source_anchor: null,
        source_format: "pdf",
        pdf_unavailable_reason: null,
      },
      "/locate": { status: 500 },
    });
    select(figureCitation());
    // The viewer still loads the stored page — locate's 500 degraded to
    // null and nothing errored the provenance surface out.
    await waitFor(() =>
      expect(view.container.textContent).toContain("ADE Baseline"),
    );
    await waitFor(() =>
      expect(view.container.textContent).toContain("some passage text"),
    );
  });
});
