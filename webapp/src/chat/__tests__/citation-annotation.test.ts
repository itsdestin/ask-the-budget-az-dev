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

  it("parses near_miss, ambiguity_count, link_basis and operation", () => {
    const figs = figuresForRender({
      figures: [{
        text: "$12.49B", start: 0, end: 7, index: 1, verdict: "unverified",
        primary: null, additional: [], derived_from: [],
        attested_chunk_ids: ["k1"], link_basis: null, ambiguity_count: null,
        operation: null,
        near_miss: { chunk_id: "k1", source_text: "12,515.4",
                     value: 12_515_400_000, distance: 0.002 },
      }],
    });
    expect(figs[0]!.nearMiss?.chunkId).toBe("k1");
    expect(figs[0]!.nearMiss?.sourceText).toBe("12,515.4");
    expect(figs[0]!.nearMiss?.distance).toBeCloseTo(0.002);
  });

  it("carries the basis a link was made on and a derived figure's operation", () => {
    const figs = figuresForRender({
      figures: [
        { text: "$8,287.7", start: 0, end: 8, index: 1, verdict: "linked",
          primary: null, additional: [], derived_from: [],
          link_basis: "tag", ambiguity_count: null, operation: null,
          near_miss: null },
        { text: "$17,654.2", start: 20, end: 29, index: 2, verdict: "derived",
          primary: null, additional: [], derived_from: [1],
          link_basis: null, ambiguity_count: null, operation: "sum",
          near_miss: null },
      ],
    });
    expect(figs[0]!.linkBasis).toBe("tag");
    expect(figs[1]!.operation).toBe("sum");
  });

  it("defaults the new fields to null on an annotation recorded before they existed", () => {
    // The annotation contract is extended, not broken: a transcript from
    // before attested linking carries none of these keys and must still
    // render rather than throw.
    const [first] = figuresForRender(ANNOTATION);
    expect(first!.linkBasis).toBeNull();
    expect(first!.ambiguityCount).toBeNull();
    expect(first!.operation).toBeNull();
    expect(first!.nearMiss).toBeNull();
  });

  it("drops a malformed near_miss instead of half-parsing it", () => {
    // A near-miss missing its value is not a near-miss an analyst can act
    // on, and a half-built one would render "differs by NaN%".
    const figs = figuresForRender({
      figures: [
        { text: "$1", start: 0, end: 2, index: 1, verdict: "unverified",
          primary: null, additional: [], derived_from: [],
          near_miss: { chunk_id: "k1", source_text: "12,515.4" },
          ambiguity_count: "three", link_basis: "sorcery", operation: 7 },
      ],
    });
    expect(figs[0]!.nearMiss).toBeNull();
    expect(figs[0]!.ambiguityCount).toBeNull();
    expect(figs[0]!.linkBasis).toBeNull();
    expect(figs[0]!.operation).toBeNull();
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
