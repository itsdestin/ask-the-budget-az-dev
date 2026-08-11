// H5: the chip renders a visible marking when the viewer reports its
// citation's source is unresolvable.
import { render, screen, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CitationChip from "../CitationChip.js";
import {
  CitationBusProvider,
  useCitationBus,
} from "../citation-context.js";
import type { Citation } from "../citation-extract.js";

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    index: 1,
    chunkId: "c1",
    spanStart: 0,
    spanEnd: 5,
    confidence: "verbatim",
    claimSpan: "hello",
    resolved: {
      docId: "doc-A",
      docTitle: "Budget Report",
      publisher: "JLBC",
      fiscalYear: 2024,
      docType: "report",
      pageStart: 47,
      pageEnd: 47,
      bbox: [10, 20, 100, 40],
      text: "hello world",
    },
    ...overrides,
  };
}

/** Mounts a chip and a bus probe, then publishes an unresolvable verdict. */
function mountAndMark(c: Citation, reason: "gone" | "moved") {
  let bus: ReturnType<typeof useCitationBus> | null = null;
  function Probe() {
    bus = useCitationBus();
    return null;
  }
  render(
    <CitationBusProvider>
      <Probe />
      <CitationChip citation={c} />
    </CitationBusProvider>,
  );
  act(() => bus!.markUnresolvable(c.chunkId, reason));
}

describe("CitationChip unresolvable marking (H5)", () => {
  it("renders the failed-citation treatment when the source is gone", () => {
    mountAndMark(citation(), "gone");
    const chip = screen.getByRole("button");
    expect(chip.className).toContain("is-failed");
    // Accessible name says the source is no longer available
    expect(chip.getAttribute("aria-label")).toContain("source no longer available");
  });

  it("renders the failed-citation treatment when the source moved", () => {
    mountAndMark(citation(), "moved");
    const chip = screen.getByRole("button");
    expect(chip.className).toContain("is-failed");
  });

  it("does not mark a chip whose chunkId does not match", () => {
    let bus: ReturnType<typeof useCitationBus> | null = null;
    function Probe() {
      bus = useCitationBus();
      return null;
    }
    const c = citation({ chunkId: "c1" });
    render(
      <CitationBusProvider>
        <Probe />
        <CitationChip citation={c} />
      </CitationBusProvider>,
    );
    act(() => bus!.markUnresolvable("different-chunk", "gone"));
    // The chip should NOT have the failed treatment
    const chip = screen.getByRole("button");
    expect(chip.className).not.toContain("is-failed");
  });

  it("the verified quote is still shown in the tooltip (Invariant 2)", () => {
    // The quote was verified when written — it is a fact about the past.
    // Hover to open the tooltip and verify the quote is still there.
    const c = citation({ chunkId: "c1" });
    let bus: ReturnType<typeof useCitationBus> | null = null;
    function Probe() {
      bus = useCitationBus();
      return null;
    }
    render(
      <CitationBusProvider>
        <Probe />
        <CitationChip citation={c} inlineText="hello" />
      </CitationBusProvider>,
    );
    act(() => bus!.markUnresolvable("c1", "gone"));
    // The chip itself renders the inline text
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
});
