import { render, screen } from "@testing-library/react";
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

  it("shows both numbers for every method tried", () => {
    render(<ExtractionChanges documents={[SWAP]} />);
    const rows = screen.getAllByTestId("adm-swap-attempt");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("OpenDataLoader");
    expect(rows[0]).toHaveTextContent("49%");
    expect(rows[0]).toHaveTextContent("31%");
    expect(rows[1]).toHaveTextContent("MinerU");
    expect(rows[1]).toHaveTextContent("0%");
  });

  it("renders an unmeasured structure score as words, never as 0%", () => {
    render(
      <ExtractionChanges
        documents={[{ ...SWAP, attempts: [
          { extractor: "mineru", coverage: 0.5, unlabelled: null },
        ] }]}
      />
    );
    expect(screen.getByTestId("adm-swap-attempt")).toHaveTextContent(
      "not measured"
    );
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
