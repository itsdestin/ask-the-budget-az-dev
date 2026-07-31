// Unit tests for the HighlightStrategy interface and the
// TextLayerSearchStrategy that wraps pdfjs text-layer search. The
// strategy abstraction is the seam where the future #57 coord-map
// strategy will plug in.
//
// Carried verbatim from web/tests/highlight-strategy.test.ts (Plan 4 Task 11)
// — only the import path changed. These four cases are the specification for
// the strict-bbox rule; do not relax them.

import { describe, expect, it } from "vitest";

import {
  TextLayerSearchStrategy,
  type HighlightStrategy,
} from "../highlight-strategy";

/** Tiny fake pdfjs page proxy — just enough surface area to drive
 *  findTextRects. We don't need to render anything; we only need
 *  getTextContent() to return TextItem-shaped objects. */
function fakePage(
  items: Array<{
    str: string;
    x: number;
    y: number;
    width: number;
    height: number;
  }>,
) {
  return {
    async getTextContent() {
      return {
        items: items.map((it) => ({
          str: it.str,
          // transform = [scaleX, skewY, skewX, scaleY, x, y]
          transform: [1, 0, 0, 1, it.x, it.y],
          width: it.width,
          height: it.height,
          hasEOL: false,
        })),
      };
    },
  } as unknown as Parameters<HighlightStrategy["resolve"]>[0]["page"];
}

/** Fake viewport — convertToViewportRectangle is identity in CSS
 *  pixels for our purposes (no rotation, scale = 1). */
function fakeViewport() {
  return {
    scale: 1,
    convertToViewportRectangle: ([x1, y1, x2, y2]: number[]) => [x1, y1, x2, y2],
  } as unknown as Parameters<HighlightStrategy["resolve"]>[0]["viewport"];
}

describe("TextLayerSearchStrategy", () => {
  it("returns a rect for a match inside the chunk bbox", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        { str: "Aviation Fund", x: 50, y: 100, width: 80, height: 12 },
        { str: "$2,587,400", x: 140, y: 100, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "Aviation Fund $2,587,400",
      bbox: { left: 40, top: 90, width: 200, height: 30 },
    });
    expect(rects.length).toBe(1);
    // x ≈ 140, y ≈ 100, width ≈ 60.
    expect(rects[0]!.left).toBeCloseTo(140, 0);
    expect(rects[0]!.width).toBeCloseTo(60, 0);
  });

  it("returns [] when the quote isn't inside the bbox-restricted region", async () => {
    // The strict-bbox change: if the match is outside the bbox, we do
    // NOT fall back to a whole-page search. Honest miss.
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        // The $2,587,400 text is at x=500, y=600 — far outside the
        // chunk bbox supplied below.
        { str: "Aviation Fund", x: 500, y: 600, width: 80, height: 12 },
        { str: "$2,587,400", x: 580, y: 600, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "Aviation Fund $2,587,400",
      bbox: { left: 40, top: 90, width: 200, height: 30 },
    });
    expect(rects).toEqual([]);
  });

  it("returns [] when bbox is null and no items match the quote", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([{ str: "Unrelated", x: 50, y: 100, width: 60, height: 12 }]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "x",
      bbox: null,
    });
    expect(rects).toEqual([]);
  });

  it("returns rects when bbox is null but the quote matches anywhere on the page", async () => {
    // Without a bbox we fall back to whole-page search (legitimate use
    // — OpenDataLoader chunks sometimes lack a bbox).
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([{ str: "$2,587,400", x: 500, y: 600, width: 60, height: 12 }]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "$2,587,400",
      bbox: null,
    });
    expect(rects.length).toBe(1);
  });

  // Added in the port (Plan 4 Task 11): the multi-pass order is described in
  // STATUS.md's failure-mode catalog but was never pinned by a test, so a
  // refactor could have dropped a pass without anything going red.
  it("falls back to the full chunk text when the quote itself doesn't match", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        { str: "Aviation Fund appropriation", x: 50, y: 100, width: 140, height: 12 },
      ]),
      viewport: fakeViewport(),
      // Quote is absent from the text layer (extraction drift); the full
      // chunk text is present.
      quote: "Aviation Fund appropriation of $2,587,400",
      fullChunkText: "Aviation Fund appropriation",
      bbox: null,
    });
    expect(rects.length).toBe(1);
  });

  it("falls back to individual currency tokens when neither text matches", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        // Only the dollar amount survived the extractor intact.
        { str: "$2,587,400", x: 50, y: 100, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "the Aviation Fund received $2,587,400 in FY 2026",
      fullChunkText: "the Aviation Fund received $2,587,400 in FY 2026",
      bbox: null,
    });
    expect(rects.length).toBe(1);
    expect(rects[0]!.left).toBeCloseTo(50, 0);
  });

  it("keeps the currency fallback inside the bbox too", async () => {
    // The last pass must not become a back door around the strict-bbox rule:
    // a dollar amount elsewhere on the page is still the WRONG dollar amount.
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([{ str: "$2,587,400", x: 500, y: 600, width: 60, height: 12 }]),
      viewport: fakeViewport(),
      quote: "the Aviation Fund received $2,587,400 in FY 2026",
      fullChunkText: "the Aviation Fund received $2,587,400 in FY 2026",
      bbox: { left: 40, top: 90, width: 200, height: 30 },
    });
    expect(rects).toEqual([]);
  });
});
