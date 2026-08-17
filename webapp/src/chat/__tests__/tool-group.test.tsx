// ToolGroup collapses a run of consecutive tool calls into one row. Fixtures
// mirror tool-card.test.tsx's `block()` helper.
//
// fireEvent, not userEvent — this webapp has no @testing-library/user-event
// dependency; every other test file in the suite drives clicks via fireEvent
// (see citation-chip.test.tsx / citation-bus.test.tsx).

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ToolGroup from "../ToolGroup.js";
import type { AssistantBlock } from "../chat-types.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

function block(overrides: Partial<ToolBlock>): ToolBlock {
  return {
    kind: "tool",
    toolUseId: "t1",
    toolName: "retrieve",
    input: { query: "Aviation Fund" },
    status: "complete",
    ...overrides,
  } as ToolBlock;
}

const retrieveComplete = block({ toolUseId: "t1", toolName: "retrieve" });
const retrieveComplete2 = block({ toolUseId: "t2", toolName: "retrieve" });
const listFiltersComplete = block({
  toolUseId: "t3",
  toolName: "list_filter_values",
  input: { field: "agency" },
});
const retrieveFailed = block({
  toolUseId: "t5",
  toolName: "retrieve",
  status: "failed",
});
const retrieveRunning = block({
  toolUseId: "t4",
  toolName: "retrieve",
  status: "running",
});

describe("ToolGroup", () => {
  it("coalesces a multi-call run into one past-tense summary row", () => {
    // 2026-08-16 — TC13 replaced the coalesced "Searched ×2, browsed filters"
    // label with a sentence naming the FIRST query, then the second kind of
    // work. This is the header-sentence version of the same property: one
    // row, past tense, everything the run did is represented.
    render(
      <ToolGroup
        tools={[retrieveComplete, retrieveComplete2, listFiltersComplete]}
      />,
    );
    const head = screen.getByRole("button", {
      name: /Searched for “Aviation Fund” and 1 more, then browsed filters/,
    });
    expect(head).toHaveTextContent(
      "Searched for “Aviation Fund” and 1 more, then browsed filters",
    );
  });

  it("renders a run of ONE, carrying that call's own summary", () => {
    render(<ToolGroup tools={[retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searched/ });
    expect(head).toHaveTextContent("Searched");
    // The query is the single most useful thing on the row and the bare
    // ToolCard this replaced showed it. Losing it would be a regression.
    expect(head).toHaveTextContent("Aviation Fund");
  });

  it("expands a run of ONE straight to that call's body — one click, not two", () => {
    // The bare ToolCard this replaced opened its body on a single click.
    // Wrapping the sole call in a child row would silently make every source
    // check a two-click operation, and every count-based assertion would
    // still pass.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(screen.getByRole("button", { name: /Searched/ }));
    expect(container.querySelector(".chat-tool-body")).not.toBeNull();
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(0);
  });

  it("expands a multi-call run to inset child rows", () => {
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Searched for “Aviation Fund”, then browsed filters/,
      }),
    );
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(2);
  });

  it("puts every expansion inside one capped container", () => {
    // TC8's cap is a single CSS rule on this element. If a future edit renders
    // the body outside it, the cap silently stops applying and a 15-passage
    // expansion buries the answer again.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Searched for “Aviation Fund”, then browsed filters/,
      }),
    );
    const expansion = container.querySelector(".chat-tool-group-expansion")!;
    expect(expansion, "the expansion must have its capped wrapper").not.toBeNull();
    expect(expansion.querySelector(".chat-tool-group-body")).not.toBeNull();
  });
});

describe("ToolGroup tense and progress", () => {
  it("uses the present participle while any call is still in flight", () => {
    // "Searched" over a call that has not finished is a false statement about
    // a live process (TC4). 2026-08-16 — TC13 folds the count into "and N
    // more" rather than a trailing "×2".
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    const head = screen.getByRole("button", {
      name: /Searching for “Aviation Fund” and 1 more…/,
    });
    expect(head).toHaveTextContent("Searching for “Aviation Fund” and 1 more…");
    expect(head).not.toHaveTextContent("Searched");
  });

  it("reports progress while a multi-call run is in flight", () => {
    // 2026-08-16 — TC13 dropped the "N of M done" tally in favour of the
    // trailing ellipsis plus "and N more": the sentence itself is the
    // in-flight signal now, not a separate counter.
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searching/ });
    expect(head).toHaveTextContent("and 1 more");
    expect(head).toHaveTextContent("…");
    expect(head).not.toHaveTextContent(/\d+ of \d+ done/);
  });

  it("shows NO per-call completion count once a multi-call run has settled", () => {
    // "all complete" is deleted, not kept, and so is any "N of M done" tally.
    // Asserting one while suppressing "1 failed" would make the card claim a
    // clean run it cannot vouch for; silence claims nothing (TC3).
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveComplete2]} />,
    );
    expect(container.textContent).not.toMatch(/\d+ of \d+ done/);
    expect(container.textContent).not.toContain("all complete");
    // The trailing ellipsis is an in-flight marker only.
    expect(container.textContent).not.toContain("…");
  });

  it("still shows the query on a settled run of one", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    const sentence = container.querySelector(".chat-tool-sentence");
    expect(sentence).not.toBeNull();
    expect(sentence!.textContent).toContain("Aviation Fund");
  });

  it("wraps a single call's expansion in the capped container too", () => {
    // The height cap is one CSS rule on .chat-tool-group-expansion. Dropping
    // the wrapper only in the n = 1 branch would pass every other test here,
    // including the one-click test, which looks for .chat-tool-body and not
    // for what contains it.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(screen.getByRole("button", { name: /Searched/ }));
    const expansion = container.querySelector(".chat-tool-group-expansion")!;
    expect(expansion).not.toBeNull();
    expect(expansion.querySelector(".chat-tool-body")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2026-08-16 — TC9. The collapsed card carries NO failure signal at all.
//
// This INVERTS what this file used to assert. The old tests pinned a red group
// header and a "1 failed" count, and carefully scoped the tint so it could not
// reach a successful child. All of that is gone, because the signal is not
// actionable: the model retries a failed call itself, so a red row usually
// marks a transient step in work that then succeeded, and alarming an analyst
// about a self-correcting event spends the trust every other warning needs.
//
// DEMOTED, NOT DELETED — the second test below is the half that matters. A
// suppression that also drops the call on the floor would satisfy the first
// test perfectly and destroy the audit trail, which is the direction this is
// most at risk of drifting in.
// ---------------------------------------------------------------------------

describe("ToolGroup failure handling", () => {
  it("looks identical to an all-successful run when collapsed", () => {
    const { container: withFailure } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    const head = withFailure.querySelector(".chat-tool-head")!;

    expect(withFailure.querySelector(".is-failed")).toBeNull();
    expect(withFailure.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
  });

  it("still records the failure inside the expansion", () => {
    // The audit trail is intact for anyone who opens the card; it simply stops
    // shouting at people who did not ask.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);

    const failedRows = container.querySelectorAll(
      ".chat-tool-group-body .chat-tool.is-failed",
    );
    expect(
      failedRows,
      "the failed call must still be visible once expanded",
    ).toHaveLength(1);
    expect(
      container.querySelectorAll(".chat-tool-group-body .chat-tool"),
    ).toHaveLength(2);
  });

  // -------------------------------------------------------------------------
  // FINAL REVIEW — IMPORTANT 1. Everything above this line uses a TWO-call run,
  // which is exactly why the "demoted, not deleted" guard never caught the
  // n = 1 hole. A run of one expands straight to ToolBody (TC5), bypassing
  // ToolCard — the only thing that draws `.chat-tool.is-failed` and the glyph's
  // "failed" accessible name — so a lone failed call expanded to an EMPTY body
  // with nothing matching /fail/i anywhere.
  //
  // The fixture deliberately carries NEITHER `isError` NOR `output`: that is
  // the state history-rehydrate.ts writes for a stored conversation whose turn
  // was stopped or torn mid-search, and every tool view gates its ErrorBlock on
  // `isError && output`, so it is the case an ErrorBlock-based fix would miss.
  // -------------------------------------------------------------------------
  it("a lone failed call still shows nothing when collapsed", () => {
    const { container } = render(<ToolGroup tools={[retrieveFailed]} />);
    const head = container.querySelector(".chat-tool-head")!;

    expect(container.querySelector(".is-failed")).toBeNull();
    expect(container.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
  });

  it("a lone failed call DOES surface its failure once expanded", () => {
    const { container } = render(<ToolGroup tools={[retrieveFailed]} />);
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);

    // Both halves, as with the multi-call pair above: the visible words and
    // the class the stylesheet paints from.
    expect(
      container.textContent,
      "an empty expansion is the defect — the failure must be stated",
    ).toMatch(/fail/i);
    expect(container.querySelector(".chat-tool-single.is-failed")).not.toBeNull();
    // Still one click to the body: the fix must not have reintroduced a child
    // row (TC5).
    expect(container.querySelector(".chat-tool-body")).not.toBeNull();
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(0);
  });

  it("names the missing result when a torn transcript recorded no error text", () => {
    const { container } = render(<ToolGroup tools={[retrieveFailed]} />);
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);
    expect(container.textContent).toContain("No result was recorded");
  });

  it("does not claim a missing result when the error text IS present", () => {
    const withError = block({
      toolUseId: "t6",
      toolName: "retrieve",
      status: "failed",
      isError: true,
      output: "Connection lost",
    });
    const { container } = render(<ToolGroup tools={[withError]} />);
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);
    expect(container.textContent).toMatch(/fail/i);
    expect(container.textContent).not.toContain("No result was recorded");
    expect(container.textContent).toContain("Connection lost");
  });

  it("a lone SUCCESSFUL call carries no failure treatment when expanded", () => {
    // Keeps the pair above non-vacuous: if the wrapper ever tinted
    // unconditionally, every expansion would read as a failure.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);
    expect(container.querySelector(".is-failed")).toBeNull();
    expect(container.textContent).not.toMatch(/fail/i);
  });
});

describe("ToolGroup header sentence", () => {
  it("renders the verb bold and the rest normal", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    const verb = container.querySelector(".chat-tool-verb")!;
    expect(verb, "the verb must be its own element so it can be bold").not.toBeNull();
    expect(verb.textContent).toBe("Searched");
    expect(container.querySelector(".chat-tool-head")!.textContent).toContain(
      "for “Aviation Fund”",
    );
  });

  it("still carries NO failure word when a call failed (TC9 survives Part 2)", () => {
    // Part 1's whole failure decision must not be undone by rewording.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    const head = container.querySelector(".chat-tool-head")!;
    expect(head.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
    expect(container.querySelector(".is-failed")).toBeNull();
  });

  it("the accessible name is the whole sentence", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    expect(
      container.querySelector(".chat-tool-head")!.getAttribute("aria-label"),
    ).toBe("Searched for “Aviation Fund”");
  });
});
