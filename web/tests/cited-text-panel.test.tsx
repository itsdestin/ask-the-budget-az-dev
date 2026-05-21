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

  it("collapses to a context window around the cited span by default", () => {
    // Long chunk where the cited span is buried in the middle. The
    // default-collapsed window should show only ~200 chars on either
    // side of the cite, with ellipses + an expand button.
    const before = "a".repeat(500);
    const cited = "$2,587,400";
    const after = "b".repeat(500);
    const chunkText = before + cited + after;
    const html = renderToString(
      <CitedTextPanel
        chunkText={chunkText}
        spanStart={500}
        spanEnd={510}
        sourceLabel="src"
      />,
    );
    // Cited span still rendered with mark.
    expect(html).toContain("<mark");
    expect(html).toContain("$2,587,400");
    // Both ellipses appear (truncated on both sides).
    expect(html).toContain("…");
    // The toggle button is rendered with the expand label.
    expect(html).toContain("Show full chunk");
    // Far edges of the chunk are NOT rendered (only ~200 chars before
    // and after the cited span survive the window).
    expect(html).not.toContain("a".repeat(300));
    expect(html).not.toContain("b".repeat(300));
  });

  it("does not show toggle button when chunk fits within the collapsed window", () => {
    const html = renderToString(
      <CitedTextPanel
        chunkText="Short chunk with $2,587,400 cited in it."
        spanStart={17}
        spanEnd={27}
        sourceLabel="src"
      />,
    );
    // Chunk is well under 200 chars on either side of the cite, so no
    // truncation occurs and no toggle is rendered.
    expect(html).not.toContain("Show full chunk");
    expect(html).not.toContain("…");
  });
});
