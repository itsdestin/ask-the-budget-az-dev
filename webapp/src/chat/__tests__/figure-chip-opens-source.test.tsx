/**
 * Clicking a linked figure chip must publish something PdfViewer can open.
 *
 * Seen in a browser 2026-08-02: every figure chip landed on "Couldn't open
 * source PDF". PdfViewer bails unless `citation.resolved.docId` and
 * `resolved.pageStart` are present, and the chip published neither — so the
 * design's whole payoff (click a number, see it highlighted on the page)
 * could never work, while every unit test passed.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FigureChip } from "../CitationChip";
import { CitationBusProvider, useCitationSelected } from "../citation-context";
import { figuresForRender } from "../citation-annotation";

function figureFrom(primary: unknown, verdict = "linked") {
  return figuresForRender({
    figures: [{
      text: "$1,391,157,700", start: 0, end: 14, index: 1, verdict,
      primary, additional: [], derived_from: [],
    }],
  })[0]!;
}

const PRIMARY = {
  chunk_id: "c-1", source_text: "1,391,157,700", start: 5, end: 18,
  doc_id: "jlbc-approps-fy2026-adc", doc_type: "approps-per-agency",
  doc_title: "FY2026 Approps — ADC", publisher: "jlbc", fiscal_year: 2026,
  page_start: 47, page_end: 47, bbox: [10, 20, 300, 40],
};

function clickChip(figure: ReturnType<typeof figureFrom>) {
  const selected: unknown[] = [];
  // Subscription is via useCitationSelected — the same hook PdfViewer uses,
  // so this test rides the real wire rather than a stand-in for it.
  function Sink() {
    useCitationSelected((c) => {
      selected.push(c);
    });
    return null;
  }
  render(
    <CitationBusProvider>
      <FigureChip figure={figure} />
      <Sink />
    </CitationBusProvider>,
  );
  screen.getByTestId("citation-chip").click();
  return selected;
}

describe("figure chip → source viewer", () => {
  it("publishes resolved doc metadata PdfViewer will accept", () => {
    const [sel] = clickChip(figureFrom(PRIMARY)) as any[];
    expect(sel).toBeTruthy();
    // These two are exactly what PdfViewer gates on.
    expect(sel.resolved?.docId).toBe("jlbc-approps-fy2026-adc");
    expect(sel.resolved?.pageStart).toBe(47);
    // And these are what makes the highlight land on the right token.
    expect(sel.sourceText).toBe("1,391,157,700");
    expect(sel.resolved?.bbox).toEqual([10, 20, 300, 40]);
  });

  it("publishes nothing at all for a derived figure", () => {
    // A derived figure has no source. Opening a viewer for it would claim
    // provenance it does not have.
    expect(clickChip(figureFrom(null, "derived"))).toEqual([]);
  });

  it("leaves resolved undefined when the payload carried no doc_id", () => {
    // Better an honest "couldn't open" than a viewer fetching /api/pdf/null.
    const [sel] = clickChip(
      figureFrom({ ...PRIMARY, doc_id: null }),
    ) as any[];
    expect(sel.resolved).toBeUndefined();
  });
});
