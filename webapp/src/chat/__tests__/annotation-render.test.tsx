/**
 * Chips come from the server annotation, land on the figure they support,
 * and are numbered in reading order. The reported defect was a ten-row
 * table with two chips numbered 1-3-4-2; this is the test that fails if
 * that returns.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CitedMarkdownContent from "../CitedMarkdownContent";

const ANSWER =
  "ADE gets $8,287.7 and $2,613.7, totalling $10,901.4; also $99,999.9.";

// Offsets are DERIVED from the answer, never hand-typed. A fixture whose
// offsets do not slice to its own text is not something the linker can
// emit, so a renderer proved against one proves nothing.
function at(text: string) {
  const start = ANSWER.indexOf(text);
  return { start, end: start + text.length };
}

const ANNOTATION = {
  figures: [
    { text: "$8,287.7", ...at("$8,287.7"), index: 1, verdict: "linked",
      primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
      additional: [{ chunk_id: "c-2", source_text: "8,287,700,000", start: 0, end: 13 }],
      derived_from: [] },
    { text: "$2,613.7", ...at("$2,613.7"), index: 2, verdict: "linked",
      primary: { chunk_id: "c-3", source_text: "2,613,700,000", start: 0, end: 13 },
      additional: [], derived_from: [] },
    { text: "$10,901.4", ...at("$10,901.4"), index: 3, verdict: "derived",
      primary: null, additional: [], derived_from: [1, 2] },
    { text: "$99,999.9", ...at("$99,999.9"), index: 4, verdict: "unverified",
      primary: null, additional: [], derived_from: [] },
  ],
};

describe("annotation rendering", () => {
  it("the fixture offsets index the fixture answer", () => {
    for (const f of ANNOTATION.figures) {
      expect(ANSWER.slice(f.start, f.end)).toBe(f.text);
    }
  });

  it("renders one chip per CITATION, numbered in reading order", () => {
    // Unverified figures draw no chip: nothing was sourced, so a numbered
    // marker would claim provenance the system does not have, and a run of
    // them buries the real citations. No count is shown either — a number
    // with no chip is already visibly uncited.
    render(
      <CitedMarkdownContent content={ANSWER} annotation={ANNOTATION} citations={[]} />,
    );
    const chips = screen.getAllByTestId("citation-chip");
    expect(chips).toHaveLength(3);
    expect(chips.map((c) => c.textContent)).toEqual(["1", "2", "3"]);
  });

  it("marks a derived figure distinctly and draws nothing for an unverified one", () => {
    render(
      <CitedMarkdownContent content={ANSWER} annotation={ANNOTATION} citations={[]} />,
    );
    expect(screen.getByTestId("citation-chip-derived-3")).toBeTruthy();
    expect(screen.queryByTestId("citation-chip-unverified-4")).toBeNull();
  });

  it("renders nothing extra for a turn with no annotation", () => {
    render(
      <CitedMarkdownContent content={ANSWER} annotation={{ figures: [] }} citations={[]} />,
    );
    expect(screen.queryAllByTestId("citation-chip")).toHaveLength(0);
  });

  it("places chips inside a markdown table rather than dropping them", () => {
    // The reported defect was a ten-row table. A chip that cannot survive
    // a table cell fixes nothing.
    const table =
      "| Agency | Amount |\n|---|---|\n| ADE | $8,287.7 |\n| AHCCCS | $2,613.7 |\n";
    const annotation = {
      figures: [
        { text: "$8,287.7", start: table.indexOf("$8,287.7"),
          end: table.indexOf("$8,287.7") + 8, index: 1, verdict: "linked",
          primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
          additional: [], derived_from: [] },
        { text: "$2,613.7", start: table.indexOf("$2,613.7"),
          end: table.indexOf("$2,613.7") + 8, index: 2, verdict: "linked",
          primary: { chunk_id: "c-2", source_text: "2,613,700,000", start: 0, end: 13 },
          additional: [], derived_from: [] },
      ],
    };
    render(
      <CitedMarkdownContent content={table} annotation={annotation} citations={[]} />,
    );
    expect(screen.getAllByTestId("citation-chip").map((c) => c.textContent))
      .toEqual(["1", "2"]);
  });

  it("still chips correctly when offsets belong to a different block", () => {
    // Annotation offsets index the whole finalAnswer; this renderer gets
    // one block. Offsets that do not slice to the figure must fall back to
    // finding the text rather than chipping the wrong characters.
    const block = "The enacted figure was $8,287.7 for ADE.";
    const annotation = {
      figures: [
        { text: "$8,287.7", start: 900, end: 908, index: 1, verdict: "linked",
          primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
          additional: [], derived_from: [] },
      ],
    };
    render(
      <CitedMarkdownContent content={block} annotation={annotation} citations={[]} />,
    );
    const chip = screen.getByTestId("citation-chip");
    expect(chip.textContent).toBe("1");
    // The chip's accessible name names the figure it sits on, so a
    // misplacement is detectable rather than merely invisible.
    expect(chip.getAttribute("aria-label")).toContain("$8,287.7");
  });
});
