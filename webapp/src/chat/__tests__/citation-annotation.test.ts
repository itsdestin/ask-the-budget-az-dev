/**
 * The annotation is the same artifact the eval judge reads. Parsing it
 * defensively matters because a turn recorded before citation linking
 * shipped has no annotation at all.
 */
import { describe, expect, it } from "vitest";
import { figuresForRender } from "../citation-annotation";

const ANNOTATION = {
  figures: [
    { text: "$8,287.7", start: 12, end: 20, index: 1, verdict: "linked",
      primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
      additional: [{ chunk_id: "c-2", source_text: "8,287,700,000", start: 5, end: 18 }],
      derived_from: [] },
    { text: "$17,654.2", start: 40, end: 49, index: 2, verdict: "derived",
      primary: null, additional: [], derived_from: [1] },
    { text: "$99.9", start: 60, end: 65, index: 3, verdict: "unverified",
      primary: null, additional: [], derived_from: [] },
  ],
};

describe("figuresForRender", () => {
  it("returns figures in reading order", () => {
    const figs = figuresForRender(ANNOTATION);
    expect(figs.map((f) => f.index)).toEqual([1, 2, 3]);
    expect(figs.map((f) => f.start)).toEqual([12, 40, 60]);
  });

  it("carries the primary source and its corroborating references", () => {
    const [first] = figuresForRender(ANNOTATION);
    expect(first.primary?.chunkId).toBe("c-1");
    expect(first.primary?.sourceText).toBe("8,287,700,000");
    expect(first.additional).toHaveLength(1);
    expect(first.additional[0]!.chunkId).toBe("c-2");
  });

  it("marks derived figures with their inputs and no source", () => {
    const derived = figuresForRender(ANNOTATION)[1]!;
    expect(derived.verdict).toBe("derived");
    expect(derived.primary).toBeNull();
    expect(derived.derivedFrom).toEqual([1]);
  });

  it("marks unverified figures", () => {
    expect(figuresForRender(ANNOTATION)[2]!.verdict).toBe("unverified");
  });

  it("returns nothing for a turn recorded before linking shipped", () => {
    expect(figuresForRender(undefined)).toEqual([]);
    expect(figuresForRender({})).toEqual([]);
    expect(figuresForRender({ figures: null })).toEqual([]);
  });

  it("drops malformed entries rather than throwing", () => {
    const figs = figuresForRender({ figures: ["nonsense", { verdict: "linked" }] });
    expect(figs).toEqual([]);
  });

  it("sorts into reading order even when the server emits out of order", () => {
    // The chip number an analyst reads must follow the page. Trusting
    // emission order is the exact defect that produced 1-3-4-2 chips.
    const figs = figuresForRender({
      figures: [
        { ...ANNOTATION.figures[2] },
        { ...ANNOTATION.figures[0] },
        { ...ANNOTATION.figures[1] },
      ],
    });
    expect(figs.map((f) => f.start)).toEqual([12, 40, 60]);
  });
});
