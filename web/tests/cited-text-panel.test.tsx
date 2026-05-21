// CitedTextPanel renders the chunk's verbatim text with the cited
// span underlined so the analyst can verify the claim even when the
// PDF highlight failed. Tests cover: cited-span rendering, missing-
// data fallback, and source-label rendering.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import CitedTextPanel from "../components/CitedTextPanel";

describe("CitedTextPanel", () => {
  it("underlines the cited span inside the chunk text", () => {
    const chunkText = "The Aviation Fund got $2,587,400 in FY 2026.";
    const html = renderToString(
      <CitedTextPanel
        chunkText={chunkText}
        spanStart={22}
        spanEnd={32}
        sourceLabel="JLBC FY26 Baseline, p. 47"
      />,
    );
    // The cited span text appears in a marked element.
    expect(html).toContain("$2,587,400");
    // The mark/underline element wraps the span.
    expect(html).toMatch(/<mark[^>]*>\$2,587,400<\/mark>/);
    // Source label is rendered.
    expect(html).toContain("JLBC FY26 Baseline, p. 47");
    // Heading is visible.
    expect(html).toContain("Cited text from this chunk");
  });

  it("renders fallback when chunkText is empty", () => {
    const html = renderToString(
      <CitedTextPanel
        chunkText=""
        spanStart={0}
        spanEnd={0}
        sourceLabel=""
      />,
    );
    expect(html).toContain("Source text unavailable in this turn");
  });

  it("renders the whole chunk text without underline when spans are sentinel (0, claimLen)", () => {
    // Legacy sentinel range used by pre-resolved-offsets cites. The
    // panel should still be useful — show the whole chunk, just no
    // underline.
    const html = renderToString(
      <CitedTextPanel
        chunkText="Whole chunk text here."
        spanStart={0}
        spanEnd={0}
        sourceLabel="src"
      />,
    );
    expect(html).toContain("Whole chunk text here.");
    expect(html).not.toContain("<mark");
  });
});
