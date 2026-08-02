/**
 * The PDF text layer contains the SOURCE's rendering of a figure
 * ("8,287,700,000"), never the answer's ("$8,287.7"). Searching for the
 * answer's form is why highlights missed.
 */
import { describe, expect, it, vi } from "vitest";
import { TextLayerSearchStrategy } from "../highlight-strategy";

function fakePage(textItems: string[]) {
  return {
    getTextContent: vi.fn().mockResolvedValue({
      items: textItems.map((str) => ({
        str,
        transform: [1, 0, 0, 1, 0, 0],
        width: 10,
        height: 5,
      })),
    }),
  } as never;
}

const viewport = {
  convertToViewportRectangle: (r: number[]) => r,
  height: 800,
} as never;

describe("TextLayerSearchStrategy", () => {
  it("finds the source rendering when given sourceText", async () => {
    const page = fakePage(["Department of Education", "8,287,700,000"]);
    const rects = await new TextLayerSearchStrategy().resolve({
      page, viewport, quote: "$8,287.7", sourceText: "8,287,700,000",
      fullChunkText: "", bbox: null,
    } as never);
    expect(rects.length).toBeGreaterThan(0);
  });

  it("prefers sourceText over the answer's rendering", async () => {
    const page = fakePage(["8,287,700,000"]);
    const strategy = new TextLayerSearchStrategy();
    const withSource = await strategy.resolve({
      page, viewport, quote: "$8,287.7", sourceText: "8,287,700,000",
      fullChunkText: "", bbox: null,
    } as never);
    const withoutSource = await strategy.resolve({
      page, viewport, quote: "$8,287.7", fullChunkText: "", bbox: null,
    } as never);
    expect(withSource.length).toBeGreaterThan(0);
    expect(withoutSource.length).toBe(0);
  });

  it("still works for a prose citation that carries no sourceText", async () => {
    // cite()/cite_batch survive for non-numeric claims and pass no
    // sourceText. Adding the field must not change their path.
    const page = fakePage(["the program shall be administered by the department"]);
    const rects = await new TextLayerSearchStrategy().resolve({
      page, viewport, quote: "administered by the department",
      fullChunkText: "", bbox: null,
    } as never);
    expect(rects.length).toBeGreaterThan(0);
  });
});
