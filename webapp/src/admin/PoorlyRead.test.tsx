import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PoorlyRead } from "./PoorlyRead";

const DOC = {
  job_id: "j1",
  title: "FY 2026 budget bill",
  kept: "docx",
  unlabelled: 0.4412,
  coverage: 0.8834,
};

describe("PoorlyRead", () => {
  it("renders nothing at all when no document is over the ceiling", () => {
    // Same rule as the two panels above it: a box on screen every day
    // teaches an admin to scroll past it. `toBeEmptyDOMElement`, not
    // "the heading is absent" — a panel that rendered its heading and an
    // empty list would pass the weaker check.
    const { container } = render(<PoorlyRead documents={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says how much of the document is figures with no words", () => {
    render(<PoorlyRead documents={[DOC]} />);
    expect(screen.getByTestId("adm-poorly-read-share")).toHaveTextContent("44%");
  });

  it("names the method the text was read with", () => {
    // The raw slug would be `docx`. An admin reading a defect report needs
    // the name a person would recognise.
    render(<PoorlyRead documents={[{ ...DOC, kept: "mineru" }]} />);
    expect(screen.getByTestId("adm-poorly-read-doc")).toHaveTextContent("MinerU");
  });

  it("shows how much text came out BESIDE how much of it was bare", () => {
    // The two numbers DISAGREE — that is the entire reason the structure
    // measure exists (the document that motivated it read 49% on coverage
    // and 31% bare). A panel showing only the flattering one recreates the
    // blindness it was built to fix, so both must be on the page.
    render(<PoorlyRead documents={[DOC]} />);
    const row = screen.getByTestId("adm-poorly-read-doc");
    expect(within(row).getByText(/88%/)).toBeInTheDocument();
    expect(within(row).getByText(/44%/)).toBeInTheDocument();
  });

  it("renders an unmeasured coverage as 'not measured', never as 0%", () => {
    // 0% would claim a worse reading than was actually taken. The rule is
    // shared with every other extraction surface (ingest/coverage.py).
    render(<PoorlyRead documents={[{ ...DOC, coverage: null }]} />);
    const row = screen.getByTestId("adm-poorly-read-doc");
    expect(within(row).getByText(/not measured/)).toBeInTheDocument();
    expect(within(row).queryByText(/\b0%/)).not.toBeInTheDocument();
  });

  it("counts the documents in the heading", () => {
    render(<PoorlyRead documents={[DOC, { ...DOC, job_id: "j2" }]} />);
    expect(screen.getByTestId("adm-poorly-read-count")).toHaveTextContent("2");
    expect(screen.getAllByTestId("adm-poorly-read-doc")).toHaveLength(2);
  });

  it("offers no button, because no button on this screen would help", () => {
    // The ladder has already run every method it has, so a re-process
    // gives the same answer; the action that helps (a cleaner source file)
    // is not something this screen can perform. A button that changes
    // nothing is worse than no button — it spends the admin's trust once
    // and teaches them the panel is decorative.
    render(<PoorlyRead documents={[DOC]} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("never claims the documents it does not list are fine", () => {
    // The panel's silence means "nothing ingested since this measure
    // shipped scored badly" — NOT "the corpus is clean". Every document
    // ingested before it has no measurement recorded and can never appear
    // here. Nothing rendered may say verified / checked / validated /
    // healthy / good: this measure detects ONE failure shape and certifies
    // nothing (a passage scoring a perfect 0% has been observed carrying a
    // units label wrong by a factor of 1,000).
    const { container } = render(<PoorlyRead documents={[DOC]} />);
    const text = container.textContent ?? "";
    for (const banned of [
      "verified",
      "checked",
      "validated",
      "healthy",
      "good",
      "clean",
    ]) {
      expect(text.toLowerCase()).not.toContain(banned);
    }
  });
});
