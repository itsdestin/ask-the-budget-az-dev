// A `moved`/`resolved` verdict is about ONE QUOTE, not a whole chunk.
//
// Found by review 2026-08-11. `markUnresolvable` carried only a chunk id, and
// two citations can share a chunk while disagreeing about whether their own
// span survived a re-ingest. Clicking the still-good one published `resolved`
// and cleared the stale mark on the one whose source really had moved — so a
// moved source went back to reading as verified, which is the Invariant 2
// failure the marking exists to prevent.
import { render, screen, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CitationChip from "../CitationChip.js";
import {
  CitationBusProvider,
  spanKeyOf,
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

/** Two citations into the SAME chunk at different spans. */
const MOVED = citation({ index: 1, spanStart: 0, spanEnd: 5, claimSpan: "hello" });
const FINE = citation({ index: 2, spanStart: 6, spanEnd: 11, claimSpan: "world" });

function mountBoth() {
  let bus: ReturnType<typeof useCitationBus> | null = null;
  function Probe() {
    bus = useCitationBus();
    return null;
  }
  render(
    <CitationBusProvider>
      <Probe />
      <CitationChip citation={MOVED} inlineText="hello" />
      <CitationChip citation={FINE} inlineText="world" />
    </CitationBusProvider>,
  );
  const chips = screen.getAllByRole("button");
  return { bus: bus!, moved: chips[0], fine: chips[1] };
}

const isFailed = (el: HTMLElement) => el.className.includes("is-failed");

describe("stale marking is scoped to the citation, not the chunk", () => {
  it("marks only the citation whose span moved", () => {
    const { bus, moved, fine } = mountBoth();
    act(() => bus.markUnresolvable(MOVED.chunkId, "moved", spanKeyOf(MOVED)));
    expect(isFailed(moved)).toBe(true);
    expect(isFailed(fine)).toBe(false);
  });

  it("a sibling's clean re-check does NOT clear a real stale mark", () => {
    const { bus, moved, fine } = mountBoth();
    act(() => bus.markUnresolvable(MOVED.chunkId, "moved", spanKeyOf(MOVED)));
    // The analyst now clicks the OTHER citation into the same chunk, and its
    // quote is still there. Before the fix this cleared both.
    act(() => bus.markUnresolvable(FINE.chunkId, "resolved", spanKeyOf(FINE)));
    expect(isFailed(moved)).toBe(true);
    expect(isFailed(fine)).toBe(false);
  });

  it("re-checking the SAME citation still clears its own mark", () => {
    const { bus, moved } = mountBoth();
    act(() => bus.markUnresolvable(MOVED.chunkId, "moved", spanKeyOf(MOVED)));
    expect(isFailed(moved)).toBe(true);
    act(() => bus.markUnresolvable(MOVED.chunkId, "resolved", spanKeyOf(MOVED)));
    expect(isFailed(moved)).toBe(false);
  });

  it("`gone` still applies to every citation in the chunk", () => {
    // The chunk 404s, so no span inside it can resolve. Published with no
    // spanKey, and both chips must take it.
    const { bus, moved, fine } = mountBoth();
    act(() => bus.markUnresolvable("c1", "gone"));
    expect(isFailed(moved)).toBe(true);
    expect(isFailed(fine)).toBe(true);
  });

  it("a verdict for a different chunk is ignored", () => {
    const { bus, moved, fine } = mountBoth();
    act(() => bus.markUnresolvable("some-other-chunk", "gone"));
    expect(isFailed(moved)).toBe(false);
    expect(isFailed(fine)).toBe(false);
  });
});
