// The Fiscal Notes page's SEARCH half (spec F6-F10, F15) and the expansion cap (F8).
//
// Split from FiscalNotes.test.tsx, which pins browsing and the title filter, for the same
// reason Search.content.test.tsx is split from Search.test.tsx: these need fake timers and a
// stubbed /api/search, and mixing those into the browse tests makes every one of them
// slower and easier to break.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as api from "../api";
import type { SearchResult } from "../api";
import { FiscalNotes } from "./FiscalNotes";

const BOX = /bill # or a question/i;

/** The REAL committed directory: 28 sessions, 2,126 bills, 241 struck titles.
 *
 *  Deliberately not a hand-written fixture. The two things these tests exist to catch —
 *  a one-letter query mounting thousands of rows, and a struck title reaching the DOM as
 *  markup — do not exist in invented data, and were found only by querying the corpus. */
const SNAPSHOT = JSON.parse(
  readFileSync(resolve(__dirname, "../../../app/data/fiscal-notes-snapshot.json"), "utf-8"),
);

function mount() {
  return render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
}

function hit(over: Partial<SearchResult> = {}): SearchResult {
  return {
    chunk_id: "c1",
    doc_id: "fn-2026-hb2407",
    doc_title: "Fiscal Note - HB 2407: victim notification",
    snippet: "The bill would appropriate $28,700,000 from the General Fund.",
    text: "The bill would appropriate $28,700,000 from the General Fund.",
    page: 2,
    score: 4.2,
    doc_type: "fiscal-note",
    fiscal_year: 2026,
    publisher: "azleg",
    agencies: [],
    doc_url: null,
    doc_meta: "Estimated Impact",
    section_of: null,
    ...over,
  } as SearchResult;
}

function searchReturns(results: SearchResult[], extra: Partial<api.SearchResponse> = {}) {
  return vi.spyOn(api, "search").mockResolvedValue({
    results,
    total: results.length,
    provider: "lance",
    inferred_fiscal_years: [],
    inferred_doc_types: [],
    dropped_filters: [],
    ...extra,
  } as api.SearchResponse);
}

beforeEach(() => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(SNAPSHOT);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// F8 — the expansion cap. THE regression this design can actually cause.
// ---------------------------------------------------------------------------

test("a broad title query does NOT expand every card", async () => {
  // Measured against this exact snapshot: `a` matches 2,029 of 2,126 rows across all 28
  // sessions. Expanding every matching card would put all of them in the DOM on ONE
  // keystroke — and short prefixes are not an edge case, they are the state every longer
  // query passes through, on every keystroke.
  const { container } = mount();
  await waitFor(() => expect(container.querySelectorAll(".yg").length).toBeGreaterThan(1));

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "a" } });

  expect(container.querySelectorAll(".yg .fnlist")).toHaveLength(3);   // bodies MOUNTED
  expect(container.querySelectorAll(".yg").length).toBeGreaterThan(20); // headers all render
});

test("a collapsed matching card still states its true match count", async () => {
  const { container } = mount();
  await waitFor(() => expect(container.querySelectorAll(".yg").length).toBeGreaterThan(1));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "a" } });

  const closed = [...container.querySelectorAll(".yg-closed")];
  expect(closed.length).toBeGreaterThan(0);
  for (const card of closed.slice(0, 3)) {
    // A count, not a hidden card: the number is a true statement about what one click away
    // holds, which is what makes collapsing honest rather than concealing.
    expect(card.querySelector(".yg-meta")?.textContent).toMatch(/^\d+ /);
  }
});

test("browsing opens the newest ONE, searching opens the newest THREE", async () => {
  const { container } = mount();
  await waitFor(() => expect(container.querySelectorAll(".yg").length).toBeGreaterThan(1));
  expect(container.querySelectorAll(".yg .fnlist")).toHaveLength(1);

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "tax" } });
  expect(container.querySelectorAll(".yg .fnlist")).toHaveLength(3);
});

test("the FIRST click on an auto-opened card closes it", async () => {
  // The defect this pins: if the toggle recomputed the mode's default instead of flipping
  // what is on screen, clicking an auto-opened card would "open" an already-open card and
  // appear to do nothing. Found in the mockups on 2026-08-13.
  const { container } = mount();
  await waitFor(() => expect(container.querySelectorAll(".yg").length).toBeGreaterThan(1));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "tax" } });

  const heads = [...container.querySelectorAll(".yg-head")];
  const second = heads[1];                       // auto-open by the newest-THREE default
  expect(second.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(second);
  expect(container.querySelectorAll(".yg-head")[1].getAttribute("aria-expanded")).toBe("false");
});

// ---------------------------------------------------------------------------
// F6 — one box, two modes, automatic escalation
// ---------------------------------------------------------------------------

test("escalation fires only at zero title hits, and only after the box goes quiet", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const spy = searchReturns([hit()]);
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());

  // A question no bill title contains as a single substring.
  fireEvent.change(screen.getByPlaceholderText(BOX), {
    target: { value: "how much does inmate health care cost" },
  });
  expect(spy).not.toHaveBeenCalled();            // still in the quiet period

  await vi.advanceTimersByTimeAsync(2100);
  await waitFor(() => expect(spy).toHaveBeenCalledWith(
    "how much does inmate health care cost", {}, "fiscal_notes",
  ));
});

test("typing again restarts the pause instead of firing on the stale timer", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const spy = searchReturns([hit()]);
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  const box = screen.getByPlaceholderText(BOX);

  fireEvent.change(box, { target: { value: "zzzz" } });
  await vi.advanceTimersByTimeAsync(1500);
  fireEvent.change(box, { target: { value: "zzzzz" } });
  await vi.advanceTimersByTimeAsync(1000);       // 2.5s since the FIRST keystroke
  expect(spy).not.toHaveBeenCalled();            // ...but only 1s since the last

  await vi.advanceTimersByTimeAsync(1200);
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
});

test("crossing back to titles does not yank the reader forward again", async () => {
  // The live defect on Budget Documents (2026-08-10). A reader who clicks back to titles is
  // BY CONSTRUCTION the population that stays at zero title hits, so a boolean flag would
  // re-escalate them on the very next render. Keyed on the QUERY, it self-invalidates the
  // moment the query changes by any route.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()]);
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);

  await waitFor(() => screen.getByRole("button", { name: /back to title matches/i }));
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));

  await vi.advanceTimersByTimeAsync(5000);
  expect(screen.queryByRole("button", { name: /back to title matches/i })).not.toBeInTheDocument();
});

test("the page commits to 'searching' the moment escalation ARMS", async () => {
  // Without this the page sits on "No note titles match" for the full 2s pause and THEN
  // swaps to a spinner, which reads as a failure that changed its mind (Destin,
  // 2026-08-11). The armed pause and the in-flight request render identically, so the
  // handoff between them is invisible.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()]);
  const { container } = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  // BEFORE the timer fires:
  expect(container.querySelector(".fnstatus")?.textContent).toMatch(/searching note contents/i);
  expect(container.querySelector(".docload")).not.toBeNull();
});

test("the mode toggle is present even when title mode HAS hits", async () => {
  // A single topical word like `water` matches 11 titles and so never auto-escalates, by
  // design. That makes the manual toggle the ONLY route to the note text exactly there —
  // the case a "pin the empty state" test would miss.
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "water" } });

  expect(screen.getByRole("button", { name: /search note contents/i })).toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// F9 — chamber and sort BOTH stand down, sharing one sentence
// ---------------------------------------------------------------------------

test("chamber and sort go inactive together, and say why exactly once", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()]);
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);

  await waitFor(() => expect(screen.getByRole("button", { name: /^house$/i })).toBeDisabled());
  expect(screen.getByRole("button", { name: /^senate$/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /^all$/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /bill number \(low to high\)/i })).toBeDisabled();
  // ONE sentence covering both: two would imply two different reasons.
  expect(screen.getAllByText(/ranked results are ordered by relevance/i)).toHaveLength(1);
});

// ---------------------------------------------------------------------------
// F10 — the results header names which case the reader got
// ---------------------------------------------------------------------------

async function runContentSearch(results: SearchResult[], extra = {}) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns(results, extra);
  const view = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);
  await waitFor(() => expect(view.container.querySelectorAll("[data-testid=fn-result]").length)
    .toBeGreaterThan(0));
  return view;
}

test("under the ceiling the header says 'all N'", async () => {
  const notes = Array.from({ length: 9 }, (_, i) => hit({ doc_id: `n${i}`, chunk_id: `c${i}`, score: 9 - i }));
  const { container } = await runContentSearch(notes);
  expect(container.querySelectorAll("[data-testid=fn-result]")).toHaveLength(9);
  expect(container.querySelector(".fnstatus")?.textContent).toContain("Showing all 9 matches");
});

test("over the ceiling the header says 'top 15', and only 15 cards render", async () => {
  const notes = Array.from({ length: 17 }, (_, i) => hit({ doc_id: `n${i}`, chunk_id: `c${i}`, score: 20 - i }));
  const { container } = await runContentSearch(notes);
  expect(container.querySelectorAll("[data-testid=fn-result]")).toHaveLength(15);
  expect(container.querySelector(".fnstatus")?.textContent).toContain("Showing top 15 matches");
});

test("no count on the page names passages", async () => {
  const notes = Array.from({ length: 4 }, (_, i) => hit({ doc_id: `n${i}`, chunk_id: `c${i}` }));
  const { container } = await runContentSearch(notes);
  // One card is one note is one match; counting passages would state a quantity nothing on
  // screen corresponds to.
  expect(container.querySelector(".fnstatus")?.textContent).not.toMatch(/passages? \d|\d+ passages/i);
});

// ---------------------------------------------------------------------------
// F15 — the page states what the search inferred, with an undo
// ---------------------------------------------------------------------------

test("a year-naming question states the session narrowing and can undo it", async () => {
  // The honesty gap: "FY 2027 ..." is hard-filtered by session while the rail still reads
  // "Any session". Worse than the doc-type guess, which the pipeline DROPS and reports when
  // it empties the page — the year guess is never dropped, so a narrow guess quietly
  // returns less, forever.
  const spy = searchReturns([hit()], { inferred_fiscal_years: [2026, 2027, 2028] });
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), {
    target: { value: "FY 2027 revenue impact of a sales tax exemption" },
  });
  await vi.advanceTimersByTimeAsync(2100);

  await waitFor(() => expect(screen.getByText(/also limited to the 2026–2028 sessions/i))
    .toBeInTheDocument());

  spy.mockClear();
  fireEvent.click(screen.getByRole("button", { name: /search every session/i }));

  // The undo sends an EXPLICIT wide session filter, which is what suppresses the inference
  // (the pipeline only infers when the caller passed no fiscal_year of its own). It does
  // NOT strip the year from the analyst's question, which would change what they asked.
  await waitFor(() => expect(spy).toHaveBeenCalled());
  const [query, filters] = spy.mock.calls[0];
  expect(query).toContain("FY 2027");
  expect((filters as api.SearchFilters).fiscal_year).toHaveLength(SNAPSHOT.sessions.length);
});

test("no inference means no sentence", async () => {
  const { container } = await runContentSearch([hit()]);
  expect(container.textContent).not.toMatch(/because your question named a year/i);
});

// ---------------------------------------------------------------------------
// F14 — the drawer, against the right corpus
// ---------------------------------------------------------------------------

test("clicking a result opens the drawer against the FISCAL-NOTE corpus", async () => {
  // `SourcePanel`'s `corpus` prop DEFAULTS TO "budget". Miss it and every drawer on this
  // page 404s against the wrong table — an honest error message, but a uniformly broken
  // feature, and completely invisible in jsdom. So assert the argument itself.
  const chunkSpy = vi.spyOn(api, "chunk").mockResolvedValue({
    chunk_id: "c1", doc_id: "fn-2026-hb2407", page: 2, bbox: null, text: "cited text",
  } as never);
  const { container } = await runContentSearch([hit()]);

  fireEvent.click(container.querySelector("[data-testid=fn-result]")!);
  await waitFor(() => expect(chunkSpy).toHaveBeenCalled());
  expect(chunkSpy.mock.calls[0][1]).toBe("fiscal_notes");
});

test("the card's label toggles to 'Close note' while its drawer is open", async () => {
  vi.spyOn(api, "chunk").mockResolvedValue({
    chunk_id: "c1", doc_id: "fn-2026-hb2407", page: 2, bbox: null, text: "cited text",
  } as never);
  const { container } = await runContentSearch([hit()]);
  const card = container.querySelector("[data-testid=fn-result]")!;
  expect(within(card as HTMLElement).getByText("Open note")).toBeInTheDocument();

  fireEvent.click(card);
  await waitFor(() =>
    expect(within(container.querySelector("[data-testid=fn-result]") as HTMLElement)
      .getByText("Close note")).toBeInTheDocument(),
  );
});

// ---------------------------------------------------------------------------
// Neither empty state is a dead end (F8)
// ---------------------------------------------------------------------------

test("an empty content result still offers the way back to titles", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([]);
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);

  await waitFor(() => expect(screen.getByText(/no passages inside the ingested notes/i))
    .toBeInTheDocument());
  expect(screen.getByRole("button", { name: /back to title matches/i })).toBeInTheDocument();
});

test("a failed content search surfaces the backend's own reason", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.spyOn(api, "search").mockRejectedValue(new Error("search: Search backend failed: OSError: share offline"));
  const { container } = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);

  // The real detail, never a guessed cause.
  await waitFor(() => expect(container.textContent).toContain("share offline"));
});

// ---------------------------------------------------------------------------
// Editing the box returns to titles (Destin, 2026-08-13)
// ---------------------------------------------------------------------------

test("backspacing into a query that matches titles drops back to title filtering", async () => {
  // The bug this pins, reported from the running page: once escalated, the page STAYED in
  // content mode no matter what was typed next. Shortening a question until it matched a
  // bill title left the reader stranded in a ranked view that no longer answered anything —
  // and because the fixture provider returns the same rows for every query, it read as a
  // page frozen on four results.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()]);
  const { container } = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  const box = screen.getByPlaceholderText(BOX);

  fireEvent.change(box, { target: { value: "waterzzz" } });     // no title hits
  await vi.advanceTimersByTimeAsync(2100);
  await waitFor(() => expect(container.querySelector(".fnresults")).not.toBeNull());

  // Backspace into a query that DOES match titles: `water` hits 11 rows in the snapshot.
  fireEvent.change(box, { target: { value: "water" } });
  expect(container.querySelector(".fnresults")).toBeNull();
  expect(container.querySelectorAll(".yg-head").length).toBeGreaterThan(0);
});

test("emptying the box returns to browsing", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()]);
  const { container } = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  const box = screen.getByPlaceholderText(BOX);

  fireEvent.change(box, { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);
  await waitFor(() => expect(container.querySelector(".fnresults")).not.toBeNull());

  fireEvent.change(box, { target: { value: "" } });
  expect(container.querySelector(".fnresults")).toBeNull();
  expect(container.querySelector(".fnstatus")?.textContent).toMatch(/across all 28 sessions/i);
});

test("a manual crossing into content mode is not undone by the next keystroke", async () => {
  // The other half of the rule, and the reason "always return to titles" is safe: the
  // MANUAL toggle is a fresh decision about the query as it stands, so it must survive
  // until the reader edits the query again. `water` has 11 title hits and so would never
  // auto-escalate — the toggle is the only route to the note text there.
  searchReturns([hit()]);
  const { container } = mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "water" } });
  fireEvent.click(screen.getByRole("button", { name: /search note contents/i }));

  await waitFor(() => expect(container.querySelector(".fnresults")).not.toBeNull());
});

test("fixture rows say so, instead of looking like a broken search", async () => {
  // The fixture provider ignores the query, so every search returns the same rows — which
  // is indistinguishable from a frozen page unless the page says which it is.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  searchReturns([hit()], { provider: "stub" });
  mount();
  await waitFor(() => expect(screen.getByPlaceholderText(BOX)).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzzqqq" } });
  await vi.advanceTimersByTimeAsync(2100);

  await waitFor(() => expect(screen.getByText(/these are sample results/i)).toBeInTheDocument());
});

test("a real search carries no sample-data banner", async () => {
  const { container } = await runContentSearch([hit()]);   // provider: "lance"
  expect(container.textContent).not.toMatch(/sample results/i);
});

test("a struck title reaches the drawer as TEXT, never as markup", async () => {
  // The card renders titles through BillTitle, which is safe. The DRAWER takes a plain
  // string and renders it as text — so the raw scraped markup printed on screen, in the
  // breadcrumb AND in the "Source:" line beneath the page. F16's rule applied to a surface
  // its own acceptance test never covered. Found by opening a real note, not by a test.
  const chunkSpy = vi.spyOn(api, "chunk").mockResolvedValue({
    chunk_id: "c1", doc_id: "d1", page: 1, bbox: null, text: "cited",
  } as never);
  const struck =
    "Fiscal Note - SB 1201: <strike>appropriation; Ganado School Loop Road</strike> S/E: prisoners";
  const { container } = await runContentSearch([hit({ doc_title: struck })]);

  fireEvent.click(container.querySelector("[data-testid=fn-result]")!);
  await waitFor(() => expect(chunkSpy).toHaveBeenCalled());

  // Whatever the drawer is handed must carry no markup at all.
  const passed = (screen.getByTestId("fn-result").ownerDocument.body.textContent) ?? "";
  expect(passed).not.toContain("<strike>");
  expect(passed).not.toContain("</strike>");
});
