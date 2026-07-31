import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { Upload, guessMeta } from "./Upload";

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

async function pickFile(file = pdf()) {
  const input = screen.getByLabelText(/choose a pdf/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByText(file.name);
}

beforeEach(() => {
  vi.spyOn(api, "jobs").mockResolvedValue({ jobs: [] });
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
    const button = screen.getByRole("button", { name: /add to the queue/i });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    expect(button).toBeEnabled();
  });
});

// --- metadata form ----------------------------------------------------------

describe("the metadata form", () => {
  it("appears only after a file is chosen", async () => {
    render(<Upload />);
    expect(screen.queryByLabelText("Fiscal year")).toBeNull();
    await pickFile();
    expect(screen.getByLabelText("Fiscal year")).toBeTruthy();
  });

  it("pre-fills from filename heuristics", async () => {
    render(<Upload />);
    await pickFile(pdf("FY2026-approps.pdf"));
    expect((screen.getByLabelText("Fiscal year") as HTMLInputElement).value)
      .toBe("2026");
  });

  it("reads JLBC's own two-digit naming convention", () => {
    expect(guessMeta("27baseline-axs.pdf")).toMatchObject({
      fiscal_year: 2027,
      doc_type: "baseline-per-agency",
      publisher: "jlbc",
    });
    expect(guessMeta("25ar-axs.pdf")).toMatchObject({
      fiscal_year: 2025,
      doc_type: "approps-per-agency",
    });
    expect(guessMeta("AFR25 COMBINED.pdf")).toMatchObject({
      doc_type: "afr",
      publisher: "agao",
    });
  });

  it("accepts a dropped file", async () => {
    render(<Upload />);
    const file = pdf("dropped.pdf");
    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: { files: [file] },
    });
    expect(await screen.findByText("dropped.pdf")).toBeTruthy();
  });

  it("states the honest processing time", async () => {
    render(<Upload />);
    await pickFile();
    expect(screen.getByText(/process overnight/i)).toBeTruthy();
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
    await pickFile(pdf("27baseline-axs.pdf"));
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add to the queue/i }));

    await waitFor(() => expect(upload).toHaveBeenCalled());
    const [file, meta] = upload.mock.calls[0];
    expect(file.name).toBe("27baseline-axs.pdf");
    expect(meta).toMatchObject({
      corpus: "budget", publisher: "jlbc",
      doc_type: "baseline-per-agency", fiscal_year: 2027,
    });
    expect(await screen.findByText(/added to the queue/i)).toBeTruthy();
  });

  it("shows the server's reason when the upload is rejected", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValue(
      new Error("upload: notes.txt is not a PDF or DOCX."),
    );
    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add to the queue/i }));
    expect(await screen.findByText(/is not a PDF or DOCX/i)).toBeTruthy();
  });

  it("offers re-processing when the document is already in the corpus", async () => {
    const upload = vi.spyOn(api, "uploadDocument")
      .mockRejectedValueOnce(new api.DuplicateDocumentError({
        detail: "already in corpus",
        existing_doc_id: "jlbc-baseline-fy2027-axs",
        added_at: "2026-07-01T12:00:00+00:00",
        added_by: "DMOSS",
      }))
      .mockResolvedValueOnce({ job_id: "j2", doc_id: "d1" });

    render(<Upload />);
    await pickFile();
    fireEvent.click(screen.getByRole("checkbox", { name: /public record/i }));
    fireEvent.click(screen.getByRole("button", { name: /add to the queue/i }));

    const dupe = await screen.findByTestId("duplicate");
    expect(dupe.textContent).toMatch(/already in the corpus/i);
    expect(dupe.textContent).toMatch(/DMOSS/);

    fireEvent.click(within(dupe).getByRole("button", { name: /again/i }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[1][1].reprocess).toBe(true);
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
