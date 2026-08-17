import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../../api";
import { ReportLinkRow } from "./ReportLinkRow";

// The admin's side of the "Full report" button, now a row inside the book card
// on /upload rather than a panel on /admin. These specs MOVED with it
// (2026-08-16) from `webapp/src/admin/ReportLinksPanel.test.tsx`, which is
// deleted — every property below was already pinned there and none was dropped.
//
// What they protect, in rough order of what it costs to get them wrong:
//
//  1. 🔴 A wrong-YEAR address is the one defect a 200 OK cannot detect — a
//     live, downloadable, wrong report behind a button labelled "Full report".
//     The server flags it and never refuses it, so the warning here is the
//     entire mitigation, on the candidate AND on what the save reports back.
//  2. 🔴 The row must show only ITS OWN family. `family` here is a SLUG
//     ("approps") and the table is keyed on a LABEL ("Appropriations Report");
//     filtering the wrong one matches NOTHING and the row reports a clean
//     sweep for a family with editions waiting.
//  3. "The host never answered" and "the host said 404" send an admin to two
//     different places. Collapsing them has somebody editing a correct address
//     while the network is down.
//  4. A size of `null` renders as nothing. "0 MB" beside a 600-page book is an
//     invented fact that reads as a broken link.
//  5. Offline still lists every edition that needs a link. Telling an offline
//     admin that fewer books need attention than really do is worse than
//     telling them nothing.
//  6. The "Already answered" list stays reachable on an ordinary day — it is
//     the only in-app repair for a link approved wrongly, and approving a wrong
//     link is exactly what makes everything else here look healthy. The admin
//     panel bought that with a deliberate deviation from spec R7 (a collapsed
//     line that never disappeared); the move buys it for free, because the book
//     card is permanently on /upload.
//
// jsdom applies no stylesheet, so nothing here says anything about how the row
// LOOKS — including whether the amber `is-need` state reads as amber.
//
// Several specs open the section before asserting. A `<details>` keeps its
// children in the DOM when closed, so a `getByTestId` that did not open it
// first would pass for content no reader can see.

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

/** Renders the row and opens it, which is what every spec about its CONTENTS
 *  needs first. `findByTestId` because the row's own fetch has to land before
 *  there is anything inside to assert about. */
async function open(family = "approps") {
  const out = render(<ReportLinkRow family={family} />);
  const details = await screen.findByTestId("report-links");
  fireEvent.click(details.querySelector("summary")!);
  expect(details.getAttribute("open")).not.toBeNull();
  return { ...out, details };
}

function openSection(testId: string) {
  const details = screen.getByTestId(testId);
  fireEvent.click(details.querySelector("summary")!);
  expect(details.getAttribute("open")).not.toBeNull();
  return details;
}

afterEach(() => vi.restoreAllMocks());

// --- the vocabulary trap -----------------------------------------------------

test("the slug->label map is the SERVER's, read off the server's own file", () => {
  // 🔴 `family` on the upload page is the slug the registry uses ("approps");
  // GET /api/admin/book-formats reports each edition's family as the DISPLAY
  // LABEL ("Appropriations Report"). Filtering on the wrong vocabulary matches
  // nothing and the row says "0 editions" for a family with editions waiting —
  // a confident wrong answer with no error anywhere.
  //
  // Read out of `app/routes/books_missing.py` at test time rather than
  // duplicated here, the same anti-drift idiom `tool-display.test.ts` uses
  // against `harness/tools.py`. A rename on the server side fails HERE rather
  // than in front of an administrator.
  const src = readFileSync(
    resolve(__dirname, "../../../../app/routes/books_missing.py"),
    "utf8",
  );
  const line = /FAMILY_LABELS\s*=\s*\{([^}]*)\}/.exec(src);
  expect(line).not.toBeNull();
  const pairs = Object.fromEntries(
    [...line![1].matchAll(/"([a-z]+)"\s*:\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]),
  );
  expect(pairs).toEqual({ approps: "Appropriations Report", baseline: "Baseline" });
});

test("a Baseline card never lists an Appropriations Report edition", async () => {
  // Verified by execution, not by reading the filter: the two families share
  // one round-trip, so a card showing the other one's work is exactly the
  // noise spec T10 removed, arriving by a new route.
  stub({
    pending: [
      PENDING,
      { family: "Baseline", fiscal_year: 2029, candidates: { single_file: null, linked_toc: null } },
    ],
    approved: [APPROVED],
  });
  await open("baseline");

  const cards = screen.getAllByTestId("report-links-pending-card");
  expect(cards).toHaveLength(1);
  // The Baseline edition's own address line is the one on screen.
  expect(screen.getByTestId("report-links").textContent).not.toContain("28ar");
  // And the other family's ANSWERED edition is not in this card's list either.
  expect(screen.queryByTestId("report-links-approved-row")).toBeNull();
  expect(screen.getByText(/FY 2029 needs one/)).toBeTruthy();
});

test("the approps card shows the approps edition, from the same one round-trip", async () => {
  // The other half of the spec above. Together they prove the filter is doing
  // work rather than emptying the list: same fixture, two families, each card
  // showing exactly its own.
  stub({
    pending: [
      PENDING,
      { family: "Baseline", fiscal_year: 2029, candidates: { single_file: null, linked_toc: null } },
    ],
  });
  await open("approps");

  expect(screen.getAllByTestId("report-links-pending-card")).toHaveLength(1);
  expect(screen.getByText(/FY 2028 needs one/)).toBeTruthy();
});

// --- what the collapsed row says --------------------------------------------

test("a waiting edition is named on the row, before anything is opened", async () => {
  // The whole reason the row carries a right-hand status: the card can be
  // scanned without opening it. Asserted against the SUMMARY, which is what is
  // on screen with nothing clicked.
  stub();
  render(<ReportLinkRow family="approps" />);
  const details = await screen.findByTestId("report-links");
  await waitFor(() =>
    expect(details.querySelector("summary")!.textContent).toMatch(/FY 2028 needs one/),
  );
  expect(details.className).toContain("is-need");
});

test("an ordinary day states how many editions are set, and is NOT amber", async () => {
  // `is-need` is the only colour in this card's body. Spending it on a row
  // with nothing to do is how an admin learns to ignore it.
  stub({ pending: [], approved: [APPROVED, { ...APPROVED, fiscal_year: 2025 }] });
  render(<ReportLinkRow family="approps" />);
  const details = await screen.findByTestId("report-links");
  // The count is read off `approved`, not a constant and not the committed
  // table's 39 — an overlay the admin has added to is a different number.
  await waitFor(() =>
    expect(details.querySelector("summary")!.textContent).toMatch(/2 editions set/),
  );
  expect(details.className).not.toContain("is-need");
  // Collapsed: the correction list is behind a closed disclosure, not on the
  // page. (`<details>` keeps its children in the DOM, so the assertion is
  // about `open`, not about presence.)
  expect(details.getAttribute("open")).toBeNull();
});

test("with nothing waiting and nothing answered the row claims nothing", async () => {
  // Silence rather than "0 editions set", which would be a claim that the app
  // looked and found none — and this row cannot tell that apart from a family
  // nobody has ever answered.
  stub({ pending: [], approved: [] });
  render(<ReportLinkRow family="approps" />);
  const details = await screen.findByTestId("report-links");
  await waitFor(() => expect(screen.queryByTestId("report-links-loading")).toBeNull());
  expect(details.querySelector("summary")!.textContent).toBe("Full report link");
  expect(details.className).not.toContain("is-need");
});

test("more than one waiting edition is counted rather than named", async () => {
  stub({
    pending: [PENDING, { ...PENDING, fiscal_year: 2029 }],
  });
  render(<ReportLinkRow family="approps" />);
  const details = await screen.findByTestId("report-links");
  await waitFor(() =>
    expect(details.querySelector("summary")!.textContent).toMatch(/2 editions need one/),
  );
});

// --- the correction path ----------------------------------------------------

test("the row opens onto the same correction editor on an ordinary day", async () => {
  // 🔴 THE RECOVERY PATH. Approving an edition with the wrong year's URL pasted
  // in — one that names the right two digits, so nothing flags it — leaves
  // everything looking healthy. On /admin that made the panel VANISH on the
  // same click, taking the only correction editor with it, and spec R7 had to
  // be deviated from to keep one collapsed line on screen. The move to the book
  // card resolves that: this row is on /upload every day whether or not
  // anything is waiting.
  stub({ pending: [], approved: [APPROVED] });
  await open();
  openSection("report-links-approved");
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));

  const editor = screen.getByTestId("report-links-edit");
  expect(within(editor).getByTestId("report-links-format-single_file")).toBeInTheDocument();
  expect(within(editor).getByTestId("report-links-approve-correction")).toBeInTheDocument();
});

test("an already-answered edition can be reopened and corrected", async () => {
  // Without this, approving a wrong link is unfixable from the app and the
  // admin is back to hand-editing JSON on the share — the exact step this
  // feature exists to remove.
  stub({ approved: [APPROVED] });
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  await open();
  openSection("report-links-approved");
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
  stub({ approved: [{ ...APPROVED, single_file: null }] });
  await open();
  openSection("report-links-approved");
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));
  const editor = screen.getByTestId("report-links-edit");
  expect(within(editor).getByTestId("report-links-single_file-none")).toHaveTextContent(
    /never published/i,
  );
});

// --- the three facts about an address ---------------------------------------

test("a waiting edition shows both addresses as openable links", async () => {
  stub();
  await open();
  const links = screen.getAllByRole("link", { name: /^open$/i });
  expect(links[0]).toHaveAttribute("href", SINGLE_URL);
  expect(links[0]).toHaveAttribute("target", "_blank");
  expect(links[0]).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(links[1]).toHaveAttribute("href", TOC_URL);
});

test("the address is shown by filename, with the whole address one click away", async () => {
  // The scheme and host are identical on all 72 of these and identify nothing;
  // the directory and filename are what say which edition and which format.
  // The full address is never HIDDEN — it is the link's href and the line's
  // title — so this shortens what is read, not what is available.
  stub();
  await open();
  const shown = screen.getByTestId("report-links-single_file-url");
  expect(shown).toHaveTextContent("28ar/fy2028approprpt.pdf");
  expect(shown).not.toHaveTextContent("azjlbc.gov");
  expect(shown).toHaveAttribute("title", SINGLE_URL);
});

test("the file size is shown, because it is half of R9's defence", async () => {
  // The other half is the year warning. Between them they are the only thing
  // catching an admin who approves without opening either link — a 0.2 MB
  // "book" or a 47 MB "contents page" is visibly wrong. A size that silently
  // never renders would leave that risk unmitigated with every test green, so
  // it is asserted rather than assumed.
  stub();
  await open();
  expect(screen.getByTestId("report-links-single_file-size")).toHaveTextContent("47.0 MB");
});

test("a server that stated no size shows nothing, never 0 MB", async () => {
  // `bytes: null` is honest — some servers decline to state a size. An
  // invented "0.0 MB" beside a 600-page book reads as a broken link and would
  // send an admin off correcting an address that is perfectly fine.
  stub({ pending: [withSingleFile({ bytes: null })] });
  await open();
  expect(screen.getByTestId("report-links-single_file-address")).toBeInTheDocument();
  expect(screen.queryByTestId("report-links-single_file-size")).toBeNull();
  expect(screen.getByTestId("report-links").textContent).not.toMatch(/0\.0 MB/);
});

test("an address that does not name the edition's year is flagged", async () => {
  // 🔴 The rolling /budget/ address returns a live 200 for a year that does not
  // exist yet. This warning is the only thing standing between that and a
  // button opening the wrong year's report.
  stub();
  await open();
  expect(screen.getByTestId("report-links-linked_toc-year")).toHaveTextContent(
    /doesn’t mention FY 2028/i,
  );
  expect(screen.getByTestId("report-links-linked_toc-year")).toHaveTextContent(
    /open it before approving/i,
  );
  // And it is not painted over an address that DOES name its year.
  expect(screen.queryByTestId("report-links-single_file-year")).toBeNull();
});

test("a candidate the host refused is marked as not responding, with its number", async () => {
  // A dead address must not look identical to a good one before it is
  // approved. `plan_edition` returns catalogued URLs with no network call at
  // all, and that catalog is known to carry addresses that 404.
  stub({ pending: [withSingleFile({ status: 404, bytes: null })] });
  await open();
  expect(screen.getByTestId("report-links-single_file-dead")).toHaveTextContent(
    /didn't respond \(404\)/i,
  );
  expect(screen.queryByTestId("report-links-single_file-unreachable")).toBeNull();
});

test("a host that never answered reads differently from one that said 404", async () => {
  // Two different states, two different next steps: check the network, or
  // correct the address. Collapsing them has an admin editing a good address
  // while the WiFi is off.
  stub({ pending: [withSingleFile({ status: null, bytes: null })] });
  await open();
  const said = screen.getByTestId("report-links-single_file-unreachable");
  expect(said).toHaveTextContent(/didn't answer at all/i);
  expect(said).toHaveTextContent(/address itself may be fine/i);
  expect(screen.queryByTestId("report-links-single_file-dead")).toBeNull();
});

// --- approving --------------------------------------------------------------

test("approving sends both addresses and removes the card", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  await open();
  fireEvent.click(screen.getByTestId("report-links-approve"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith("Appropriations Report", 2028, SINGLE_URL, TOC_URL),
  );
  await waitFor(() => expect(screen.queryByTestId("report-links-pending-card")).toBeNull());
});

test("marking a format as never published sends null for it", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  await open();
  const row = screen.getByTestId("report-links-format-single_file");
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
  await open();
  for (const format of ["single_file", "linked_toc"]) {
    const row = screen.getByTestId(`report-links-format-${format}`);
    fireEvent.click(within(row).getByRole("button", { name: /none published/i }));
  }
  expect(screen.getByTestId("report-links-blocked")).toHaveTextContent(
    /at least one of the two formats needs a link/i,
  );
  expect(screen.getByTestId("report-links-approve")).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
});

test("an emptied address box blocks Approve instead of claiming JLBC published none", async () => {
  // 🔴 `urlFor` maps an empty typed box to `null`, and `null` on the wire is
  // the POSITIVE claim "JLBC published no such format" (spec R1). Reproduced
  // end to end: reopen an approved edition, clear the Whole book box, press
  // Approve — a good link deleted AND replaced by a claim about JLBC, on one
  // keystroke, with nothing on screen. `{typed, ""}` and `{none}` are different
  // intentions and must not collapse.
  stub({ approved: [APPROVED] });
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  await open();
  openSection("report-links-approved");
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));

  const editor = screen.getByTestId("report-links-edit");
  const single = within(editor).getByTestId("report-links-format-single_file");
  fireEvent.change(within(single).getByLabelText(/web address/i), { target: { value: "  " } });

  // Named in the words the row uses for it. The panel said "Single File PDF";
  // the row says "Whole book", and a warning naming a control that is not on
  // screen is a warning an admin cannot act on.
  expect(screen.getByTestId("report-links-blank")).toHaveTextContent(/Whole book/);
  // And it names the way to say "there isn't one", so the block is a route
  // forward rather than a dead end.
  expect(screen.getByTestId("report-links-blank")).toHaveTextContent(/none published/i);
  const approve = within(editor).getByTestId("report-links-approve-correction");
  expect(approve).toBeDisabled();
  fireEvent.click(approve);
  expect(save).not.toHaveBeenCalled();
});

test("Approve cannot be pressed twice while the first save is in flight", async () => {
  // One approval, one write. Without the busy guard a double click sends the
  // same PUT twice and the second lands on an edition the first already moved
  // out of the pending list.
  stub();
  let release!: (v: typeof CLEAN_SAVE) => void;
  const save = vi
    .spyOn(api, "saveBookFormat")
    .mockReturnValue(new Promise((r) => { release = r; }));
  await open();
  const approve = screen.getByTestId("report-links-approve");
  fireEvent.click(approve);
  await waitFor(() => expect(approve).toBeDisabled());
  fireEvent.click(approve);
  expect(save).toHaveBeenCalledTimes(1);
  release(CLEAN_SAVE);
  await waitFor(() => expect(screen.queryByTestId("report-links-pending-card")).toBeNull());
});

test("the save's own year check warns even when Check was never pressed", async () => {
  // 🔴 Defence in depth. Nothing forces an admin to press Check first, so the
  // whole R6 mitigation would otherwise rest on a step they can skip. The
  // route reports what it stored; this is the app repeating it back.
  stub({ pending: [withSingleFile({ names_its_year: true })] });
  vi.spyOn(api, "saveBookFormat").mockResolvedValue({
    ok: true,
    names_its_year: { single_file: false, linked_toc: true },
  });
  await open();
  fireEvent.click(screen.getByTestId("report-links-approve"));
  const warn = await screen.findByTestId("report-links-saved-warn");
  expect(warn).toHaveTextContent(/Whole book/);
  expect(warn).toHaveTextContent(/doesn’t mention FY 2028/i);
});

test("correcting a flagged edition clears its warning rather than stacking another", async () => {
  // The warnings used to be a list keyed on their own sentence: correcting the
  // same edition twice produced two identical rows under a DUPLICATE React
  // key, and a correction that FIXED the year left the old complaint on screen
  // forever — telling an admin a stored address is wrong when it no longer is.
  stub({ pending: [withSingleFile({ names_its_year: true })] });
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue({
    ok: true,
    names_its_year: { single_file: false, linked_toc: true },
  });
  await open();
  fireEvent.click(screen.getByTestId("report-links-approve"));
  expect(await screen.findByTestId("report-links-saved-warn")).toBeInTheDocument();

  // Now correct it, and let the save come back clean.
  save.mockResolvedValue(CLEAN_SAVE);
  openSection("report-links-approved");
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2028/i }));
  const editor = screen.getByTestId("report-links-edit");
  fireEvent.change(
    within(within(editor).getByTestId("report-links-format-single_file")).getByLabelText(
      /web address/i,
    ),
    { target: { value: "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf" } },
  );
  fireEvent.click(within(editor).getByTestId("report-links-approve-correction"));

  await waitFor(() => expect(screen.queryByTestId("report-links-saved-warn")).toBeNull());
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
  await open();
  fireEvent.click(screen.getByTestId("report-links-approve"));
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
  await open();
  fireEvent.click(screen.getByTestId("report-links-approve"));
  expect(await screen.findByTestId("report-links-save-error")).toHaveTextContent(/500/);
  expect(screen.getByTestId("report-links-pending-card")).toBeInTheDocument();
});

// --- a pasted replacement ---------------------------------------------------

// Named for what it asserts, not for a rule the app does not enforce. It used
// to be called "a typed replacement is checked before it can be approved" —
// NOTHING requires Check before Approve, and the save's own year echo (pinned
// above) is the real control. This repo has shipped four comments that
// measurement contradicted; a test NAME making a false claim about the system
// is the same defect wearing a green tick.
test("a typed replacement is described by the same three facts as an offered one", async () => {
  stub();
  const check = vi
    .spyOn(api, "checkBookFormatUrl")
    .mockResolvedValue({ ok: true, status: 200, bytes: 123_000, names_its_year: true, reason: null });
  await open();
  const row = screen.getByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /^change$/i }));
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
  await open();
  const row = screen.getByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /^change$/i }));
  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/budget/apprpttoc.pdf" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /^check$/i }));
  expect(
    await screen.findByTestId("report-links-single_file-checked-year"),
  ).toHaveTextContent(/doesn’t mention FY 2028/i);
});

test("editing the address throws away the verdict about the OLD one", async () => {
  // 🔴 Reproduced before this guard: check a good FY2028 address, then edit the
  // box to the rolling /budget/ one without pressing Check again. The card
  // showed the NEW address beside the OLD 47.0 MB size and NO year warning,
  // and Approve sent the new one. That is the wrong-year approval this whole
  // row exists to prevent, committed while the screen displays evidence
  // gathered about a different file.
  stub();
  vi.spyOn(api, "checkBookFormatUrl").mockResolvedValue({
    ok: true, status: 200, bytes: 47_000_000, names_its_year: true, reason: null,
  });
  await open();
  const row = screen.getByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /^change$/i }));
  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /^check$/i }));
  await screen.findByTestId("report-links-single_file-checked-size");

  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/budget/apprpttoc.pdf" },
  });
  // No verdict at all now — not a stale one shown beside a new address.
  expect(screen.queryByTestId("report-links-single_file-checked-size")).toBeNull();
  expect(screen.queryByTestId("report-links-single_file-checked-address")).toBeNull();
});

test("a checked address that failed is explained in the check route's own words", async () => {
  // The route already writes this sentence for this reader. Re-deriving it
  // here would give the office two wordings for one fact — the same
  // duplication `write_edition`'s docstring forbids for the 400.
  stub();
  vi.spyOn(api, "checkBookFormatUrl").mockResolvedValue({
    ok: false,
    status: 404,
    bytes: null,
    names_its_year: true,
    reason: "That address answered 404, so nothing would download.",
  });
  await open();
  const row = screen.getByTestId("report-links-format-single_file");
  fireEvent.click(within(row).getByRole("button", { name: /^change$/i }));
  fireEvent.change(within(row).getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/28ar/gone.pdf" },
  });
  fireEvent.click(within(row).getByRole("button", { name: /^check$/i }));
  expect(await screen.findByTestId("report-links-single_file-checked-dead")).toHaveTextContent(
    "That address answered 404, so nothing would download.",
  );
});

// --- degraded states --------------------------------------------------------

test("an offline check says so instead of showing an empty list", async () => {
  stub({
    pending: [],
    online: false,
    reason: "Couldn't reach azjlbc.gov to look up the links.",
  });
  await open();
  expect(screen.getByTestId("report-links-offline")).toHaveTextContent(
    /couldn't reach azjlbc\.gov/i,
  );
});

test("an offline check with no stated reason still explains itself", async () => {
  // Latent today — the route always writes a reason — but a null reason would
  // otherwise render as an empty warning: a row saying something is wrong and
  // declining to say what.
  stub({ pending: [], online: false, reason: null });
  await open();
  expect(screen.getByTestId("report-links-offline")).toHaveTextContent(
    /couldn’t reach azjlbc\.gov/i,
  );
});

test("an offline check still lists every edition that needs a link", async () => {
  // The route ships a FULL pending list when it is offline, with every
  // candidate null — which editions are unanswered needs no network at all.
  // Hiding the rows would tell an offline admin that fewer books need
  // attention than really do.
  stub({
    pending: [
      { family: "Appropriations Report", fiscal_year: 2028, candidates: { single_file: null, linked_toc: null } },
      { family: "Appropriations Report", fiscal_year: 2027, candidates: { single_file: null, linked_toc: null } },
    ],
    online: false,
    reason: "Couldn't reach azjlbc.gov to look up the links.",
  });
  await open();
  expect(screen.getAllByTestId("report-links-pending-card")).toHaveLength(2);
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
  await open();
  expect(screen.getByTestId("report-links-problem")).toHaveTextContent(
    /ignoring the saved links/i,
  );
});

test("a failed lookup says so on the row rather than reading as a clean sweep", async () => {
  // The row's whole job is saying what still needs a link. A fetch that failed
  // must not render as "nothing to do here", which is what an empty list would
  // look like.
  vi.spyOn(api, "bookFormats").mockRejectedValue(new Error("whole-report links: admin only"));
  render(<ReportLinkRow family="approps" />);
  const details = await screen.findByTestId("report-links");
  await waitFor(() =>
    expect(details.querySelector("summary")!.textContent).toMatch(/couldn’t check/),
  );
  fireEvent.click(details.querySelector("summary")!);
  expect(screen.getByTestId("report-links-error")).toHaveTextContent(/admin only/);
});

test("Look again asks the server to ignore its 12-hour cache", async () => {
  // Without this an edition published an hour after the last look is invisible
  // until tomorrow, with nothing on screen saying why.
  stub();
  await open();
  fireEvent.click(screen.getByRole("button", { name: /look again/i }));
  await waitFor(() => expect(api.bookFormats).toHaveBeenCalledWith(true));
});

test("'not now' closes the row without deciding anything", async () => {
  // From the approved mockup. After scrolling past two address lines the row's
  // own caret is off screen, so there is a way out beside the Approve button —
  // and it must not send anything, which is what tells it apart from the
  // "None published" answer sitting a few pixels away.
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue(CLEAN_SAVE);
  const { details } = await open();
  fireEvent.click(screen.getByRole("button", { name: /not now/i }));
  expect(details.getAttribute("open")).toBeNull();
  expect(save).not.toHaveBeenCalled();
});
