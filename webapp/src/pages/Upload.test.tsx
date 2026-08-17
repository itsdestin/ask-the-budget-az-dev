import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { Upload, defaultFiscalYear } from "./Upload";

function job(over: Partial<api.Job> = {}): api.Job {
  return {
    job_id: "20260730T120000Z-abcd1234",
    doc_id: "jlbc-baseline-fy2027-axs",
    title: "FY 2027 Baseline — AHCCCS",
    corpus: "budget",
    state: "extracting",
    pct: 16,
    stage_detail: "page 34/210",
    error: null,
    machine: "JLBC-PC-4",
    user: "DMOSS",
    created_at: "2026-07-30T12:00:00+00:00",
    updated_at: "2026-07-30T12:05:00+00:00",
    ...over,
  };
}

function pdf(name = "27baseline-axs.pdf"): File {
  return new File([new Uint8Array([37, 80, 68, 70])], name, {
    type: "application/pdf",
  });
}

// The rows GET /api/document-types returns, per task-5-report.md's captured
// live shape. Real registry (data/document-types.yaml) has exactly two
// redirect rows (baseline-book, approps-report) and four file-accepting rows
// (afr, governors-budget, agency-submission, budget-bill-summary). This
// fixture carries three of the six; that's enough to exercise every branch
// (redirect / plain / staged) without the whole file re-deriving all six
// every time a row's copy changes upstream.
const ROWS: api.DocTypeCard[] = [
  { key: "baseline-book", label: "Baseline Book", group: "JLBC", formats: [".pdf"],
    where_published: "JLBC, each January.", which_file: "",
    redirect: { action: "add-jlbc-book", family: "baseline",
                detail: "Stored as one document per agency." },
    stage_field: false, agency_field: false, order: 10 },
  { key: "afr", label: "Annual Financial Report", group: "Auditor General",
    formats: [".pdf"], where_published: "Auditor General, gao.az.gov.",
    which_file: "The combined PDF.", redirect: null, stage_field: false, agency_field: false, order: 30 },
  { key: "budget-bill-summary", label: "Budget Bill Summary", group: "JLBC",
    formats: [".pdf"], where_published: "azjlbc.gov/budget/",
    which_file: "The House and Senate Budget Bills PDF.",
    redirect: null, stage_field: true, agency_field: false, order: 60 },
];

// The single row every OTHER describe block in this file selects and fills
// in (the old single-dropzone-era tests below assume exactly one type is
// ever relevant — see pickFile()). It's ROWS' own "afr" entry, not a fresh
// fixture, so the two can't quietly drift apart.
const DEFAULT_ROW = ROWS[1];

// The one row that asks which agency. Kept out of ROWS so the blocks above,
// which assume no row needs an agency, stay unambiguous.
const AGENCY_ROW: api.DocTypeCard = {
  key: "agency-row", label: "Agency Submission", group: "Agencies",
  formats: [".pdf"], where_published: "Each agency's own website.",
  which_file: "That agency's budget request.", redirect: null,
  stage_field: false, agency_field: true, order: 50,
};

const AGENCIES: api.AgencyOption[] = [
  { canonical_id: "agency:adc", name: "Department of Corrections", source: "catalog" },
  { canonical_id: "agency:des", name: "Department of Economic Security", source: "catalog" },
  { canonical_id: "agency:office-made-up", name: "Office of Made-Up Things", source: "office" },
];

/** Opens a document type's card by clicking its header. Every describe block
 *  below needs this first: the whole point of the accordion is that no form
 *  exists until a card is opened.
 *
 *  `findByRole("button", { name })` and not a class or a test id — the card
 *  head IS a disclosure button, and asserting through the accessible name is
 *  what keeps these specs pinned to behaviour rather than to whichever
 *  element the head happens to be built from this month (it has been six
 *  cards, then a radio row, then this). */
async function selectType(label: string | RegExp = /annual financial report/i) {
  const head = await screen.findByRole("button", { name: label });
  fireEvent.click(head);
  return head;
}

async function pickFile(file = pdf()) {
  await selectType();
  // findByLabelText, not getByLabelText: the type list itself arrives via an
  // async GET /api/document-types fetch, so the form isn't necessarily in
  // the DOM on the synchronous render this used to run against, and it
  // never exists at all before selectType() above runs.
  const input = (await screen.findByLabelText(/choose a pdf/i)) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByText(file.name);
}

beforeEach(() => {
  vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [], finished_count: 0, showing: "active" as const });
  // Default: exactly one plain (non-redirect, non-staged) row, so every test
  // written against the old single-form assumptions (one file input, one
  // "Fiscal year" field, one submit button) still resolves unambiguously.
  // The "the type picker and form" describe below overrides this with the
  // full fixture.
  vi.spyOn(api, "documentTypes").mockResolvedValue([DEFAULT_ROW]);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// --- Invariant 8 ------------------------------------------------------------

describe("the public-record notice", () => {
  it("states the rule with no interaction, and cannot be dismissed", () => {
    // 🔴 REWRITTEN 2026-08-15, and the rewrite is the point. This used to
    // assert the notice named all seven allowed document kinds — 20 words
    // restating the list of cards directly below it, inside an 87-word
    // block that was 40% of everything on the page before an analyst could
    // act. The list is gone; the six rows ARE the list.
    //
    // What Invariant 8 actually requires is that the RULE is unavoidable,
    // so that is what is asserted, and asserted against the <summary> —
    // the part that is on screen with nothing clicked. A `<details>` keeps
    // its body in the DOM when closed, so a document-wide `getByText` here
    // would pass whether or not the sentence were visible, which is a test
    // that proves nothing.
    render(<Upload />);
    const notice = screen.getByTestId("public-record-notice");
    const summary = notice.querySelector("summary")!;
    expect(summary.textContent).toMatch(/public record only/i);
    expect(summary.textContent).toMatch(/never confidential state data/i);
    // No dismiss: a notice you can close is a notice that gets closed.
    expect(within(notice).queryByRole("button")).toBeNull();
  });

  it("uses the SAME disclosure caret as the document-type rows", () => {
    // One page, one disclosure pattern. The notice used to carry a small
    // sideways triangle plus the word "why?" while the rows below carried a
    // rotating chevron — two glyphs for one idea, on one screen. The word
    // is gone too: a caret on a notice is already understood, and "why?"
    // competed with the rule itself, which is the only thing on that line
    // anybody must read.
    render(<Upload />);
    const notice = screen.getByTestId("public-record-notice");
    const summary = notice.querySelector("summary")!;
    expect(summary.querySelector(".up-card-caret")).toBeTruthy();
    expect(summary.textContent).not.toMatch(/why/i);
  });

  it("keeps the AI-provider and shared-drive warning on the page, one click away", () => {
    // Demoted, not deleted. This is the sentence that explains WHY the rule
    // exists, and it is read once and skipped for ever after — so it sits
    // behind the disclosure rather than above the work. Asserted to be in
    // the notice's BODY and NOT its summary, which is exactly the split.
    render(<Upload />);
    const notice = screen.getByTestId("public-record-notice");
    const summary = notice.querySelector("summary")!;
    const body = notice.textContent!.replace(summary.textContent!, "");
    expect(body).toMatch(/outside AI provider/i);
    expect(body).toMatch(/shared drive/i);
  });

  it("keeps the submit button disabled until the checkbox is ticked", async () => {
    render(<Upload />);
    await pickFile();
    const button = screen.getByRole("button", { name: /add document/i });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    expect(button).toBeEnabled();
  });
});

// --- the type picker itself --------------------------------------------------

describe("the type cards", () => {
  it("shows no form at all before a card is opened", async () => {
    render(<Upload />);
    await screen.findByRole("button", { name: /annual financial report/i });
    expect(screen.queryByLabelText("Fiscal year")).toBeNull();
    expect(screen.queryByLabelText(/choose a pdf/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /add document/i })).toBeNull();
  });

  it("shows the form for the opened card as soon as it's opened, before any file", async () => {
    // Carried through three shapes now (six open cards, a radio list, this
    // accordion) because the property is what matters, not the widget: the
    // analyst needs to see "does this type want a stage?" before hunting for
    // a file, not after choosing one.
    render(<Upload />);
    await selectType();
    expect(await screen.findByLabelText("Fiscal year")).toBeTruthy();
  });

  it("reports its open/closed state where a screen reader can hear it", async () => {
    // aria-expanded, not a class: this is the one signal a keyboard or
    // screen-reader user has for whether the thing they just pressed did
    // anything, and jsdom can see it where it cannot see the caret rotate.
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
    render(<Upload />);
    const head = await screen.findByRole("button", { name: /annual financial report/i });
    expect(head.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(head);
    expect(head.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes the card that was open when another is opened", async () => {
    // "One at a time" is the property that kept this rework from re-earning
    // the original complaint about six simultaneous upload forms. Asserted
    // as ONE Add button in the whole document, which is the thing that
    // actually goes wrong if this breaks.
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
    render(<Upload />);
    await selectType(/annual financial report/i);
    await selectType(/budget bill summary/i);

    expect(
      screen.getByRole("button", { name: /annual financial report/i })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.getAllByRole("button", { name: /add document/i })).toHaveLength(1);
    expect(screen.getAllByLabelText(/choose a pdf/i)).toHaveLength(1);
  });

  it("closes an open card when its own head is pressed again", async () => {
    // A radio could never be un-picked, so the old picker had no way back to
    // "nothing open". The head is a toggle.
    render(<Upload />);
    await selectType();
    expect(screen.getByLabelText("Fiscal year")).toBeTruthy();
    await selectType();
    expect(screen.queryByLabelText("Fiscal year")).toBeNull();
  });

  it("leaves every other card listed and reachable while one is open", async () => {
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
    render(<Upload />);
    await selectType(/annual financial report/i);
    expect(screen.getAllByTestId("doc-type-card")).toHaveLength(ROWS.length);
    expect(screen.getByRole("button", { name: /baseline book/i })).toBeTruthy();
  });
});

// --- metadata form ----------------------------------------------------------

describe("the metadata form", () => {
  it("pre-fills from filename heuristics", async () => {
    render(<Upload />);
    await pickFile(pdf("FY2026-approps.pdf"));
    expect((screen.getByLabelText("Fiscal year") as HTMLInputElement).value)
      .toBe("2026");
  });

  it("reads JLBC's own two-digit naming convention", () => {
    expect(defaultFiscalYear("27baseline-axs.pdf")).toBe(2027);
    expect(defaultFiscalYear("25ar-axs.pdf")).toBe(2025);
  });

  it("states the honest processing time", async () => {
    render(<Upload />);
    expect(await screen.findByText(/searchable within the hour/i)).toBeTruthy();
    expect(screen.getByText(/progress survives restarts/i)).toBeTruthy();
  });
});

// --- submitting -------------------------------------------------------------

describe("submitting", () => {
  it("posts the file with its metadata and reports success", async () => {
    const upload = vi.spyOn(api, "uploadDocument").mockResolvedValue({
      job_id: "j1", doc_id: "d1",
    });
    render(<Upload />);
    await pickFile(pdf("AFR25 COMBINED.pdf"));
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    await waitFor(() => expect(upload).toHaveBeenCalled());
    const [file, meta] = upload.mock.calls[0];
    expect(file.name).toBe("AFR25 COMBINED.pdf");
    expect(meta).toMatchObject({
      corpus: "budget", doc_type: "afr",
    });
    // The client used to post a hand-maintained `publisher` guess
    // (ROW_PUBLISHERS's `?? "jlbc"` fallback) that a seventh registry row
    // could silently get wrong. The server derives publisher from the
    // doc_type's registry row instead, so the client must send NOTHING for
    // it — sending even a correct-looking value here would be the same
    // hand-maintained-copy shape the fix removed.
    expect(meta).not.toHaveProperty("publisher");
    const confirmation = await screen.findByText(/AFR25 COMBINED\.pdf added to the queue\./i);
    expect(confirmation.getAttribute("role")).toBe("status");
  });

  it("shows the success confirmation inside the one form on the page", async () => {
    // With six independent cards this used to need to prove the message was
    // scoped to the submitting ROW, since a page-level message couldn't say
    // which of six had succeeded. There's only one form now, so that
    // specific hazard is gone by construction — this instead pins the
    // confirmation to the form region (not floating somewhere else on the
    // page), and the "switching the selected type" spec below covers the
    // hazard the rework actually introduces: the message surviving a switch
    // to a DIFFERENT type.
    vi.spyOn(api, "uploadDocument").mockResolvedValue({ job_id: "j", doc_id: "d" });
    render(<Upload />);
    await pickFile(pdf("agao-afr-fy2025.pdf"));
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    const form = await screen.findByTestId("upload-form");
    expect(within(form).getByText(/added to the queue/i)).toBeTruthy();
  });

  it("clears a stale success message once a fresh attempt starts for the same type", async () => {
    // A success line left over from an EARLIER upload of this type must not
    // sit above a NEW attempt's result — otherwise a failing second upload
    // would read as if it, too, had succeeded. This is the "same type twice
    // in a row" case; a switch to a DIFFERENT type is covered separately
    // below, by a different mechanism (remount, not this reset).
    vi.spyOn(api, "uploadDocument")
      .mockResolvedValueOnce({ job_id: "j1", doc_id: "d1" })
      .mockRejectedValueOnce(new Error("upload: notes.txt is not a PDF or DOCX."));
    render(<Upload />);

    await pickFile(pdf("first.pdf"));
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await screen.findByText(/first\.pdf added to the queue\./i);

    const input = screen.getByLabelText(/choose a pdf/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdf("second.pdf")] } });
    await screen.findByText("second.pdf");
    expect(screen.queryByText(/added to the queue/i)).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    expect(await screen.findByText(/is not a PDF or DOCX/i)).toBeTruthy();
    expect(screen.queryByText(/added to the queue/i)).toBeNull();
  });

  // NOT TESTED: resetting the native file input's displayed filename after
  // a successful submit (Upload.tsx's fileInputRef.current.value = "").
  // jsdom never lets a scripted `.files` assignment change `input.value` in
  // the first place (real browsers only set it from actual user selection),
  // so an assertion here would pass identically whether or not the reset
  // code exists — verified by deleting the reset line and re-running: the
  // assertion still passed. A test that can't fail is worse than no test;
  // this needs a real browser.

  it("shows the server's reason when the upload is rejected", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValue(
      new Error("upload: notes.txt is not a PDF or DOCX."),
    );
    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    expect(await screen.findByText(/is not a PDF or DOCX/i)).toBeTruthy();
  });

  it("offers re-processing when the document is already in the corpus", async () => {
    const upload = vi.spyOn(api, "uploadDocument")
      .mockRejectedValueOnce(new api.DuplicateDocumentError({
        detail: "already in corpus",
        existing_doc_id: "agao-afr-fy2025",
        added_at: "2026-07-01T12:00:00+00:00",
        added_by: "DMOSS",
      }))
      .mockResolvedValueOnce({ job_id: "j2", doc_id: "d1" });

    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    const dupe = await screen.findByTestId("duplicate");
    expect(dupe.textContent).toMatch(/already in the corpus/i);
    expect(dupe.textContent).toMatch(/DMOSS/);

    fireEvent.click(within(dupe).getByRole("button", { name: /again/i }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[1][1].reprocess).toBe(true);
  });

  // Plan B Blocking 3 (T12): the server's own coverage sentence
  // (app/routes/upload.py's `_duplicate_health`) was computed and pinned by
  // six backend tests but never reached the page — these two are the two
  // branches that finding named: a measured duplicate shows the server's
  // OWN sentence, verbatim; an unmeasured (legacy) one shows nothing extra
  // and today's fixed sentence is untouched.

  it("shows the server's own coverage sentence for a duplicate extraction looked incomplete", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValueOnce(
      new api.DuplicateDocumentError({
        detail: "already in corpus",
        existing_doc_id: "agao-afr-fy2024",
        added_at: null,
        added_by: null,
        health: { coverage: 0.02, recommend_reprocess: true },
        message:
          "Extraction produced 2% as much text as the file contains. Re-processing is recommended.",
      }),
    );

    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    const dupe = await screen.findByTestId("duplicate");
    // Rendered VERBATIM — a client-composed paraphrase of `health` would
    // not necessarily match this exact server sentence, and the point of
    // T12 is that it must.
    expect(await screen.findByTestId("duplicate-health")).toHaveTextContent(
      "Extraction produced 2% as much text as the file contains. Re-processing is recommended.",
    );
    expect(dupe.textContent).toMatch(/already in the corpus/i);
  });

  it("adds nothing beyond today's sentence for a duplicate with no recorded coverage", async () => {
    // No `health` / `message` at all — the shape every real legacy
    // document's lookup sends (`_duplicate_health` returns `health=None`
    // for the 7,434 documents with no recorded coverage), and also the
    // shape this fixture always sent before Blocking 3.
    vi.spyOn(api, "uploadDocument").mockRejectedValueOnce(
      new api.DuplicateDocumentError({
        detail: "already in corpus",
        existing_doc_id: "jlbc-baseline-fy2020-axs",
        added_at: "2026-07-01T12:00:00+00:00",
        added_by: "DMOSS",
      }),
    );

    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    const dupe = await screen.findByTestId("duplicate");
    // Today's sentence, unchanged.
    expect(dupe.textContent).toMatch(/already in the corpus/i);
    expect(dupe.textContent).toMatch(/DMOSS/);
    // And nothing else — this is the branch that must stay silent.
    expect(screen.queryByTestId("duplicate-health")).toBeNull();
  });
});

// --- switching the selected type (the hazard this rework introduces) -------

describe("switching the selected type", () => {
  // Six independent cards used to make this a non-issue — each type had its
  // own React state, so nothing COULD leak between them. One form serving
  // six types can, unless every one of these is deliberately cleared on a
  // switch: a file, a customized fiscal year, a stage, an error, a
  // duplicate notice, and a success message. Each is asserted separately so
  // a partial fix (e.g. clearing the file but not the error) still fails.
  beforeEach(() => {
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
  });

  it("does not carry a picked file or a customized fiscal year to the next type", async () => {
    render(<Upload />);
    await selectType(/annual financial report/i);
    const input = (await screen.findByLabelText(/choose a pdf/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pdf("agao-afr-fy2025.pdf")] } });
    await screen.findByText("agao-afr-fy2025.pdf");
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "1999" } });

    await selectType(/budget bill summary/i);

    expect(screen.queryByText("agao-afr-fy2025.pdf")).toBeNull();
    expect((screen.getByLabelText("Fiscal year") as HTMLInputElement).value)
      .not.toBe("1999");
  });

  it("does not carry a public-record tick to the next type", async () => {
    render(<Upload />);
    await selectType(/annual financial report/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    expect(screen.getByRole("checkbox", { name: /public record/i })).toBeChecked();

    await selectType(/budget bill summary/i);

    expect(screen.getByRole("checkbox", { name: /public record/i })).not.toBeChecked();
  });

  it("does not carry a picked stage to a different staged type's form", async () => {
    // Both budget-bill-summary swaps here are the SAME type, so this can't
    // be checked directly against a second staged row in the tiny fixture —
    // instead it goes staged -> unstaged -> staged and confirms the second
    // arrival is fresh, not the first arrival's leftover "engrossed".
    render(<Upload />);
    await selectType(/budget bill summary/i);
    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "engrossed" } });
    expect((screen.getByLabelText("Version") as HTMLSelectElement).value).toBe("engrossed");

    await selectType(/annual financial report/i);
    await selectType(/budget bill summary/i);

    expect((screen.getByLabelText("Version") as HTMLSelectElement).value).toBe("");
  });

  it("does not carry an error message to the next type", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValue(
      new Error("upload: notes.txt is not a PDF or DOCX."),
    );
    render(<Upload />);
    await selectType(/annual financial report/i);
    fireEvent.change(await screen.findByLabelText(/choose a pdf/i), {
      target: { files: [pdf()] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await screen.findByText(/is not a PDF or DOCX/i);

    await selectType(/budget bill summary/i);

    expect(screen.queryByText(/is not a PDF or DOCX/i)).toBeNull();
  });

  it("does not carry a duplicate notice to the next type", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValue(
      new api.DuplicateDocumentError({
        detail: "already in corpus", existing_doc_id: "x",
        added_at: null, added_by: null,
      }),
    );
    render(<Upload />);
    await selectType(/annual financial report/i);
    fireEvent.change(await screen.findByLabelText(/choose a pdf/i), {
      target: { files: [pdf()] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await screen.findByTestId("duplicate");

    await selectType(/budget bill summary/i);

    expect(screen.queryByTestId("duplicate")).toBeNull();
  });

  it("does not carry a success message to the next type", async () => {
    vi.spyOn(api, "uploadDocument").mockResolvedValue({ job_id: "j", doc_id: "d" });
    render(<Upload />);
    await selectType(/annual financial report/i);
    fireEvent.change(await screen.findByLabelText(/choose a pdf/i), {
      target: { files: [pdf()] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await screen.findByText(/added to the queue/i);

    await selectType(/budget bill summary/i);

    expect(screen.queryByText(/added to the queue/i)).toBeNull();
  });
});

// --- the document-types fetch itself ----------------------------------------

describe("when the document-type registry can't be reached", () => {
  it("says so plainly instead of rendering nothing", async () => {
    vi.spyOn(api, "documentTypes").mockRejectedValue(new Error("document types: 500"));
    render(<Upload />);
    expect(await screen.findByText(/couldn.t load the list of document types/i))
      .toBeTruthy();
  });
});

// --- the type picker and form, per document type ----------------------------

describe("the type picker and form", () => {
  beforeEach(() => {
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
  });

  it("holds every type card inside one named card", async () => {
    // Six separated boxes with nothing around them read as six unrelated
    // features — the objection that killed the very first six-card layout.
    // Separation was never the problem; unrelatedness was. The outer card
    // is what makes them read as contained.
    render(<Upload />);
    const cards = await screen.findAllByTestId("doc-type-card");
    const outer = screen.getByRole("region", { name: /uploads/i });
    for (const card of cards) expect(outer.contains(card)).toBe(true);
  });

  it("lists one card per document type from the API, in order", async () => {
    render(<Upload />);
    expect(await screen.findByText("Annual Financial Report")).toBeInTheDocument();
    expect(screen.getByText("Budget Bill Summary")).toBeInTheDocument();
    expect(screen.getAllByTestId("doc-type-card")).toHaveLength(ROWS.length);
  });

  it("tags a closed row with its publisher and NO prose at all", async () => {
    // Measured: the six rows carried 101 words of `where_published` around
    // six names totalling 14 — the list you came to scan was the minority of
    // its own text. A closed row now carries the name and a publisher tag
    // (`group`, already on the wire and previously displayed nowhere), so
    // six rows can be sorted by eye without reading a sentence.
    //
    // Both registry sentences are asserted ABSENT while closed and PRESENT
    // once open. Nothing is deleted — the AFR's "gao.az.gov blocks automated
    // downloads, so save it from a browser" is the clearest case of guidance
    // that matters when you act and is noise while you choose.
    render(<Upload />);
    expect(await screen.findByText("Auditor General")).toBeInTheDocument();
    expect(screen.queryByText(/gao\.az\.gov/)).toBeNull();
    expect(screen.queryByText(/The combined PDF\./)).toBeNull();

    await selectType(/annual financial report/i);
    expect(screen.getByText(/gao\.az\.gov/)).toBeInTheDocument();
    expect(screen.getByText(/The combined PDF\./)).toBeInTheDocument();
  });

  it("shows each book row ITS OWN count, without opening either", async () => {
    // The one honest state a collapsed row can carry, and the reason the
    // check is fetched by the PAGE. It answers the only question anyone has
    // about a book row.
    //
    // 🔴 TWO redirect rows and BOTH families missing, deliberately. The
    // first version of this spec used one redirect row and one missing
    // edition, and a mutation proved it vacuous: dropping the family filter
    // entirely — so every book row reports every family's gap — left it
    // green. With two rows carrying different counts, the unfiltered
    // version reports "2 to add" on both and the spec fails.
    vi.spyOn(api, "documentTypes").mockResolvedValue([
      ROWS[0],
      { ...ROWS[0], key: "approps-row", label: "Appropriations Report",
        redirect: { action: "add-jlbc-book", family: "approps",
                    detail: "Stored as one document per agency." } },
    ]);
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(),
      online: true,
      reason: null,
      missing: [
        { family: "baseline", fiscal_year: 2028, document_count: 110, source: "catalog" },
        { family: "baseline", fiscal_year: 2029, document_count: 110, source: "catalog" },
      ],
      present: [],
      unavailable: [],
    });
    render(<Upload />);
    const cards = await screen.findAllByTestId("doc-type-card");
    const baseline = cards.find((c) => c.getAttribute("data-doc-type") === ROWS[0].key)!;
    const approps = cards.find((c) => c.getAttribute("data-doc-type") === "approps-row")!;

    expect(await within(baseline).findByText("2 to add")).toBeInTheDocument();
    expect(within(approps).getByText("up to date")).toBeInTheDocument();
    // Still closed — the point is that nothing had to be opened.
    expect(within(baseline).getByRole("button").getAttribute("aria-expanded")).toBe("false");
  });

  it("gives the four file types no invented state", async () => {
    // The app cannot know whether the Auditor General has published this
    // year's AFR until somebody looks, so those rows carry nothing. Four
    // filler labels that say nothing would undo the point of the column.
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(), online: true, reason: null,
      missing: [], present: [], unavailable: [],
    });
    render(<Upload />);
    const cards = await screen.findAllByTestId("doc-type-card");
    const afr = cards.find((c) => c.getAttribute("data-doc-type") === ROWS[1].key)!;
    await within(cards[0]).findByText("up to date");
    expect(afr.querySelector(".up-card-state")).toBeNull();
  });

  it("a book row says it cannot check, rather than claiming to be up to date", async () => {
    // An offline check must not render as "up to date" — that is a
    // confident wrong answer produced by a network failure, on the one row
    // whose job is telling you what is missing.
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(),
      online: false,
      reason: "Couldn't reach azjlbc.gov to check for new editions (OSError).",
      missing: [],
      present: [],
      unavailable: [],
    });
    render(<Upload />);
    expect(await screen.findAllByText("can’t check")).toHaveLength(1);
    expect(screen.queryByText("up to date")).toBeNull();
  });

  it("a JLBC-book type opens into its own family's gap, not a file form", async () => {
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(),
      online: true,
      reason: null,
      missing: [],
      present: [],
      unavailable: [],
    });
    render(<Upload />);
    await selectType(/baseline book/i);

    // No form at all for a book type — not a disabled one, and above all
    // not a file input for a document that is never uploaded as one file.
    expect(screen.queryByTestId("upload-form")).toBeNull();
    expect(screen.queryByLabelText(/choose a pdf/i)).toBeNull();

    const panel = await screen.findByTestId("book-panel");
    expect(panel.getAttribute("data-family")).toBe("baseline");
    expect(panel.textContent).toMatch(/Stored as one document per agency/);
  });

  it("sends each book card its OWN family, off the wire", async () => {
    // The family comes from the registry's `redirect.family`, never from a
    // key -> family map written in the webapp: Upload.tsx is under the
    // no-hardcoded-slug spec below precisely because a second hand-typed
    // copy of the type list has shipped bugs twice.
    vi.spyOn(api, "documentTypes").mockResolvedValue([
      { ...ROWS[0], redirect: { action: "add-jlbc-book", family: "made-up-family",
                                detail: "Detail." } },
    ]);
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(), online: true, reason: null,
      missing: [], present: [], unavailable: [],
    });
    render(<Upload />);
    await selectType(/baseline book/i);
    expect((await screen.findByTestId("book-panel")).getAttribute("data-family"))
      .toBe("made-up-family");
  });

  it("only the bill summary asks for a stage", async () => {
    render(<Upload />);
    await selectType(/annual financial report/i);
    expect(screen.queryByLabelText("Version")).toBeNull();

    await selectType(/budget bill summary/i);
    expect(screen.getByLabelText("Version")).toBeTruthy();
  });

  it("sends the stage with the upload", async () => {
    // fireEvent, not userEvent — this webapp has no @testing-library/user-event
    // (see other test files in this repo for the same note), and "no new
    // dependency" is a hard constraint.
    const up = vi.spyOn(api, "uploadDocument").mockResolvedValue(
      { job_id: "j", doc_id: "d" });
    render(<Upload />);
    await selectType(/budget bill summary/i);
    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "engrossed" } });
    fireEvent.change(screen.getByLabelText(/choose a pdf/i), {
      target: { files: [new File(["x"], "bills.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await waitFor(() => expect(up).toHaveBeenCalled());
    expect(up.mock.calls[0][1]).toMatchObject({
      doc_type: "budget-bill-summary", stage: "engrossed",
    });
  });

  it("cannot be submitted without a stage on a staged type", async () => {
    // The gate that makes "Engrossed supersedes Introduced" true: a staged
    // type must be unsubmittable with no stage picked, same as it's
    // unsubmittable with no file and no public-record tick.
    render(<Upload />);
    await selectType(/budget bill summary/i);
    fireEvent.change(screen.getByLabelText(/choose a pdf/i), {
      target: { files: [new File(["x"], "bills.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    expect(screen.getByRole("button", { name: /add document/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "introduced" } });
    expect(screen.getByRole("button", { name: /add document/i })).toBeEnabled();
  });

  it("accepts a file dropped on the form, going through the same path as a picked one", async () => {
    // Drag-and-drop exercises the fiscal-year filename sniff too, to prove
    // the dropped file goes through selectFile(), the exact function the
    // file <input>'s onChange calls — not a second, divergent path.
    render(<Upload />);
    await selectType(/annual financial report/i);
    const form = await screen.findByTestId("upload-form");
    const file = pdf("FY2026-approps.pdf");
    fireEvent.drop(form, { dataTransfer: { files: [file] } });
    expect(await screen.findByText(file.name)).toBeTruthy();
    expect((screen.getByLabelText("Fiscal year") as HTMLInputElement).value)
      .toBe("2026");
  });

  it("gives the file-accepting form a visible drop affordance, and gives a book type none", async () => {
    // jsdom applies no stylesheet, so this can only pin the MARKUP (the
    // .up-drop box + its hint text), not that the dashed border actually
    // renders — see the report for the human-in-a-browser follow-up.
    vi.spyOn(api, "booksMissing").mockResolvedValue({
      checked_at: new Date().toISOString(), online: true, reason: null,
      missing: [], present: [], unavailable: [],
    });
    render(<Upload />);
    await selectType(/annual financial report/i);
    const form = await screen.findByTestId("upload-form");
    expect(form.querySelector(".up-drop")).toBeTruthy();
    expect(within(form).getByText(/drag and drop it here/i)).toBeTruthy();

    await selectType(/baseline book/i);
    expect(screen.queryByTestId("upload-form")).toBeNull();
  });

  it("keeps the real file input reachable, not display:none'd away", async () => {
    // The visible "Choose a PDF document" control is a <label> wearing the
    // app's chip style, because the browser's own file widget is what made
    // this page read as a raw HTML form. The input behind it must still be
    // a real, labelled, focusable input — hiding it with display:none would
    // take it out of the accessibility tree and off the keyboard, turning a
    // cosmetic change into a functional regression. Its discoverability by
    // LABEL is the part jsdom can actually check.
    render(<Upload />);
    await selectType();
    const input = (await screen.findByLabelText(/choose a pdf/i)) as HTMLInputElement;
    expect(input.type).toBe("file");
    expect(input.hidden).toBe(false);
    expect(input.disabled).toBe(false);
  });

  it("requires a fresh stage pick before a second upload of the same type", async () => {
    // "Engrossed supersedes Introduced" is only true if EVERY upload
    // carries a stage, including a second document pushed through the same
    // type after it already succeeded once (e.g. Introduced today,
    // Engrossed next week). If the picker remembered the last value, a
    // re-upload could silently reuse a stale stage instead of forcing a
    // fresh choice.
    vi.spyOn(api, "uploadDocument").mockResolvedValue({ job_id: "j", doc_id: "d" });
    render(<Upload />);
    await selectType(/budget bill summary/i);
    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "introduced" } });
    fireEvent.change(screen.getByLabelText(/choose a pdf/i), {
      target: { files: [new File(["x"], "bills.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /add document/i })).toBeDisabled());
    expect((screen.getByLabelText("Version") as HTMLSelectElement).value).toBe("");
  });

  it("offers NO title field on any type", async () => {
    // 🔴 Removing the Title box was invisible to this suite — nothing had
    // ever asserted it existed, so nothing failed when it went. This is the
    // guard the other direction: a future edit that re-adds a free-text
    // title fails here and has to argue for it.
    //
    // The reason it went: every type is named completely by its type and
    // year ("FY 2025 Annual Financial Report" IS the AFR, there is one a
    // year), so the box offered a choice where there was none — and a typed
    // title WINS over the automatic one in build_title, so the only thing it
    // could do was make a correct title worse.
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
    render(<Upload />);
    for (const label of [/annual financial report/i, /budget bill summary/i]) {
      await selectType(label);
      expect(screen.queryByLabelText(/^title/i)).toBeNull();
      await selectType(label);
    }
  });

  it("asks which agency only on the row that declares one", async () => {
    vi.spyOn(api, "agencies").mockResolvedValue(AGENCIES);
    vi.spyOn(api, "documentTypes").mockResolvedValue([...ROWS, AGENCY_ROW]);
    render(<Upload />);

    await selectType(/annual financial report/i);
    expect(screen.queryByLabelText("Agency")).toBeNull();

    await selectType(/agency submission/i);
    expect(await screen.findByLabelText("Agency")).toBeTruthy();
  });

  it("stays unsubmittable until the typed text resolves to a real agency", async () => {
    // The typed text is not the answer — the canonical id is. A half-typed
    // "Depart" must not become a document's title, so the gate is the same
    // shape as the staged-type gate beside it.
    vi.spyOn(api, "agencies").mockResolvedValue(AGENCIES);
    vi.spyOn(api, "documentTypes").mockResolvedValue([AGENCY_ROW]);
    render(<Upload />);
    await selectType(/agency submission/i);
    fireEvent.change(await screen.findByLabelText(/choose a pdf/i), {
      target: { files: [pdf("request.pdf")] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));

    const add = screen.getByRole("button", { name: /add document/i });
    expect(add).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Agency"), { target: { value: "Depart" } });
    expect(add).toBeDisabled();
    expect(screen.getByText(/No agency by that name/i)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Agency"), {
      target: { value: "Department of Corrections" },
    });
    expect(add).toBeEnabled();
    expect(screen.queryByText(/No agency by that name/i)).toBeNull();
  });

  it("sends the agency's canonical id, not the words that were typed", async () => {
    const up = vi.spyOn(api, "uploadDocument").mockResolvedValue(
      { job_id: "j", doc_id: "d" });
    vi.spyOn(api, "agencies").mockResolvedValue(AGENCIES);
    vi.spyOn(api, "documentTypes").mockResolvedValue([AGENCY_ROW]);
    render(<Upload />);
    await selectType(/agency submission/i);
    fireEvent.change(await screen.findByLabelText(/choose a pdf/i), {
      target: { files: [pdf("request.pdf")] },
    });
    fireEvent.change(screen.getByLabelText("Agency"), {
      // Cased and spaced differently from the catalog on purpose: the match
      // is case-insensitive and whitespace-collapsed, and the ID is what
      // travels either way.
      target: { value: "  department of corrections " },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    await waitFor(() => expect(up).toHaveBeenCalled());
    expect(up.mock.calls[0][1]).toMatchObject({
      doc_type: AGENCY_ROW.key,
      agency_canonical_id: "agency:adc",
    });
    expect(up.mock.calls[0][1].title).toBe("");
  });

  it("never sends an agency for a type that does not take one", async () => {
    // The route 422s on this, so sending it would turn a good upload into a
    // confusing rejection.
    const up = vi.spyOn(api, "uploadDocument").mockResolvedValue(
      { job_id: "j", doc_id: "d" });
    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));

    await waitFor(() => expect(up).toHaveBeenCalled());
    expect(up.mock.calls[0][1].agency_canonical_id).toBeUndefined();
  });

  it("keeps agencies an admin added separable from the shipped catalog", async () => {
    // Nothing in the corpus is stamped with an office-added id, so the two
    // are genuinely different things and the list should not pretend
    // otherwise.
    vi.spyOn(api, "agencies").mockResolvedValue(AGENCIES);
    vi.spyOn(api, "documentTypes").mockResolvedValue([AGENCY_ROW]);
    render(<Upload />);
    await selectType(/agency submission/i);
    await screen.findByLabelText("Agency");
    const office = document.querySelector(
      '#up-agency-options option[value="Office of Made-Up Things"]',
    )!;
    expect(office.getAttribute("label")).toMatch(/added by your office/i);
  });

  it("says so when the agency list cannot be loaded", async () => {
    vi.spyOn(api, "agencies").mockRejectedValue(new Error("agencies: 500"));
    vi.spyOn(api, "documentTypes").mockResolvedValue([AGENCY_ROW]);
    render(<Upload />);
    await selectType(/agency submission/i);
    expect(await screen.findByText(/Couldn.t load the agency list/i)).toBeTruthy();
  });

  it("holds no hardcoded doc_type strings of its own", async () => {
    // Broadened (carried over from Task 6's final review): reads every key
    // the registry itself defines and checks BOTH literal shapes a slug
    // could reappear in — a quoted string (any of "x"/'x'/`x`) and a bare
    // object-key (`afr:`) — so a repeat of the old ROW_PUBLISHERS-shaped
    // defect fails here, not just today's known slugs.
    const src = (await import("./Upload.tsx?raw")).default;
    const registry = readFileSync(
      resolve(process.cwd(), "../data/document-types.yaml"),
      "utf-8",
    );
    const slugs = [...registry.matchAll(/-\s*key:\s*(\S+)/g)].map((m) => m[1]);
    // Sanity check on the extraction itself: a regex that silently matched
    // nothing would make every assertion below vacuously true.
    expect(slugs.length).toBeGreaterThanOrEqual(15);
    expect(slugs).toContain("agency-submission");

    for (const slug of slugs) {
      expect(src, `quoted literal for "${slug}"`).not.toMatch(
        new RegExp(`["'\`]${slug}["'\`]`),
      );
      // Bare object-key form only applies to slugs that are valid JS
      // identifiers on their own (every hyphenated slug can only be spelled
      // quoted, already covered above) — "afr" is the sole such slug today.
      if (/^[A-Za-z_$][\w$]*$/.test(slug)) {
        expect(src, `bare object key "${slug}:"`).not.toMatch(
          new RegExp(`(?:^|[^\\w$])${slug}\\s*:`, "m"),
        );
      }
    }
  });
});

// --- the queue --------------------------------------------------------------

describe("the queue", () => {
  it("renders progress and stage detail per job", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [job()], finished_count: 0, showing: "active" as const });
    render(<Upload />);
    const row = await screen.findByTestId("job");
    expect(row.textContent).toMatch(/Reading the document/);
    expect(row.textContent).toMatch(/page 34\/210/);
    expect(within(row).getByRole("progressbar").getAttribute("aria-valuenow"))
      .toBe("16");
  });

  it("polls for updates", async () => {
    vi.useFakeTimers();
    const list = vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [], finished_count: 0, showing: "active" as const });
    render(<Upload />);
    await vi.advanceTimersByTimeAsync(3000);
    expect(list.mock.calls.length).toBeGreaterThan(1);
  });

  it("offers Retry on a failed job and Cancel on a running one", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue({
      jobs: [
        job({ job_id: "bad", state: "failed", error: "mineru exploded" }),
        job({ job_id: "busy", state: "embedding" }),
      ],
      finished_count: 0,
      showing: "active" as const,
    });
    const retry = vi.spyOn(api, "retryJob").mockResolvedValue({ job: job() });
    const cancel = vi.spyOn(api, "cancelJob").mockResolvedValue({ job: job() });

    render(<Upload />);
    const rows = await screen.findAllByTestId("job");
    expect(rows[0].textContent).toMatch(/mineru exploded/);

    fireEvent.click(within(rows[0]).getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith("bad"));

    expect(within(rows[0]).queryByRole("button", { name: /cancel/i })).toBeNull();
    fireEvent.click(within(rows[1]).getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("busy"));
  });

  it("has no progress bar or cancel once a job is live", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [job({ state: "live" })], finished_count: 0, showing: "active" as const });
    render(<Upload />);
    const row = await screen.findByTestId("job");
    expect(within(row).queryByRole("progressbar")).toBeNull();
    expect(within(row).queryByRole("button")).toBeNull();
    expect(row.textContent).toMatch(/Searchable/);
  });

  it("keeps the last good queue when a refresh fails", async () => {
    // Fake timers throughout, and the initial load is flushed by advancing 0
    // rather than waitFor — waitFor polls on real timers and would hang here.
    vi.useFakeTimers();
    vi.spyOn(api, "jobs")
      .mockResolvedValueOnce({ jobs: [job()], finished_count: 0, showing: "active" as const })
      .mockRejectedValue(new Error("jobs: share offline"));
    render(<Upload />);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getAllByTestId("job")).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(3000);
    expect(screen.getAllByTestId("job")).toHaveLength(1);  // last good kept
    expect(screen.getByText(/share offline/i)).toBeTruthy();
  });

  it("says so plainly when nothing is processing", async () => {
    render(<Upload />);
    expect(await screen.findByText(/nothing is processing/i)).toBeTruthy();
  });
});

// --- Add a JLBC book --------------------------------------------------------


// --- who may set a "Full report" link ---------------------------------------

describe("the 'Full report link' row on a book card", () => {
  // The page resolves WHO IS LOOKING once and hands it to both book cards.
  // /upload is open to the whole office; approving a whole-report address
  // changes what every analyst's "Full report" button downloads, so the row
  // is admin-only (Destin's call, 2026-08-16, over showing it read-only).
  //
  // 🔴 This is the WIRE, and it has been the silent failure twice on this
  // feature: the panel this replaces was once deleted from its page with
  // 1008 of 1008 specs green, and its api layer was once entirely unpinned.
  // The row's own behaviour lives in `upload/ReportLinkRow.test.tsx`; these
  // two specs assert only that the page decides, and that the decision
  // arrives.

  function bookRows(isAdmin: boolean) {
    vi.spyOn(api, "documentTypes").mockResolvedValue([ROWS[0]]);
    vi.spyOn(api, "me").mockResolvedValue({
      user: "DMOSS",
      is_admin: isAdmin,
      admin_username: isAdmin ? "DMOSS" : "SOMEONEELSE",
      admin_claimable: false,
      admin_reset_pending: false,
    });
    vi.spyOn(api, "bookFormats").mockResolvedValue({
      pending: [],
      approved: [
        {
          family: "Baseline",
          fiscal_year: 2027,
          single_file: "https://www.azjlbc.gov/27baseline/fy2027baseline.pdf",
          linked_toc: "https://www.azjlbc.gov/27baseline/baselinetoc.pdf",
        },
      ],
      online: true,
      reason: null,
      problems: [],
    });
  }

  it("reaches an admin's book card", async () => {
    bookRows(true);
    render(<Upload />);
    await selectType(/baseline book/i);
    const row = await screen.findByTestId("report-links");
    // Not merely mounted: it resolved this card's own family, which is the
    // half of the wire the slug-vs-label trap breaks silently.
    await waitFor(() =>
      expect(row.querySelector("summary")!.textContent).toMatch(/1 edition set/),
    );
  });

  it("is absent for everyone else, and asks the server nothing", async () => {
    bookRows(false);
    render(<Upload />);
    await selectType(/baseline book/i);
    // The card is open and fully rendered — asserted through a control that
    // is always there — so this is a real absence, not a not-yet-rendered one.
    expect(await screen.findByTestId("book-about")).toBeTruthy();
    expect(screen.queryByTestId("report-links")).toBeNull();
    expect(api.bookFormats).not.toHaveBeenCalled();
  });
});
