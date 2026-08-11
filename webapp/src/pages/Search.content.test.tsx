import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

// Content (retrieval) mode. The browse/title half lives in Search.test.tsx;
// splitting them keeps either file readable.

// terms: [] — Task 4 made CorpusDocument.terms required repo-wide; content
// (retrieval) mode doesn't use queryHit, so an empty array is a neutral filler.
const DOCS: api.CorpusDocument[] = [
  { doc_id: "b27-ahcccs", title: "FY 2027 Baseline — AHCCCS", publisher: "jlbc",
    doc_type: "baseline-per-agency", fiscal_year: 2027, doc_url: "https://x/axs.pdf", terms: [] },
  { doc_id: "afr26", title: "FY 2026 Annual Financial Report", publisher: "agao",
    doc_type: "afr", fiscal_year: 2026, doc_url: "https://x/afr26.pdf", terms: [] },
];

// text: same as snippet — Task 1 made `text` required alongside `snippet`;
// these fixtures' snippets are already the whole sentence (well under 280
// chars), so text/snippet coincide and this file (which predates the
// highlighting work) doesn't need a longer passage to exercise anything.
const HITS: api.SearchResult[] = [
  { chunk_id: "c1", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The FY 2027 Baseline includes $89,432,700 for child care subsidy assistance.",
    text: "The FY 2027 Baseline includes $89,432,700 for child care subsidy assistance.",
    page: 142, score: 0.9, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
  { chunk_id: "c2", doc_id: "b27-ahcccs", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "The child care waiting list contained 6,218 children.",
    text: "The child care waiting list contained 6,218 children.",
    page: 143, score: 0.5, doc_type: "baseline-per-agency", fiscal_year: 2027,
    publisher: "jlbc", agencies: [], doc_url: "https://x/axs.pdf", doc_meta: null },
];

// A single-passage document with no page number — covers two PassageCard
// branches the shared HITS fixture above can't reach: "More from this
// document" is absent when there is nothing more, and page:null renders
// "no page" rather than a bogus "p. null".
const SINGLE_HIT: api.SearchResult[] = [
  { chunk_id: "c3", doc_id: "afr26", doc_title: "FY 2026 Annual Financial Report",
    snippet: "General Fund revenue collections grew year over year.",
    text: "General Fund revenue collections grew year over year.",
    page: null, score: 0.7, doc_type: "afr", fiscal_year: 2026,
    publisher: "agao", agencies: [], doc_url: "https://x/afr26.pdf", doc_meta: null },
];

// A promise this test can resolve/reject on its own schedule, unlike
// `mockResolvedValue`/`mockRejectedValue` (used everywhere else in this
// file) which settle on the same microtask tick every request was made on —
// fine for asserting the RESULT of one request, useless for putting two
// requests genuinely in flight at once to exercise the stale-response guard.
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// Waiting on a bare `await Promise.resolve()` only drains the MICROTASK
// queue, not React 18's update scheduler (it commits via a MessageChannel
// macrotask outside of `act()`). Verified with a throwaway repro: an
// unguarded effect's late `setState` call was still invisible in the DOM
// after two `await Promise.resolve()`s, which would have made the two tests
// below pass whether or not the real guard existed. A `setTimeout` tick
// flushes the macrotask queue and makes the commit observable either way.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

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

test("typing again restarts the escalation pause instead of firing on the stale timer", async () => {
  // WHY this test exists: the escalation effect's dependency array used to be
  // [mode, searching, titleHits, phase.kind] — missing `q`. titleHits stays 0
  // across successive zero-hit keystrokes, so that effect never re-ran after
  // the FIRST such keystroke, and the 2000ms timer it started kept ticking
  // regardless of further typing: escalation fired 2s after the first
  // zero-hit keystroke, not 2s after the box went quiet, contradicting the
  // effect's own "only after the box goes quiet" comment. This types,
  // advances the clock partway, types again, and advances partway again —
  // under the bug the stale timer from keystroke #1 has already fired inside
  // that window; fixed, the second keystroke restarts the pause.
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  await vi.advanceTimersByTimeAsync(1500);
  fireEvent.change(box(), { target: { value: "child care subsidy x" } });
  await vi.advanceTimersByTimeAsync(1500);
  // Only 1500ms have passed since the SECOND keystroke — must not have fired
  // yet. (Buggy: the first keystroke's timer hits its 2000ms mark at t=2000,
  // inside this 3000ms cumulative window, and fires early.)
  expect(search).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(500);
  expect(search).toHaveBeenCalledWith("child care subsidy x", {}, "budget");
  vi.useRealTimers();
});

test("clicking back to title matches is not a dead end that yanks the reader back into content mode", async () => {
  // CRITICAL, 2026-08-10: escalation only ever happens at zero title hits, so
  // the reader who clicks "Back to title matches" is, by construction, still
  // at zero hits after returning. `mode` is one of the escalation effect's
  // own deps, so without suppression that effect re-ran on the very re-render
  // the click caused and armed a FRESH 2000ms timer — 2s after the reader
  // asked to leave content mode, they were yanked straight back into it and a
  // retrieval request re-fired. This types a zero-hit query, lets it
  // auto-escalate, clicks back, and asserts nothing re-fires — then types a
  // genuinely NEW query and asserts THAT one still escalates normally (a
  // suppression flag that never clears would pass the first half of this
  // test with the same bug still present for every query after the first).
  vi.useFakeTimers();
  const search = mount();
  await vi.waitFor(() => expect(screen.getByText(/Fiscal Year 2027/)).toBeInTheDocument());
  fireEvent.change(box(), { target: { value: "child care subsidy" } });
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledTimes(1);
  await vi.waitFor(() =>
    expect(screen.getByRole("button", { name: /back to title matches/i })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  await vi.waitFor(() => expect(screen.getByText(/searching document titles/i)).toBeInTheDocument());

  await vi.advanceTimersByTimeAsync(5000);
  expect(search).toHaveBeenCalledTimes(1); // still 1 — no re-escalation
  expect(screen.getByText(/searching document titles/i)).toBeInTheDocument();

  // A genuinely new query must still escalate on its own.
  fireEvent.change(box(), { target: { value: "another zero hit query" } });
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledTimes(2);
  expect(search).toHaveBeenNthCalledWith(2, "another zero hit query", {}, "budget");
  vi.useRealTimers();
});

// A second useSearchParams() consumer in the SAME router, standing in for an
// outside navigation — Back/Forward, a pasted link, an in-app nav to a new
// ?q= while this page stays mounted — the exact class of URL change Search's
// own `lastWritten` ref (Search.tsx:704) does NOT recognise as its own write,
// so it goes through the URL read-effect (:716) rather than the search box's
// onChange. Same trick as UrlProbe below, but writing instead of reading.
function UrlDriver() {
  const [, setParams] = useSearchParams();
  return (
    <button type="button" onClick={() => setParams({ q: "another zero hit query" })}>
      simulate external nav
    </button>
  );
}

test("a query arriving via the URL, not the box, still escalates after a prior suppression", async () => {
  // Finding 2, pre-merge re-review (2026-08-10): suppressEscalationFor used
  // to be a boolean cleared ONLY by the search box's own onChange. A query
  // that instead arrives through the URL read-effect never went through
  // onChange, so under the old code the boolean stayed set from the earlier
  // "Back to title matches" click and the new query could never auto-escalate
  // until the reader typed a character. UrlDriver reproduces that arrival
  // path (setSearchParams from a second consumer, not fireEvent.change on the
  // box) so this exercises the exact gap the fix closed.
  vi.useFakeTimers();
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  const search = vi.spyOn(api, "search").mockResolvedValue({
    results: HITS, total: HITS.length, provider: "test",
  });
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care%20subsidy"]}>
      <Search />
      <UrlDriver />
    </MemoryRouter>,
  );
  await vi.waitFor(() => expect(screen.getByText(/searching document titles/i)).toBeInTheDocument());
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledTimes(1); // the initial ?q= escalated normally

  await vi.waitFor(() =>
    expect(screen.getByRole("button", { name: /back to title matches/i })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  await vi.waitFor(() => expect(screen.getByText(/searching document titles/i)).toBeInTheDocument());
  await vi.advanceTimersByTimeAsync(5000);
  expect(search).toHaveBeenCalledTimes(1); // suppression held for the original query

  // A NEW query arrives via the URL — not the box.
  fireEvent.click(screen.getByRole("button", { name: /simulate external nav/i }));
  await vi.waitFor(() => expect(box()).toHaveValue("another zero hit query"));
  await vi.advanceTimersByTimeAsync(2000);
  expect(search).toHaveBeenCalledTimes(2); // must still escalate — this is a different query
  expect(search).toHaveBeenNthCalledWith(2, "another zero hit query", {}, "budget");
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

test("content results render one card per document with the passage quoted", async () => {
  mount("/search?q=child%20care&in=contents");
  expect(await screen.findByText(/89,432,700/)).toBeInTheDocument();
  // Two passages, ONE document, therefore ONE card.
  expect(document.querySelectorAll(".grp")).toHaveLength(1);
  expect(screen.getByText("p. 142")).toBeInTheDocument();
});

test("the query term is marked inside the quote", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  expect(document.querySelector("mark")).toHaveTextContent("child care");
});

test("the header names which search produced the list", async () => {
  mount("/search?q=child%20care&in=contents");
  expect(await screen.findByText(/searching document contents/i)).toBeInTheDocument();
});

test("the passage count is phrased as a top-k cap, not a total", async () => {
  // IMPORTANT, 2026-08-10: app/routes/search.py defaults top_k=20 and the
  // frontend never overrides it, so `results.length` is a truncation count,
  // not a corpus-wide total — for any common term the number reads the same
  // every time. Both places that print it (`.docstatus` and the results
  // header's `.yg-meta`) must say "Top N", not bare "N".
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  expect(screen.getByText(/^top 2 passages, in 1 document, matching/i)).toBeInTheDocument();
  expect(screen.getByText(/top 2 passages · 1 document matching/i)).toBeInTheDocument();
});

test("More from this document reveals the remaining passages", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  expect(screen.queryByText(/6,218 children/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /more from this document/i }));
  expect(screen.getByText(/6,218 children/)).toBeInTheDocument();
});

test("the toggle switches modes and is present on BOTH sides", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  fireEvent.click(screen.getByRole("button", { name: /back to title matches/i }));
  expect(await screen.findByText(/searching document titles/i)).toBeInTheDocument();
  // No title matches for this query — but the way back must still be there.
  expect(screen.getByRole("button", { name: /search document contents/i })).toBeInTheDocument();
});

test("content search finding nothing says so, and does not blame filters", async () => {
  mount("/search?q=zzqx&in=contents", []);
  expect(await screen.findByText(/no passages inside the ingested documents mention/i))
    .toBeInTheDocument();
  expect(screen.queryByText(/clearing/i)).toBeNull();
});

test("no count is claimed while the content request is still loading", async () => {
  // IMPORTANT, 2026-08-10: the header's count used to fall back to 0 for
  // BOTH "loading" and "error" ContentPhase kinds, so it read "0 passages ·
  // 0 documents matching …" at the exact moment the block below says
  // "Searching document contents…" — a finished, empty answer claimed while
  // the search was still running. `.docstatus` already got this right
  // (renders "" unless ready); the header's own count must follow the same
  // rule.
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockReturnValue(new Promise(() => {})); // never settles
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  await screen.findByText(/reading inside every ingested pdf/i);
  expect(screen.queryByText(/passage/i)).toBeNull();
  expect(screen.queryByText(/0 documents/i)).toBeNull();
});

test("the toggle is hidden while the request is in flight", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  vi.spyOn(api, "search").mockReturnValue(new Promise(() => {})); // never settles
  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  // The loading block's sub-line ("reading inside every ingested PDF") is the
  // one piece of copy unique to it — the header's own "(searching document
  // contents)" qualifier is ALSO on screen at the same moment (by design, see
  // the WHY at that JSX), so matching the shared phrase here is ambiguous
  // (`findByText` throws "Found multiple elements").
  expect(await screen.findByText(/reading inside every ingested pdf/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /back to title matches/i })).toBeNull();
});

test("a document with one matching passage has no tray toggle, and a null page renders 'no page'", async () => {
  mount("/search?q=revenue&in=contents", SINGLE_HIT);
  // "collections grew" sits AFTER the highlighted "revenue" — querying it
  // (rather than text overlapping the <mark> split) avoids the "text is
  // broken up by multiple elements" trap highlight() runs create.
  await screen.findByText(/collections grew/i);
  expect(screen.getByText("no page")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /more from this document/i })).toBeNull();
});

test("a query with no literal match in the snippet still renders the quote, unmarked", async () => {
  // "growth" never appears verbatim in "grew year over year" — highlight()
  // must fall through to a single unhit run rather than throwing or marking
  // a partial word.
  mount("/search?q=growth&in=contents", SINGLE_HIT);
  await screen.findByText(/General Fund revenue/i);
  expect(document.querySelector("mark")).toBeNull();
});

test("More from this document tray closes again on a second click", async () => {
  mount("/search?q=child%20care&in=contents");
  await screen.findByText(/89,432,700/);
  fireEvent.click(screen.getByRole("button", { name: /more from this document/i }));
  expect(screen.getByText(/6,218 children/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /more from this document/i }));
  expect(screen.queryByText(/6,218 children/)).toBeNull();
});

// The content-fetch effect's `let ignore = false` closure (Search.tsx) exists
// to stop an older, slower response from painting over a newer one. Every
// other test in this file resolves `api.search` with `mockResolvedValue` /
// `mockRejectedValue`, which settle on the SAME microtask tick as the call —
// two requests are never actually in flight together, so none of them can
// tell a working guard from a deleted one. These two do.
test("a stale response from an older request is discarded, not painted over the newer one", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  const older = deferred<api.SearchResponse>();
  const newer = deferred<api.SearchResponse>();
  const search = vi
    .spyOn(api, "search")
    .mockReturnValueOnce(older.promise)
    .mockReturnValueOnce(newer.promise);

  render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));

  // Fire a SECOND content request while the first is still pending, without
  // touching `mode` or `q` — typing in the filter box always bounces mode
  // back to "titles" (see its onChange), so a document-type filter toggle
  // (already exercised the same way by "the rail's filters reach the backend
  // as doc_type SLUGS" above) is what actually re-runs the content effect
  // while staying in contents mode.
  fireEvent.click(screen.getByRole("button", { name: /document type/i }));
  fireEvent.click(screen.getByRole("button", { name: /^Baseline/ }));
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));

  // Resolve the NEWER request first, then the OLDER one arrives late — the
  // guard must keep the newer result on screen and never flicker back.
  newer.resolve({ results: SINGLE_HIT, total: SINGLE_HIT.length, provider: "test" });
  await screen.findByText(/General Fund revenue/i);
  expect(screen.queryByText(/89,432,700/)).toBeNull();

  older.resolve({ results: HITS, total: HITS.length, provider: "test" });
  // Let the (ignored) older .then callback run AND commit; a broken guard
  // would call setContent here and swap the results back to HITS.
  await flush();
  expect(screen.getByText(/General Fund revenue/i)).toBeInTheDocument();
  expect(screen.queryByText(/89,432,700/)).toBeNull();
});

test("no state update fires after the content-search component unmounts mid-request", async () => {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: DOCS });
  const pending = deferred<api.SearchResponse>();
  vi.spyOn(api, "search").mockReturnValue(pending.promise);
  // React logs unmounted-state-update warnings (and any other renderer
  // warning) through console.error — asserting it was never called is the
  // "test output stays clean" check the finding asks for.
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

  const view = render(
    <MemoryRouter initialEntries={["/search?q=child%20care&in=contents"]}>
      <Search />
    </MemoryRouter>,
  );
  await screen.findByText(/reading inside every ingested pdf/i);

  view.unmount();

  // Resolve AFTER unmount. The effect's cleanup already flipped its `ignore`
  // closure to true when React tore the component down; if that guard were
  // missing, this is where a state update — and any warning React logs for
  // one — would show up.
  pending.resolve({ results: HITS, total: HITS.length, provider: "test" });
  await flush();

  expect(errorSpy).not.toHaveBeenCalled();
  errorSpy.mockRestore();
});
