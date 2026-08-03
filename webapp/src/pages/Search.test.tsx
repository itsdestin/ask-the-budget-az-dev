import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

// Budget Documents browse page — the 2026-08-03 rebuild. These replace the old
// retrieval-backed Search tests: the page now auto-loads the corpus listing
// (api.corpusDocuments) and filters/searches it client-side. The tests
// intercept the listing with vi.spyOn and assert behavior, not mechanism —
// filtered rows are REMOVED (not display:none), the two card states are
// pinned, the latest-year-expanded default holds, and searching collapses the
// year cards into one unified Results region.

/** A small hand-built corpus: two years, several families, one single-doc
 *  family (AFR), one folded-publisher doc (legislature), one with no URL. */
const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
  { doc_id: "b27-edu", title: "FY 2027 Baseline — Department of Education", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/edu.pdf" },
  { doc_id: "b27-dcs", title: "FY 2027 Baseline — Department of Child Safety", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/dcs.pdf" },
  { doc_id: "eb27", title: "FY 2027 Executive Budget — Governor's Office", publisher: "governor", doc_type: "governors-budget", fiscal_year: 2027, doc_url: "https://x/eb27.pdf" },
  { doc_id: "ar26-ahcccs", title: "FY 2026 Appropriations Report — AHCCCS", publisher: "jlbc", doc_type: "approps-per-agency", fiscal_year: 2026, doc_url: "https://x/ar-axs.pdf" },
  { doc_id: "ar26-edu", title: "FY 2026 Appropriations Report — Department of Education", publisher: "jlbc", doc_type: "approps-per-agency", fiscal_year: 2026, doc_url: "https://x/ar-edu.pdf" },
  { doc_id: "afr26", title: "FY 2026 Annual Financial Report", publisher: "agao", doc_type: "afr", fiscal_year: 2026, doc_url: "https://x/afr26.pdf" },
  // The folded "legislature" code displays as JLBC; this one has no URL.
  { doc_id: "bb26", title: "FY 2026 General Appropriations Act (SB 1735)", publisher: "legislature", doc_type: "budget-bill", fiscal_year: 2026, doc_url: null },
];

function mount(docs = DOCS, entry = "/search") {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: docs });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Search />
    </MemoryRouter>,
  );
}

const AHCCCS27 = /FY 2027 Baseline — AHCCCS/;

// --- browse: auto-load + year grouping + the default open year -------------

test("auto-loads the corpus grouped by fiscal year, newest year expanded", async () => {
  mount();
  // Both year cards render; FY 2027 is the newest and starts expanded…
  const y27 = await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const y26 = screen.getByRole("button", { name: /Fiscal Year 2026:/i });
  expect(y27).toHaveAttribute("aria-expanded", "true");
  expect(y26).toHaveAttribute("aria-expanded", "false");
  // …so FY 2027's bare report rows are visible, FY 2026's are mounted but hidden.
  expect(screen.getByText("FY 2027 Baseline")).toBeInTheDocument();
  const y26card = document.querySelector('[data-year-card="2026"]') as HTMLElement;
  expect(within(y26card).getByText("FY 2026 Annual Financial Report")).toBeInTheDocument();
  expect(y26card.querySelector(".yg-body")).toHaveAttribute("hidden");
});

test("a collapsed year expands on click and the toggle persists", async () => {
  mount();
  const y26 = await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  const y26card = document.querySelector('[data-year-card="2026"]') as HTMLElement;
  // The body is mounted but hidden while collapsed (the mockup's innerHTML
  // re-render would destroy it); the same node is revealed on expand.
  const bodyBefore = y26card.querySelector(".yg-body");
  fireEvent.click(y26);
  expect(y26).toHaveAttribute("aria-expanded", "true");
  expect(y26card.querySelector(".yg-body")).not.toHaveAttribute("hidden");
  expect(y26card.querySelector(".yg-body")).toBe(bodyBefore); // revealed, not remounted
  // FY 2027 stays open; expanding a prior year does not collapse the latest.
  expect(screen.getByRole("button", { name: /Fiscal Year 2027:/i })).toHaveAttribute("aria-expanded", "true");
});

// --- idle card state: bare report rows + the dashed tray --------------------

test("idle family cards are bare report rows with a collapsible documents tray", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The FY 2027 Baseline report row is the top level; its 3 documents sit
  // behind the dashed tray, not listed.
  expect(screen.getByText("FY 2027 Baseline")).toBeInTheDocument();
  expect(screen.queryByText(AHCCCS27)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /browse documents/i }));
  // All three FY 2027 baseline agency pages are now listed, title A→Z.
  const titles = screen.getAllByText(/FY 2027 Baseline — /).map((n) => n.textContent);
  expect(titles).toEqual([
    "FY 2027 Baseline — AHCCCS",
    "FY 2027 Baseline — Department of Child Safety",
    "FY 2027 Baseline — Department of Education",
  ]);
});

test("single-document families get no dashed tray", async () => {
  mount();
  const y26 = await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.click(y26);
  // The AFR is a one-document report: the report row links the document and
  // there is NO "N documents in this report" box for it.
  const afr = screen.getByText("FY 2026 Annual Financial Report");
  expect(afr.closest(".grp")!.querySelector(".ctx")).toBeNull();
});

test("full-report links appear only where a hand-verified URL exists", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // FY 2027 Baseline has a verified single-file URL.
  expect(screen.getByRole("link", { name: /full report/i })).toHaveAttribute(
    "href",
    "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
  );
  // FY 2026's families have none.
  fireEvent.click(screen.getByRole("button", { name: /Fiscal Year 2026:/i }));
  const y26card = document.querySelector('[data-year-card="2026"]') as HTMLElement;
  expect(within(y26card).queryByRole("link", { name: /full report/i })).toBeNull();
});

// --- the publisher chip (folded vocabulary) ---------------------------------

test("every row leads with a copper publisher chip in the folded vocabulary", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // governor → OSPB on the Executive Budget report row.
  expect(screen.getByText("FY 2027 Executive Budget").closest(".doc")!
    .querySelector(".doc-pub")).toHaveTextContent("OSPB");
  // The folded legislature → JLBC on the budget-bill report row (FY 2026).
  fireEvent.click(screen.getByRole("button", { name: /Fiscal Year 2026:/i }));
  const bill = screen.getByText("FY 2026 Budget Bill").closest(".doc")!;
  expect(bill.querySelector(".doc-pub")).toHaveTextContent("JLBC");
  // And jlbc → JLBC inside a tray. Scope to FY 2027's card to click ITS button.
  const y27card = document.querySelector('[data-year-card="2027"]') as HTMLElement;
  fireEvent.click(within(y27card).getByRole("button", { name: /browse documents/i }));
  expect(screen.getByText(AHCCCS27).closest(".doc")!.querySelector(".doc-pub")).toHaveTextContent("JLBC");
  // Nowhere does the page render the OLD vocabulary.
  expect(document.querySelector(".page-docs")!.textContent).not.toMatch(/AGAO|Governor's Office of|Legislature/);
});

test("a row with no doc_url renders unlinked, not as a dead link", async () => {
  mount();
  const y26 = await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.click(y26);
  // The budget-bill report row has no verified URL and its single document has
  // none either, so it renders unlinked — the title is there, no <a> wraps it.
  expect(screen.queryByRole("link", { name: /FY 2026 Budget Bill/ })).toBeNull();
  expect(screen.getByText("FY 2026 Budget Bill")).toBeInTheDocument();
});

// --- rail filters -------------------------------------------------------------

/** The rail's filter trigger buttons. Scoped to `.docside` because the year
 *  CARD toggle buttons ("Fiscal Year 2026: …") would otherwise also match a
 *  bare /fiscal year/i name query. */
function railTrigger(name: RegExp) {
  return within(document.querySelector(".docside") as HTMLElement).getByRole("button", { name });
}

test("the Document Type filter removes non-matching families", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.click(railTrigger(/document type/i));
  fireEvent.click(screen.getByRole("button", { name: /^annual financial report/i }));
  // Only the AFR family survives, in FY 2026; FY 2027 (no AFR) disappears, and
  // the trigger tints with the single pick's label.
  expect(screen.getByRole("button", { name: /annual financial report/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Fiscal Year 2027:/i })).toBeNull();
  expect(screen.getByText("FY 2026 Annual Financial Report")).toBeInTheDocument();
  expect(screen.queryByText("FY 2027 Baseline")).toBeNull();
});

test("the Fiscal Year filter scopes the year cards", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.click(railTrigger(/fiscal year/i));
  fireEvent.click(screen.getByRole("button", { name: /^fy 2027/i }));
  expect(screen.getByRole("button", { name: /Fiscal Year 2027:/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Fiscal Year 2026:/i })).toBeNull();
});

// --- search: unified collapse + promoted match -------------------------------

test("searching collapses the years into one Results card with promoted matches", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahcccs" },
  });
  // The year cards are gone; ONE Results card holds the AHCCCS matches across
  // both years, the match promoted to the card top with "Part of" framing.
  expect(screen.queryByRole("button", { name: /Fiscal Year 2027:/i })).toBeNull();
  expect(screen.getByText("Results")).toBeInTheDocument();
  expect(screen.getByText(AHCCCS27)).toBeInTheDocument();
  expect(screen.getByText(/Part of the FY 2027 Baseline/)).toBeInTheDocument();
  expect(screen.getByText(/FY 2026 Appropriations Report — AHCCCS/)).toBeInTheDocument();
});

test("a query in the title matches; non-matching documents are removed", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "child safety" },
  });
  expect(screen.getByText(/FY 2027 Baseline — Department of Child Safety/)).toBeInTheDocument();
  expect(screen.queryByText(AHCCCS27)).toBeNull();
  expect(screen.queryByText(/Department of Education/)).toBeNull();
});

test("a query matching nothing shows an honest empty state", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "zzz-no-such-thing" },
  });
  expect(screen.getByText(/no documents match/i)).toBeInTheDocument();
});

test("clearing the box returns to the year browse", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const box = screen.getByLabelText(/filter documents by agency or keyword/i);
  fireEvent.change(box, { target: { value: "ahcccs" } });
  expect(screen.getByText("Results")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
  expect(screen.queryByText("Results")).toBeNull();
  expect(screen.getByRole("button", { name: /Fiscal Year 2027:/i })).toBeInTheDocument();
});

// --- the ?q= hand-off ---------------------------------------------------------

test("an arriving ?q= seeds the box and lands in the unified search state", async () => {
  mount(DOCS, "/search?q=ahcccs");
  // No year cards; the unified Results state, with the query in the box.
  await screen.findByText("Results");
  expect(screen.getByLabelText(/filter documents by agency or keyword/i)).toHaveValue("ahcccs");
  expect(screen.getByText(AHCCCS27)).toBeInTheDocument();
});

// --- status line --------------------------------------------------------------

test("the status line reports honest counts", async () => {
  mount();
  // 5 reports · 8 documents across all fiscal years.
  await screen.findByText(/5 reports · 8 documents, across all fiscal years\./i);
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahcccs" },
  });
  await screen.findByText(/2 documents across 2 reports, in all fiscal years, matching “ahcccs”\./i);
});
