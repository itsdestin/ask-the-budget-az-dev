/**
 * What a figure's tooltip SAYS when the system could not claim a source.
 *
 * A bare "not found" is the least useful thing the system knows. When
 * matching failed by a hair, the nearest source value is what lets an
 * analyst catch a wrong answer — and when the value sits in several
 * documents, the honest sentence is that no single source is claimed, not
 * that the figure is unsupported. The tooltip reports; it never accuses
 * (spec A6).
 *
 * Companion to figure-tooltip-position.test.tsx, which pins WHERE the same
 * tooltip renders.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FigureChip } from "../CitationChip";
import { CitationBusProvider } from "../citation-context";
import { figuresForRender } from "../citation-annotation";

/** Build the figure through the real parser, so the copy is asserted
 *  against the server's wire shape rather than a hand-built object that
 *  could drift from it. */
function mountFigure(raw: Record<string, unknown>) {
  const [figure] = figuresForRender({
    figures: [{
      text: "$12.49B", start: 0, end: 7, index: 3, verdict: "unverified",
      primary: null, additional: [], derived_from: [], ...raw,
    }],
  });
  render(
    <CitationBusProvider>
      <FigureChip figure={figure!} />
    </CitationBusProvider>,
  );
  fireEvent.mouseEnter(screen.getByTestId("citation-chip"));
  // JSX wraps the copy across source lines; the analyst reads one sentence.
  return screen.getByRole("tooltip").textContent!.replace(/\s+/g, " ");
}

describe("figure tooltip copy", () => {
  it("tells the analyst what the nearest source value actually is", () => {
    const text = mountFigure({
      near_miss: { chunk_id: "k1", source_text: "12,515.4",
                   value: 12_515_400_000, distance: 0.002 },
    });
    expect(text).toMatch(/Nearest source value: 12,515\.4/);
    expect(text).toMatch(/differs by 0\.2%/);
  });

  it("says how many documents hold an ambiguous value rather than picking one", () => {
    const text = mountFigure({ ambiguity_count: 3 });
    expect(text).toMatch(/appears in 3 different documents/);
    expect(text).toMatch(/no single source is claimed/);
  });

  it("still says plainly that a figure with no near miss was not found", () => {
    const text = mountFigure({});
    expect(text).toMatch(/was not found in the retrieved sources/);
  });

  it("names the operation a derived figure was computed by", () => {
    const text = mountFigure({
      verdict: "derived", operation: "difference", derived_from: [2, 5],
    });
    expect(text).toMatch(/Computed \(difference\) from \[2\] and \[5\]/);
  });
});
