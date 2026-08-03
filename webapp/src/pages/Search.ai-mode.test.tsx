// Budget Documents and AI Mode — the guarantee that they are now SEPARATE.
//
// Destin removed the per-page AI Mode toggle on 2026-07-31 ("I hate that 'AI
// Mode' is part of the budget search tab"). What survives here is the inverse
// of each old assertion — no AI control on this page, the directory is never
// replaced by a conversation — because "the toggle came back" is the
// regression this page has to be protected from. The panel behaviours
// themselves live in Ai.test.tsx; nothing was dropped on the floor.
//
// The old file's passage-row keyboard spec is GONE with the old page: the
// 2026-08-03 browse rebuild has no retrieval passages and no source panel —
// its rows link straight to the source PDF (or render unlinked), so there is
// no chunk drawer to open from the keyboard.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Search } from "./Search";
import * as api from "./ai-test-fixtures";
import * as realApi from "../api";
import { AI_STATUS, stubScrollIntoView } from "./ai-test-fixtures";

const DOCS: realApi.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
  { doc_id: "b27-edu", title: "FY 2027 Baseline — Department of Education", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/edu.pdf" },
];

function mount() {
  vi.spyOn(realApi, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  // Still stubbed even though this page never probes: if someone reintroduces
  // a status probe here, the assertions below should fail, not hit a real fetch.
  vi.spyOn(realApi, "aiStatus").mockResolvedValue(AI_STATUS);
  return render(
    <MemoryRouter initialEntries={["/search"]}>
      <Search />
    </MemoryRouter>,
  );
}

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("Budget Documents — AI Mode is not on this page", () => {
  it("has no AI control anywhere on the page", async () => {
    api.stubConversationFetch();
    mount();
    await screen.findByText(/FY 2027 Baseline/);
    // Nothing named "AI Mode", and no chat surface mounted.
    expect(screen.queryByRole("button", { name: /ai mode/i })).toBeNull();
    expect(screen.queryByTestId("ai-panel")).toBeNull();
  });

  it("renders the document directory unconditionally — nothing can replace it", async () => {
    api.stubConversationFetch();
    const view = mount();
    await screen.findByText(/FY 2027 Baseline/);
    expect(view.container.querySelector(".docmain")).not.toBeNull();
    expect(view.container.querySelector(".ai-panel")).toBeNull();
    // The filter rail is likewise always present — it used to be hidden in AI
    // Mode, and there is no longer any state in which it disappears.
    expect(view.container.querySelector(".docside")).not.toBeNull();
  });
});
