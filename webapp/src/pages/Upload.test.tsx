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
    stage_field: false, order: 10 },
  { key: "afr", label: "Annual Financial Report", group: "Auditor General",
    formats: [".pdf"], where_published: "Auditor General, gao.az.gov.",
    which_file: "The combined PDF.", redirect: null, stage_field: false, order: 30 },
  { key: "budget-bill-summary", label: "Budget Bill Summary", group: "JLBC",
    formats: [".pdf"], where_published: "azjlbc.gov/budget/",
    which_file: "The House and Senate Budget Bills PDF.",
    redirect: null, stage_field: true, order: 60 },
];

// The single row every OTHER describe block in this file selects and fills
// in (the old single-dropzone-era tests below assume exactly one type is
// ever relevant — see pickFile()). It's ROWS' own "afr" entry, not a fresh
// fixture, so the two can't quietly drift apart.
const DEFAULT_ROW = ROWS[1];

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
  it("is always visible and names the allowed document types", () => {
    render(<Upload />);
    const notice = screen.getByRole("heading", { name: /public record/i })
      .closest("section")!;
    expect(notice).toBeTruthy();
    const text = notice.textContent ?? "";
    expect(text).toMatch(/public record/i);
    for (const kind of [
      /baseline books/i,
      /appropriations reports/i,
      /fiscal notes/i,
      /bills/i,
      /executive budget requests/i,
      /agency budget requests/i,
      /Annual Financial Reports/i,
    ]) {
      expect(text).toMatch(kind);
    }
  });

  it("says plainly that uploads are exposed to the AI provider and the share", () => {
    render(<Upload />);
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/confidential/i);
    expect(text).toMatch(/shared drive/i);
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

  it("lists one card per document type from the API, in order", async () => {
    render(<Upload />);
    expect(await screen.findByText("Annual Financial Report")).toBeInTheDocument();
    expect(screen.getByText("Budget Bill Summary")).toBeInTheDocument();
    expect(screen.getAllByTestId("doc-type-card")).toHaveLength(ROWS.length);
  });

  it("names the publisher on the closed card, and which file to get inside it", async () => {
    // These two registry fields are deliberately split across the fold.
    // `where_published` is the RECOGNITION cue ("gao.az.gov") and has to be
    // readable while choosing, so it rides on the closed head. `which_file`
    // ("The combined PDF") is an instruction for the moment you go and fetch
    // the file, which is after you have opened the card — putting it on the
    // head as well would put six paragraphs above the fold and make the list
    // unscannable, which is the thing the accordion is for.
    render(<Upload />);
    expect(await screen.findByText(/gao\.az\.gov/)).toBeInTheDocument();
    expect(screen.queryByText(/The combined PDF\./)).toBeNull();

    await selectType(/annual financial report/i);
    expect(screen.getByText(/The combined PDF\./)).toBeInTheDocument();
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

