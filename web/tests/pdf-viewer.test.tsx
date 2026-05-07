// SSR + client-render smoke tests for PdfViewer. Confirm the empty
// state renders by default, and that a bus.select() with a
// fully-resolved citation flips the viewer to the loaded state with
// the right embed src + breadcrumb.
//
// PdfViewer subscribes via a useEffect, so we drive the test through
// React's createRoot + act() rather than renderToString — the
// useEffect doesn't run during SSR.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { JSDOM } from "jsdom";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";

import PdfViewer from "../components/PdfViewer";
import {
  CitationBusProvider,
  useCitationBus,
} from "../state/citation-context";
import type { Citation } from "../lib/citation-extract.js";

function citation(): Citation {
  return {
    index: 1,
    chunkId: "doc-A:p47:s1",
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
  };
}

describe("PdfViewer empty state (SSR)", () => {
  it("renders the empty state inside a CitationBusProvider", () => {
    const html = renderToString(
      <CitationBusProvider>
        <PdfViewer />
      </CitationBusProvider>,
    );
    expect(html).toContain("Source viewer");
    expect(html).toContain("Click a citation chip");
  });

  it("does not render the embed without a selection", () => {
    const html = renderToString(
      <CitationBusProvider>
        <PdfViewer />
      </CitationBusProvider>,
    );
    expect(html).not.toContain("</embed>");
    expect(html).not.toContain("/api/pdf/");
  });
});

describe("PdfViewer bus subscription (client)", () => {
  // We need a DOM for createRoot / useEffect / state updates. JSDOM
  // covers it without pulling in the @testing-library/react dep.
  it("flips to the loaded state when bus.select() fires", async () => {
    const dom = new JSDOM("<!doctype html><html><body></body></html>");
    const { window } = dom;
    // React 19 expects the global IS_REACT_ACT_ENVIRONMENT flag.
    (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    (globalThis as unknown as { window: Window }).window =
      window as unknown as Window;
    (globalThis as unknown as { document: Document }).document =
      window.document;
    (globalThis as unknown as { HTMLElement: typeof HTMLElement }).HTMLElement =
      window.HTMLElement;

    const container = window.document.createElement("div");
    window.document.body.appendChild(container);

    let busHandle: ReturnType<typeof useCitationBus> | null = null;
    function BusProbe() {
      busHandle = useCitationBus();
      return null;
    }

    let root: Root | null = null;
    await act(async () => {
      root = createRoot(container);
      root.render(
        <CitationBusProvider>
          <BusProbe />
          <PdfViewer />
        </CitationBusProvider>,
      );
    });
    expect(container.textContent).toContain("Source viewer");

    await act(async () => {
      busHandle!.select(citation());
    });
    // After bus selection: breadcrumb + embed appear, empty state gone.
    expect(container.textContent).not.toContain("Click a citation chip");
    expect(container.textContent).toContain("JLBC Baseline Book");
    expect(container.textContent).toContain("47");
    const embed = container.querySelector("embed");
    expect(embed).not.toBeNull();
    expect(embed!.getAttribute("src")).toBe(
      "/api/pdf/doc-A#page=47&toolbar=1&navpanes=0",
    );

    await act(async () => {
      root!.unmount();
    });
  });

  it("ignores citations whose resolved.docId / pageStart are missing", async () => {
    const dom = new JSDOM("<!doctype html><html><body></body></html>");
    const { window } = dom;
    (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    (globalThis as unknown as { window: Window }).window =
      window as unknown as Window;
    (globalThis as unknown as { document: Document }).document =
      window.document;
    (globalThis as unknown as { HTMLElement: typeof HTMLElement }).HTMLElement =
      window.HTMLElement;

    const container = window.document.createElement("div");
    window.document.body.appendChild(container);

    let busHandle: ReturnType<typeof useCitationBus> | null = null;
    function BusProbe() {
      busHandle = useCitationBus();
      return null;
    }

    let root: Root | null = null;
    await act(async () => {
      root = createRoot(container);
      root.render(
        <CitationBusProvider>
          <BusProbe />
          <PdfViewer />
        </CitationBusProvider>,
      );
    });

    const dangling: Citation = {
      index: 1,
      chunkId: "ghost-chunk",
      spanStart: 0,
      spanEnd: 5,
      confidence: "paraphrase",
      claimSpan: "x",
      // No `resolved` block — citation chip emitted from a turn
      // that didn't include a matching retrieve().
    };
    await act(async () => {
      busHandle!.select(dangling);
    });
    // Empty state stays — viewer doesn't render an embed for an
    // unresolvable citation.
    expect(container.textContent).toContain("Source viewer");
    expect(container.querySelector("embed")).toBeNull();

    await act(async () => {
      root!.unmount();
    });
  });
});
