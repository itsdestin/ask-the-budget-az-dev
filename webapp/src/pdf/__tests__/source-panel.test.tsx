// SourcePanel — the search page's source drawer. New in Plan 4 Task 11 (the
// retired app had no search surface), so these tests are written rather than
// carried. What they pin:
//   - a PDF-backed chunk shows the page chrome AND the verbatim cited text;
//   - a source with no page image shows the BACKEND's 415 sentence and no
//     PDF chrome, but still shows the text — a DOCX bill is verifiable too
//     (Core Invariant 1 makes no exception for file format);
//   - a failed fetch surfaces the backend's own detail, not a bare status.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as api from "../../api";
import { SourcePanel } from "../SourcePanel";

const PDF_CHUNK: api.ChunkSource = {
  chunk_id: "c1",
  doc_id: "jlbc-baseline-fy2027-ahcccs",
  page: 47,
  bbox: [10, 20, 100, 40],
  text: "The Aviation Fund got $2,587,400 in FY 2026.",
  source_format: "pdf",
  pdf_unavailable_reason: null,
};

const DOCX_REASON =
  "This source is a docx file, not a PDF, so there is no page to display. " +
  "Show the cited text panel instead — the passage and its citation are still valid.";

function panel(overrides: Partial<api.ChunkSource> = {}) {
  vi.spyOn(api, "chunk").mockResolvedValue({ ...PDF_CHUNK, ...overrides });
  return render(
    <SourcePanel
      chunkId="c1"
      docTitle="AHCCCS — FY 2027 Baseline"
      fiscalYear={2027}
      onClose={() => {}}
    />,
  );
}

describe("SourcePanel", () => {
  it("fetches the clicked chunk and shows its page + verbatim text", async () => {
    const view = panel();
    await waitFor(() =>
      expect(screen.getByText("AHCCCS — FY 2027 Baseline")).toBeInTheDocument(),
    );
    expect(api.chunk).toHaveBeenCalledWith("c1", "budget");
    // Breadcrumb page number and the always-visible cited-text panel.
    expect(view.container.textContent).toContain("47");
    expect(view.container.textContent).toContain("Cited text from this chunk");
    expect(view.container.textContent).toContain("$2,587,400");
    // The full-PDF escape hatch points at the streaming route.
    expect(screen.getByRole("link", { name: /open original/i })).toHaveAttribute(
      "href",
      "/api/pdf/jlbc-baseline-fy2027-ahcccs#page=47",
    );
  });

  it("shows the backend's own wording and no PDF chrome for a non-PDF source", async () => {
    const view = panel({
      source_format: "docx",
      pdf_unavailable_reason: DOCX_REASON,
      page: null,
      bbox: null,
    });
    await waitFor(() =>
      expect(view.container.textContent).toContain("Couldn’t open source PDF"),
    );
    // Verbatim backend copy — the UI must not paraphrase the 415 detail.
    expect(view.container.textContent).toContain(DOCX_REASON);
    // No zoom toolbar, no "open original" link: there is no PDF to open.
    expect(screen.queryByRole("link", { name: /open original/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /zoom in/i })).toBeNull();
    // …but the passage is still verifiable by eye.
    expect(view.container.textContent).toContain("$2,587,400");
  });

  it("surfaces the backend's detail when the chunk can't be fetched", async () => {
    vi.spyOn(api, "chunk").mockRejectedValue(
      new Error("chunk: No chunk named 'c1' is in the budget corpus."),
    );
    render(
      <SourcePanel chunkId="c1" docTitle="AHCCCS" onClose={() => {}} />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No chunk named 'c1'/)).toBeInTheDocument(),
    );
  });

  it("closes on the close button and on Escape", async () => {
    const onClose = vi.fn();
    vi.spyOn(api, "chunk").mockResolvedValue(PDF_CHUNK);
    render(<SourcePanel chunkId="c1" docTitle="AHCCCS" onClose={onClose} />);
    // Settle the fetch before interacting, so the click isn't racing an
    // in-flight state update (React logs an act() warning when it is).
    await screen.findByText("Cited text from this chunk");
    fireEvent.click(screen.getByRole("button", { name: /close source panel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
