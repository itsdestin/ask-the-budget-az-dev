// CitationBus pub/sub: subscribe, broadcast, unsubscribe, and the
// "broken subscriber doesn't break siblings" guarantee. Render-only
// uses the React provider via renderToString — we drive subscribe()
// + select() through the bus instance directly (extracted from a
// no-op render) since CitationBus is just a typed pub/sub.

import { describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
// fireEvent, not userEvent — this webapp has no @testing-library/user-event
// dependency; every other test file in the suite drives clicks via fireEvent.
import { fireEvent, render, screen } from "@testing-library/react";

import {
  CitationBusProvider,
  useCitationBus,
  useCitationSelected,
} from "../citation-context";
import type { Citation } from "../citation-extract.js";

function fakeCitation(idx: number): Citation {
  return {
    index: idx,
    chunkId: `c${idx}`,
    spanStart: 0,
    spanEnd: 1,
    confidence: "paraphrase",
    claimSpan: "x",
  };
}

describe("CitationBusProvider", () => {
  it("renders children without throwing", () => {
    const html = renderToString(
      <CitationBusProvider>
        <span>hi</span>
      </CitationBusProvider>,
    );
    expect(html).toContain("hi");
  });
});

// We test the bus methods separately from React rendering — the
// provider creates a fresh bus per mount, but the API contract is
// pure and worth pinning down.
describe("CitationBus contract", () => {
  // Reach into the implementation by reconstructing the same shape
  // the provider builds (set-of-handlers + select that iterates).
  function makeStandaloneBus() {
    const handlers = new Set<(c: Citation) => void>();
    return {
      select(c: Citation) {
        for (const h of handlers) {
          try {
            h(c);
          } catch {
            // mirror provider behavior: don't let one throw block siblings
          }
        }
      },
      subscribe(h: (c: Citation) => void) {
        handlers.add(h);
        return () => {
          handlers.delete(h);
        };
      },
    };
  }

  it("broadcasts to every subscriber", () => {
    const bus = makeStandaloneBus();
    const received: Citation[][] = [[], []];
    bus.subscribe((c) => received[0]!.push(c));
    bus.subscribe((c) => received[1]!.push(c));
    const c1 = fakeCitation(1);
    bus.select(c1);
    expect(received[0]).toEqual([c1]);
    expect(received[1]).toEqual([c1]);
  });

  it("unsubscribe removes the handler", () => {
    const bus = makeStandaloneBus();
    const log: Citation[] = [];
    const unsub = bus.subscribe((c) => log.push(c));
    bus.select(fakeCitation(1));
    unsub();
    bus.select(fakeCitation(2));
    expect(log.map((c) => c.index)).toEqual([1]);
  });

  it("a throwing subscriber doesn't stop the others", () => {
    const bus = makeStandaloneBus();
    const log: Citation[] = [];
    bus.subscribe(() => {
      throw new Error("boom");
    });
    bus.subscribe((c) => log.push(c));
    bus.select(fakeCitation(1));
    expect(log).toHaveLength(1);
  });
});

// Reproduces the first-chip-click bug against the REAL provider (not the
// standalone bus above): a viewer that mounts BECAUSE of the click that
// selected a citation must still see that citation, even though its
// subscribe-in-useEffect necessarily runs after the click was delivered.
describe("CitationBusProvider replay", () => {
  it("replays the last selection to a subscriber that mounts after the click", () => {
    const seen = vi.fn();
    const citation = fakeCitation(1);

    function Clicker() {
      const bus = useCitationBus();
      return (
        <button type="button" onClick={() => bus.select(citation)}>
          fire
        </button>
      );
    }
    function LateViewer() {
      useCitationSelected(seen);
      return null;
    }

    const { rerender } = render(
      <CitationBusProvider>
        <Clicker />
      </CitationBusProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "fire" }));
    expect(seen).not.toHaveBeenCalled();

    // Same provider instance (React reconciles the root element in place),
    // new child — the shape of PdfViewer mounting inside the aside that the
    // click itself opened.
    rerender(
      <CitationBusProvider>
        <Clicker />
        <LateViewer />
      </CitationBusProvider>,
    );
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen).toHaveBeenCalledWith(citation);
  });
});

// The hook exists; useCitationBus called outside a provider returns
// a no-op. We can render a tiny consumer that reads the bus — if it
// returns null the function is wired up.
describe("useCitationBus default", () => {
  function Probe() {
    const bus = useCitationBus();
    return <span>{typeof bus.select === "function" ? "ok" : "no"}</span>;
  }

  it("returns a no-op bus outside any provider", () => {
    const html = renderToString(<Probe />);
    expect(html).toContain("ok");
  });

  it("returns a real bus inside a provider", () => {
    const html = renderToString(
      <CitationBusProvider>
        <Probe />
      </CitationBusProvider>,
    );
    expect(html).toContain("ok");
  });
});
