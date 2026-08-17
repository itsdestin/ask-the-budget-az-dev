import type React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api";
import { BookFamilyPanel } from "./BookFamilyPanel";

// Spec T10: the panel answers "what has JLBC published that we don't have?"
//
// Measured before that change: 62 editions offered, **0** of them usefully
// addable. Every assertion below is about WHAT IS OFFERED, which is the
// entire point of the inversion.
//
// Second change, 2026-08-15: the standalone "Add a JLBC book" section is
// gone and this panel now renders inside ONE document-type row, for ONE book
// family, and is HANDED the check rather than fetching it. The added specs
// are about that scoping — a Baseline Book row offering an Appropriations
// Report would be exactly the noise T10 removed, arriving by a new route.
//
// Third change, 2026-08-16: STATE -> ACTIONS -> EXPLANATION. Measured before
// it, 102 words were visible on opening a Baseline Book card and the answer
// ("Every published Baseline Book is already here.") was the FOURTH thing you
// read, 54 words in. The card now opens with that answer, in one line naming
// the newest year present, and the three explanatory paragraphs moved behind
// two disclosure rows that each carry what is outstanding inside them.
//
// So several specs below OPEN a section before asserting its contents. That
// is deliberate and is not ceremony: a `getByText` that finds prose inside a
// closed <details> would pass for text no reader can see, which is exactly
// the property this change is about.
//
// jsdom applies no stylesheet, so nothing here says anything about how the
// panel looks — including whether the "can't be added" rows read as greyed,
// and including the type-size contrast that IS the new hierarchy.

function check(over: Partial<api.BookCheck> = {}): api.BookCheck {
  return {
    checked_at: new Date().toISOString(),
    online: true,
    reason: null,
    missing: [],
    present: [],
    unavailable: [],
    ...over,
  };
}

const FY2027_APPROPS = {
  family: "approps",
  fiscal_year: 2027,
  document_count: null,
  source: "probed" as const,
};

const FY2028_BASELINE = {
  family: "baseline",
  fiscal_year: 2028,
  document_count: 110,
  source: "catalog" as const,
};

/** The Appropriations Report row's panel — the family every test below uses
 *  unless it is specifically about scoping.
 *
 *  The check is a PROP, not a fetch: the page owns it, because it answers
 *  for BOTH families in one round-trip and the collapsed rows above show a
 *  count off it, so a panel-local copy would be a second call and a second
 *  version of the same number. It makes these tests simpler too — the
 *  panel's behaviour is exercised by handing it an answer, with no api mock
 *  standing between the setup and the assertion.
 */
function renderPanel(
  props: Partial<React.ComponentProps<typeof BookFamilyPanel>> = {},
) {
  return render(
    <BookFamilyPanel
      family="approps"
      label="Appropriations Report"
      detail="Stored as one document per agency."
      wherePublished="Published by JLBC after the session at azjlbc.gov."
      check={check()}
      checking={false}
      checkError=""
      onRecheck={() => {}}
      onQueued={() => {}}
      {...props}
    />,
  );
}

/** Open one of the card's disclosure rows, the way a reader does. Asserting
 *  against a closed section's contents would be asserting against text
 *  nobody can see. */
function openSection(testId: "book-older" | "book-about") {
  const details = screen.getByTestId(testId);
  fireEvent.click(details.querySelector("summary")!);
  expect(details.getAttribute("open")).not.toBeNull();
  return details;
}

afterEach(() => vi.restoreAllMocks());

describe("a book row offers only what its own family is missing", () => {
  it("offers an edition the corpus lacks", () => {
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });

    const row = screen.getByTestId("missing-edition");
    expect(row.textContent).toContain("FY 2027 Appropriations Report");
    expect(row.textContent).toContain("not in your corpus");
    expect(within(row).getByRole("button", { name: "Add" })).toBeTruthy();
  });

  it("ignores the OTHER family's missing edition entirely", () => {
    // The endpoint answers for both families in one round-trip (one fetch,
    // one 12-hour cache, two rows). Each row must show only its own — a
    // Baseline Book row offering an Appropriations Report is the same class
    // of noise T10 exists to remove.
    renderPanel({ check: check({ missing: [FY2027_APPROPS, FY2028_BASELINE] }) });

    const rows = screen.getAllByTestId("missing-edition");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("FY 2027");
    expect(document.body.textContent).not.toContain("FY 2028");
  });

  it("ignores the other family's UN-addable editions too", () => {
    renderPanel({
      check: check({
        unavailable: [
          { family: "baseline", fiscal_year: 2006, era_note: "Baseline era note." },
          { family: "approps", fiscal_year: 1984, era_note: "Approps era note." },
        ],
      }),
    });

    openSection("book-older");
    const rows = screen.getAllByTestId("unavailable-edition");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("FY 1984");
    // The count is the row's OWN family's, and it is on the row rather than
    // only inside it — see "each row states what is outstanding" below.
    expect(screen.getByText("1 can’t be added")).toBeTruthy();
  });

  it("names an edition with the row's OWN label, not a name of its own", () => {
    // The panel is handed `label` rather than mapping family -> words here,
    // so an edition is named with the same words as the row it sits in,
    // from one source (the registry).
    renderPanel({
      family: "baseline",
      label: "Baseline Book",
      check: check({ missing: [FY2028_BASELINE] }),
    });

    const row = screen.getByTestId("missing-edition");
    expect(row.textContent).toContain("FY 2028 Baseline Book");
    expect(row.textContent).toContain("110 documents");
  });

  it("keeps the registry's own two sentences, inside About this book", () => {
    // Both moved INSIDE when the collapsed row was cut back to a name — see
    // Upload.tsx's header comment for the measurement — and moved again into
    // this section when the body was reordered. They explain rather than
    // answer, so they are behind a disclosure; but they must still be
    // somewhere, and they must be REACHABLE, which is why this opens it.
    renderPanel();
    const about = openSection("book-about");
    expect(within(about).getByText("Stored as one document per agency.")).toBeTruthy();
    expect(
      within(about).getByText("Published by JLBC after the session at azjlbc.gov."),
    ).toBeTruthy();
  });

  it("opens with the answer, naming the newest year it has", () => {
    // The state the live corpus is in for every edition but one, and the
    // whole point of the reorder: the card's first line is what you opened
    // it to find out. The YEAR is derived from the check's own `present`
    // list — a hardcoded one becomes a lie the January JLBC publishes the
    // next edition.
    const first = renderPanel({
      check: check({
        missing: [],
        present: [
          { family: "approps", fiscal_year: 2025 },
          { family: "approps", fiscal_year: 2027 },
          // The other family's newer edition must not be borrowed.
          { family: "baseline", fiscal_year: 2028 },
        ],
      }),
    });

    expect(screen.getByTestId("book-state").textContent).toBe(
      "Every edition through FY 2027 is here.",
    );
    expect(screen.queryByTestId("missing-edition")).toBeNull();

    // Asserted TWICE against different data, so a year written into the
    // sentence cannot satisfy it. This card is read every January, in the
    // week the number changes.
    first.unmount();
    renderPanel({
      check: check({ missing: [], present: [{ family: "approps", fiscal_year: 2031 }] }),
    });
    expect(screen.getByTestId("book-state").textContent).toBe(
      "Every edition through FY 2031 is here.",
    );
  });

  it("says what is missing, in the same first line, when something is", () => {
    // The answer is an answer in both directions. One missing edition names
    // its year; several report a count, because the list right underneath
    // names them all anyway.
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });
    expect(screen.getByTestId("book-state").textContent).toBe("FY 2027 is missing.");
  });

  it("counts several missing editions rather than listing them twice", () => {
    renderPanel({
      check: check({
        missing: [FY2027_APPROPS, { ...FY2027_APPROPS, fiscal_year: 2026 }],
      }),
    });
    expect(screen.getByTestId("book-state").textContent).toBe("2 editions are missing.");
  });

  it("puts the answer FIRST and the explanation behind a row", () => {
    // The measured defect this reorder fixed: opening the card used to put
    // the answer FOURTH, 54 words in, behind the publisher line and four
    // lines of chunking rationale. Asserting document order rather than mere
    // presence is what pins that — every piece was "present" before too.
    renderPanel({
      check: check({ missing: [], present: [{ family: "approps", fiscal_year: 2027 }] }),
    });

    const panel = screen.getByTestId("book-panel");
    const state = screen.getByTestId("book-state");
    expect(panel.firstElementChild).toBe(state);
    // Node.DOCUMENT_POSITION_FOLLOWING === 4: every disclosure comes after it.
    for (const section of ["book-older", "book-about"] as const) {
      expect(state.compareDocumentPosition(screen.getByTestId(section)) & 4).toBe(4);
    }
    // And the registry prose is inside a section, not loose in the body.
    expect(
      screen.getByText("Stored as one document per agency.").closest("details"),
    ).toBe(screen.getByTestId("book-about"));
  });

  it("keeps an edition to add OUT of a disclosure", () => {
    // Outstanding work is the one thing this card exists for. Filing it
    // behind a row you have to open would be the defect this change fixed,
    // arriving by the new structure's own door.
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });
    expect(screen.getByTestId("missing-edition").closest("details")).toBeNull();
  });

  it("states what is outstanding on each row, without opening it", () => {
    // The card is scannable: the counts sit on the closed rows.
    renderPanel({
      check: check({
        unavailable: [
          { family: "approps", fiscal_year: 1984, era_note: "Era note." },
          { family: "approps", fiscal_year: 1985, era_note: "Era note." },
        ],
      }),
    });

    expect(screen.getByTestId("book-older").getAttribute("open")).toBeNull();
    expect(within(screen.getByTestId("book-older")).getByText("2 can’t be added"))
      .toBeTruthy();
    expect(within(screen.getByTestId("book-about")).getByText("how it’s stored, timing"))
      .toBeTruthy();
  });

  it("says nothing about un-addable editions when there are none", () => {
    // An empty count on the row would be a claim about a number, and there
    // is no number. Silence is the honest state.
    renderPanel({ check: check({ unavailable: [] }) });
    expect(screen.getByTestId("book-older").textContent).not.toMatch(/can’t be added/);
  });

  it("shows an un-addable edition's reason and offers NO Add button", () => {
    // Spec T10: shown with its era_note, but not selectable. Asserting the
    // button is ABSENT, not merely disabled — a disabled button still says
    // "this is a thing you could do", and it is not.
    const note = "Whole book only — JLBC did not publish per-agency pages before FY2005.";
    renderPanel({
      check: check({
        unavailable: [{ family: "approps", fiscal_year: 1984, era_note: note }],
      }),
    });

    openSection("book-older");
    const row = screen.getByTestId("unavailable-edition");
    expect(row.textContent).toContain("FY 1984 Appropriations Report");
    expect(row.textContent).toContain(note);
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("says when azjlbc.gov could not be reached, rather than reporting no gap", () => {
    // A network failure must not read as "everything is already here" — a
    // confident wrong answer on the one panel whose job is saying what is
    // missing. This app is verified to cold-start with WiFi disconnected.
    renderPanel({
      check: check({
        online: false,
        reason: "Couldn't reach azjlbc.gov to check for new editions (OSError).",
        missing: [],
      }),
    });

    expect(screen.getByText(/Couldn't reach azjlbc\.gov/)).toBeTruthy();
    // No state line at all, in either direction. "Every edition ... is here"
    // would be the wrong answer; so would "nothing is missing".
    expect(screen.queryByTestId("book-state")).toBeNull();
  });

  it("surfaces the page's own check failure rather than saying nothing", () => {
    // The fetch belongs to the page now, so its error arrives as a prop. An
    // unexplained empty panel would read as "nothing to add".
    renderPanel({ check: null, checkError: "books missing: 500" });
    expect(screen.getByText("books missing: 500")).toBeTruthy();
  });

  it("says it is still checking before the answer arrives", () => {
    renderPanel({ check: null, checking: true });
    expect(screen.getByText(/Checking azjlbc\.gov/)).toBeTruthy();
  });

  it("says how stale the check is and can ask the page to look again", () => {
    const onRecheck = vi.fn();
    renderPanel({ onRecheck });
    expect(screen.getByText(/Checked azjlbc\.gov/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /check again/i }));

    expect(onRecheck).toHaveBeenCalled();
  });
});

describe("adding and previewing", () => {
  it("queues the whole book and reports what was skipped", async () => {
    const ingest = vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 137,
      skipped_existing: 2,
      unreachable: [],
      batch_id: "jlbc-approps-fy2027",
    } as never);
    const onQueued = vi.fn();
    const onRecheck = vi.fn();
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }), onQueued, onRecheck });

    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(ingest).toHaveBeenCalledWith("approps", 2027));
    expect(await screen.findByText(/Queued 137 documents/)).toBeTruthy();
    expect(screen.getByText(/2 were already here/)).toBeTruthy();
    expect(onQueued).toHaveBeenCalled();
    // The row above this panel shows a count off the same check, so adding a
    // book has to refresh the PAGE's copy, not a private one.
    expect(onRecheck).toHaveBeenCalled();
  });

  it("previews an edition without queuing anything", async () => {
    const discover = vi.spyOn(api, "discoverBook").mockResolvedValue({
      source: "probed",
      count: 139,
      documents: [],
      unreachable: [],
      notes: [],
    } as never);
    const ingest = vi.spyOn(api, "ingestBook");
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(await screen.findByTestId("book-plan")).toBeTruthy();
    expect(screen.getByText(/Found 139 documents/)).toBeTruthy();
    expect(discover).toHaveBeenCalledWith("approps", 2027);
    expect(ingest).not.toHaveBeenCalled();
  });

  it("surfaces the rolling-folder warning from the preview", async () => {
    const note =
      "Found under the rolling /budget/ directory — its contents are checked " +
      "against the requested year before anything is queued.";
    vi.spyOn(api, "discoverBook").mockResolvedValue({
      source: "probed",
      count: 139,
      documents: [],
      unreachable: [],
      notes: [note],
    } as never);
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(note)).toBeTruthy();
  });

  it("surfaces a discovery failure verbatim", async () => {
    // DiscoveryError's own sentence names the file a new URL pattern has to
    // be added to. Rewriting it here would throw that away.
    const detail =
      "No FY2028 approps book found on azjlbc.gov. If it has just been " +
      "published under a new URL pattern, it needs to be added to the " +
      "candidate list in ingest/book_discovery.py.";
    vi.spyOn(api, "discoverBook").mockRejectedValue(new Error(detail));
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(detail)).toBeTruthy();
  });

  it("keeps a by-hand path for a year the automatic check missed", async () => {
    // Spec T10: "a specific year can still be requested", reaching the probe
    // ladder directly. The family picker this used to carry is gone — the
    // row IS the family — so the by-hand path must send THIS row's family
    // and not whatever a stray select happened to hold.
    const ingest = vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 5,
      skipped_existing: 0,
      unreachable: [],
      batch_id: "jlbc-baseline-fy2014",
    } as never);
    renderPanel({
      family: "baseline",
      label: "Baseline Book",
      check: check({ missing: [] }),
    });

    openSection("book-older");
    fireEvent.click(screen.getByRole("button", { name: /add a specific year/i }));
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2014" } });
    fireEvent.click(within(screen.getByTestId("manual-edition")).getByRole("button"));

    await waitFor(() => expect(ingest).toHaveBeenCalledWith("baseline", 2014));
  });

  it("states the overnight cost without softening it", () => {
    // Moved into About this book, not softened and not dropped: an analyst
    // who expects a book in five minutes concludes the app is broken. The
    // public-record clause travels with it — it is why this panel has no
    // Invariant 8 checkbox, which is the spec below.
    renderPanel();
    const about = openSection("book-about");
    expect(
      within(about).getByText(/A full book takes overnight on office computers/),
    ).toBeTruthy();
    expect(within(about).getByText(/Public record, so no confirmation is needed/))
      .toBeTruthy();
  });

  it("has no Invariant 8 checkbox — JLBC reports are public record", () => {
    renderPanel({ check: check({ missing: [FY2027_APPROPS] }) });
    expect(screen.getByTestId("missing-edition")).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
