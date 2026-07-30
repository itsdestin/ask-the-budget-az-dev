import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

const RESULT = {
  chunk_id: "c1", doc_id: "d1",
  doc_title: "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
  snippet: "…provider rate increases…", page: 14, score: 0.91,
  doc_type: "baseline-per-agency", fiscal_year: 2027, publisher: "jlbc",
  agencies: ["ahcccs"],
  doc_url: "https://www.azjlbc.gov/27baseline/axs.pdf",
  doc_meta: "Agency Budget Detail · Baseline Book · FY 2027",
};
const TITLE = /Health Care Cost Containment System/;

test("runs the ?q= query on mount and groups results by document", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT, { ...RESULT, chunk_id: "c2", page: 15 }],
    total: 2, provider: "stub",
  });
  render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText(TITLE)).toBeInTheDocument());
  // The row shows the TITLE only — no tagline/meta, no passage text, no
  // publisher pill, no visible percentage (Destin 2026-07-30: the mockup-index
  // titles already carry agency/report/year). Passages live in the collapsed
  // tray.
  expect(
    screen.queryByText("Agency Budget Detail · Baseline Book · FY 2027"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/provider rate increases/)).not.toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  // No publisher pill in the RESULTS (the filter strip's JLBC chip is separate
  // and must stay).
  expect(document.querySelector(".results")?.textContent).not.toContain("JLBC");
  expect(screen.queryByText(/p\.\s*1[45]/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /2 passages/i }));
  expect(screen.getAllByText(/p\.\s*1[45]/)).toHaveLength(2);
  expect(api.search).toHaveBeenCalledWith("ahcccs", expect.anything(), "budget");
});

test("the headline row links to the document's own source PDF", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT], total: 1, provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  const row = await screen.findByRole("link", { name: TITLE });
  expect(row).toHaveAttribute("href", "https://www.azjlbc.gov/27baseline/axs.pdf");
  expect(row).toHaveAttribute("target", "_blank");
});

test("a row with no doc_url renders unlinked, not as a dead link", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [{ ...RESULT, doc_url: null }], total: 1, provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  await waitFor(() =>
    expect(screen.getByText(TITLE)).toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("link", { name: TITLE }),
  ).not.toBeInTheDocument();
});

test("sibling documents of the same report start collapsed and expand", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [
      RESULT,
      {
        ...RESULT, chunk_id: "c9", doc_id: "d2", score: 0.5,
        doc_title: "Child Safety, Department of — FY 2027 Baseline", page: 4,
        doc_url: "https://www.azjlbc.gov/27baseline/dcs.pdf",
      },
    ],
    total: 2, provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  await waitFor(() =>
    expect(screen.getByText(TITLE)).toBeInTheDocument(),
  );
  // The sibling is behind the collapsed "more" tray…
  expect(screen.queryByText(/Child Safety, Department of/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /1 more document/i }));
  // …and is a real link once revealed.
  const sibling = screen.getByRole("link", { name: /Child Safety, Department of/ });
  expect(sibling).toHaveAttribute("href", "https://www.azjlbc.gov/27baseline/dcs.pdf");
});

test("publisher filter chip re-queries", async () => {
  const spy = vi.spyOn(api, "search").mockResolvedValue({
    results: [], total: 0, provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  await waitFor(() => expect(spy).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: /jlbc/i }));
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "x", expect.objectContaining({ publisher: ["jlbc"] }), "budget",
    ),
  );
});

test("empty results show honest message, not blank", async () => {
  vi.spyOn(api, "search").mockResolvedValue({ results: [], total: 0, provider: "stub" });
  render(<MemoryRouter initialEntries={["/search?q=zz"]}><Search /></MemoryRouter>);
  await waitFor(() =>
    expect(screen.getByText(/no matches/i)).toBeInTheDocument(),
  );
});

// Toggling a filter must not blank the results while the new response is in
// flight. With the stub's instant fixtures the gap is invisible, so only a test
// that HOLDS the second request open can pin it — and a real provider on a slow
// network is exactly this test in slow motion.
test("keeps the previous results on screen while refetching", async () => {
  let releaseSecond: (r: { results: typeof RESULT[]; total: number; provider: string }) => void;
  const spy = vi
    .spyOn(api, "search")
    .mockResolvedValueOnce({ results: [RESULT], total: 1, provider: "stub" })
    .mockImplementationOnce(() => new Promise((resolve) => { releaseSecond = resolve; }));

  render(<MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>);
  await waitFor(() =>
    expect(screen.getByText(TITLE)).toBeInTheDocument(),
  );

  // Narrow by publisher; the second request is now hanging.
  fireEvent.click(screen.getByRole("button", { name: /jlbc/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

  // The old results are STILL rendered (not replaced by a blank panel), and the
  // panel says it is busy so the stale rows aren't presented as current.
  expect(screen.getByText(TITLE)).toBeInTheDocument();
  expect(screen.getByText("Searching…")).toBeInTheDocument();
  expect(document.querySelector(".card.stale")).toHaveAttribute("aria-busy", "true");

  releaseSecond!({ results: [RESULT], total: 1, provider: "stub" });
  await waitFor(() =>
    expect(document.querySelector(".card.stale")).not.toBeInTheDocument(),
  );
});

// A failed search must be recoverable. The search runs off ?q=, so re-submitting
// the same text writes an identical ?q= and used to change nothing at all — the
// error was a dead end for the one action that would fix a transient failure.
test("a failed search surfaces the backend detail and can be retried", async () => {
  const spy = vi
    .spyOn(api, "search")
    .mockRejectedValueOnce(new Error("search: index is rebuilding"))
    .mockResolvedValue({ results: [RESULT], total: 1, provider: "stub" });

  render(<MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>);

  // The api client's message reaches the screen verbatim — not replaced by a guess.
  await waitFor(() =>
    expect(screen.getByText(/index is rebuilding/)).toBeInTheDocument(),
  );
  expect(spy).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: /retry/i }));

  await waitFor(() =>
    expect(screen.getByText(TITLE)).toBeInTheDocument(),
  );
  // Same query, second request actually issued.
  expect(spy).toHaveBeenCalledTimes(2);
  expect(spy).toHaveBeenLastCalledWith("ahcccs", {}, "budget");
  // The error is gone, not stacked under the results.
  expect(screen.queryByText(/index is rebuilding/)).not.toBeInTheDocument();
});

// Same dead end, reached through the search box instead of the Retry button:
// pressing Search again on unchanged text must re-run the query.
test("resubmitting the identical query re-runs the search", async () => {
  const spy = vi
    .spyOn(api, "search")
    .mockResolvedValue({ results: [RESULT], total: 1, provider: "stub" });

  render(<MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>);
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

  // Text untouched, so ?q= will be written with the value it already has.
  fireEvent.submit(screen.getByLabelText(/search arizona budget documents/i));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
});

// Regression guard: a filter you set must stay clearable even when it matches
// nothing. Year options are derived from the results, and the derived list is
// RESET when the query changes — but the filter itself persists. So searching
// again under a filter that now excludes every row used to erase that filter's
// own option, leaving it applied and still sent to the API with no way to undo
// it.
//
// NOTE for whoever edits this: the failure needs the QUERY to change. Choosing a
// filter on the same query can't reproduce it, because the facet list accumulates
// within a query (see mergeFacets in Search.tsx).
test("a year filter kept across a new query stays selectable and clearable", async () => {
  const spy = vi
    .spyOn(api, "search")
    // Only the FIRST search finds anything, and it is what offers FY 2027.
    .mockResolvedValueOnce({ results: [RESULT], total: 1, provider: "stub" })
    .mockResolvedValue({ results: [], total: 0, provider: "stub" });

  render(<MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>);

  const dropdown = await screen.findByLabelText(/filter by fiscal year/i);
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "FY 2027" })).toBeInTheDocument(),
  );
  fireEvent.change(dropdown, { target: { value: "2027" } });
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "ahcccs",
      expect.objectContaining({ fiscal_year: [2027] }),
      "budget",
    ),
  );

  // Search for something else. FY 2027 stays selected, but the new (empty)
  // response offers no years at all — the moment the option used to disappear.
  const box = screen.getByLabelText(/search arizona budget documents/i);
  fireEvent.change(box, { target: { value: "roads" } });
  fireEvent.submit(box);
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "roads",
      expect.objectContaining({ fiscal_year: [2027] }),
      "budget",
    ),
  );

  // The selected year is still an option and still selected.
  expect(screen.getByRole("option", { name: "FY 2027" })).toBeInTheDocument();
  expect(dropdown).toHaveValue("2027");
  // The empty state blames the filter, not the corpus.
  expect(screen.getByText(/with the filters above/i)).toBeInTheDocument();

  // And it really does undo: "All years" drops the dimension entirely, not
  // sending an empty array.
  fireEvent.change(dropdown, { target: { value: "" } });
  await waitFor(() => expect(spy).toHaveBeenLastCalledWith("roads", {}, "budget"));
});

// The curated type buckets (reportFamilies.ts): one chip toggles its whole slug
// family through the doc_type filter, and toggling off drops the dimension.
test("a type bucket chip sends its whole slug family", async () => {
  const spy = vi
    .spyOn(api, "search")
    .mockResolvedValue({ results: [], total: 0, provider: "stub" });

  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  await waitFor(() => expect(spy).toHaveBeenCalled());

  // Bucket chips are a fixed curated set — visible before any results exist.
  const chip = screen.getByRole("button", { name: /baseline books/i });
  fireEvent.click(chip);
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "x",
      expect.objectContaining({
        doc_type: ["baseline-per-agency", "baseline-cross-cut"],
      }),
      "budget",
    ),
  );
  expect(chip).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(chip);
  await waitFor(() => expect(spy).toHaveBeenLastCalledWith("x", {}, "budget"));
});

// Family grouping (Destin, 2026-07-29): documents of the same report and year
// share one card titled for the report, with a link to its full single-file PDF
// when a hand-verified URL exists.
test("results group under their report family with a full-PDF link", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [
      RESULT,
      { ...RESULT, chunk_id: "c9", doc_id: "d2", doc_title: "Child Safety, Department of — FY 2027 Baseline", page: 4 },
    ],
    total: 2,
    provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);

  // One family card: the best document is the headline, the family identity
  // lives in the "Part of the …" badge, the sibling waits in a collapsed tray.
  await waitFor(() =>
    expect(screen.getByText(/Part of the FY 2027 Baseline/)).toBeInTheDocument(),
  );
  expect(screen.getByText(TITLE)).toBeInTheDocument();
  expect(screen.queryByText(/Child Safety, Department of/)).not.toBeInTheDocument();

  // "Full report" opens the mockup's format chooser (both hand-verified
  // formats exist for this report) — Linked TOC vs Single File PDF.
  fireEvent.click(screen.getByRole("button", { name: /full report/i }));
  const dialog = screen.getByRole("dialog", { name: /open the full report/i });
  expect(dialog).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /linked table of contents/i })).toHaveAttribute(
    "href",
    "https://www.azjlbc.gov/budget/27baselinelinks.pdf",
  );
  expect(screen.getByRole("link", { name: /single file pdf/i })).toHaveAttribute(
    "href",
    "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
  );
  // Escape closes it, like the mockup.
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

// No verified URL for a family -> no button at all. A guessed link behind an
// "open the report" action would violate the auditability invariants.
test("families without a known single-file PDF get no full-report link", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [
      {
        ...RESULT,
        doc_id: "d3",
        doc_title: "FY 2026 Budget Bill (SB 1735)",
        doc_type: "budget-bill",
        fiscal_year: 2026,
        publisher: "legislature",
      },
    ],
    total: 1,
    provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);

  // A standalone document with no verified report formats and no siblings gets
  // NO report card at all — no "Part of…" badge, no Full report action.
  await waitFor(() =>
    expect(screen.getByText(/FY 2026 Budget Bill \(SB 1735\)/)).toBeInTheDocument(),
  );
  expect(screen.queryByText(/part of the/i)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /full report/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /full report/i })).not.toBeInTheDocument();
});
