// Budget Documents and AI Mode — the guarantee that they are now SEPARATE.
//
// This file used to pin the per-page AI Mode toggle: the pill in the subhero,
// the on/off round trip that swapped the results panel for a conversation, and
// the search box's second destination. Destin removed that on 2026-07-31 ("I
// hate that 'AI Mode' is part of the budget search tab"), so those assertions
// are wrong by design and are gone. What survives is the inverse of each one —
// no AI control here, the results list is never replaced, the box has exactly
// one destination — because "the toggle came back" and "the box forks again"
// are the regressions this page now has to be protected from. The panel
// behaviours themselves moved to Ai.test.tsx; nothing was dropped on the floor.
//
// The passage-row keyboard spec at the bottom is unchanged and unrelated to AI
// Mode; it lives here because it was written against these fixtures.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Search } from "./Search";
import * as api from "../api";
import { AI_STATUS, stubConversationFetch, stubScrollIntoView } from "./ai-test-fixtures";

const RESULT = {
  chunk_id: "c1",
  doc_id: "d1",
  doc_title: "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
  snippet: "…provider rate increases…",
  page: 14,
  score: 0.91,
  doc_type: "baseline-per-agency",
  fiscal_year: 2027,
  publisher: "jlbc",
  agencies: ["ahcccs"],
  doc_url: "https://www.azjlbc.gov/27baseline/axs.pdf",
  doc_meta: "Agency Budget Detail · Baseline Book · FY 2027",
};

function mountWithResults(status = AI_STATUS) {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT],
    total: 1,
    provider: "lance",
  });
  // Still stubbed even though this page no longer probes: if someone
  // reintroduces a status probe here, the test should fail on the assertion
  // below, not on an unmocked fetch.
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}>
      <Search />
    </MemoryRouter>,
  );
}

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("Budget Documents — AI Mode is not on this page", () => {
  it("has no AI control anywhere on the page", async () => {
    stubConversationFetch();
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    // Nothing named "AI Mode", and no chat surface mounted.
    expect(screen.queryByRole("button", { name: /ai mode/i })).toBeNull();
    expect(screen.queryByTestId("ai-panel")).toBeNull();
  });

  it("renders the results list unconditionally — nothing can replace it", async () => {
    // The S12 guarantee, restated for a page with no mode switch: the results
    // presentation was iterated live with Destin, and it is the only answer
    // surface this page has.
    const view = mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    expect(view.container.querySelector(".results")).not.toBeNull();
    expect(view.container.querySelector(".ai-panel")).toBeNull();
    // The filter rail is likewise always present — it used to be hidden in AI
    // Mode, and there is no longer any state in which it disappears.
    expect(view.container.querySelector(".filters")).not.toBeNull();
  });

  it("sends the search box to a keyword search, never to a conversation", async () => {
    const { calls } = stubConversationFetch();
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    const before = (api.search as unknown as { mock: { calls: unknown[] } }).mock.calls
      .length;

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "how much for provider rates?" } });
    await act(async () => {
      fireEvent.submit(box.closest("form")!);
    });

    // The query ran as a search…
    expect(
      (api.search as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
    ).toBeGreaterThan(before);
    // …and opened no conversation. The box had two destinations while the
    // toggle existed; it has one now.
    expect(calls.filter((c) => c.url === "/api/conversations")).toHaveLength(0);
    // The submit button says what it does, with no second label.
    expect(screen.getByRole("button", { name: /^search$/i })).toBeEnabled();
  });
});

describe("Search — passage rows are keyboard reachable", () => {
  it("opens the source panel from the keyboard", async () => {
    stubConversationFetch();
    vi.spyOn(api, "chunk").mockResolvedValue({
      chunk_id: "c1",
      doc_id: "d1",
      page: 14,
      bbox: null,
      text: "…provider rate increases…",
      source_format: "pdf",
      pdf_unavailable_reason: null,
    });
    const view = mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    fireEvent.click(screen.getByRole("button", { name: /1 passage/i }));

    const row = view.container.querySelector('[data-chunk-id="c1"]') as HTMLElement;
    // A new user-facing action on the provenance path cannot be mouse-only.
    expect(row.tabIndex).toBe(0);
    expect(row).toHaveAttribute("role", "button");
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    expect(await screen.findByLabelText("Source passage")).toBeInTheDocument();
  });
});
