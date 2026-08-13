import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExtractionChanges } from "./ExtractionChanges";

const SWAP = {
  job_id: "j1",
  title: "FY 2024 Annual Financial Report",
  kept: "mineru",
  attempts: [
    { extractor: "opendataloader", coverage: 0.4903, unlabelled: 0.3063 },
    { extractor: "mineru", coverage: 0.4477, unlabelled: 0.0 },
  ],
};

describe("ExtractionChanges", () => {
  it("renders nothing at all when no document changed method", () => {
    const { container } = render(<ExtractionChanges documents={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the method that was kept", () => {
    render(<ExtractionChanges documents={[SWAP]} />);
    expect(screen.getByTestId("adm-swap-kept")).toHaveTextContent("MinerU");
  });

  it("shows both numbers for every method tried, coverage before unlabelled", () => {
    render(<ExtractionChanges documents={[SWAP]} />);
    const rows = screen.getAllByTestId("adm-swap-attempt");
    expect(rows).toHaveLength(2);

    // Scoped to the numeric cells of EACH row, in DOM order -- not
    // "does 49% appear somewhere in this row's text". A prior version of
    // this test used whole-row toHaveTextContent substring checks, which
    // stayed green when a reviewer swapped the two
    // <span>{pct(...)}</span> lines in ExtractionChanges.tsx: unlabelled
    // rendered in the coverage position and vice versa, with every
    // assertion still passing because both numbers were still present
    // SOMEWHERE in the row.
    expect(rows[0]).toHaveTextContent("OpenDataLoader");
    const row0Cells = within(rows[0]).getAllByText(/^(not measured|\d+%)$/);
    expect(row0Cells[0]).toHaveTextContent("49%"); // coverage
    expect(row0Cells[1]).toHaveTextContent("31%"); // unlabelled

    expect(rows[1]).toHaveTextContent("MinerU");
    const row1Cells = within(rows[1]).getAllByText(/^(not measured|\d+%)$/);
    expect(row1Cells[0]).toHaveTextContent("45%"); // coverage
    expect(row1Cells[1]).toHaveTextContent("0%"); // unlabelled
  });

  it("renders an unmeasured structure score as words, never as 0%, beside its sibling coverage", () => {
    render(
      <ExtractionChanges
        documents={[{ ...SWAP, attempts: [
          { extractor: "mineru", coverage: 0.5, unlabelled: null },
        ] }]}
      />
    );
    const row = screen.getByTestId("adm-swap-attempt");
    // Position-scoped, same as above: the coverage cell must still read
    // its own real number in this same row, not just "not measured"
    // appearing somewhere in the row while coverage silently broke.
    const cells = within(row).getAllByText(/^(not measured|\d+%)$/);
    expect(cells[0]).toHaveTextContent("50%"); // coverage
    expect(cells[1]).toHaveTextContent("not measured"); // unlabelled
  });

  it("is styled as a card panel, like every other admin panel", () => {
    // Finding 4: this was the one admin panel with none of `.card`/
    // `.adm-panel`'s chrome and no gap between one swapped document's rows
    // and the next document's title -- jsdom applies no stylesheet, so this
    // only pins that the CLASSES are present, not how they render; a human
    // at a browser still has to confirm the paint.
    render(<ExtractionChanges documents={[SWAP]} />);
    expect(screen.getByTestId("adm-swaps")).toHaveClass("card", "adm-panel");
    expect(screen.getByTestId("adm-swap")).toHaveClass("adm-attention-item");
  });

  it("never describes the kept reading as verified, checked or healthy", () => {
    const { container } = render(<ExtractionChanges documents={[SWAP]} />);
    const text = container.textContent ?? "";
    for (const banned of [
      "verified", "checked", "validated", "healthy", "good",
    ]) {
      expect(text.toLowerCase()).not.toContain(banned);
    }
  });
});
