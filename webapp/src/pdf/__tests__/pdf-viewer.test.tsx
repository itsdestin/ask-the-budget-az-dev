// PdfViewer wiring: the empty state renders by default, a bus.select()
// with a fully-resolved citation flips the viewer to the loaded state with
// the right breadcrumb + cited text, and a citation with no resolved chunk
// says so instead of looking identical to "no clicks yet".
//
// Ported from web/tests/pdf-viewer.test.tsx (Plan 4 Task 11). Two adaptations,
// both framework-shaped rather than behavioral:
//   - the original's first two cases used renderToString to prove the lazy
//     PdfPage never reached the Next.js SERVER pass. This app has no server
//     pass, so the same facts are asserted on a client render: the empty
//     state renders, and nothing PDF-shaped is in the DOM until a citation
//     is selected.
//   - the original hand-rolled JSDOM + createRoot + act because the Next.js
//     app had no @testing-library/react. This app does, and the webapp suite
//     uses it everywhere, so the driving is RTL's.
// Assertions are otherwise unchanged.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PdfViewer from "../PdfViewer";
import {
  CitationBusProvider,
  useCitationBus,
  type CitationBus,
} from "../../chat/citation-context";
import type { Citation } from "../../chat/citation-extract";

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

/** Mount the viewer and hand back the bus its chips would publish on. */
function mountViewer() {
  let bus: CitationBus | null = null;
  function BusProbe() {
    bus = useCitationBus();
    return null;
  }
  const view = render(
    <CitationBusProvider>
      <BusProbe />
      <PdfViewer />
    </CitationBusProvider>,
  );
  return { view, select: (c: Citation) => act(() => bus!.select(c)) };
}

describe("PdfViewer empty state", () => {
  it("renders the empty state inside a CitationBusProvider", () => {
    mountViewer();
    expect(
      screen.getByText("Click a citation to see its source."),
    ).toBeInTheDocument();
  });

  it("does not render the lazy PdfPage without a selection", () => {
    // pdfjs-dist is behind React.lazy; nothing should reference the PDF
    // route or draw a canvas until a citation is actually selected.
    const { view } = mountViewer();
    expect(view.container.innerHTML).not.toContain("/api/pdf/");
    expect(view.container.querySelector("canvas")).toBeNull();
  });
});

describe("PdfViewer bus subscription", () => {
  it("flips to the loaded state when bus.select() fires", () => {
    const { view, select } = mountViewer();
    expect(view.container.textContent).toContain(
      "Click a citation to see its source.",
    );

    select(citation());

    // After bus selection: breadcrumb appears. The canvas itself lives in
    // PdfPage, which needs a measured container and a real PDF over HTTP —
    // an integration concern, not a PdfViewer wiring concern.
    expect(view.container.textContent).not.toContain(
      "Click a citation to see its source.",
    );
    expect(view.container.textContent).toContain("JLBC Baseline Book");
    expect(view.container.textContent).toContain("47");
  });

  it("renders CitedTextPanel beneath the loaded PDF page", () => {
    const { view, select } = mountViewer();
    select(citation());
    expect(view.container.innerHTML).toContain("Cited text from this chunk");
    // Cited span (chunkText.slice(0, 5) = "hello") is present.
    expect(view.container.innerHTML).toContain("hello");
  });

  it("ignores citations whose resolved.docId / pageStart are missing", () => {
    const { view, select } = mountViewer();
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
    select(dangling);
    // The unresolved-citation message replaces the empty state and
    // explicitly tells the user the click landed but we can't load
    // the source. The chunk_id and chip number must surface so the
    // user has something concrete to debug from.
    expect(view.container.textContent).toContain("Couldn’t open source PDF");
    expect(view.container.textContent).toContain("ghost-chunk");
    expect(view.container.textContent).toContain("[1]");
    expect(view.container.querySelector("embed")).toBeNull();
  });
});

describe("PdfViewer mount-after-select (bus replay)", () => {
  it("shows the source on the FIRST chip click (mount-after-select)", () => {
    // The real sequence: chip click -> select() -> AiModePanel opens the
    // aside -> PdfViewer mounts. Without the citation-bus replay (fixed in
    // citation-context.tsx), PdfViewer's useCitationSelected subscribes only
    // after this render, missing the click it was mounted to react to, and
    // the panel would show the empty state until a second click.
    function Clicker() {
      const bus = useCitationBus();
      return (
        <button type="button" onClick={() => bus.select(citation())}>
          chip
        </button>
      );
    }

    const { rerender } = render(
      <CitationBusProvider>
        <Clicker />
      </CitationBusProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "chip" }));

    // Same provider instance, new child — PdfViewer mounting only because
    // the click above told the surrounding panel to open it.
    rerender(
      <CitationBusProvider>
        <Clicker />
        <PdfViewer />
      </CitationBusProvider>,
    );

    expect(screen.getByText("JLBC Baseline Book")).toBeInTheDocument();
    expect(
      screen.queryByText("Click a citation to see its source."),
    ).not.toBeInTheDocument();
  });
});
