import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../api";
import { ReportLinksPanel } from "./ReportLinksPanel";

// The admin's side of the "Full report" button. What these specs protect, in
// rough order of what it costs to get them wrong:
//
//  1. A wrong-YEAR address is the one defect a 200 OK cannot detect — a live,
//     downloadable, wrong report behind a button labelled "Full report". The
//     server flags it and never refuses it, so the warning here is the entire
//     mitigation, on the candidate AND on what the save reports back.
//  2. "The host never answered" and "the host said 404" send an admin to two
//     different places. Collapsing them has somebody editing a correct address
//     while the network is down.
//  3. A size of `null` renders as nothing. "0 MB" beside a 600-page book is an
//     invented fact that reads as a broken link.
//  4. Offline still lists every edition that needs a link. Telling an offline
//     admin that fewer books need attention than really do is worse than
//     telling them nothing.
//  5. The panel is SILENT on a healthy install, however long the
//     already-answered list is.

const SINGLE_URL = "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf";
const TOC_URL = "https://www.azjlbc.gov/budget/apprpttoc.pdf";

const PENDING: api.PendingEdition = {
  family: "Appropriations Report",
  fiscal_year: 2028,
  candidates: {
    single_file: { url: SINGLE_URL, status: 200, bytes: 47_000_000, names_its_year: true },
    // Deliberately the real year-less address: the rolling /budget/ rung
    // returns a live 200 for a year that does not exist yet.
    linked_toc: { url: TOC_URL, status: 200, bytes: 200_000, names_its_year: false },
  },
  source: "probed",
};

const APPROVED: api.ApprovedEdition = {
  family: "Appropriations Report",
  fiscal_year: 2026,
  single_file: "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf",
  linked_toc: "https://www.azjlbc.gov/26ar/apprpttoc.pdf",
};

const CLEAN_SAVE = {
  ok: true,
  names_its_year: { single_file: true, linked_toc: true },
};

function stub(over: Partial<api.BookFormats> = {}) {
  vi.spyOn(api, "bookFormats").mockResolvedValue({
    pending: [PENDING],
    approved: [],
    online: true,
    reason: null,
    problems: [],
    ...over,
  });
}

/** One pending edition with one candidate replaced. */
function withSingleFile(over: Partial<api.BookFormatCandidate> | null): api.PendingEdition {
  return {
    ...PENDING,
    candidates: {
      ...PENDING.candidates,
      single_file: over === null ? null : { ...PENDING.candidates.single_file!, ...over },
    },
  };
}

afterEach(() => vi.restoreAllMocks());

test("renders nothing at all when no edition is waiting", async () => {
  // Same rule as NoticesPanel and NeedsAttention directly above it: a box on
  // screen every day teaches an admin to scroll past it. `approved` is
  // populated here on purpose — the already-answered list must not be what
  // keeps the panel on screen.
  stub({ pending: [], approved: [APPROVED] });
  const { container } = render(<ReportLinksPanel />);
  await waitFor(() => expect(api.bookFormats).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test("a waiting edition shows both addresses as openable links", async () => {
  stub();
  render(<ReportLinksPanel />);
  const links = await screen.findAllByRole("link", { name: /open to check/i });
  expect(links[0]).toHaveAttribute("href", SINGLE_URL);
  expect(links[0]).toHaveAttribute("target", "_blank");
  expect(links[0]).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(links[1]).toHaveAttribute("href", TOC_URL);
});

test("the file size is shown, because it is half of R9's defence", async () => {
  // The other half is the year warning. Between them they are the only thing
  // catching an admin who approves without opening either link — a 0.2 MB
  // "book" or a 47 MB "table of contents" is visibly wrong. A size that
  // silently never renders would leave that risk unmitigated with every test
  // green, so it is asserted rather than assumed.
  stub();
  render(<ReportLinksPanel />);
  expect(await screen.findByTestId("report-links-single_file-size")).toHaveTextContent(
    "47.0 MB",
  );
});

test("a server that stated no size shows nothing, never 0 MB", async () => {
  // `bytes: null` is honest — some servers decline to state a size. An
  // invented "0.0 MB" beside a 600-page book reads as a broken link and would
  // send an admin off correcting an address that is perfectly fine.
  stub({ pending: [withSingleFile({ bytes: null })] });
  render(<ReportLinksPanel />);
  await screen.findByTestId("report-links-single_file-address");
  expect(screen.queryByTestId("report-links-single_file-size")).toBeNull();
  expect(screen.getByTestId("admin-report-links").textContent).not.toMatch(/0\.0 MB/);
});

test("an address that does not name the edition's year is flagged", async () => {
  // The rolling /budget/ address returns a live 200 for a year that does not
  // exist yet. This warning is the only thing standing between that and a
  // button opening the wrong year's report.
  stub();
  render(<ReportLinksPanel />);
  expect(await screen.findByTestId("report-links-linked_toc-year")).toHaveTextContent(
    /doesn't mention FY 2028/i,
  );
  // And it is not painted over an address that DOES name its year.
  expect(screen.queryByTestId("report-links-single_file-year")).toBeNull();
});

test("a candidate the host refused is marked as not responding, with its number", async () => {
  // A dead address must not look identical to a good one before it is
  // approved. `plan_edition` returns catalogued URLs with no network call at
  // all, and that catalog is known to carry addresses that 404.
  stub({ pending: [withSingleFile({ status: 404, bytes: null })] });
  render(<ReportLinksPanel />);
  expect(await screen.findByTestId("report-links-single_file-dead")).toHaveTextContent(
    /didn't respond \(404\)/i,
  );
  expect(screen.queryByTestId("report-links-single_file-unreachable")).toBeNull();
});

test("a host that never answered reads differently from one that said 404", async () => {
  // Two different states, two different next steps: check the network, or
  // correct the address. Collapsing them has an admin editing a good address
  // while the WiFi is off.
  stub({ pending: [withSingleFile({ status: null, bytes: null })] });
  render(<ReportLinksPanel />);
  const said = await screen.findByTestId("report-links-single_file-unreachable");
  expect(said).toHaveTextContent(/didn't answer at all/i);
  expect(said).toHaveTextContent(/address itself may be fine/i);
  expect(screen.queryByTestId("report-links-single_file-dead")).toBeNull();
});

test("approving sends both addresses and removes the card", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByTestId("report-links-approve"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("Appropriations Report", 2028, SINGLE_URL, TOC_URL),
  );
  await waitFor(() => expect(screen.queryByTestId("report-links-pending-card")).toBeNull());
});

test("marking a format as never published sends null for it", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  render(<ReportLinksPanel />);
  const row = await screen.findByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /none published/i }));
  fireEvent.click(screen.getByTestId("report-links-approve"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("Appropriations Report", 2028, null, TOC_URL),
  );
});

test("approve is refused, with a reason on screen, when neither format has a link", async () => {
  // The server refuses this too — an entry with two nulls is indistinguishable
  // from no entry, so the edition would silently re-appear as unanswered
  // forever. A silently dead button reads as the page being broken.
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  render(<ReportLinksPanel />);
  for (const format of ["single_file", "linked_toc"]) {
    const row = await screen.findByTestId(`report-links-format-${format}`);
    fireEvent.click(within(row).getByRole("button", { name: /none published/i }));
  }
  expect(screen.getByTestId("report-links-blocked")).toHaveTextContent(
    /at least one of the two formats needs a link/i,
  );
  expect(screen.getByTestId("report-links-approve")).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
});

test("a typed replacement is checked before it can be approved", async () => {
  stub();
  const check = vi
    .spyOn(api, "checkBookFormatUrl")
    .mockResolvedValue({ ok: true, status: 200, bytes: 123_000, names_its_year: true, reason: null });
  render(<ReportLinksPanel />);
  const row = await screen.findByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /use a different link/i }));
  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/28ar/other.pdf" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /^check$/i }));
  await waitFor(() =>
    expect(check).toHaveBeenCalledWith("https://www.azjlbc.gov/28ar/other.pdf", 2028),
  );
  // The pasted address is described with the SAME three facts as an offered
  // one, so a hand-typed link is not judged by a weaker standard.
  expect(
    await screen.findByTestId("report-links-single_file-checked-size"),
  ).toHaveTextContent("0.1 MB");
});

test("a typed replacement that does not name the year is flagged too", async () => {
  stub();
  vi.spyOn(api, "checkBookFormatUrl").mockResolvedValue({
    ok: true, status: 200, bytes: 123_000, names_its_year: false, reason: null,
  });
  render(<ReportLinksPanel />);
  const row = await screen.findByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /use a different link/i }));
  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/budget/apprpttoc.pdf" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /^check$/i }));
  expect(
    await screen.findByTestId("report-links-single_file-checked-year"),
  ).toHaveTextContent(/doesn't mention FY 2028/i);
});

test("the save's own year check warns even when Check was never pressed", async () => {
  // Defence in depth. Nothing forces an admin to press Check first, so the
  // whole R6 mitigation would otherwise rest on a step they can skip. The
  // route reports what it stored; this is the app repeating it back.
  stub({ pending: [withSingleFile({ names_its_year: true })] });
  vi.spyOn(api, "saveBookFormat").mockResolvedValue({
    ok: true,
    names_its_year: { single_file: false, linked_toc: true },
  });
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByTestId("report-links-approve"));
  const warn = await screen.findByTestId("report-links-saved-warn");
  expect(warn).toHaveTextContent(/Single File PDF/);
  expect(warn).toHaveTextContent(/doesn't mention FY 2028/i);
});

test("a refusal from the server is shown in the server's own words", async () => {
  // The store writes that sentence for this reader. Rewriting it here would
  // give the office two wordings for one refusal.
  stub();
  vi.spyOn(api, "saveBookFormat").mockRejectedValue(
    new Error(
      "saving the whole-report links: At least one of the two formats must have a link.",
    ),
  );
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByTestId("report-links-approve"));
  expect(await screen.findByTestId("report-links-save-error")).toHaveTextContent(
    /at least one of the two formats must have a link/i,
  );
  // And the card stays: the approval did not stick, so it is still waiting.
  expect(screen.getByTestId("report-links-pending-card")).toBeInTheDocument();
});

test("a failed save is visible rather than silently doing nothing", async () => {
  stub();
  vi.spyOn(api, "saveBookFormat").mockRejectedValue(
    new Error("saving the whole-report links failed: 500"),
  );
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByTestId("report-links-approve"));
  expect(await screen.findByTestId("report-links-save-error")).toHaveTextContent(/500/);
  expect(screen.getByTestId("report-links-pending-card")).toBeInTheDocument();
});

test("an offline check says so instead of showing an empty list", async () => {
  stub({
    pending: [],
    online: false,
    reason: "Couldn't reach azjlbc.gov to look up the links.",
  });
  render(<ReportLinksPanel />);
  expect(await screen.findByTestId("report-links-offline")).toHaveTextContent(
    /couldn't reach azjlbc\.gov/i,
  );
});

test("an offline check still lists every edition that needs a link", async () => {
  // The route ships a FULL pending list when it is offline, with every
  // candidate null — which editions are unanswered needs no network at all.
  // Hiding the rows would tell an offline admin that fewer books need
  // attention than really do.
  stub({
    pending: [
      { family: "Appropriations Report", fiscal_year: 2028, candidates: { single_file: null, linked_toc: null }, source: null },
      { family: "Baseline", fiscal_year: 2028, candidates: { single_file: null, linked_toc: null }, source: null },
    ],
    online: false,
    reason: "Couldn't reach azjlbc.gov to look up the links.",
  });
  render(<ReportLinksPanel />);
  expect(await screen.findAllByTestId("report-links-pending-card")).toHaveLength(2);
  // And a row with no suggestion says so rather than showing an empty space.
  expect(
    screen.getAllByTestId("report-links-single_file-nothing-found")[0],
  ).toHaveTextContent(/no address for this one/i);
});

test("a problem with the saved file is shown to the admin", async () => {
  stub({
    pending: [],
    problems: ["Ignoring the saved links for Bogus:2028: unknown report family."],
  });
  render(<ReportLinksPanel />);
  expect(await screen.findByTestId("report-links-problem")).toHaveTextContent(
    /ignoring the saved links/i,
  );
});

test("Look again asks the server to ignore its 12-hour cache", async () => {
  // Without this an edition published an hour after the last look is invisible
  // until tomorrow, with nothing on screen saying why.
  stub();
  render(<ReportLinksPanel />);
  await screen.findByTestId("report-links-pending-card");
  fireEvent.click(screen.getByRole("button", { name: /look again/i }));
  await waitFor(() => expect(api.bookFormats).toHaveBeenCalledWith(true));
});

test("an already-answered edition can be reopened and corrected", async () => {
  // Without this, approving a wrong link is unfixable from the app and the
  // admin is back to hand-editing JSON on the share — the exact step this
  // feature exists to remove. It is deliberately behind a disclosure, so the
  // panel still renders nothing when nothing is waiting.
  stub({ approved: [APPROVED] });
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByRole("button", { name: /already answered/i }));
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));

  const editor = screen.getByTestId("report-links-edit");
  const single = within(editor).getByTestId("report-links-format-single_file");
  fireEvent.change(within(single).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/26ar/corrected.pdf" },
  });
  fireEvent.click(within(editor).getByTestId("report-links-approve-correction"));

  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "Appropriations Report",
      2026,
      "https://www.azjlbc.gov/26ar/corrected.pdf",
      // The format nobody touched keeps exactly what was stored — an overlay
      // entry replaces its key wholesale, so a correction that dropped the
      // other half would delete a good link.
      APPROVED.linked_toc,
    ),
  );
});

test("an approved edition stored as never-published reopens on that answer", async () => {
  // `null` means "JLBC published no such format" and an absent key means
  // "nobody has answered yet" — different states (spec R1). An editor that
  // reopened a null as an empty text box would invite an admin to think the
  // address had been lost.
  stub({
    approved: [{ ...APPROVED, single_file: null }],
  });
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByRole("button", { name: /already answered/i }));
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));
  const editor = screen.getByTestId("report-links-edit");
  expect(within(editor).getByTestId("report-links-single_file-none")).toHaveTextContent(
    /never published/i,
  );
});
