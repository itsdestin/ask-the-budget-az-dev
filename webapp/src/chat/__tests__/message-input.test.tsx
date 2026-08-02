// The ask bar (2026-08-02). Replaces the auto-grow-textarea specs that lived
// here — the textarea is gone, and with it the overflow-y juggling that stopped
// Firefox painting a scrollbar inside an empty one-line box.

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import MessageInput from "../MessageInput.js";

const composer = () => screen.getByRole("textbox") as HTMLInputElement;

describe("the ask bar", () => {
  it("is a single-line input, not a textarea", () => {
    render(<MessageInput onSubmit={vi.fn()} />);
    expect(composer().tagName).toBe("INPUT");
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
    expect(order).toEqual(["ask-attach", "tools", "input", "button"]);
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
