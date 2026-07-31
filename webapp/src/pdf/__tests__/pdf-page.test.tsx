// PdfPage's two load-bearing behaviors, pinned in jsdom by mocking pdfjs
// itself (jsdom cannot rasterize a PDF, and never could — the retired app's
// suite didn't cover this component at all, which is why the strict-bbox fix
// and the "couldn't pinpoint" badge had no regression net until now):
//
//   1. the chunk's bbox reaches the highlight strategy, so the text-layer
//      search is restricted to it rather than roaming the page;
//   2. an empty result from the strategy renders the honest badge and NO
//      highlight rectangle — the 2026-05-12 regression was a yellow box drawn
//      over an unrelated dollar amount, and silence is the correct answer.
//
// The pdfjs mock is deliberately thin: getDocument -> a page that reports a
// letter-size viewport and resolves its render immediately. Everything this
// test asserts happens after that.

import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HighlightRect, HighlightStrategy, ResolveArgs } from "../highlight-strategy";

vi.mock("pdfjs-dist", () => {
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({
      width: 612 * scale,
      height: 792 * scale,
      scale,
    }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }),
    getTextContent: async () => ({ items: [] }),
  };
  return {
    GlobalWorkerOptions: {} as { workerPort?: unknown },
    getDocument: () => ({ promise: Promise.resolve({ getPage: async () => page }) }),
  };
});

// PdfPage constructs the pdfjs worker; jsdom has no Worker constructor and no
// canvas 2D context. Both are environment gaps, not behavior — stub them.
class FakeWorker {}
vi.stubGlobal("Worker", FakeWorker);

/** Records what PdfPage asked for and answers with a canned result. */
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
});

describe("PdfPage", () => {
  it("restricts the highlight search to the chunk's bbox (MinerU normalized)", async () => {
    const { strategy, calls } = spyStrategy([]);
    render(
      <PdfPage
        docId="doc-A"
        pageNumber={3}
        // MinerU's 0-1000 per-axis space. It is recognized as normalized
        // BECAUSE 900 exceeds the page's larger dimension in points (792);
        // that comparison is the whole auto-detect, so the fixture has to
        // clear it or the values are read as points instead.
        bbox={[0, 0, 900, 250]}
        searchTexts={["$2,587,400", "chunk text"]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() => expect(calls.length).toBe(1));
    const { bbox, quote, fullChunkText } = calls[0]!;
    // Non-null bbox is what makes the search strict; null would silently
    // re-enable the whole-page roam this component removed.
    expect(bbox).not.toBeNull();
    expect(bbox!.left).toBeCloseTo(0, 0);
    expect(bbox!.width).toBeCloseTo(550.8, 0); // 900/1000 * 612pt at scale 1
    expect(bbox!.height).toBeCloseTo(198, 0); // 250/1000 * 792pt at scale 1
    // Multi-pass order: the cited quote first, the full chunk text second.
    expect(quote).toBe("$2,587,400");
    expect(fullChunkText).toBe("chunk text");
  });

  it("reads a bbox that fits inside the page as PDF points (OpenDataLoader)", async () => {
    // The other half of the auto-detect. Same numbers, different meaning:
    // every value here is within the page's point dimensions, so they are
    // taken literally instead of being divided by 1000.
    const { strategy, calls } = spyStrategy([]);
    render(
      <PdfPage
        docId="doc-A"
        pageNumber={3}
        bbox={[72, 100, 540, 160]}
        searchTexts={["$2,587,400"]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() => expect(calls.length).toBe(1));
    const { bbox } = calls[0]!;
    expect(bbox!.left).toBeCloseTo(72, 0);
    expect(bbox!.width).toBeCloseTo(468, 0);
    expect(bbox!.height).toBeCloseTo(60, 0);
  });

  it("shows the couldn't-pinpoint badge and draws nothing when the search misses", async () => {
    const { strategy } = spyStrategy([]);
    const view = render(
      <PdfPage
        docId="doc-A"
        pageNumber={3}
        bbox={[0, 0, 500, 125]}
        searchTexts={["$2,587,400"]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() =>
      expect(view.container.textContent).toContain(
        "exact text couldn’t be pinpointed",
      ),
    );
    expect(view.container.querySelectorAll(".pdf-highlight").length).toBe(0);
  });

  it("draws one highlight per rect the strategy returns", async () => {
    const { strategy } = spyStrategy([
      { left: 10, top: 20, width: 100, height: 12 },
      { left: 10, top: 40, width: 60, height: 12 },
    ]);
    const view = render(
      <PdfPage
        docId="doc-A"
        pageNumber={3}
        bbox={null}
        searchTexts={["$2,587,400"]}
        containerWidth={612}
        strategy={strategy}
      />,
    );
    await waitFor(() =>
      expect(view.container.querySelectorAll(".pdf-highlight").length).toBe(2),
    );
    expect(view.container.textContent).not.toContain("couldn’t be pinpointed");
  });
});
