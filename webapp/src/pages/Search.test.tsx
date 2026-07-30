import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

const RESULT = {
  chunk_id: "c1", doc_id: "d1", doc_title: "FY 2027 Baseline — AHCCCS",
  snippet: "…provider rate increases…", page: 14, score: 0.91,
  doc_type: "baseline-per-agency", fiscal_year: 2027, publisher: "jlbc",
  agencies: ["ahcccs"],
};

test("runs the ?q= query on mount and groups results by document", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT, { ...RESULT, chunk_id: "c2", page: 15 }],
    total: 2, provider: "stub",
  });
  render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByText("FY 2027 Baseline — AHCCCS")).toBeInTheDocument(),
  );
  // Two chunks, one document -> one card with two page hits.
  expect(screen.getAllByText(/p\.\s*1[45]/)).toHaveLength(2);
  expect(api.search).toHaveBeenCalledWith("ahcccs", expect.anything(), "budget");
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
    expect(screen.getByText("FY 2027 Baseline — AHCCCS")).toBeInTheDocument(),
  );

  // Narrow by publisher; the second request is now hanging.
  fireEvent.click(screen.getByRole("button", { name: /jlbc/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

  // The old results are STILL rendered (not replaced by a blank panel), and the
  // panel says it is busy so the stale rows aren't presented as current.
  expect(screen.getByText("FY 2027 Baseline — AHCCCS")).toBeInTheDocument();
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
    expect(screen.getByText("FY 2027 Baseline — AHCCCS")).toBeInTheDocument(),
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
// nothing. Year/type chips are derived from the results, and the derived list is
// RESET when the query changes — but the filter itself persists. So searching
// again under a filter that now excludes every row used to erase that filter's
// own chip, leaving it applied and still sent to the API with no way to undo it.
//
// NOTE for whoever edits this: the failure needs the QUERY to change. Toggling a
// filter on the same query can't reproduce it, because the facet list accumulates
// within a query (see mergeFacets in Search.tsx).
test("a filter kept across a new query stays visible and clearable", async () => {
  const spy = vi
    .spyOn(api, "search")
    // Only the FIRST search finds anything, and it is what offers the FY 2027 chip.
    .mockResolvedValueOnce({ results: [RESULT], total: 1, provider: "stub" })
    .mockResolvedValue({ results: [], total: 0, provider: "stub" });

  render(<MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: /FY 2027/ }));
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "ahcccs",
      expect.objectContaining({ fiscal_year: [2027] }),
      "budget",
    ),
  );

  // Search for something else. FY 2027 stays selected, but the new (empty)
  // response offers no years at all — the moment the chip used to disappear.
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

  const stillThere = screen.getByRole("button", { name: /FY 2027/ });
  expect(stillThere).toHaveAttribute("aria-pressed", "true");
  // The empty state blames the filter, not the corpus.
  expect(screen.getByText(/with the filters above/i)).toBeInTheDocument();

  // And it really does undo: the dimension is dropped, not sent as an empty array.
  fireEvent.click(stillThere);
  await waitFor(() => expect(spy).toHaveBeenLastCalledWith("roads", {}, "budget"));
});
