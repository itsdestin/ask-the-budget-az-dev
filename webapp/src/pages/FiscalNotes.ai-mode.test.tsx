// Fiscal Notes — the same AI Mode toggle, on the fiscal-note corpus.
//
// The toggle lives in the PAGE-HEAD region only: Plan 3 owns the filter rail
// (`.fside-search` and the semantic-search box under it) and these edits stay
// disjoint from it.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { FiscalNotes } from "./FiscalNotes";
import * as api from "../api";
import {
  AI_STATUS,
  stubConversationFetch,
  stubScrollIntoView,
} from "./ai-test-fixtures";

const SNAPSHOT = {
  sessions: [
    {
      year: 2026,
      name: "Fifty-seventh Legislature — Second Regular Session",
      bills: [
        {
          bill_number: "HB2001",
          title: "appropriation; state parks",
          chamber: "H" as const,
          fiscal_note_url: "https://www.azjlbc.gov/fiscalnotes/hb2001.pdf",
        },
      ],
    },
  ],
};

function mountPage(status = AI_STATUS) {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(SNAPSHOT);
  vi.spyOn(api, "fiscalNotesStatus").mockResolvedValue({ chunks: 0 });
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
}

const toggle = () => screen.getByRole("button", { name: /ai mode/i });

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("FiscalNotes — AI Mode toggle", () => {
  it("puts the pill in the page head, not in the filter rail", async () => {
    stubConversationFetch();
    mountPage();
    await screen.findByText(/HB2001/);
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(toggle().closest(".subhero")).not.toBeNull();
    // Plan 3's rail is untouched by this task.
    expect(toggle().closest(".fnside")).toBeNull();
  });

  it("opens a fiscal-note conversation, not a budget one", async () => {
    const { calls } = stubConversationFetch();
    mountPage();
    await screen.findByText(/HB2001/);

    fireEvent.click(toggle());
    const composer = await screen.findByRole("textbox");
    fireEvent.change(composer, { target: { value: "have we noted a parks bill before?" } });
    await act(async () => {
      fireEvent.keyDown(composer, { key: "Enter" });
    });

    const create = calls.find((c) => c.url === "/api/conversations")!;
    expect(JSON.parse(create.init!.body as string)).toEqual({
      corpus: "fiscal_notes",
    });
  });

  it("offers no starter questions — the shipped ones are budget questions", async () => {
    // SuggestionRow hardcodes "the FY2025 Aviation Fund balance", "ADOT in
    // FY2024" and "General Fund revenue projections". Pointed at the
    // fiscal-note corpus those are three guaranteed empty retrievals, so a
    // coordinator's first click would land straight in the refusal banner.
    stubConversationFetch();
    mountPage();
    await screen.findByText(/HB2001/);
    fireEvent.click(toggle());
    await screen.findByTestId("ai-panel");
    expect(screen.queryByText(/Aviation Fund balance/)).toBeNull();
    expect(screen.queryByText(/ADOT receive/)).toBeNull();
  });

  it("returns the bill directory unchanged when switched back off", async () => {
    stubConversationFetch();
    const view = mountPage();
    await screen.findByText(/HB2001/);
    const before = view.container.querySelector(".fnlayout")!.innerHTML;

    fireEvent.click(toggle());
    await waitFor(() =>
      expect(view.container.querySelector(".fnlayout")).toBeNull(),
    );
    fireEvent.click(toggle());
    await waitFor(() =>
      expect(view.container.querySelector(".fnlayout")).not.toBeNull(),
    );
    expect(view.container.querySelector(".fnlayout")!.innerHTML).toBe(before);
  });

  it("dims the pill when AI is unavailable", async () => {
    stubConversationFetch();
    mountPage({ ...AI_STATUS, available: false, reason: "no API key configured" });
    await screen.findByText(/HB2001/);
    await waitFor(() =>
      expect(toggle()).toHaveAttribute("aria-disabled", "true"),
    );
    expect(toggle()).toHaveAttribute(
      "title",
      "AI answers require an API key — ask your admin.",
    );
  });
});
