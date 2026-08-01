import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type * as api from "../api";
import { ModelPicker, perQuestion } from "./ModelPicker";

// A closed dropdown that opens into a rich menu. Two things are pinned:
//
//  1. It is COMPACT at rest — one row, the current choice and its cost. The
//     radio-list version showed eight options permanently, which is more
//     page than a twice-a-year setting earns.
//  2. It is fully keyboard-operable. A native <select> gets that for free;
//     this is hand-rolled because options need chips and blurbs, so every
//     key a <select> would have handled is a deliberate test here. A custom
//     control a keyboard can't drive is a regression from what it replaced.
//
// And what must NOT appear: any speed or latency rating. OpenRouter
// publishes those fields but returned null for every shipped recommendation
// when checked on 2026-07-31.

function card(over: Partial<api.ModelCard> = {}): api.ModelCard {
  return {
    id: "vendor/model",
    name: "A Model",
    context_length: 1_000_000,
    prompt_usd_per_m: 0.32,
    completion_usd_per_m: 1.28,
    supports_tools: true,
    available: true,
    tier_hint: "standard",
    blurb: "Does the thing.",
    max_output_tokens: 131_072,
    is_open_weights: true,
    usd_per_question: 0.0127,
    intelligence_index: 39,
    intelligence_percent: 58,
    agentic_index: 20.8,
    ...over,
  };
}

function setup(options: api.ModelCard[], selected = "") {
  const onChange = vi.fn();
  const view = render(
    <ModelPicker
      tier="standard"
      label="Standard"
      selected={selected}
      options={options}
      onChange={onChange}
    />,
  );
  const trigger = screen.getByRole("button", { name: /model for standard/i });
  return { onChange, trigger, ...view };
}

// Percentages are what the server sends; the raw index rides along only for
// the tooltip. 33.7 -> 50%, 57.1 -> 85% against the shipped ceiling.
const TWO = [
  card({
    id: "a", name: "Cheap", usd_per_question: 0.0049,
    intelligence_index: 33.7, intelligence_percent: 50,
  }),
  card({
    id: "b", name: "Pricey", usd_per_question: 0.184,
    intelligence_index: 57.1, intelligence_percent: 85,
  }),
];

describe("cost per question, in money a person reads", () => {
  it("uses cents, because that is what makes the comparison obvious", () => {
    // 0.0049 vs 0.5625 is a 100x difference that reads as counting decimal
    // places. "half a cent" vs "56¢" reads as itself.
    expect(perQuestion(0.0049)).toBe("under half a cent a question");
    expect(perQuestion(0.0127)).toBe("about 1¢ a question");
    expect(perQuestion(0.184)).toBe("about 18¢ a question");
    expect(perQuestion(0.5625)).toBe("about 56¢ a question");
  });

  it("falls back to dollars above a dollar", () => {
    expect(perQuestion(2.5)).toBe("about $2.50 a question");
  });

  it("says nothing when there is no price to work from", () => {
    // An offline catalog, or a model the list could not confirm. Silence,
    // never a confident $0.00.
    expect(perQuestion(null)).toBeNull();
  });

  it("never claims more precision than it has", () => {
    for (const value of [0.0049, 0.0127, 0.184, 2.5]) {
      expect(perQuestion(value)).toMatch(/about|under/);
    }
  });
});

describe("at rest", () => {
  it("is one row: the current choice and what it costs", () => {
    const { trigger } = setup(TWO, "b");
    expect(trigger).toHaveTextContent("Pricey");
    expect(trigger).toHaveTextContent("about 18¢ a question");
    // Nothing else on the page until asked — that is the whole point.
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.queryByText("Cheap")).toBeNull();
  });

  it("prompts when nothing is chosen yet", () => {
    const { trigger } = setup(TWO);
    expect(trigger).toHaveTextContent(/pick a model/i);
  });

  it("says so when the configured model has been retired", () => {
    const { trigger } = setup([card({ id: "a", name: "Fine" })], "vendor/vanished");
    // Not silently deselected — the admin has to see what happened.
    expect(trigger).toHaveTextContent("vendor/vanished");
    expect(trigger).toHaveTextContent(/no longer available/i);
  });

  it("reports its own expanded state", () => {
    const { trigger } = setup(TWO, "a");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});

describe("the open menu", () => {
  it("shows every option's cost and intelligence at once", () => {
    const { trigger } = setup(TWO, "a");
    fireEvent.click(trigger);

    const list = screen.getByRole("listbox");
    const cheap = within(list).getByRole("option", { name: /cheap/i });
    expect(cheap).toHaveTextContent("under half a cent a question");
    expect(cheap).toHaveTextContent("intelligence 50%");
    const pricey = within(list).getByRole("option", { name: /pricey/i });
    expect(pricey).toHaveTextContent("about 18¢ a question");
    expect(pricey).toHaveTextContent("intelligence 85%");
  });

  it("renders the percentage the server sent, not the raw index", () => {
    // The scale is defined once, server-side. If the component ever went
    // back to reading intelligence_index it would render "57%" here — a
    // number on a different scale that happens to look plausible, which is
    // the worst kind of wrong.
    const { trigger } = setup(TWO, "a");
    fireEvent.click(trigger);
    const pricey = screen.getByRole("option", { name: /pricey/i });
    expect(pricey).toHaveTextContent("intelligence 85%");
    expect(pricey).not.toHaveTextContent("57%");
  });

  it("sizes the bar to match the number beside it", () => {
    // The bar used to be the raw index read as a percentage — 57 became a
    // 57%-wide bar by coincidence. Now the two say the same thing.
    const { trigger, container } = setup(TWO, "a");
    fireEvent.click(trigger);
    const bars = container.querySelectorAll(".adm-cap-bar > span");
    const widths = [...bars].map((b) => (b as HTMLElement).style.width);
    expect(widths).toContain("50%");
    expect(widths).toContain("85%");
  });

  it("says nothing about a model nobody has scored", () => {
    const { trigger } = setup([
      card({ id: "a", name: "Unscored", intelligence_index: null,
             intelligence_percent: null }),
    ], "a");
    fireEvent.click(trigger);
    // A zero-length bar would say "this model is bad" when what is true is
    // "nobody has measured it".
    expect(screen.getByRole("option", { name: /unscored/i })).not.toHaveTextContent(
      /intelligence/i,
    );
  });

  it("explains what the intelligence figure is measured against", () => {
    const { trigger, container } = setup(TWO, "a");
    fireEvent.click(trigger);
    expect(container.textContent).toMatch(/Artificial Analysis/);
    // The headroom is the part an admin would otherwise misread: a top model
    // at 85% looks like a mark against 100 unless the page says otherwise.
    expect(container.textContent).toMatch(/nothing reaches 100%/i);
  });

  it("marks the current choice", () => {
    const { trigger } = setup(TWO, "b");
    fireEvent.click(trigger);
    expect(screen.getByRole("option", { name: /pricey/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("option", { name: /cheap/i })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("chooses on click and closes", () => {
    const { trigger, onChange } = setup(TWO, "a");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: /pricey/i }));

    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("keeps a retired model visible but unchoosable", () => {
    const { trigger, onChange } = setup([
      card({ id: "a", name: "Fine" }),
      card({ id: "b", name: "Gone", available: false, usd_per_question: null }),
    ], "a");
    fireEvent.click(trigger);

    const gone = screen.getByRole("option", { name: /gone/i });
    expect(gone).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(gone);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("closes when the pointer goes elsewhere", () => {
    const { trigger } = setup(TWO, "a");
    fireEvent.click(trigger);
    // Otherwise a click on another card leaves this menu hanging open, and
    // two pickers can look open at once.
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("keeps the caveat inside the menu, not on the page at rest", () => {
    const { trigger, container } = setup(TWO, "a");
    expect(container.textContent).not.toMatch(/guide rather than a quote/i);
    fireEvent.click(trigger);
    expect(container.textContent).toMatch(/guide rather than a quote/i);
  });

  it("shows no speed or latency rating anywhere", () => {
    const { trigger, container } = setup(TWO, "a");
    fireEvent.click(trigger);
    const text = (container.textContent ?? "").toLowerCase();
    for (const invented of ["latency", "throughput", "tokens/s", "speed"]) {
      expect(text).not.toContain(invented);
    }
  });
});

// A native <select> would have given all of this for free. It is hand-rolled
// because options need chips and blurbs, so each key is a deliberate test.
describe("the keyboard", () => {
  function openWithKeyboard(selected = "a") {
    const view = setup(TWO, selected);
    fireEvent.keyDown(view.trigger, { key: "ArrowDown" });
    return { ...view, list: screen.getByRole("listbox") };
  }

  it("opens from the trigger", () => {
    const { trigger } = setup(TWO, "a");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("opens on Enter and on Space too", () => {
    for (const key of ["Enter", " "]) {
      const { trigger, unmount } = setup(TWO, "a");
      fireEvent.keyDown(trigger, { key });
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      unmount();
    }
  });

  it("starts on the current choice, not at the top", () => {
    const { list } = openWithKeyboard("b");
    const activeId = list.getAttribute("aria-activedescendant");
    expect(document.getElementById(activeId!)).toHaveTextContent("Pricey");
  });

  it("moves with the arrow keys and wraps", () => {
    const { list } = openWithKeyboard("a");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(
      document.getElementById(list.getAttribute("aria-activedescendant")!),
    ).toHaveTextContent("Pricey");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(
      document.getElementById(list.getAttribute("aria-activedescendant")!),
    ).toHaveTextContent("Cheap");
  });

  it("chooses with Enter", () => {
    const { list, onChange } = openWithKeyboard("a");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    fireEvent.keyDown(list, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes on Escape without choosing, and gives focus back", () => {
    const { list, onChange, trigger } = openWithKeyboard("a");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    fireEvent.keyDown(list, { key: "Escape" });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
    // Focus must come back, or Escape strands the keyboard at the top of
    // the document.
    expect(trigger).toHaveFocus();
  });

  it("closes on Tab rather than leaving an orphaned menu", () => {
    const { list } = openWithKeyboard("a");
    fireEvent.keyDown(list, { key: "Tab" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("jumps with Home and End", () => {
    const { list } = openWithKeyboard("a");
    fireEvent.keyDown(list, { key: "End" });
    expect(
      document.getElementById(list.getAttribute("aria-activedescendant")!),
    ).toHaveTextContent("Pricey");
    fireEvent.keyDown(list, { key: "Home" });
    expect(
      document.getElementById(list.getAttribute("aria-activedescendant")!),
    ).toHaveTextContent("Cheap");
  });

  it("skips over a retired model instead of landing on it", () => {
    const options = [
      card({ id: "a", name: "One" }),
      card({ id: "b", name: "Gone", available: false }),
      card({ id: "c", name: "Three" }),
    ];
    const { trigger } = setup(options, "a");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const list = screen.getByRole("listbox");

    fireEvent.keyDown(list, { key: "ArrowDown" });
    // Straight past "Gone" — stopping on a row Enter cannot act on is a
    // dead end a keyboard user has to guess their way out of.
    expect(
      document.getElementById(list.getAttribute("aria-activedescendant")!),
    ).toHaveTextContent("Three");
  });
});
