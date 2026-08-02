// A cross-branch defect, and the reason this file exists.
//
// Two changes landed independently: master taught the system to link figures
// itself (`FigureChip`), and the AI Mode redesign made `.chat-cite-tooltip`
// `position: fixed` so it escapes the thread scroller's clip. Neither touched
// the other's lines, so git merged them without a murmur — but a fixed box
// with `auto` offsets is laid out at its static position and then frozen to
// the VIEWPORT, so FigureChip's tooltip detached from its chip on the first
// scroll while every test stayed green.
//
// These specs pin the coordinates onto the element, which is the only place
// the two decisions actually meet.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FigureChip } from "../CitationChip";
import { CitationBusProvider } from "../citation-context";
import type { AnnotationFigure } from "../citation-annotation";

function figure(overrides: Partial<AnnotationFigure> = {}): AnnotationFigure {
  return {
    index: 1,
    text: "$1,234,500",
    start: 0,
    end: 10,
    verdict: "unverified",
    derivedFrom: [],
    additional: [],
    ...overrides,
  } as AnnotationFigure;
}

function mount(fig: AnnotationFigure) {
  return render(
    <CitationBusProvider>
      <FigureChip figure={fig} />
    </CitationBusProvider>,
  );
}

/** jsdom gives every element a zero rect, so the measurement has to be fed. */
function stubChipRect(left: number, top: number) {
  Element.prototype.getBoundingClientRect = function () {
    return { left, top, right: left + 20, bottom: top + 16, width: 20, height: 16, x: left, y: top, toJSON: () => ({}) } as DOMRect;
  };
}

describe("FigureChip's tooltip carries viewport coordinates", () => {
  for (const verdict of ["unverified", "derived", "linked"] as const) {
    it(`positions the ${verdict} tooltip against the chip`, () => {
      stubChipRect(120, 300);
      const fig =
        verdict === "linked"
          ? figure({
              verdict,
              primary: {
                chunkId: "c-1",
                start: 0,
                end: 5,
                sourceText: "$1,234,500",
                docId: "d-1",
              },
            } as Partial<AnnotationFigure>)
          : figure({ verdict, derivedFrom: verdict === "derived" ? [1, 2] : [] });
      mount(fig);

      fireEvent.mouseEnter(screen.getByTestId(`citation-chip-${verdict}-1`));

      const tip = screen.getByRole("tooltip");
      // Not merely "has a style" — the numbers must come from the chip's own
      // rect, which is what makes the tooltip follow its chip.
      expect(tip.style.left).toBe("120px");
      expect(tip.style.bottom).toBe(`${window.innerHeight - 300 + 4}px`);
    });
  }

  it("clamps a chip near the right edge so the tooltip stays on screen", () => {
    // The overflow this clamp prevents was the phantom horizontal scrollbar.
    stubChipRect(window.innerWidth - 30, 200);
    mount(figure());
    fireEvent.mouseEnter(screen.getByTestId("citation-chip-unverified-1"));
    const left = parseFloat(screen.getByRole("tooltip").style.left);
    expect(left + 320).toBeLessThanOrEqual(window.innerWidth);
  });
});
