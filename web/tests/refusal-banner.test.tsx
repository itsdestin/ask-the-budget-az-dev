// SSR smoke tests for RefusalBanner. The banner is props-driven for
// v1 (WS3/WS5 will wire detection); we just pin down the spec-§11
// copy + the chunk-preview rendering for the synthesis case.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import RefusalBanner, {
  type RefusalChunkPreview,
} from "../components/RefusalBanner";

function chunk(overrides: Partial<RefusalChunkPreview>): RefusalChunkPreview {
  return {
    chunkId: "doc-A:p1:s1",
    docTitle: "JLBC Baseline Book",
    publisher: "JLBC",
    fiscalYear: 2024,
    pageStart: 1,
    pageEnd: 1,
    text: "passage text",
    ...overrides,
  };
}

describe("RefusalBanner", () => {
  it("renders refusal_no_retrieval copy + corpus summary when provided", () => {
    const html = renderToString(
      <RefusalBanner
        refusal={{
          kind: "no_retrieval",
          corpusSummary: "JLBC FY24 + FY25",
        }}
      />,
    );
    expect(html).toContain("Refusal");
    // SSR HTML-encodes the apostrophe as &#x27; — match the
    // surrounding plain-text substrings instead.
    expect(html).toContain("find anything in the corpus that addresses");
    expect(html).toContain("JLBC FY24 + FY25");
  });

  it("renders refusal_synthesis copy + top-5 chunks", () => {
    const chunks = [1, 2, 3, 4, 5, 6].map((i) =>
      chunk({ chunkId: `c${i}`, docTitle: `Doc ${i}` }),
    );
    const html = renderToString(
      <RefusalBanner refusal={{ kind: "synthesis", chunks }} />,
    );
    // Apostrophe HTML-encoded by SSR; match the post-apostrophe phrase.
    expect(html).toContain("confidently synthesize");
    expect(html).toContain("Doc 1");
    expect(html).toContain("Doc 5");
    // 6th chunk should be sliced off (top-5 cap per spec).
    expect(html).not.toContain("Doc 6");
  });

  it("renders refusal_out_of_scope copy with no chunk list", () => {
    const html = renderToString(
      <RefusalBanner refusal={{ kind: "out_of_scope" }} />,
    );
    expect(html).toContain("editorial or policy question");
    expect(html).toContain("Refusal");
    // Must not render a chunk list in the out_of_scope case.
    expect(html).not.toContain("p. 1");
  });

  it("uses page range when start ≠ end in synthesis chunks", () => {
    const html = renderToString(
      <RefusalBanner
        refusal={{
          kind: "synthesis",
          chunks: [
            chunk({ pageStart: 10, pageEnd: 12, docTitle: "Multi-page" }),
          ],
        }}
      />,
    );
    expect(html).toContain("pp. 10");
    expect(html).toContain("12");
  });

  it("truncates long chunk text with an ellipsis", () => {
    const longText = "x".repeat(500);
    const html = renderToString(
      <RefusalBanner
        refusal={{
          kind: "synthesis",
          chunks: [chunk({ text: longText })],
        }}
      />,
    );
    expect(html).toContain("…");
  });
});
