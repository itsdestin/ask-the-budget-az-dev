// SSR smoke tests for the CitationChip — the chip itself is a
// hover-driven popover (the tooltip only mounts on mouseenter), so
// renderToString sees just the button. We assert the right glyph,
// label, and number make it onto the page; click + tooltip behavior
// will get exercised by a follow-up Playwright test once the dev
// server is wired into CI.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import CitationChip from "../components/CitationChip";
import { CitationBusProvider } from "../state/citation-context";
import type { Citation } from "../lib/citation-extract.js";

function citation(overrides: Partial<Citation>): Citation {
  return {
    index: 1,
    chunkId: "c1",
    spanStart: 0,
    spanEnd: 5,
    confidence: "verbatim",
    claimSpan: "hello",
    resolved: {
      docId: "doc-A",
      docTitle: "JLBC Baseline Book",
      publisher: "JLBC",
      fiscalYear: 2024,
      docType: "jlbc-baseline-book",
      pageStart: 47,
      pageEnd: 47,
      bbox: [10, 20, 100, 40],
      text: "hello world",
    },
    ...overrides,
  };
}

describe("CitationChip", () => {
  it("renders the chip number and verbatim glyph", () => {
    const c = citation({ index: 3, confidence: "verbatim" });
    const html = renderToString(
      <CitationBusProvider>
        <CitationChip citation={c} />
      </CitationBusProvider>,
    );
    expect(html).toContain("3");
    expect(html).toContain("✓");
    // aria-label spells out the confidence for screen readers.
    expect(html).toContain("verbatim");
  });

  it("renders the paraphrase glyph for paraphrase citations", () => {
    const html = renderToString(
      <CitationBusProvider>
        <CitationChip citation={citation({ confidence: "paraphrase" })} />
      </CitationBusProvider>,
    );
    expect(html).toContain("≈");
    expect(html).toContain("paraphrase");
  });
});
