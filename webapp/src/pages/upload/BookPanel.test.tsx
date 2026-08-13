import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api";
import { BookPanel } from "./BookPanel";

// Spec T10: the panel answers "what has JLBC published that we don't have?"
//
// Measured before this change: 62 editions offered, **0** of them usefully
// addable. Every assertion below is about WHAT IS OFFERED, which is the
// entire point of the inversion.
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

afterEach(() => vi.restoreAllMocks());

describe("the Add-a-JLBC-book panel offers only what is missing", () => {
  it("offers an edition the corpus lacks", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    render(<BookPanel onQueued={() => {}} />);

    const row = await screen.findByTestId("missing-edition");
    expect(row.textContent).toContain("FY 2027 Appropriations Report");
    expect(row.textContent).toContain("not in your corpus");
    expect(within(row).getByRole("button", { name: "Add" })).toBeTruthy();
  });

  it("says so plainly when there is nothing to add", async () => {
    // The state the live corpus is in for every edition but one. The old
    // panel showed 62 rows here and gave no way to tell.
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [] }));
    render(<BookPanel onQueued={() => {}} />);

    expect(
      await screen.findByText("Everything else JLBC publishes is already here."),
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
    render(<BookPanel onQueued={() => {}} />);

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
    render(<BookPanel onQueued={() => {}} />);

    expect(await screen.findByText(/Couldn't reach azjlbc\.gov/)).toBeTruthy();
    expect(screen.queryByText("Everything else JLBC publishes is already here.")).toBeNull();
  });

  it("says how stale the check is and can look again", async () => {
    const load = vi.spyOn(api, "booksMissing").mockResolvedValue(check());
    render(<BookPanel onQueued={() => {}} />);
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
    render(<BookPanel onQueued={onQueued} />);

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
    render(<BookPanel onQueued={() => {}} />);

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
    render(<BookPanel onQueued={() => {}} />);

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
    render(<BookPanel onQueued={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText(detail)).toBeTruthy();
  });

  it("keeps a by-hand path for a year the automatic check missed", async () => {
    // Spec T10: "a specific year can still be requested", reaching the probe
    // ladder directly.
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [] }));
    const ingest = vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 5,
      skipped_existing: 0,
      unreachable: [],
      batch_id: "jlbc-baseline-fy2014",
    } as never);
    render(<BookPanel onQueued={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: /choose a specific year/i }));
    fireEvent.change(screen.getByLabelText("Book"), { target: { value: "baseline" } });
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2014" } });
    fireEvent.click(within(screen.getByTestId("manual-edition")).getByRole("button"));

    await waitFor(() => expect(ingest).toHaveBeenCalledWith("baseline", 2014));
  });

  it("states the overnight cost without softening it", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check());
    render(<BookPanel onQueued={() => {}} />);
    expect(
      await screen.findByText(/A full book takes overnight on office computers/),
    ).toBeTruthy();
  });

  it("has no Invariant 8 checkbox — JLBC reports are public record", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue(check({ missing: [FY2027_APPROPS] }));
    render(<BookPanel onQueued={() => {}} />);
    await screen.findByTestId("missing-edition");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
