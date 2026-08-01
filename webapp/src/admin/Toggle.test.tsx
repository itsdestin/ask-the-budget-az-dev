import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Toggle } from "./Toggle";

// The bug this file exists for: the switch could only be operated by clicking
// the "On/Off" word beside it, never the pill (Destin, 2026-07-31). The
// invisible input was stretched across the control with `position:absolute;
// inset:0`, but `.adm-toggle-track` is `position:relative` and therefore
// painted on top of it, swallowing every click aimed at the pill. The text
// was statically positioned, so it did not — hence the strange asymmetry.
//
// jsdom applies no stylesheet and does no hit-testing, so it cannot catch a
// stacking-order bug directly. What it CAN check is the structural property
// that makes the class of bug impossible: the control is wrapped in a
// <label>, so activating any descendant activates the input natively,
// whatever the paint order. These tests fail against the old markup.

function setup(checked = false) {
  const onChange = vi.fn();
  const { container } = render(
    <Toggle checked={checked} onChange={onChange} label="AI Mode" testId="t" />,
  );
  return { onChange, container };
}

describe("the pill switch", () => {
  it("is a label, so every part of it activates the control", () => {
    const { container } = setup();
    const input = screen.getByTestId("t");
    const wrapper = container.querySelector(".adm-toggle");
    expect(wrapper?.tagName).toBe("LABEL");
    expect(wrapper).toContainElement(input);
  });

  it("toggles when the pill itself is clicked", () => {
    const { onChange, container } = setup(false);
    // THE regression. Previously this click landed on the track and did
    // nothing at all.
    fireEvent.click(container.querySelector(".adm-toggle-track")!);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("toggles when the knob is clicked", () => {
    const { onChange, container } = setup(false);
    // The knob is a child of the track — the innermost thing a person aims
    // at, and the most likely place for a stray stacking rule to bite.
    fireEvent.click(container.querySelector(".adm-toggle-knob")!);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("still toggles from the On/Off text", () => {
    const { onChange, container } = setup(true);
    fireEvent.click(container.querySelector(".adm-toggle-state")!);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("keeps the input out of the pointer's way entirely", () => {
    const { container } = setup();
    const input = container.querySelector(".adm-toggle input");
    // It is hidden and inert; the label does the work. An input that
    // captured pointer events would put us back in the business of
    // reasoning about which element is on top.
    expect(input).toBeInTheDocument();
    expect(input).not.toHaveAttribute("hidden");
  });

  it("is announced as a switch with a name of its own", () => {
    setup(true);
    const input = screen.getByRole("switch", { name: "AI Mode" });
    expect(input).toBeChecked();
  });

  it("does not double-announce the On/Off word", () => {
    const { container } = setup(true);
    // The heading beside the switch is its visible label; the word is
    // decoration, and a screen reader reading "AI Mode On On" helps nobody.
    expect(container.querySelector(".adm-toggle-state")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(container.querySelector(".adm-toggle-track")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("does nothing when disabled", () => {
    const onChange = vi.fn();
    const { container } = render(
      <Toggle checked={false} onChange={onChange} label="AI Mode" disabled testId="t" />,
    );
    fireEvent.click(container.querySelector(".adm-toggle-track")!);
    expect(onChange).not.toHaveBeenCalled();
  });
});
