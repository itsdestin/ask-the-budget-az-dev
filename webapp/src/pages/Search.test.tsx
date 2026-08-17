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
// Task 4: CorpusDocument.terms is now required (route always sends it; the
// client never computes it — see api.ts). `terms: []` on every literal below
// keeps these 9 pre-existing fixtures' matching behaviour identical to before
// this task, since an empty terms array can never satisfy an exact-equality
// check.
const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf", section_of: null, terms: [] },
  { doc_id: "b27-edu", title: "FY 2027 Baseline — Department of Education", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/edu.pdf", section_of: null, terms: [] },
  { doc_id: "b27-dcs", title: "FY 2027 Baseline — Department of Child Safety", publisher: "jlbc", doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/dcs.pdf", section_of: null, terms: [] },
  { doc_id: "eb27", title: "FY 2027 Executive Budget — Governor's Office", publisher: "governor", doc_type: "governors-budget", fiscal_year: 2027, doc_url: "https://x/eb27.pdf", section_of: null, terms: [] },
  { doc_id: "ar26-ahcccs", title: "FY 2026 Appropriations Report — AHCCCS", publisher: "jlbc", doc_type: "approps-per-agency", fiscal_year: 2026, doc_url: "https://x/ar-axs.pdf", section_of: null, terms: [] },
  { doc_id: "ar26-edu", title: "FY 2026 Appropriations Report — Department of Education", publisher: "jlbc", doc_type: "approps-per-agency", fiscal_year: 2026, doc_url: "https://x/ar-edu.pdf", section_of: null, terms: [] },
  { doc_id: "afr26", title: "FY 2026 Annual Financial Report", publisher: "agao", doc_type: "afr", fiscal_year: 2026, doc_url: "https://x/afr26.pdf", section_of: null, terms: [] },
  // The folded "legislature" code displays as JLBC; this one has no URL.
  { doc_id: "bb26", title: "FY 2026 General Appropriations Act (SB 1735)", publisher: "legislature", doc_type: "budget-bill", fiscal_year: 2026, doc_url: null, section_of: null, terms: [] },
  // An unregistered doc_type (IMPORTANT 5, 2026-08-10): reportFamilies.ts's
  // FAMILY_OF_DOC_TYPE has no entry for it, so it must still render — under
  // its own raw slug as its own family, per familyOf's documented contract
  // (orderFamilies' WHY comment in Search.tsx) — rather than being silently
  // dropped. No prior fixture in this file exercised that path. Shifts the
  // report count from 5 to 6; see "the status line counts reports" below.
  { doc_id: "misc26", title: "FY 2026 Special Program Review", publisher: "jlbc", doc_type: "program-review", fiscal_year: 2026, doc_url: "https://x/pr26.pdf", section_of: null, terms: [] },
  // The SECOND program-review document, and the only reason it exists: it
  // makes "program-review" FY 2026 a MULTI-DOCUMENT family with no entry in
  // FIXTURE_FORMATS below, which is the fixture the CRITICAL 2026-08-10
  // docs[0]-fallback guard needs (see "full-report actions appear only where a
  // hand-verified URL exists" below). That guard used to lean on FY 2026
  // Appropriations Report being uncurated; it is curated as of 2026-08-16, and
  // every JLBC book year now is. A raw-slug family can never acquire an entry
  // — familyOf returns the slug only for doc_types FAMILY_OF_DOC_TYPE does not
  // name — so this fixture cannot be invalidated the same way twice.
  // Adds no report to the count: same family AND same year as misc26.
  { doc_id: "misc26b", title: "FY 2026 Special Program Review — Volume 2", publisher: "jlbc", doc_type: "program-review", fiscal_year: 2026, doc_url: "https://x/pr26b.pdf", section_of: null, terms: [] },
];

// The whole-report link table now arrives from the SERVER on the same corpus
// response (spec R1, 2026-08-16) instead of being a constant compiled into the
// bundle, so this file has to state which editions it expects a "Full report"
// control for. These are exactly the two the assertions below depend on.
//
// The third family the tests exercise, "program-review", is deliberately
// ABSENT — it is the fixture for the CRITICAL docs[0]-fallback guard and must
// stay unanswered.
const FIXTURE_FORMATS: api.ReportFormatTable = {
  "Baseline:2027": {
    single_file: "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
    linked_toc: "https://www.azjlbc.gov/budget/27baselinelinks.pdf",
  },
  "Appropriations Report:2026": {
    single_file: "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf",
    linked_toc: "https://www.azjlbc.gov/26ar/apprpttoc.pdf",
  },
};

function mount(docs = DOCS, entry = "/search", formats: api.ReportFormatTable = FIXTURE_FORMATS) {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({
    documents: docs,
    report_formats: formats,
  });
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

test("idle family cards are bare report rows with a collapsible sections tray", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The FY 2027 Baseline report row is the top level; its 3 documents sit
  // behind the dashed tray, not listed.
  expect(screen.getByText("FY 2027 Baseline")).toBeInTheDocument();
  expect(screen.queryByText(AHCCCS27)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /browse sections/i }));
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
  // there is NO "N sections in this report" box for it.
  const afr = screen.getByText("FY 2026 Annual Financial Report");
  expect(afr.closest(".grp")!.querySelector(".ctx")).toBeNull();
});

test("full-report actions appear only where a hand-verified URL exists", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // FY 2027 Baseline has BOTH formats — a chooser button, not a link.
  expect(screen.getByText("FY 2027 Baseline").closest(".doc")!).toHaveTextContent(/full report/i);
  fireEvent.click(screen.getByRole("button", { name: /Fiscal Year 2026:/i }));
  // FY 2026's Budget Bill has neither format AND no doc_url: no pill at all.
  const bill = screen.getByText("FY 2026 Budget Bill").closest(".doc")!;
  expect(bill).not.toHaveTextContent(/full report/i);
  expect(bill).toHaveClass("doc-unlinked");
  // CRITICAL, 2026-08-10: a family with no entry in the server's
  // report-formats table AND more than one document must NOT fall back to
  // docs[0]?.doc_url, or the pill silently links to whichever section happens
  // to sort first (demonstrated pre-fix on FY 2026 Appropriations Report: the
  // AHCCCS section PDF, labeled "Full report"). The fixture is now
  // "program-review" — a raw-slug family, which by construction can never
  // gain a table entry — because every JLBC book year DID gain one on
  // 2026-08-16.
  const multi = screen.getByText("FY 2026 program-review").closest(".doc")!;
  expect(multi).not.toHaveTextContent(/full report/i);
  expect(multi).toHaveClass("doc-unlinked");
  // …and the year that used to play that role now offers the chooser, because
  // both of its formats were downloaded and read (reportFamilies.ts).
  const ar = screen.getByText("FY 2026 Appropriations Report").closest(".doc")!;
  expect(ar).toHaveTextContent(/full report/i);
  expect(ar.tagName).toBe("BUTTON");
});

test("an edition absent from the server's table renders no Full report control", async () => {
  // The whole point of Task 3: the page has no built-in URLs left. If this
  // passes with an EMPTY table while the test above passes with a populated
  // one, the data is genuinely coming off the wire — the same page, the same
  // fixture documents, and the only difference is what the server sent.
  mount(DOCS, "/search", {});
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row).not.toHaveTextContent(/full report/i);
  // A multi-document family with nothing to open renders UNLINKED, never as a
  // dead href — the same three-way rule, arrived at from the server's silence
  // instead of from a missing constant.
  expect(row).toHaveClass("doc-unlinked");
});

test("a response missing report_formats entirely renders the listing, not a crash", async () => {
  // Minor 2, review 2026-08-16: api.ts types `report_formats` REQUIRED, but
  // the wire is not the type checker — an older `app/` serving a newer
  // bundle, or any proxy in between, can genuinely omit the key. Without a
  // defensive default, `table[key]` inside `reportFormats()` throws on
  // `undefined`, white-screening the whole Budget Documents page over what
  // should just be a missing button. Cast is required because the TYPE
  // forbids this shape — the real wire carries no such promise.
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({
    documents: DOCS,
  } as unknown as Awaited<ReturnType<typeof api.corpusDocuments>>);
  render(
    <MemoryRouter initialEntries={["/search"]}>
      <Search />
    </MemoryRouter>,
  );
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row).not.toHaveTextContent(/full report/i);
  expect(row).toHaveClass("doc-unlinked");
});

test("the report row's own action is Full report, not a generic Open", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row).toHaveTextContent(/full report/i);
  expect(row).not.toHaveTextContent(/^Open$/);
  // …and the dashed block below no longer repeats it.
  const card = row.closest(".grp")!;
  expect(card.querySelector(".ctx")!.textContent).not.toMatch(/full report/i);
});

test("a report with BOTH formats opens the chooser instead of navigating", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // FY 2027 Baseline has both a single-file and a linked-TOC URL, so its row
  // must be a button — an interactive pill nested in an <a> is invalid markup.
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row.tagName).toBe("BUTTON");
  fireEvent.click(row);
  expect(screen.getByRole("dialog", { name: /open the full report/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /linked table of contents/i })).toBeInTheDocument();
});

test("a report with ONE format links straight to it — no pointless chooser", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /Fiscal Year 2026:/i }));
  const row = screen.getByText("FY 2026 Annual Financial Report").closest(".doc")!;
  expect(row.tagName).toBe("A");
  fireEvent.click(row);
  expect(screen.queryByRole("dialog")).toBeNull();
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
  fireEvent.click(within(y27card).getByRole("button", { name: /browse sections/i }));
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

// --- search: full-report control (parity with the browse view) -------------
//
// Task 9: the browse branch's ReportRow has always offered "Full report",
// but the search branch (this file's other FamilyCard rendering path) had
// no equivalent control at all — a typed query left a reader with no way to
// open the whole report. These pin the same three-way rule ReportRow already
// follows (both formats -> chooser; one -> plain link; neither -> unlinked,
// never a dead href), now reachable from a search too.

test("a search match with BOTH formats offers Full report as a chooser button", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // "department" uniquely picks out the two FY 2027 Baseline agency docs
  // (Education, Child Safety) — a family with BOTH curated formats — so this
  // also proves the control sits correctly alongside "N more matches".
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "department" },
  });
  const ctxRow = screen.getByText(/Part of the FY 2027 Baseline/).closest(".ctx-row")! as HTMLElement;
  const fullReportBtn = within(ctxRow).getByRole("button", { name: /full report/i });
  // A dialog-opening control must be a <button>, not an <a> — an interactive
  // element nested in a link is invalid markup (same reasoning as ReportRow).
  expect(fullReportBtn.tagName).toBe("BUTTON");
  fireEvent.click(fullReportBtn);
  expect(screen.getByRole("dialog", { name: /open the full report/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /linked table of contents/i })).toBeInTheDocument();
});

test("Full report sits before the N more matches toggle in the row", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "department" },
  });
  const ctxRow = screen.getByText(/Part of the FY 2027 Baseline/).closest(".ctx-row")! as HTMLElement;
  const buttons = within(ctxRow).getAllByRole("button");
  expect(buttons[0]).toHaveTextContent(/full report/i);
  expect(buttons[1]).toHaveTextContent(/more match/i);
});

test("a search match with ONE format links straight to it — no chooser", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The AFR has no entry in FIXTURE_FORMATS, so ReportRow's own fallback
  // (docs[0]?.doc_url) is what supplies its one link — same rule here.
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "annual" },
  });
  const ctxRow = screen.getByText(/Part of the FY 2026 Annual Financial Report/).closest(".ctx-row")! as HTMLElement;
  const link = within(ctxRow).getByRole("link", { name: /full report/i });
  expect(link).toHaveAttribute("href", "https://x/afr26.pdf");
  fireEvent.click(link);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a search match with NEITHER format renders no Full report control at all", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The Budget Bill has no curated format AND no doc_url on its one document
  // — neither format is available, so the row must render unlinked, not as
  // a dead href.
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "General Appropriations Act" },
  });
  const ctxRow = screen.getByText(/Part of the FY 2026 Budget Bill/).closest(".ctx-row")! as HTMLElement;
  expect(within(ctxRow).queryByText(/full report/i)).toBeNull();
  expect(ctxRow.querySelector("a")).toBeNull();
  expect(ctxRow.querySelector("button")).toBeNull();
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

test("zero title hits shows the contents spinner immediately, never a no-results flash", async () => {
  // Destin, 2026-08-11: the page used to sit on "No document titles match “X”"
  // for the full 2s escalation pause and THEN swap to the spinner, which read
  // as a hiccup — as if the search had failed and then changed its mind. The
  // pause is a debounce, not a result, so the moment escalation is armed the
  // page presents as content search and keeps doing so through the request.
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "zzz-no-such-thing" },
  });
  // The loading block's sub-line, not "searching document contents" — that
  // phrase is deliberately in BOTH the header and the block, so matching it
  // finds two elements.
  expect(screen.getByText(/reading inside every ingested pdf/i)).toBeInTheDocument();
  expect(screen.queryByText(/no document titles match/i)).toBeNull();
  // The header agrees with the body — one statement of what is happening.
  expect(screen.getByText(/\(searching document contents\)/i)).toBeInTheDocument();
  // And no count is claimed for an answer that does not exist yet.
  expect(screen.queryByText(/passages? ·/i)).toBeNull();
});

test("a query matching nothing shows an honest empty state once the reader opts back out", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "zzz-no-such-thing" },
  });
  // The title empty state is now reached by declining the escalation, which
  // the toggle offers throughout the pause — a reader must never have to sit
  // through a retrieval request to get back to titles.
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  // Names what was searched (titles), and does NOT tell the reader to clear a
  // filter they never set.
  expect(screen.getByText(/no document titles match “zzz-no-such-thing”\./i)).toBeInTheDocument();
  expect(screen.queryByText(/clearing one/i)).toBeNull();
});

test("the empty state blames filters only when filters are set", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // Narrow to one type, then search for something no title in it contains.
  fireEvent.click(screen.getByRole("button", { name: /document type/i }));
  fireEvent.click(screen.getByRole("button", { name: /^Budget Bill/i }));
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "zzz-no-such-thing" },
  });
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  expect(screen.getByText(/with those filters — try clearing one/i)).toBeInTheDocument();
});

test("an empty corpus says so instead of blaming filters", async () => {
  // The listing route degrades a missing sidecar AND an unreadable chunk table
  // to the same empty list, so the page must not name a cause — and must not
  // tell the reader to clear a filter when none is set.
  mount([]);
  expect(await screen.findByText(/no budget documents are available\./i)).toBeInTheDocument();
  expect(screen.queryByText(/clearing one/i)).toBeNull();
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

test("the status line counts reports, not the sections inside them", async () => {
  // A Baseline book is ONE report ingested as many per-agency documents
  // (Destin, 2026-08-10). The fixture's 9 documents (8 curated + the
  // unregistered-doc_type addition, IMPORTANT 5) collapse to 6 reports, and 6
  // is the only number the page may show — counting the agency pages was
  // counting something nobody asked for.
  //
  // This count moved from 5 to 6 when the "program-review" document was added
  // to the shared DOCS fixture for the IMPORTANT 5 regression test below —
  // its doc_type has no curated family, so it becomes its own report.
  mount();
  await screen.findByText(/^6 reports, across all fiscal years\.$/i);
  expect(screen.queryByText(/9 documents/i)).toBeNull();
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahcccs" },
  });
  // Unaffected by the fixture addition: "program-review" doesn't match "ahcccs".
  await screen.findByText(/^2 reports in all fiscal years, matching “ahcccs”\.$/i);
});

test("an unregistered doc_type still renders, under its raw slug, after the curated families, and is counted", async () => {
  // Regression coverage for orderFamilies' own WHY comment (Search.tsx): an
  // unknown doc_type used to be SILENTLY DROPPED from the page while the
  // status line still counted its document, so the page could claim more
  // documents than it rendered. No prior fixture in this file held an
  // unregistered doc_type, so nothing exercised the fix (IMPORTANT 5,
  // 2026-08-10). The "program-review" doc lives in the shared DOCS fixture —
  // see its own comment there for what that shifted.
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /Fiscal Year 2026:/i }));
  // Renders under its raw slug, as its own family, after the curated five.
  expect(screen.getByText("FY 2026 program-review")).toBeInTheDocument();
  // Ordering, not just presence (re-review finding, 2026-08-10): the name of
  // this test claims "after the curated families" but until now nothing read
  // DOM order, so a regression that sorted unknown families FIRST would still
  // pass. Every FY 2026 family here renders exactly one ".doc-title" (each
  // family has either 1 doc, or 2+ with the tray collapsed by default), so
  // reading them in DOM order is reading family order. Expected sequence
  // hand-verified against FAMILY_ORDER and orderFamilies in Search.tsx: this
  // fixture's FY 2026 families are Appropriations Report, Annual Financial
  // Report, Budget Bill (the FY 2026-present subset of FAMILY_ORDER, in
  // FAMILY_ORDER's order), then program-review (orderFamilies' alphabetical,
  // unrecognized-last tail).
  const y26card = document.querySelector('[data-year-card="2026"]') as HTMLElement;
  const familyTitles = within(y26card)
    .getAllByText(/^FY 2026 /)
    .map((el) => el.textContent);
  expect(familyTitles).toEqual([
    "FY 2026 Appropriations Report",
    "FY 2026 Annual Financial Report",
    "FY 2026 Budget Bill",
    "FY 2026 program-review",
  ]);
  // Appears in the Document Type filter menu.
  fireEvent.click(railTrigger(/document type/i));
  expect(screen.getByRole("button", { name: /^program-review/i })).toBeInTheDocument();
});

test("the year card head counts reports only", async () => {
  mount();
  const head = await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The accessible name is what a screen reader announces; it must agree with
  // the visible meta line, and neither may quote a per-agency document total.
  expect(head).toHaveAccessibleName(/Fiscal Year 2027: \d+ reports?$/i);
  expect(head.textContent).not.toMatch(/document/i);
});

// --- Task 4: all-words matching + terms (analyst shorthand) -----------------

// Two real-shaped rows for the shorthand tests. Terms are supplied
// explicitly: the client never computes them, it only matches what the
// route handed it (app/search_terms.py).
const SHORTHAND_DOCS: api.CorpusDocument[] = [
  {
    doc_id: "jlbc-approps-fy2026-ema",
    title: "Emergency and Military Affairs, Department of — FY 2026 Appropriations Report",
    publisher: "jlbc",
    doc_type: "approps-per-agency",
    fiscal_year: 2026,
    doc_url: "https://x/ar-ema.pdf",
    section_of: null,
    terms: ["26ar", "ar", "dema", "ema"],
  },
  {
    doc_id: "jlbc-approps-fy2026-adc",
    title: "Corrections, State Department of — FY 2026 Appropriations Report",
    publisher: "jlbc",
    doc_type: "approps-per-agency",
    fiscal_year: 2026,
    doc_url: "https://x/ar-adc.pdf",
    section_of: null,
    terms: ["26ar", "adc", "ar", "doc"],
  },
];

test("shorthand finds a document whose title contains none of it", async () => {
  // "dema" matched 0 of 5,330 titles before this — it is the agency's spoken
  // acronym, not any word in "Emergency and Military Affairs, Department of".
  mount(SHORTHAND_DOCS);
  await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "26ar dema" },
  });
  expect(screen.getByText(/Emergency and Military Affairs/i)).toBeInTheDocument();
  // 2026-08-11 review finding 2: the fixture's title is "Corrections, STATE
  // Department of" — the old regex ("Corrections, Department of", missing
  // "State") could never match that row whether or not it rendered, so this
  // half of the test passed even with the matcher completely broken.
  expect(screen.queryByText(/Corrections, State Department of/i)).toBeNull();
});

test("every word must match — one unmatchable word returns nothing", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahcccs zzz-no-such-thing" },
  });
  expect(screen.queryByText(/AHCCCS/i)).toBeNull();
});

test("terms match whole tokens only, never as substrings", async () => {
  // "ar" must not match a document merely because its terms contain "26ar" —
  // exact equality is what stops short slugs matching half the corpus.
  // NOTE the title deliberately contains no "ar": title matching stays
  // substring, so a title with "Arizona" in it would match "ar" honestly and
  // prove nothing about terms.
  mount([
    {
      doc_id: "jlbc-s-fy2027-01",
      title: "Something Else Entirely",
      publisher: "jlbc",
      doc_type: "s-pdf",
      fiscal_year: 2027,
      doc_url: null,
      section_of: null,
      terms: ["26ar"],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ar" },
  });
  expect(screen.queryByText(/Something Else Entirely/i)).toBeNull();
});

test("partial title typing still works", async () => {
  // Title matching stays SUBSTRING. This change may only ever add.
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahccc" },
  });
  // AHCCCS27, not a bare /AHCCCS/i: DOCS has TWO titles containing "AHCCCS"
  // (the FY 2027 Baseline row and the FY 2026 Appropriations Report row), so
  // the loose regex throws "found multiple elements" — a selector defect, not
  // a matching regression (both rows correctly match "ahccc" by substring).
  expect(screen.getByText(AHCCCS27)).toBeInTheDocument();
});

test("a stored publisher code matches, not just its display label", async () => {
  // publisherLabel maps "governor" -> "OSPB", and only the label was searched,
  // so typing the code a reader sees in the corpus matched nothing.
  mount([
    {
      doc_id: "ospb-exec-fy2027",
      title: "Executive Budget — FY 2027",
      publisher: "governor",
      doc_type: "governors-budget",
      fiscal_year: 2027,
      doc_url: "https://x/eb27.pdf",
      section_of: null,
      terms: ["27exec", "exec"],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "governor" },
  });
  // Exact title string, not /Executive Budget/i: the page's always-on intro
  // paragraph ("...executive budgets, and budget bills.") also matches that
  // regex, so the loose form throws "found multiple elements" — a selector
  // defect, not a matching regression.
  expect(screen.getByText("Executive Budget — FY 2027")).toBeInTheDocument();
});

test("matching is case-insensitive on both sides", async () => {
  // JLBC's own URLs spell it /26AR/.
  mount(SHORTHAND_DOCS);
  await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "26AR DEMA" },
  });
  expect(screen.getByText(/Emergency and Military Affairs/i)).toBeInTheDocument();
});

test("insurance still finds its agency by title alone — the change is purely additive", async () => {
  // 2026-08-11 review finding 5c: spec decision D6 requires that typing
  // "insurance" still find "Insurance, Department of" by TITLE — the
  // concrete proof that AMBIGUOUS_PHRASES = {insurance} (which governs NAME
  // matching in retrieval) was never consulted here, and that this whole
  // feature only ADDS matching rather than removing any. `terms: []` is
  // deliberate: it proves the row is found through the pre-existing title
  // substring match, not because search_terms emitted anything for it.
  mount([
    {
      doc_id: "jlbc-baseline-fy2026-ins",
      title: "Insurance, Department of — FY 2026 Baseline",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2026,
      doc_url: "https://x/ins.pdf",
      section_of: null,
      terms: [],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "insurance" },
  });
  expect(screen.getByText(/Insurance, Department of/i)).toBeInTheDocument();
});

// --- Task 8: fold book sections into their parent book (spec B5-B8) --------

test("no raw machine slug appears as a report family", async () => {
  // 647 documents used to render as "FY 2027 s-pdf" beside "FY 2027 Baseline".
  // bd/bh/s are JLBC's printed page-number prefixes, not document types.
  mount([
    {
      doc_id: "jlbc-baseline-fy2027-s1",
      title: "Statement of General Fund Revenues — FY 2027 Baseline",
      publisher: "jlbc",
      doc_type: "s-pdf",
      fiscal_year: 2027,
      doc_url: "https://x/s1.pdf",
      section_of: "Baseline",
      terms: [],
    },
    {
      doc_id: "jlbc-baseline-fy2027-ahcccs",
      title: "FY 2027 Baseline — AHCCCS",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/axs.pdf",
      section_of: null,
      terms: [],
    },
  ]);
  expect(await screen.findByText("FY 2027 Baseline")).toBeInTheDocument();
  expect(screen.queryByText(/s-pdf/)).not.toBeInTheDocument();
});

test("a section is COUNTED under its parent book, not dropped", async () => {
  // The counts describe what renders (spec B7). Folding must move a document,
  // never delete one -- documents were once counted but never displayed.
  mount([
    {
      doc_id: "a",
      title: "A section",
      publisher: "jlbc",
      doc_type: "s-pdf",
      fiscal_year: 2027,
      doc_url: null,
      section_of: "Baseline",
      terms: [],
    },
    {
      doc_id: "b",
      title: "B agency page",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: null,
      section_of: null,
      terms: [],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  // The rail's "group" of options only exists in the DOM once the dropdown is
  // open (RailMultiSelect mounts `.fmenu` conditionally) — every other test in
  // this file that reads option rows opens the trigger first (see
  // railTrigger's own call sites above).
  fireEvent.click(railTrigger(/document type/i));
  const rail = screen.getByRole("group", { name: /document type/i });
  expect(within(rail).getByText(/Baseline/)).toBeInTheDocument();
  expect(within(rail).getByText("2")).toBeInTheDocument();
});

test("a doc_type nobody has named still renders under its own slug", async () => {
  // familyOf's contract survives (spec B8). This behaviour was itself a bug
  // fix -- such documents used to be counted and never shown.
  mount([
    {
      doc_id: "z",
      title: "Some Special Program Review",
      publisher: "jlbc",
      doc_type: "brand-new-type",
      fiscal_year: 2027,
      doc_url: null,
      section_of: null,
      terms: [],
    },
  ]);
  expect(await screen.findByText(/brand-new-type/)).toBeInTheDocument();
});

test("every section slug stays findable by the title filter box after folding", async () => {
  // The design spec's Testing section asks for this directly: folding a
  // section into its parent book (spec B5) must never make the section
  // ITSELF unfindable -- nothing may stop being findable is the branch's
  // hardest constraint. queryHit (line 182 above) runs per-document title
  // substring match against group.docs, which groupCorpus (line 122) already
  // includes section docs in (grouped by familyOf, not filtered out) -- so a
  // search-mode query should surface a section doc directly via its own
  // DocRow, with no tray click needed. One doc per slug, distinct titles so
  // each assertion can only be satisfied by its own row. The five slugs are
  // passed as literals here (a test, not production code) rather than a
  // second hand-maintained copy of ingest/section_types.py's vocabulary.
  const sectionDocs: api.CorpusDocument[] = [
    { doc_id: "dl1", title: "Detailed List of Changes — FY 2027 Baseline", publisher: "jlbc",
      doc_type: "detailed-list-pdf", fiscal_year: 2027, doc_url: "https://x/dl1.pdf",
      section_of: "Baseline", terms: [] },
    { doc_id: "s1", title: "Statement of General Fund Revenues — FY 2027 Baseline", publisher: "jlbc",
      doc_type: "s-pdf", fiscal_year: 2027, doc_url: "https://x/s1.pdf",
      section_of: "Baseline", terms: [] },
    { doc_id: "bd1", title: "Budget Detail Summary of Spending — FY 2027 Appropriations Report",
      publisher: "jlbc", doc_type: "bd-pdf", fiscal_year: 2027, doc_url: "https://x/bd1.pdf",
      section_of: "Appropriations Report", terms: [] },
    { doc_id: "bh1", title: "Budget History Comparison — FY 2027 Appropriations Report",
      publisher: "jlbc", doc_type: "bh-pdf", fiscal_year: 2027, doc_url: "https://x/bh1.pdf",
      section_of: "Appropriations Report", terms: [] },
    { doc_id: "topic1", title: "Topical Highlight on Water Policy — FY 2027 Appropriations Report",
      publisher: "jlbc", doc_type: "topic-pdf", fiscal_year: 2027, doc_url: "https://x/topic1.pdf",
      section_of: "Appropriations Report", terms: [] },
    // One agency page per family so each family has more than a lone
    // section -- otherwise the AFR-style single-document fallback would
    // make every one of these its own "featured" report by default, and the
    // search-mode DocRow path wouldn't be the thing under test.
    { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
      doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf",
      section_of: null, terms: [] },
    { doc_id: "ar27-ahcccs", title: "FY 2027 Appropriations Report — AHCCCS", publisher: "jlbc",
      doc_type: "approps-per-agency", fiscal_year: 2027, doc_url: "https://x/ar-axs.pdf",
      section_of: null, terms: [] },
  ];
  mount(sectionDocs);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const box = screen.getByLabelText(/filter documents by agency or keyword/i);

  for (const { title, needle } of [
    { title: "Detailed List of Changes — FY 2027 Baseline", needle: "Detailed List" },
    { title: "Statement of General Fund Revenues — FY 2027 Baseline", needle: "Statement of General Fund" },
    { title: "Budget Detail Summary of Spending — FY 2027 Appropriations Report", needle: "Budget Detail Summary" },
    { title: "Budget History Comparison — FY 2027 Appropriations Report", needle: "Budget History Comparison" },
    { title: "Topical Highlight on Water Policy — FY 2027 Appropriations Report", needle: "Topical Highlight" },
  ]) {
    fireEvent.change(box, { target: { value: needle } });
    expect(await screen.findByText(title)).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "" } });
  }
});

// --- Task 9: two groups in a book's tray -----------------------------------
// The brief's snippet used helper functions (`corpusDoc`, `renderSearchWith`)
// and `userEvent` that don't exist in this file -- adapted to the file's own
// conventions (literal doc objects + the existing `mount()`/`fireEvent`
// helpers), matching the brief's own instruction to reuse whatever the file
// already uses rather than introduce a second pattern. Assertions and doc
// shapes are otherwise verbatim from the brief.

test("a book's tray separates summary sections from agency pages", async () => {
  mount([
    {
      doc_id: "s1",
      title: "General Fund Revenue",
      publisher: "jlbc",
      doc_type: "s-pdf",
      fiscal_year: 2027,
      doc_url: "https://x/s1.pdf",
      section_of: "Baseline",
      terms: [],
    },
    {
      doc_id: "ahcccs",
      title: "FY 2027 Baseline — AHCCCS",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/axs.pdf",
      section_of: null,
      terms: [],
    },
  ]);
  fireEvent.click(await screen.findByRole("button", { name: /browse sections/i }));

  const summary = screen.getByRole("group", { name: /summary sections/i });
  expect(within(summary).getByText("General Fund Revenue")).toBeInTheDocument();

  const agencies = screen.getByRole("group", { name: /agency pages/i });
  expect(within(agencies).getByText(/AHCCCS/)).toBeInTheDocument();
});

test("a book with no summary sections shows no empty group", async () => {
  // An empty state must name only conditions that are true.
  mount([
    {
      doc_id: "ahcccs",
      title: "FY 2027 Baseline — AHCCCS",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/axs.pdf",
      section_of: null,
      terms: [],
    },
    {
      doc_id: "edu",
      title: "FY 2027 Baseline — Department of Education",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/edu.pdf",
      section_of: null,
      terms: [],
    },
  ]);
  fireEvent.click(await screen.findByRole("button", { name: /browse sections/i }));
  expect(screen.queryByRole("group", { name: /summary sections/i })).not.toBeInTheDocument();
});

test("a book with only agency pages renders no group heading at all", async () => {
  // Fix round 1: every AFR, Executive Budget and Budget Bill has ZERO
  // summary sections -- this single-group shape is the common case, not
  // an edge case. A heading over the only group in the tray restates what
  // the reader can already see, so no heading should print here even
  // though the rows still must.
  mount([
    {
      doc_id: "ahcccs",
      title: "FY 2027 Baseline — AHCCCS",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/axs.pdf",
      section_of: null,
      terms: [],
    },
    {
      doc_id: "edu",
      title: "FY 2027 Baseline — Department of Education",
      publisher: "jlbc",
      doc_type: "baseline-per-agency",
      fiscal_year: 2027,
      doc_url: "https://x/edu.pdf",
      section_of: null,
      terms: [],
    },
  ]);
  fireEvent.click(await screen.findByRole("button", { name: /browse sections/i }));

  // The rows are still there -- the group split partitions the tray, it
  // never filters it.
  expect(screen.getByText(/AHCCCS/)).toBeInTheDocument();
  expect(screen.getByText(/Department of Education/)).toBeInTheDocument();

  // But with only one group present, no heading of either name should
  // print -- there is nothing for a label to distinguish.
  expect(screen.queryByRole("heading", { name: /agency pages/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /summary sections/i })).not.toBeInTheDocument();
});
