import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FiscalNotes } from "./FiscalNotes";
import * as api from "../api";

// These are the plan's three pinned tests plus the behaviors of the mockup's JS island
// (reference/fiscal-notes-build/build.py lines 153-201), which is the source of truth for
// how this page filters.
//
// Two updates to the plan's originals, both markup-level, neither loosening a pinned
// behavior:
//   - The filter box is found by the GENERATED page's real placeholder, "Bill # or
//     keyword…", not by /filter/i. The plan predates the discovery that
//     subpage-fiscal-notes.html (not base.html) is the source page, and porting its
//     placeholder verbatim is the S12 requirement.
//   - The mock session names ("2026 Legislative Session") differ from the real snapshot's
//     ("57th Legislature, 2nd Reg. Session (2026)"). That is fine; they are mocks.

const BOX = /bill # or a question/i;

const DATA = {
  sessions: [
    {
      year: 2026,
      name: "2026 Legislative Session",
      bills: [
        {
          bill_number: "HB2001",
          title: "appropriations; K-12 rollover",
          chamber: "H" as const,
          fiscal_note_url: "https://example.gov/hb2001.pdf",
        },
        {
          bill_number: "SB1101",
          title: "AHCCCS; provider rates",
          chamber: "S" as const,
          fiscal_note_url: "https://example.gov/sb1101.pdf",
        },
      ],
    },
    {
      year: 2025,
      name: "2025 Legislative Session",
      bills: [
        {
          bill_number: "HB2500",
          title: "school facilities; funding",
          chamber: "H" as const,
          fiscal_note_url: "https://example.gov/hb2500.pdf",
        },
      ],
    },
  ],
};

/** One session of arbitrary bills — for the pins that need specific numbers or titles. */
function oneSession(bills: { no: string; title: string; chamber?: "H" | "S" }[]) {
  return {
    sessions: [
      {
        year: 2026,
        name: "2026 Legislative Session",
        bills: bills.map((b) => ({
          bill_number: b.no,
          title: b.title,
          chamber: b.chamber ?? (b.no.startsWith("H") ? ("H" as const) : ("S" as const)),
          fiscal_note_url: `https://example.gov/${b.no.replace(/\s+/g, "")}.pdf`,
        })),
      },
    ],
  };
}

function mount() {
  return render(
    <MemoryRouter>
      <FiscalNotes />
    </MemoryRouter>,
  );
}

/** The bill numbers currently rendered, in DOM order. */
function rows(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".fbill-no")].map((el) => el.textContent ?? "");
}

/** Open the rail's Legislative Session multi-select and tick a year (spec F1).
 *  The 28-row scrolling radio list is gone; this is Budget Documents' control. */
function pickSession(year: number) {
  fireEvent.click(screen.getByRole("button", { name: /any session|selected|^\d{4}$/i }));
  // Scope to the open menu: the option and the session CARD's collapse header now share a
  // visible name ("2025 (2025 Legislative Session)"), so a page-wide query finds both.
  const menu = screen.getByRole("group", { name: /legislative session options/i });
  const opt = [...menu.querySelectorAll("button")].find((b) =>
    (b.getAttribute("aria-label") ?? "").startsWith(String(year)),
  );
  if (!opt) throw new Error(`no session option for ${year}`);
  fireEvent.click(opt);
}

/** Open the rail's Sort dropdown and choose an order (spec F5 — it left the card
 *  headers, where it forced one element to be both a collapse toggle and a menu). */
function pickSort(label: RegExp) {
  fireEvent.click(screen.getByRole("button", { name: /bill (number|title) \(/i }));
  fireEvent.click(screen.getByRole("button", { name: label }));
}


beforeEach(() => vi.spyOn(api, "fiscalNotes").mockResolvedValue(DATA));

// ---------------------------------------------------------------------------
// The plan's three pinned tests
// ---------------------------------------------------------------------------

test("renders sessions with bill cards", async () => {
  mount();
  await waitFor(() => expect(screen.getByText("HB2001")).toBeInTheDocument());
  // Exact text, not /2026 legislative session/i as the plan had it: the status line now also
  // names the session ("2 fiscal notes in 2026 Legislative Session."), so the loose regex
  // matches two elements. This asserts the card's own `.yg-yr` heading, which is the thing
  // the plan meant.
  expect(screen.getByText("2026 (2026 Legislative Session)")).toBeInTheDocument();
  // Every in-scope session gets a card now (spec F1) — the page browses the corpus by
  // year instead of showing one session. Priors are COLLAPSED, so 2025's card is present
  // while its rows are not.
  expect(screen.getByText("2025 (2025 Legislative Session)")).toBeInTheDocument();
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();
});

test("chamber switcher filters", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
  expect(screen.getByText("SB1101")).toBeInTheDocument();
});

test("text filter matches bill number prefix and title keywords", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "ahcccs" } });
  expect(screen.getByText("SB1101")).toBeInTheDocument();
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// Island parity — query semantics (build.py:177-184)
// ---------------------------------------------------------------------------

// The island collapses whitespace on a letter-bearing query before prefix-matching, so the
// snapshot's spaced numbers ("HB 2011") answer to what people actually type.
test("a letter+digit query ignores the space in 'HB 2011'", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([
      { no: "HB 2011", title: "individual income tax; subtraction; adoption" },
      { no: "HB 2725", title: "AHCCCS; prescription drug coverage" },
    ]),
  );
  mount();
  await waitFor(() => screen.getByText("HB 2011"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "hb2011" } });
  expect(screen.getByText("HB 2011")).toBeInTheDocument();
  expect(screen.queryByText("HB 2725")).not.toBeInTheDocument();
});

// build.py:157 states the contract: "2015", "HB 2015" and "HB2015" all hit HB 2015. A
// DIGITS-ONLY query prefix-matches the numeric part and searches nothing else — pinned in
// both directions, because SB 1015's title contains "2015" and must NOT match.
test("a digits-only query prefix-matches the bill number and never the title", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([
      { no: "HB 2015", title: "schools; facilities funding" },
      { no: "SB 1015", title: "budget reconciliation; 2015 revisions" },
    ]),
  );
  const { container } = mount();
  await waitFor(() => screen.getByText("HB 2015"));
  const box = screen.getByPlaceholderText(BOX);

  for (const typed of ["2015", "HB 2015", "HB2015"]) {
    fireEvent.change(box, { target: { value: typed } });
    expect(rows(container), `query ${typed}`).toEqual(["HB 2015"]);
  }

  // "20" is a prefix of 2015 only; 1015 does not start with it.
  fireEvent.change(box, { target: { value: "20" } });
  expect(rows(container)).toEqual(["HB 2015"]);
});

// The island tests the title with ONE indexOf over the whole query — not AND-ed terms. A
// first pass at this page split the query on whitespace, which silently made it match more
// than the mockup does; this pins the mockup's semantics.
test("a keyword query is a single substring, not AND-ed terms", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([{ no: "HB 2500", title: "school facilities; funding" }]),
  );
  mount();
  await waitFor(() => screen.getByText("HB 2500"));
  const box = screen.getByPlaceholderText(BOX);

  fireEvent.change(box, { target: { value: "school facilities" } });
  expect(screen.getByText("HB 2500")).toBeInTheDocument();
  // Both words are in the title, but not adjacently — the mockup does not match this.
  fireEvent.change(box, { target: { value: "school funding" } });
  expect(screen.queryByText("HB 2500")).not.toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// Island parity — scope, selection, sort
// ---------------------------------------------------------------------------

test("the session control is a FILTER, and ticking one narrows the cards", async () => {
  // Spec F1: this replaced a 28-row radio list where exactly one session could be seen.
  // Nothing ticked = every session in scope, which is the whole point of the change.
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  expect(screen.getByText("2025 (2025 Legislative Session)")).toBeInTheDocument();

  pickSession(2025);
  expect(screen.queryByText("2026 (2026 Legislative Session)")).not.toBeInTheDocument();
  expect(screen.getByText("2025 (2025 Legislative Session)")).toBeInTheDocument();
});

test("search always spans everything in scope, with no widening pill (spec F7)", async () => {
  // The retired control's REPLACEMENT behaviour: a title query reaches every in-scope
  // session by default, which is what made "Search all legislative sessions" redundant.
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "school" } });
  expect(screen.getByText("HB2500")).toBeInTheDocument();          // 2025, un-widened
  expect(screen.queryByRole("button", { name: /search all legislative sessions/i }))
    .not.toBeInTheDocument();
});

test("clearing the box returns to browsing", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "school" } });
  fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
  expect(screen.getByPlaceholderText(BOX)).toHaveValue("");
  expect(screen.getByText("HB2001")).toBeInTheDocument();
});

test("a ticked session narrows a title search too", async () => {
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2001"));
  // "o" hits all three bills ("rollover", "provider", "school"), which keeps the page in
  // TITLE mode — a query with zero title hits would arm escalation and the assertion below
  // would be about the content spinner instead of about narrowing.
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "o" } });
  expect(screen.getByText("HB2500")).toBeInTheDocument();

  pickSession(2025);
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
  expect(screen.getByText("HB2500")).toBeInTheDocument();
  // The page's own status line, not `getByRole("status")`: content mode's spinner is also
  // a live region, so the role query is ambiguous the moment escalation arms.
  expect(container.querySelector(".fnstatus")).toHaveTextContent(/the 2025 session/i);
});

// The mockup offers four orders (build.py:62-73); the default is bill number ascending,
// which is also the order it emits into the DOM.
test("the rail's sort reorders bills inside each card", async () => {
  // Spec F5: the 4-way menu left the card headers, where it forced the header to be both a
  // collapse toggle and a menu. Sessions stay newest-first; this reorders bills INSIDE a
  // card and never flattens them into one list.
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2001"));
  expect(rows(container)).toEqual(["SB1101", "HB2001"]);

  pickSort(/bill number — high to low/i);
  expect(rows(container)).toEqual(["HB2001", "SB1101"]);

  pickSort(/bill title — a to z/i);
  expect(rows(container)).toEqual(["SB1101", "HB2001"]);

  pickSort(/bill title — z to a/i);
  expect(rows(container)).toEqual(["HB2001", "SB1101"]);
});

// ---------------------------------------------------------------------------
// Count semantics — the two deliberate divergences from the artifact (deviation 9)
// ---------------------------------------------------------------------------

// The rail's `.frow-n` is a session INVENTORY, so it follows the chamber lens but must ignore
// the typed query — "matches" is what the status line reports. Pinned because "make the
// counts consistent" is exactly the refactor that would silently break it.
test("the session dropdown's counts narrow by chamber but not by the typed query", async () => {
  // A session's INVENTORY is a different quantity from "matches", which the status line
  // states outright. Pinned because "make the counts consistent" is exactly the refactor
  // that would silently break it. The counts moved from the retired radio rows to the
  // dropdown's options (spec F1); the semantics did not move.
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.click(screen.getByRole("button", { name: /any session/i }));
  const counts = () => [...container.querySelectorAll(".fopt-n")].map((el) => el.textContent);
  expect(counts()).toEqual(["2", "1"]);

  // Typing does not touch them.
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "ahcccs" } });
  expect(counts()).toEqual(["2", "1"]);

  // The chamber lens does. Cleared first, deliberately: with "ahcccs" typed there are zero
  // House title hits, which ARMS escalation, which correctly greys out the chamber
  // segments (spec F9) — so clicking one there would be a no-op and the test would be
  // asserting against a control the design has stood down on purpose.
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: /^house$/i }));
  expect(counts()).toEqual(["1", "1"]);
  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(counts()).toEqual(["1", "0"]);
});

// With no query the mockup keeps the selected session's card and only hides its rows, so an
// empty chamber must still render the card — with a count that tells the truth about it.
test("with no query, a chamber-emptied session still shows its card", async () => {
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2001"));
  pickSession(2025);
  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));

  expect(screen.getByText("2025 (2025 Legislative Session)")).toBeInTheDocument();
  // `.yg-meta` counts what is rendered, not the pre-filter total the artifact bakes in.
  expect(screen.getByText("0 Senate Notes")).toBeInTheDocument();
  expect(container.querySelectorAll(".fbill")).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// Titles: the AZ strike/NOW convention
// ---------------------------------------------------------------------------

// ~241 of the 2,126 real titles carry raw <strike> markup from the source. React escapes
// strings, so rendering the title as-is would show literal "<strike>" tags to users; using
// dangerouslySetInnerHTML on scraped text would inject them. This pins the third path:
// parse the known pattern into real elements.
test("a struck-and-renamed title renders as real elements, never as tag text", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([
      {
        no: "HB2002",
        title:
          "<strike>DCS; intake hotline; multiple reports</strike> (NOW: deficiencies; denial; credentialing)",
      },
    ]),
  );
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2002"));

  const struck = container.querySelector("s");
  expect(struck).not.toBeNull();
  expect(struck).toHaveTextContent("DCS; intake hotline; multiple reports");
  expect(screen.getByText(/NOW: deficiencies; denial; credentialing/)).toBeInTheDocument();
  expect(container.textContent).not.toContain("<strike>");
  expect(container.textContent).not.toContain("</strike>");
});

// The title filter must match the words a user can SEE. Matching the raw string would let
// "strike" find 241 unrelated bills and would break on the tag boundary.
test("text filter matches the visible words of a struck title", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([
      {
        no: "HB2002",
        title: "<strike>light rail expansion; prohibition</strike> (NOW: feasibility review)",
      },
    ]),
  );
  mount();
  await waitFor(() => screen.getByText("HB2002"));
  const box = screen.getByPlaceholderText(BOX);

  fireEvent.change(box, { target: { value: "strike" } });
  expect(screen.queryByText("HB2002")).not.toBeInTheDocument();

  fireEvent.change(box, { target: { value: "feasibility" } });
  expect(screen.getByText("HB2002")).toBeInTheDocument();
});

// The fallback path: anything that is not the one documented pattern must degrade to plain
// text. Never injected HTML, never visible tags.
test("unrecognized or unclosed markup in a title degrades to plain text", async () => {
  vi.spyOn(api, "fiscalNotes").mockResolvedValue(
    oneSession([{ no: "HB2003", title: "<em>county roads; <strike>funding" }]),
  );
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2003"));

  expect(screen.getByText("county roads; funding")).toBeInTheDocument();
  expect(container.querySelector("em")).toBeNull();
  expect(container.querySelector("s")).toBeNull();
  expect(container.textContent).not.toContain("<");
  // …and it is still findable by its visible words.
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "county roads" } });
  expect(screen.getByText("HB2003")).toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// Status line, links, placeholder, failure
// ---------------------------------------------------------------------------

test("the status line is a live region and counts exactly what is on screen", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  const line = screen.getByRole("status");
  // Scope is now "all N sessions" by default, because the session control is a filter and
  // an empty filter is the WIDEST scope, not the narrowest (spec F1).
  expect(line).toHaveTextContent("3 fiscal notes across all 2 sessions.");

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "ahcccs" } });
  expect(line).toHaveTextContent('1 fiscal note matching “ahcccs”');

  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(line).toHaveTextContent('1 Senate note matching “ahcccs”');
});

test("bills link to their fiscal note PDF", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  const link = screen.getByText("HB2001").closest("a");
  expect(link).toHaveAttribute("href", "https://example.gov/hb2001.pdf");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
});

// ---------------------------------------------------------------------------
// The rail's SECOND search box is gone (spec F6)
// ---------------------------------------------------------------------------
//
// `SemanticRailSearch` — "Search note text" — is deleted, and with it the six tests that
// pinned its disabled state, its corpus argument, its empty result and its error surface.
// Nothing was lost: the one remaining box does title filtering AND escalates to the same
// `api.search(..., "fiscal_notes")` call, and FiscalNotes.content.test.tsx pins all of it
// on the surviving control. Two boxes side by side asked the reader to know, before
// typing, which kind of question they had — which is the thing this design removed.

test("the rail has exactly ONE search box", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  expect(screen.queryByPlaceholderText(/semantic search across all notes/i)).not.toBeInTheDocument();
  expect(screen.queryByTestId("fn-semantic")).not.toBeInTheDocument();
  expect(screen.getAllByPlaceholderText(BOX)).toHaveLength(1);
});
