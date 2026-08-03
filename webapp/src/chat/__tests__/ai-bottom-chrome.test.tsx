// The composer's new floating chrome (Task 8, Stage 2 of the redesign).
//
// Two things this pins: (1) the tier switch / input / stop / footer live
// inside one distinct block (`ai-bottom-chrome`) rather than as loose
// siblings of the thread, and (2) that block measures its OWN real height
// (via ResizeObserver) and publishes it as a CSS custom property on the
// chat column — Task 9's scroller pads its bottom by exactly that number
// instead of a guessed constant.
//
// Fixtures follow refusal-banner.test.tsx's fakeChat/chatState shapes and
// ai-mode-panel-source.test.tsx's pattern of mocking the PDF viewer so
// pdfjs never loads in this DOM-only suite (the viewer isn't opened here,
// but AiModePanel imports it unconditionally).

import { render, screen } from "@testing-library/react";

import { AiModePanel } from "../AiModePanel";
import { initialChatState } from "../chat-types";
import type { ChatState } from "../chat-types";
import type { UseChatResult } from "../use-chat";
import { stubScrollIntoView } from "../../pages/ai-test-fixtures";

vi.mock("../../pdf/PdfViewer", () => ({
  default: () => <div data-testid="pdf-viewer" />,
}));

function chatState(turns: ChatState["turns"] = []): ChatState {
  return { ...initialChatState, turns };
}

/** Minimal stand-in for useChat()'s return value — same shape
 *  refusal-banner.test.tsx uses. */
function fakeChat(state: ChatState): UseChatResult {
  return {
    state,
    send: async () => {},
    stop: () => {},
    clearError: () => {},
    tier: "standard",
    setTier: () => {},
    busy: false,
    health: null,
  };
}

// jsdom never lays anything out, so `offsetHeight` is 0 unless a test
// stubs it. This fake ResizeObserver both stands in for the browser API and
// pins the element's measured height at a known, non-zero value, so the
// test can assert the EXACT string the effect publishes.
class MeasuredRO {
  cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe(el: Element) {
    Object.defineProperty(el, "offsetHeight", { value: 132, configurable: true });
    this.cb([{ target: el } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  disconnect() {}
  unobserve() {}
}

describe("floating bottom chrome", () => {
  beforeEach(() => stubScrollIntoView());

  it("the composer block floats and publishes its measured height", () => {
    vi.stubGlobal("ResizeObserver", MeasuredRO);
    render(
      <AiModePanel chat={fakeChat(chatState())} status={null} corpus="budget" />,
    );
    const chrome = screen.getByTestId("ai-bottom-chrome");
    expect(chrome).toContainElement(screen.getByRole("textbox"));
    // The chat column carries the measured height as a custom property so the
    // scroller (Task 9) can pad by exactly the chrome's real height.
    const chatCol = chrome.parentElement!;
    expect(chatCol.style.getPropertyValue("--ai-bottom-chrome")).toBe("132px");
    vi.unstubAllGlobals();
  });
});
