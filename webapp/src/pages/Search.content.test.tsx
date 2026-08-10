import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

// Content (retrieval) mode. The browse/title half lives in Search.test.tsx;
// splitting them keeps either file readable.

const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
    doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf" },
  { doc_id: "afr26", title: "FY 2026 Annual Financial Report", publisher: "agao",
    doc_type: "afr", fiscal_year: 2026, doc_url: "https://x/afr26.pdf" },
];

const HITS: api.SearchResult[] = [
  { chunk_id: "c1", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The FY 2027 Baseline includes $89,432,700 for child care subsidy assistance.",
    page: 142, score: 0.9, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
  { chunk_id: "c2", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The child care waiting list contained 6,218 children.",
    page: 143, score: 0.5, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
];

function mount(entry = "/search", hits = HITS) {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  const search = vi.spyOn(api, "search").mockResolvedValue({
    results: hits, total: hits.length, provider: "test",
  });
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Search />
    </MemoryRouter>,
  );
  return search;
}

const box = () => screen.getByLabelText(/filter documents by agency or keyword/i);

test("no title match escalates to content search after the pause", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  expect(search).not.toHaveBeenCalled();       // not yet — the pause has not elapsed
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledWith("child care subsidy", {}, "budget");
  vi.useRealTimers();
});

test("a query that DOES match a title never escalates on its own", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "ahcccs" } });
  await vi.advanceTimersByTimeAsync(5000);
  expect(search).not.toHaveBeenCalled();
  vi.useRealTimers();
});

test("the rail's filters reach the backend as doc_type SLUGS", async () => {
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /document type/i }));
  fireEvent.click(screen.getByRole("button", { name: /^Baseline/ }));
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledWith(
    "child care subsidy",
    { doc_type: ["baseline-per-agency", "baseline-cross-cut"] },
    "budget",
  );
  vi.useRealTimers();
});

test("?q= and ?in=contents restore a content search on load", async () => {
  const search = mount("/search?q=child%20care&in=contents");
  await waitFor(() => expect(search).toHaveBeenCalledWith("child care", {}, "budget"));
});

// `window.location` is NOT the right probe here: MemoryRouter (used by every
// test in this file, and everywhere else `<Search />` is mounted) keeps its
// own in-memory history via `createMemoryHistory` and never touches the real
// `window.location` — confirmed with an isolated repro against react-router's
// own MemoryRouter source, and true regardless of what Search.tsx does. A
// second `useSearchParams()` consumer inside the SAME router reads the exact
// location state Search.tsx's `setParams(..., { replace: true })` writes to,
// which is what "a search can be linked" actually depends on.
function UrlProbe() {
  const [params] = useSearchParams();
  return <div data-testid="url-probe">{params.toString()}</div>;
}

test("the box writes ?q= so a search can be linked", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockResolvedValue({ results: HITS, total: HITS.length, provider: "test" });
  render(
    <MemoryRouter initialEntries={["/search"]}>
      <Search />
      <UrlProbe />
    </MemoryRouter>,
  );
  await screen.findByText(/Fiscal Year 2027/);
  fireEvent.change(box(), { target: { value: "ahcccs" } });
  await waitFor(() => expect(screen.getByTestId("url-probe").textContent).toContain("q=ahcccs"));
});

test("a failed content search surfaces the backend's own detail", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockRejectedValue(new Error("search: query is empty"));
  render(
    <MemoryRouter initialEntries={["/search?q=zzz&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/search: query is empty/)).toBeInTheDocument();
});
