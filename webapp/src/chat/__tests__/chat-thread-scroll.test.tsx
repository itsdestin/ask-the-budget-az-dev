// The scroll model: welcome renders inside the ONE scroller; the refusal
// banner is part of the thread flow (scrolls with history) rather than
// permanent chrome; a jump-to-bottom pill appears when scrolled up.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ChatThread from "../ChatThread";
import type { AssistantTurn } from "../chat-types";
import type { RefusalReason } from "../RefusalBanner";

const idleMascot = { kind: "idle", pose: "clasped" } as never;

// Minimal fixtures in the same shape as refusal-banner.test.tsx's `turn()` /
// CHUNK builders — duplicated rather than imported because that file exports
// neither, and the two suites test different things (detection logic there,
// layout/scroll behavior here).
const assistantTurnFixture: AssistantTurn = {
  kind: "assistant",
  id: "a1",
  blocks: [{ kind: "text", uuid: "u1", text: "AHCCCS gets $12.3 M." }],
  isComplete: true,
  stopReason: "end_turn",
  timestamp: 1,
};

const refusalFixture: RefusalReason = { kind: "no_retrieval" };

it("empty state renders the welcome INSIDE the thread scroller", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [], isThinking: false, error: null } as never}
      mascot={idleMascot}
    />,
  );
  const scroller = container.querySelector(".chat-thread-scroll")!;
  expect(scroller).not.toBeNull();
  expect(scroller.querySelector(".chat-welcome")).not.toBeNull();
});

it("renders the refusal banner inside the thread column when passed", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
      refusal={refusalFixture}
    />,
  );
  const column = container.querySelector(".chat-thread-column")!;
  expect(column.querySelector(".chat-refusal")).not.toBeNull();
});

it("shows the jump-to-bottom pill only when scrolled away from the bottom", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
    />,
  );
  expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();
  const scroller = container.querySelector(".chat-thread-scroll")!;
  // Simulate being 200px above the bottom.
  Object.defineProperty(scroller, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(scroller, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(scroller, "scrollTop", { value: 400, writable: true, configurable: true });
  fireEvent.scroll(scroller);
  expect(screen.getByRole("button", { name: /Jump to latest/ })).toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// FINAL REVIEW — CRITICAL 1: the mascot docks from JS, not a container query
// ---------------------------------------------------------------------------
//
// The dock used to be a CSS `@container (max-width: 1084px)` rule on the
// thread scroller. `container-type` applies layout containment, which makes
// the scroller a containing block for `position: fixed` descendants — so the
// citation tooltip (fixed precisely to ESCAPE this scroller's overflow clip,
// and the only place a FAILED citation's reason is readable) got re-clipped.
// The measurement therefore moved into a ResizeObserver here; these specs pin
// that it still happens, at the same threshold, in both directions.
//
// jsdom ships no ResizeObserver, so the component's own
// `typeof ResizeObserver === "undefined"` guard would skip the effect
// entirely. This stub stands in for it and lets a test drive a width.

interface StubEntry {
  target: Element;
  contentRect: { width: number };
}

class StubResizeObserver {
  static instances: StubResizeObserver[] = [];
  targets: Element[] = [];
  constructor(private cb: (entries: StubEntry[]) => void) {
    StubResizeObserver.instances.push(this);
  }
  observe(el: Element) {
    this.targets.push(el);
  }
  unobserve() {}
  disconnect() {
    this.targets = [];
  }
  /** Pretend the browser reported a new CONTENT-box width for this target. */
  emit(width: number) {
    this.cb(this.targets.map((target) => ({ target, contentRect: { width } })));
  }
}

/** The observer watching `el`, or undefined. ChatThread runs two observers
 *  (one re-pins the scroll on content growth, one measures the width); this
 *  picks the width one out by the element it was pointed at. */
function observerFor(el: Element): StubResizeObserver | undefined {
  return StubResizeObserver.instances.find((o) => o.targets.includes(el));
}

function renderThreadWithStubObserver() {
  StubResizeObserver.instances = [];
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver =
    StubResizeObserver;
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
    />,
  );
  const scroller = container.querySelector(".chat-thread-scroll")!;
  return { container, scroller, observer: observerFor(scroller)! };
}

afterEach(() => {
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
});

it("docks the mascot when the scroller is too narrow for the column plus the figure", () => {
  const { container, observer } = renderThreadWithStubObserver();
  expect(observer, "the scroller's own width must be observed").toBeDefined();

  // 1083 is one pixel under the derived 1084px no-clip requirement.
  act(() => observer.emit(1083));
  expect(
    container.querySelector(".chat-mascot-slot")!.className,
  ).toContain("is-cramped");
});

it("undocks again once the column is wide enough, and never leaves the a11y tree", () => {
  const { container, observer } = renderThreadWithStubObserver();
  act(() => observer.emit(1083));
  act(() => observer.emit(1084));
  const slot = container.querySelector(".chat-mascot-slot")!;
  expect(slot.className).not.toContain("is-cramped");
  // Docked or not, the mascot's role="img" label is the only status the
  // assistant exposes to assistive tech — it must never be unmounted.
  act(() => observer.emit(600));
  expect(container.querySelector('[role="img"]')).not.toBeNull();
});
