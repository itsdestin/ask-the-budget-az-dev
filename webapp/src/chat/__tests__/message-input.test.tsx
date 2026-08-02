// The composer's auto-grow effect owns the textarea's scrollbar.
//
// Why this file exists: left on the CSS default (`overflow-y: auto`), an
// UNCAPPED composer overflows itself. The effect sets height from
// scrollHeight, which is an integer, while the line box is fractional
// (14px x 1.6 = 22.4px) — so the box lands a sliver short of the content it
// was measured from, and Firefox paints a full up-arrow/thumb/down-arrow
// scrollbar inside an empty one-line composer. jsdom applies no layout, so
// the only way to pin the behaviour is to feed the effect a scrollHeight.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import MessageInput from "../MessageInput.js";

// The cap in MessageInput.tsx. Duplicated deliberately: if that constant
// moves, these specs should fail rather than silently follow it.
const MAX_HEIGHT_PX = 240;

/** Make every textarea report a fixed scrollHeight, the way layout would. */
function stubScrollHeight(px: number) {
  const original = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollHeight",
  );
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get: () => px,
  });
  return () => {
    delete (HTMLTextAreaElement.prototype as unknown as Record<string, unknown>)
      .scrollHeight;
    if (original) {
      Object.defineProperty(HTMLElement.prototype, "scrollHeight", original);
    }
  };
}

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
});

describe("MessageInput auto-grow", () => {
  it("hides the scrollbar while the box is still growing", () => {
    restore = stubScrollHeight(38);
    render(<MessageInput onSubmit={vi.fn()} />);
    const ta = screen.getByRole("textbox") as HTMLTextAreaElement;

    // The stray arrow glyph: a scrollbar on a box that is not capped.
    expect(ta.style.overflowY).toBe("hidden");
    expect(ta.style.height).toBe("38px");
  });

  it("allows scrolling once the box is capped", () => {
    restore = stubScrollHeight(MAX_HEIGHT_PX + 120);
    render(<MessageInput onSubmit={vi.fn()} />);
    const ta = screen.getByRole("textbox") as HTMLTextAreaElement;

    // Past the cap the content genuinely cannot fit, so a scrollbar is the
    // honest affordance rather than an artifact.
    expect(ta.style.overflowY).toBe("auto");
    expect(ta.style.height).toBe(`${MAX_HEIGHT_PX}px`);
  });
});
