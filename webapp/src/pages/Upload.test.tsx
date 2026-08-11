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
// (afr, governors-budget, agency-submission, budget-bill-summary) — "six
// guided rows". This fixture carries three of the six; that's enough to
// exercise every branch (redirect / plain / staged) without the whole file
// re-deriving all six every time a row's copy changes upstream.
const ROWS: api.DocTypeCard[] = [
  { key: "baseline-book", label: "Baseline Book", group: "JLBC", formats: [".pdf"],
    where_published: "JLBC, each January.", which_file: "",
    redirect: { action: "add-jlbc-book", label: "Use “Add a JLBC book” instead",
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

// The single row every OTHER describe block in this file renders (the old
// single-dropzone tests below assume exactly one thing to interact with —
// see pickFile()). It's ROWS' own "afr" entry, not a fresh fixture, so the
// two can't quietly drift apart.
const DEFAULT_ROW = ROWS[1];

async function pickFile(file = pdf()) {
  // findByLabelText, not getByLabelText: the row itself now arrives via an
  // async GET /api/document-types fetch (Task 6), so it isn't necessarily
  // in the DOM on the synchronous render this used to run against.
  const input = (await screen.findByLabelText(/choose a pdf/i)) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByText(file.name);
}

beforeEach(() => {
  vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [] });
  // Default: exactly one plain (non-redirect, non-staged) row, so every test
  // written against the old single-form assumptions (one file input, one
  // "Fiscal year" field, one submit button) still resolves unambiguously.
  // The "upload rows" describe below overrides this with the full fixture.
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

// --- metadata form ----------------------------------------------------------

describe("the metadata form", () => {
  // Superseded, not just renamed: the old single dropzone gated its whole
  // meta form behind a chosen file. A DocTypeRow shows its fields
  // immediately — the analyst needs to see "does this row want a stage?"
  // before hunting for a file, and the brief's own row-shape tests
  // ("only the bill summary asks for a stage") depend on that being true
  // with no file chosen at all.
  it("shows metadata fields without requiring a file first", async () => {
    render(<Upload />);
    expect(await screen.findByLabelText("Fiscal year")).toBeTruthy();
  });

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
      corpus: "budget", publisher: "agao", doc_type: "afr",
    });
  });

  it("clears the native file input once the upload is queued", async () => {
    vi.spyOn(api, "uploadDocument").mockResolvedValue({ job_id: "j1", doc_id: "d1" });
    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add document/i }));
    await waitFor(() =>
      expect((screen.getByLabelText(/choose a pdf/i) as HTMLInputElement).value).toBe(""));
  });

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

// --- the six guided rows (Task 6) -------------------------------------------

describe("upload rows", () => {
  beforeEach(() => {
    vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS);
  });

  it("renders one row per document type from the API", async () => {
    render(<Upload />);
    expect(await screen.findByText("Annual Financial Report")).toBeInTheDocument();
    expect(screen.getByText("Budget Bill Summary")).toBeInTheDocument();
  });

  it("shows where to get the file and which file to get", async () => {
    render(<Upload />);
    expect(await screen.findByText(/The combined PDF\./)).toBeInTheDocument();
    expect(screen.getByText(/gao\.az\.gov/)).toBeInTheDocument();
  });

  it("a redirect row offers no file input", async () => {
    render(<Upload />);
    const row = (await screen.findByText("Baseline Book")).closest("[data-doc-type]")!;
    expect(row.querySelector('input[type="file"]')).toBeNull();
    expect(row.textContent).toMatch(/Add a JLBC book/);
  });

  it("only the bill summary asks for a stage", async () => {
    render(<Upload />);
    await screen.findByText("Budget Bill Summary");
    const summary = screen.getByText("Budget Bill Summary").closest("[data-doc-type]")!;
    const afr = screen.getByText("Annual Financial Report").closest("[data-doc-type]")!;
    expect(summary.querySelector('select[name="stage"]')).not.toBeNull();
    expect(afr.querySelector('select[name="stage"]')).toBeNull();
  });

  it("sends the stage with the upload", async () => {
    // fireEvent, not userEvent — this webapp has no @testing-library/user-event
    // (see other test files in this repo for the same note). The brief's own
    // sketch imported userEvent; that dependency does not exist here and
    // "no new dependency" is a hard constraint, so every interaction below
    // is fireEvent instead.
    const up = vi.spyOn(api, "uploadDocument").mockResolvedValue(
      { job_id: "j", doc_id: "d" });
    render(<Upload />);
    await screen.findByText("Budget Bill Summary");
    const row = screen.getByText("Budget Bill Summary").closest("[data-doc-type]")! as HTMLElement;
    fireEvent.change(row.querySelector("select[name=stage]")!, {
      target: { value: "engrossed" },
    });
    fireEvent.change(row.querySelector('input[type="file"]')!, {
      target: { files: [new File(["x"], "bills.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(row.querySelector('input[type="checkbox"]')!);
    fireEvent.click(within(row).getByRole("button", { name: /add document/i }));
    await waitFor(() => expect(up).toHaveBeenCalled());
    expect(up.mock.calls[0][1]).toMatchObject({
      doc_type: "budget-bill-summary", stage: "engrossed",
    });
  });

  it("requires a fresh stage pick before a second upload through the same row", async () => {
    // Correction 2: "Engrossed supersedes Introduced" is only true if EVERY
    // upload carries a stage, including a second document pushed through a
    // row that already succeeded once (e.g. Introduced today, Engrossed
    // next week). If the picker remembered the last value, a re-upload
    // could silently reuse a stale stage instead of forcing a fresh choice.
    vi.spyOn(api, "uploadDocument").mockResolvedValue({ job_id: "j", doc_id: "d" });
    render(<Upload />);
    await screen.findByText("Budget Bill Summary");
    const row = screen.getByText("Budget Bill Summary").closest("[data-doc-type]")! as HTMLElement;
    fireEvent.change(row.querySelector("select[name=stage]")!, {
      target: { value: "introduced" },
    });
    fireEvent.change(row.querySelector('input[type="file"]')!, {
      target: { files: [new File(["x"], "bills.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(row.querySelector('input[type="checkbox"]')!);
    fireEvent.click(within(row).getByRole("button", { name: /add document/i }));

    await waitFor(() =>
      expect(within(row).getByRole("button", { name: /add document/i })).toBeDisabled());
    expect((row.querySelector('select[name=stage]') as HTMLSelectElement).value).toBe("");
  });

  it("holds no hardcoded doc_type strings of its own", async () => {
    // The point is to make drift impossible, not to fix today's alignment.
    const src = await import("./Upload.tsx?raw");
    for (const slug of ["baseline-per-agency", "approps-per-agency", "s-pdf",
                        "bh-pdf", "bd-pdf", "detailed-list-pdf", "topic-pdf"]) {
      expect(src.default).not.toContain(`"${slug}"`);
    }
  });
});

// --- the queue --------------------------------------------------------------

describe("the queue", () => {
  it("renders progress and stage detail per job", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [job()] });
    render(<Upload />);
    const row = await screen.findByTestId("job");
    expect(row.textContent).toMatch(/Reading the document/);
    expect(row.textContent).toMatch(/page 34\/210/);
    expect(within(row).getByRole("progressbar").getAttribute("aria-valuenow"))
      .toBe("16");
  });

  it("polls for updates", async () => {
    vi.useFakeTimers();
    const list = vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [] });
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
    vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [job({ state: "live" })] });
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
      .mockResolvedValueOnce({ jobs: [job()] })
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

describe("the Add-a-JLBC-book panel", () => {
  const EDITIONS: api.BookEdition[] = [
    {
      key: "baseline-fy2027", family: "baseline", fiscal_year: 2027,
      ingestable: true, rolling: false, era_note: "",
      single_file_url: null, linked_toc_url: "https://x/27baselinelinks.pdf",
      document_count: 129,
    },
    {
      key: "approps-fy1996", family: "approps", fiscal_year: 1996,
      ingestable: false, rolling: false, era_note: "Whole book only",
      single_file_url: "https://x/FY1996.pdf", linked_toc_url: null,
      document_count: 0,
    },
  ];

  it("offers only editions that have something to ingest", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    render(<Upload />);
    const picker = await screen.findByLabelText("Edition");
    const options = within(picker).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toMatch(/FY 2027 Baseline — 129 documents/);
  });

  it("discovers without queuing anything", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    const discover = vi.spyOn(api, "discoverBook").mockResolvedValue({
      source: "catalog", count: 129, documents: [], notes: [],
      unreachable: ["https://x/gone.pdf", "https://x/also-gone.pdf"],
      single_file_url: null, linked_toc_url: null,
    });
    const ingest = vi.spyOn(api, "ingestBook");

    render(<Upload />);
    await screen.findByLabelText("Edition");
    fireEvent.click(screen.getByRole("button", { name: /discover/i }));

    await waitFor(() => expect(discover).toHaveBeenCalledWith("baseline", 2027));
    const plan = await screen.findByTestId("book-plan");
    expect(plan.textContent).toMatch(/Found 129 documents for FY 2027 Baseline/);
    expect(plan.textContent).toMatch(/2 unreachable/);
    expect(within(plan).getByText("https://x/gone.pdf")).toBeTruthy();
    expect(ingest).not.toHaveBeenCalled();
  });

  it("queues the whole book and reports what was skipped", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    vi.spyOn(api, "ingestBook").mockResolvedValue({
      queued: 127, skipped_existing: 2, unreachable: [],
    });
    render(<Upload />);
    await screen.findByLabelText("Edition");
    fireEvent.click(screen.getByRole("button", { name: /add all/i }));
    expect(await screen.findByText(/Queued 127 documents; 2 already in the corpus/i))
      .toBeTruthy();
  });

  it("states the overnight cost without softening it", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    render(<Upload />);
    const panel = await screen.findByTestId("add-book");
    expect(panel.textContent).toMatch(/takes overnight on office computers/i);
    expect(panel.textContent).toMatch(/one book at a time/i);
  });

  it("has no Invariant 8 checkbox — JLBC reports are public record", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    render(<Upload />);
    const panel = await screen.findByTestId("add-book");
    expect(within(panel).queryByRole("checkbox")).toBeNull();
    expect(panel.textContent).toMatch(/public record, so no confirmation is needed/i);
  });

  it("warns when the edition lives in the rolling folder", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({
      editions: [{ ...EDITIONS[0], rolling: true }],
    });
    render(<Upload />);
    expect(await screen.findByText(/folder JLBC reuses each year/i)).toBeTruthy();
  });

  it("surfaces a discovery failure verbatim", async () => {
    vi.spyOn(api, "bookCatalog").mockResolvedValue({ editions: EDITIONS });
    vi.spyOn(api, "discoverBook").mockRejectedValue(
      new Error("discover: No FY2029 approps book found on azjlbc.gov."),
    );
    render(<Upload />);
    await screen.findByLabelText("Edition");
    fireEvent.click(screen.getByRole("button", { name: /discover/i }));
    expect(await screen.findByText(/No FY2029 approps book/)).toBeTruthy();
  });
});
