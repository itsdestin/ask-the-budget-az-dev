// The bug: the initial measurement used clientWidth (which INCLUDES the
// scroller's 24px padding) while the ResizeObserver wrote contentRect.width
// (which EXCLUDES it), and both were then reduced by a constant 24 — so in a
// real browser the page rendered 24px narrower than fit-to-width, forever.
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const pageProps = vi.fn();
vi.mock("../PdfPage", () => ({
  default: (props: Record<string, unknown>) => {
    pageProps(props);
    return <div data-testid="pdf-page" />;
  },
}));

import { SourceView } from "../SourceView";

class ImmediateRO {
  cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe() {
    // Fire like a real browser's initial observation, with a known width.
    this.cb(
      [{ contentRect: { width: 500 } }] as unknown as ResizeObserverEntry[],
      this as unknown as ResizeObserver,
    );
  }
  disconnect() {}
  unobserve() {}
}

describe("SourceView container sizing", () => {
  it("passes the content-box width through to PdfPage unreduced", async () => {
    vi.stubGlobal("ResizeObserver", ImmediateRO);
    render(
      <SourceView
        docId="doc-1"
        page={3}
        bbox={null}
        chunkText="some chunk text"
        spanStart={0}
        spanEnd={4}
        docTitle="Test Doc"
        sourceLabel="Test Doc, p. 3"
      />,
    );
    await waitFor(() => expect(screen.getByTestId("pdf-page")).toBeInTheDocument());
    const last = pageProps.mock.calls.at(-1)![0] as { containerWidth: number };
    expect(last.containerWidth).toBe(500); // NOT 476
    vi.unstubAllGlobals();
  });
});
