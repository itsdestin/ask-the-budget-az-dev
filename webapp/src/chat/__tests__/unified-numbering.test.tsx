/**
 * ONE numbering sequence across both kinds of mark.
 *
 * Citation linking introduced a second, independent sequence: figures are
 * numbered 1..N by the server annotation while model prose citations are
 * numbered 1..M by the webapp. Rendered in the same answer, nothing
 * reconciles them — a "4" appears under figures numbered 1-3 and means
 * something unrelated, and a prose [1] and a figure [1] can coexist
 * pointing at different sources. Seen in a browser 2026-08-02.
 *
 * The number an analyst reads must mean "the Nth mark down this answer".
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CitedMarkdownContent from "../CitedMarkdownContent";
import type { Citation } from "../citation-extract";

const ANSWER =
  "ADOT received $1,391,157,700 for highways. The program is administered " +
  "by the department under statute. A further $2,613,700,000 went to transit.";

function figureAt(text: string, index: number) {
  const start = ANSWER.indexOf(text);
  return {
    text, start, end: start + text.length, index, verdict: "linked",
    primary: {
      chunk_id: `c-${index}`, source_text: text.replace("$", ""),
      start: 0, end: 13, doc_id: `d-${index}`, doc_type: "approps-per-agency",
      doc_title: "FY2026 Approps", publisher: "jlbc", fiscal_year: 2026,
      page_start: 4, page_end: 4, bbox: null,
    },
    additional: [], derived_from: [],
  };
}

const ANNOTATION = {
  figures: [figureAt("$1,391,157,700", 1), figureAt("$2,613,700,000", 2)],
};

// A prose citation anchored to the MIDDLE sentence — so in reading order it
// sits between the two figures.
const PROSE: Citation[] = [{
  index: 1,
  chunkId: "c-prose",
  spanStart: 0,
  spanEnd: 10,
  confidence: "verbatim",
  claimSpan: "administered by the department under statute",
  citationId: "cit-1",
}];

describe("unified citation numbering", () => {
  it("numbers figures and prose citations in one reading-order sequence", () => {
    render(
      <CitedMarkdownContent
        content={ANSWER}
        citations={PROSE}
        annotation={ANNOTATION}
      />,
    );
    // Three marks down the page: figure, prose, figure.
    const chips = screen.getAllByTestId(/^citation-chip$|^prose-chip$/);
    expect(chips.map((c) => c.textContent?.replace(/[^\d]/g, ""))).toEqual([
      "1", "2", "3",
    ]);
  });

  it("gives the second figure 3, not 2, once a prose cite precedes it", () => {
    render(
      <CitedMarkdownContent
        content={ANSWER}
        citations={PROSE}
        annotation={ANNOTATION}
      />,
    );
    // The annotation calls this figure 2; on the page it is the 3rd mark.
    const second = screen.getByLabelText(/\$2,613,700,000/);
    expect(second.textContent).toBe("3");
  });

  it("still numbers 1..N when there are no prose citations", () => {
    render(
      <CitedMarkdownContent content={ANSWER} citations={[]} annotation={ANNOTATION} />,
    );
    expect(
      screen.getAllByTestId("citation-chip").map((c) => c.textContent),
    ).toEqual(["1", "2"]);
  });
});

describe("orphan prose citations", () => {
  const ORPHAN: Citation[] = [{
    index: 1,
    chunkId: "c-orphan",
    spanStart: 0,
    spanEnd: 5,
    confidence: "verbatim",
    // Does not appear anywhere in the answer — the shape that produced the
    // bare floating pill.
    claimSpan: "a claim the model never actually wrote",
    citationId: "cit-9",
  }];

  it("collects an unattachable citation under a labelled footer", () => {
    render(
      <CitedMarkdownContent content={ANSWER} citations={ORPHAN} annotation={ANNOTATION} />,
    );
    // The label is what stops a bare pill reading as a numbering bug.
    expect(screen.getByText(/Other sources for this answer/i)).toBeTruthy();
  });

  it("does not render the footer label when every citation attached", () => {
    render(
      <CitedMarkdownContent content={ANSWER} citations={PROSE} annotation={ANNOTATION} />,
    );
    expect(screen.queryByText(/Other sources for this answer/i)).toBeNull();
  });
});
