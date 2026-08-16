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
// gone and this panel now renders inside ONE document-type card, for ONE
// book family. The added specs are about that scoping — a Baseline Book
// card offering an Appropriations Report would be exactly the noise T10
// removed, arriving by a new route.
//
// jsdom applies no stylesheet, so nothing here says anything about how the
// panel looks — including whether the "can't be added" rows read as greyed.

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

/** The Appropriations Report card's panel — the family every test below
 *  uses unless it is specifically about scoping. `label` is the document
 *  type's own label, which is what an edition gets named with. */
function renderApprops(onQueued: () => void = () => {}) {
  return render(
    <BookFamilyPanel
      family="approps"
      label="Appropriations Report"
      detail="Stored as one document per agency."
      onQueued={onQueued}
    />,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("a book card offers only what its own family is missing", () => {
  it("offers an edition the corpus lacks", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    renderApprops();

    const row = await screen.findByTestId("missing-edition");
    expect(row.textContent).toContain("FY 2027 Appropriations Report");
    expect(row.textContent).toContain("not in your corpus");
    expect(within(row).getByRole("button", { name: "Add" })).toBeTruthy();
  });

  it("ignores the OTHER family's missing edition entirely", async () => {
    // The endpoint answers for both families in one round-trip (one fetch,
    // one 12-hour cache, two cards). Each card must show only its own — a
    // Baseline Book card offering an Appropriations Report is the same
    // class of noise T10 exists to remove.
    vi.spyOn(api, "booksMissing").mockResolvedValue(
      check({ missing: [FY2027_APPROPS, FY2028_BASELINE] }),
    );
    renderApprops();

    const rows = await screen.findAllByTestId("missing-edition");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("FY 2027");
    expect(document.body.textContent).not.toContain("FY 2028");
  });

  it("ignores the other family's UN-addable editions too", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(
      check({
        unavailable: [
          { family: "baseline", fiscal_year: 2006, era_note: "Baseline era note." },
          { family: "approps", fiscal_year: 1984, era_note: "Approps era note." },
        ],
      }),
    );
    renderApprops();

    const rows = await screen.findAllByTestId("unavailable-edition");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("FY 1984");
    expect(screen.getByText(/1 older editions/)).toBeTruthy();
  });

  it("names an edition with the card's OWN label, not a name of its own", async () => {
    // The panel is handed `label` rather than mapping family -> words here,
    // so an edition is named with the same words as the card it sits in,
    // from one source (the registry).
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2028_BASELINE] }));
    render(
      <BookFamilyPanel
        family="baseline"
        label="Baseline Book"
        detail="Stored as one document per agency."
        onQueued={() => {}}
      />,
    );

    const row = await screen.findByTestId("missing-edition");
    expect(row.textContent).toContain("FY 2028 Baseline Book");
    expect(row.textContent).toContain("110 documents");
  });

  it("renders the registry's own explanation of why this type is fetched", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check());
    renderApprops();
    expect(await screen.findByText("Stored as one document per agency.")).toBeTruthy();
  });

  it("says so plainly when there is nothing to add", async () => {
    // The state the live corpus is in for every edition but one. The old
    // panel showed 62 rows here and gave no way to tell.
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [] }));
    renderApprops();

    expect(
      await screen.findByText("Every published Appropriations Report is already here."),
    ).toBeTruthy();
    expect(screen.queryByTestId("missing-edition")).toBeNull();
  });

  it("shows an un-addable edition's reason and offers NO Add button", async () => {
    // Spec T10: shown with its era_note, but not selectable. Asserting the
    // button is ABSENT, not merely disabled — a disabled button still says
    // "this is a thing you could do", and it is not.
    const note = "Whole book only — JLBC did not publish per-agency pages before FY2005.";
    vi.spyOn(api, "booksMissing").mockResolvedValue(
      check({ unavailable: [{ family: "approps", fiscal_year: 1984, era_note: note }] }),
    );
    renderApprops();

    const row = await screen.findByTestId("unavailable-edition");
    expect(row.textContent).toContain("FY 1984 Appropriations Report");
    expect(row.textContent).toContain(note);
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("says when azjlbc.gov could not be reached, rather than reporting no gap", async () => {
    // A network failure must not read as "everything is already here" — a
    // confident wrong answer on the one panel whose job is saying what is
    // missing. This app is verified to cold-start with WiFi disconnected.
    vi.spyOn(api, "booksMissing").mockResolvedValue(
      check({
        online: false,
        reason: "Couldn't reach azjlbc.gov to check for new editions (OSError).",
        missing: [],
      }),
    );
    renderApprops();

    expect(await screen.findByText(/Couldn't reach azjlbc\.gov/)).toBeTruthy();
    expect(
      screen.queryByText("Every published Appropriations Report is already here."),
    ).toBeNull();
  });

  it("says how stale the check is and can look again", async () => {
    const load = vi.spyOn(api, "booksMissing").mockResolvedValue(check());
    renderApprops();
    await screen.findByText(/Checked azjlbc\.gov/);

    fireEvent.click(screen.getByRole("button", { name: /check again/i }));

    await waitFor(() => expect(load).toHaveBeenCalledWith(true));
  });
});

describe("adding and previewing", () => {
  it("queues the whole book and reports what was skipped", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    const ingest = vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 137,
      skipped_existing: 2,
      unreachable: [],
      batch_id: "jlbc-approps-fy2027",
    } as never);
    const onQueued = vi.fn();
    renderApprops(onQueued);

    fireEvent.click(await screen.findByRole("button", { name: "Add" }));

    await waitFor(() => expect(ingest).toHaveBeenCalledWith("approps", 2027));
    expect(await screen.findByText(/Queued 137 documents/)).toBeTruthy();
    expect(screen.getByText(/2 were already here/)).toBeTruthy();
    expect(onQueued).toHaveBeenCalled();
  });

  it("previews an edition without queuing anything", async () => {
    // The old panel's "Discover", kept when the panel was inverted: it is
    // what found the FY2027 Appropriations Report (139 documents, 0
    // unreachable) and the only way to see an edition's warnings before
    // committing to an overnight run.
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    const discover = vi.spyOn(api, "discoverBook").mockResolvedValue({
      source: "probed",
      count: 139,
      documents: [],
      unreachable: [],
      notes: [],
    } as never);
    const ingest = vi.spyOn(api, "ingestBook");
    renderApprops();

    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));

    expect(await screen.findByTestId("book-plan")).toBeTruthy();
    expect(screen.getByText(/Found 139 documents/)).toBeTruthy();
    expect(discover).toHaveBeenCalledWith("approps", 2027);
    expect(ingest).not.toHaveBeenCalled();
  });

  it("surfaces the rolling-folder warning from the preview", async () => {
    const note =
      "Found under the rolling /budget/ directory — its contents are checked " +
      "against the requested year before anything is queued.";
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    vi.spyOn(api, "discoverBook").mockResolvedValue({
      source: "probed",
      count: 139,
      documents: [],
      unreachable: [],
      notes: [note],
    } as never);
    renderApprops();

    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText(note)).toBeTruthy();
  });

  it("surfaces a discovery failure verbatim", async () => {
    // DiscoveryError's own sentence names the file a new URL pattern has to
    // be added to. Rewriting it here would throw that away.
    const detail =
      "No FY2028 approps book found on azjlbc.gov. If it has just been " +
      "published under a new URL pattern, it needs to be added to the " +
      "candidate list in ingest/book_discovery.py.";
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    vi.spyOn(api, "discoverBook").mockRejectedValue(new Error(detail));
    renderApprops();

    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText(detail)).toBeTruthy();
  });

  it("keeps a by-hand path for a year the automatic check missed", async () => {
    // Spec T10: "a specific year can still be requested", reaching the probe
    // ladder directly. The family picker this used to carry is gone — the
    // card IS the family — so the by-hand path must send THIS card's family
    // and not whatever a stray select happened to hold.
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [] }));
    const ingest = vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 5,
      skipped_existing: 0,
      unreachable: [],
      batch_id: "jlbc-baseline-fy2014",
    } as never);
    render(
      <BookFamilyPanel
        family="baseline"
        label="Baseline Book"
        detail="Stored as one document per agency."
        onQueued={() => {}}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /add a specific year/i }));
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2014" } });
    fireEvent.click(within(screen.getByTestId("manual-edition")).getByRole("button"));

    await waitFor(() => expect(ingest).toHaveBeenCalledWith("baseline", 2014));
  });

  it("states the overnight cost without softening it", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check());
    renderApprops();
    expect(
      await screen.findByText(/A full book takes overnight on office computers/),
    ).toBeTruthy();
  });

  it("has no Invariant 8 checkbox — JLBC reports are public record", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    renderApprops();
    await screen.findByTestId("missing-edition");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
