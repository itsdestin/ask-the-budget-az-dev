// The ask bar (2026-08-02). Replaces the auto-grow-textarea specs that lived
// here — the textarea is gone, and with it the overflow-y juggling that stopped
// Firefox painting a scrollbar inside an empty one-line box.

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import MessageInput from "../MessageInput.js";

const composer = () => screen.getByRole("textbox") as HTMLTextAreaElement;

/** jsdom lays nothing out, so scrollHeight is 0 forever and the auto-grow
 *  effect can never observe overflow on its own. These stubs are what let the
 *  fade specs below test the real decision instead of a mock of it. */
function stubBox(contentPx: number, visiblePx: number, scrollTop = 0) {
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get: () => contentPx,
  });
  Object.defineProperty(HTMLTextAreaElement.prototype, "clientHeight", {
    configurable: true,
    get: () => visiblePx,
  });
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: () => {},
  });
  return () => {
    for (const k of ["scrollHeight", "clientHeight", "scrollTop"]) {
      delete (HTMLTextAreaElement.prototype as unknown as Record<string, unknown>)[k];
    }
  };
}

describe("the ask bar", () => {
  it("wraps instead of running off sideways", () => {
    // A plain <input> pushed a long question horizontally off the end of the
    // field, which is unreadable while you are still writing it.
    render(<MessageInput onSubmit={vi.fn()} />);
    const ta = composer();
    expect(ta.tagName).toBe("TEXTAREA");
    expect(ta).toHaveAttribute("rows", "1");
  });

  it("states its four-line ceiling once, and hands it to the CSS", () => {
    // The cap lives in CSS (max-height in em, next to the line-height it
    // depends on) but the NUMBER comes from the component, so the two cannot
    // drift into disagreeing about how tall four lines is.
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer().style.getPropertyValue("--ask-max-rows")).toBe("4");
  });

  it("keeps Shift+Enter for a newline now that it wraps", () => {
    const onSubmit = vi.fn();
    render(<MessageInput onSubmit={onSubmit} />);
    fireEvent.change(composer(), { target: { value: "line one" } });
    fireEvent.keyDown(composer(), { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("asks about the budget by default, and says whatever it is told to", () => {
    const { unmount } = render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer()).toHaveAttribute("placeholder", "Ask about the budget…");
    unmount();
    // The caller names the corpus here (AiModePanel does), because the corpus
    // toggle lives in a menu that closes — this placeholder is the only
    // permanent statement of which documents an answer can come from.
    render(<MessageInput onSubmit={vi.fn()} placeholder="Ask about fiscal notes…" />);
    expect(composer()).toHaveAttribute("placeholder", "Ask about fiscal notes…");
  });

  it("sends on Enter and clears itself", () => {
    const onSubmit = vi.fn();
    render(<MessageInput onSubmit={onSubmit} />);
    fireEvent.change(composer(), { target: { value: "  ADOT in FY2024?  " } });
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("ADOT in FY2024?");
    expect(composer().value).toBe("");
  });

  it("will not send blank or whitespace-only questions", () => {
    const onSubmit = vi.fn();
    render(<MessageInput onSubmit={onSubmit} />);
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    fireEvent.change(composer(), { target: { value: "   " } });
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(send).toBeDisabled();
  });

  it("refuses a second send while one is in flight", () => {
    // A second concurrent POST is answered 409 by the server. That is a mistake
    // to prevent, not an error to render.
    const onSubmit = vi.fn();
    render(<MessageInput onSubmit={onSubmit} disabled />);
    fireEvent.change(composer(), { target: { value: "another question" } });
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("renders the tools slot between the paperclip and the input", () => {
    render(<MessageInput onSubmit={vi.fn()} tools={<span data-testid="tools" />} />);
    const bar = screen.getByTestId("ask-attach").parentElement!;
    const order = Array.from(bar.children).map((el) =>
      el.getAttribute("data-testid") ?? el.tagName.toLowerCase(),
    );
    expect(order).toEqual(["ask-attach", "tools", "textarea", "button"]);
  });
});

describe("the paperclip is an honest stub", () => {
  it("says attachments are not implemented, in a tooltip that can actually appear", () => {
    render(<MessageInput onSubmit={vi.fn()} />);
    const clip = screen.getByTestId("ask-attach");
    expect(clip).toHaveAttribute("title", "Attachments not yet implemented");
    // aria-disabled, NOT `disabled`. A genuinely disabled button receives no
    // pointer events, so the browser never shows its title — the tooltip
    // explaining why the button does nothing would itself do nothing.
    expect(clip).toHaveAttribute("aria-disabled", "true");
    expect(clip).not.toBeDisabled();
  });

  it("does nothing when clicked — it has no handler to accidentally acquire", () => {
    const onSubmit = vi.fn();
    render(<MessageInput onSubmit={onSubmit} />);
    fireEvent.click(screen.getByTestId("ask-attach"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(composer().value).toBe("");
  });
});

describe("send and stop", () => {
  it("Send says Send", () => {
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Send" })).toHaveTextContent("Send");
  });

  it("Stop is an icon, so it carries its accessible name in an attribute", () => {
    // A button whose only content is an <svg> is unlabelled to a screen reader
    // without this — and this one is the only way to interrupt a turn.
    render(<MessageInput onSubmit={vi.fn()} disabled onStop={vi.fn()} />);
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop.querySelector("svg")).not.toBeNull();
    expect(stop).toHaveTextContent("");
  });

  it("offers no Stop when nothing is streaming", () => {
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it("shows Stop to the LEFT of Send while a turn streams, and Send stays put", () => {
    // Deliberately not a swap. If Send became Stop in place, the click that
    // meant "send my next question" would land on "throw away the answer"
    // whenever the stream started between the intent and the click.
    const onStop = vi.fn();
    render(<MessageInput onSubmit={vi.fn()} disabled onStop={onStop} />);
    const send = screen.getByRole("button", { name: "Send" });
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(send).toBeDisabled();
    expect(stop.nextElementSibling).toBe(send);
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("keeps Stop live even though the bar is disabled", () => {
    // `disabled` is about the INPUT. An interrupt that went inert the moment
    // the turn it interrupts began would never be clickable at all.
    const onStop = vi.fn();
    render(<MessageInput onSubmit={vi.fn()} disabled onStop={onStop} />);
    expect(screen.getByRole("button", { name: "Stop" })).not.toBeDisabled();
  });
});

describe("the four-line ceiling and its fades", () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
  });

  it("fades neither edge while everything fits", () => {
    // The whole point of doing this per-edge: an always-on top fade would make
    // a one-line question look like broken text.
    restore = stubBox(33, 33);
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer().className).toBe("");
  });

  it("fades the BOTTOM once there is more text below", () => {
    restore = stubBox(200, 120, 0);
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer()).toHaveClass("is-fade-bottom");
  });

  it("fades the TOP once scrolled to the end", () => {
    restore = stubBox(200, 120, 80);
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer()).toHaveClass("is-fade-top");
  });

  it("fades BOTH edges in the middle of a long question", () => {
    restore = stubBox(200, 120, 40);
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer()).toHaveClass("is-fade-both");
  });

  it("treats a sub-pixel rounding difference as no overflow", () => {
    // 15.5px x 1.6 = 24.8px per line against an integer scrollHeight. This is
    // the same rounding that once made Firefox paint a scrollbar inside an
    // empty composer; here it would fade a box that is not scrollable.
    restore = stubBox(122, 120, 1);
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer().className).toBe("");
  });
});
