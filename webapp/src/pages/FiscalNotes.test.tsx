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

const BOX = /bill # or keyword/i;

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
  expect(screen.getByText("2026 Legislative Session")).toBeInTheDocument();
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

test("selecting a session in the rail swaps which card is shown", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  // Default scope is the newest session only, exactly as the generated page ships it.
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /2025 legislative session/i }));
  expect(screen.getByText("HB2500")).toBeInTheDocument();
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();

  // And back to the newest row — the one whose selection is the page's default.
  fireEvent.click(screen.getByRole("button", { name: /2026 legislative session/i }));
  expect(screen.getByText("HB2001")).toBeInTheDocument();
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();
});

test("'search all sessions' widens the scope, and is inert with an empty box", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  const pill = screen.getByRole("button", { name: /search all legislative sessions/i });
  // build.py:174 force-unchecks the toggle whenever the box is empty, so it can do nothing
  // there; the port says so with a real disabled attribute.
  expect(pill).toBeDisabled();

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "school" } });
  // Nothing in the selected session matches…
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();
  expect(pill).toBeEnabled();

  // …until the scope widens to every session.
  fireEvent.click(pill);
  expect(screen.getByText("HB2500")).toBeInTheDocument();
  expect(screen.getAllByText(/2025 legislative session/i).length).toBeGreaterThan(0);
});

test("clearing the box drops the widened scope, as the island does", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "school" } });
  fireEvent.click(screen.getByRole("button", { name: /search all legislative sessions/i }));
  expect(screen.getByText("HB2500")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
  expect(screen.getByPlaceholderText(BOX)).toHaveValue("");
  // Back to the selected session only, and the toggle is inert again.
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();
  expect(screen.getByText("HB2001")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /search all legislative sessions/i })).toBeDisabled();
});

test("picking a session also drops the widened scope", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "school" } });
  fireEvent.click(screen.getByRole("button", { name: /search all legislative sessions/i }));
  expect(screen.getByText("HB2500")).toBeInTheDocument();

  // Selecting a session narrows back to it (build.py:199 unchecks #fnAll on a year change).
  fireEvent.click(screen.getByRole("button", { name: /2026 legislative session/i }));
  expect(screen.queryByText("HB2500")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    /matching "school" in 2026 Legislative Session/i,
  );
});

// The mockup offers four orders (build.py:62-73); the default is bill number ascending,
// which is also the order it emits into the DOM.
test("the sort menu reorders the list", async () => {
  const { container } = mount();
  await waitFor(() => screen.getByText("HB2001"));
  // Default: by number, low to high — 1101 before 2001.
  expect(rows(container)).toEqual(["SB1101", "HB2001"]);

  fireEvent.click(screen.getByRole("button", { name: /bill number — high to low/i }));
  expect(rows(container)).toEqual(["HB2001", "SB1101"]);

  // "AHCCCS; provider rates" vs "appropriations; K-12 rollover": A→Z puts AHCCCS first.
  fireEvent.click(screen.getByRole("button", { name: /bill title — a to z/i }));
  expect(rows(container)).toEqual(["SB1101", "HB2001"]);

  fireEvent.click(screen.getByRole("button", { name: /bill title — z to a/i }));
  expect(rows(container)).toEqual(["HB2001", "SB1101"]);
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
  expect(line).toHaveTextContent("2 fiscal notes in 2026 Legislative Session.");

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "ahcccs" } });
  expect(line).toHaveTextContent(
    '1 of 2 fiscal notes matching "ahcccs" in 2026 Legislative Session.',
  );

  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(line).toHaveTextContent(
    '1 of 1 Senate note matching "ahcccs" in 2026 Legislative Session.',
  );

  fireEvent.change(screen.getByPlaceholderText(BOX), { target: { value: "zzz" } });
  expect(line).toHaveTextContent(/^No Senate notes matching "zzz" in 2026 Legislative Session/);
});

test("bills link to their fiscal note PDF", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  const link = screen.getByText("HB2001").closest("a");
  expect(link).toHaveAttribute("href", "https://example.gov/hb2001.pdf");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
});

test("the semantic-search box is honestly disabled until the corpus is ingested", async () => {
  mount();
  await waitFor(() => screen.getByText("HB2001"));
  const box = screen.getByPlaceholderText(/semantic search across all notes/i);
  expect(box).toBeDisabled();
  expect(screen.getByText(/unlocks when the fiscal-note corpus is ingested/i)).toBeInTheDocument();
});

test("a failed load shows the backend's own detail and can be retried", async () => {
  const spy = vi
    .spyOn(api, "fiscalNotes")
    .mockRejectedValueOnce(new Error("fiscal-notes: snapshot missing"));
  mount();
  await waitFor(() => expect(screen.getByText(/snapshot missing/)).toBeInTheDocument());

  spy.mockResolvedValue(DATA);
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  await waitFor(() => expect(screen.getByText("HB2001")).toBeInTheDocument());
});
