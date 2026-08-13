// Fiscal Notes and AI Mode — the guarantee that they are now SEPARATE.
//
// This file used to pin the page-head AI Mode toggle. Destin moved AI Mode to
// its own tab on 2026-07-31, so the toggle specs are wrong by design and are
// gone; every behaviour they covered moved to Ai.test.tsx with the corpus
// picker standing in for the pill (the fiscal-note corpus is still reachable,
// still gets no budget starter chips, still explains a missing key). What is
// left here is the inverse guarantee: the directory is the whole page, and the
// Plan 3 rail is still nobody else's business.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { FiscalNotes } from "./FiscalNotes";
import * as api from "../api";
import { AI_STATUS, stubConversationFetch, stubScrollIntoView } from "./ai-test-fixtures";

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
  // Still stubbed although the page no longer probes — see the same note in
  // Search.ai-mode.test.tsx.
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
}

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("Fiscal Notes — AI Mode is not on this page", () => {
  it("has no AI control, and the bill directory always renders", async () => {
    stubConversationFetch();
    const view = mountPage();
    await screen.findByText(/HB2001/);
    expect(screen.queryByRole("button", { name: /ai mode/i })).toBeNull();
    expect(screen.queryByTestId("ai-panel")).toBeNull();
    // The directory used to be unmounted while the toggle was on; there is no
    // longer any state in which it disappears.
    expect(view.container.querySelector(".fnlayout")).not.toBeNull();
  });

  it("leaves Plan 3's filter rail intact", async () => {
    // The toggle removal touched the page-head band only; the rail is not its business.
    // Updated 2026-08-13 for the browse rebuild: the session control is a multi-select
    // (`.fctl`) rather than a `.yscroll` radio list (spec F1), and the rail's SECOND
    // search box is deleted (spec F6). What this test is actually for — "removing AI Mode
    // did not take the filter rail with it" — is unchanged.
    stubConversationFetch();
    const view = mountPage();
    await screen.findByText(/HB2001/);
    const rail = view.container.querySelector(".fnside")!;
    expect(rail.querySelector(".fside-search")).not.toBeNull();
    expect(rail.querySelector(".chswitch")).not.toBeNull();
    expect(rail.querySelector(".fctl")).not.toBeNull();
  });
});
