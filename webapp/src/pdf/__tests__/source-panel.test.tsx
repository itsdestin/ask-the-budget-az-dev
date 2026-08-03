// SourcePanel — the search page's source drawer. New in Plan 4 Task 11 (the
// retired app had no search surface), so these tests are written rather than
// carried. What they pin:
//   - a PDF-backed chunk shows the page chrome AND the verbatim cited text;
//   - a source with no page image shows the BACKEND's 415 sentence and no
//     PDF chrome, but still shows the text — a DOCX bill is verifiable too
//     (Core Invariant 1 makes no exception for file format);
//   - a failed fetch surfaces the backend's own detail, not a bare status.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    // The full-PDF escape hatch points at the streaming route. Task 15
    // shortened the link text from "Open original ↗" to "Open ↗" when the
    // breadcrumb and toolbar merged into one header row — the query below
    // is adjusted to match, the assertion's meaning (the href) is not.
    expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute(
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

  it("drops a response whose chunk_id is not the one it asked for", async () => {
    // The identity guard, isolated from the timing guard: nothing was torn
    // down here, the answer simply isn't for this chunk. Rendering it would
    // put one passage's text under another passage's title — a provenance
    // lie, and the exact failure this surface exists to prevent. The route
    // echoes chunk_id back so this comparison is possible.
    vi.spyOn(api, "chunk").mockResolvedValue({
      ...PDF_CHUNK,
      chunk_id: "c1",
      text: "STALE passage belonging to c1",
    });
    const view = render(
      <SourcePanel chunkId="c2" docTitle="AHCCCS" onClose={() => {}} />,
    );
    await waitFor(() => expect(api.chunk).toHaveBeenCalledWith("c2", "budget"));
    // Flush the resolved promise's continuation.
    await act(async () => {});
    expect(view.container.textContent).not.toContain("STALE passage");
    // Still waiting, rather than confidently showing the wrong source.
    expect(screen.getByText("Loading source…")).toBeInTheDocument();
  });

  it("keeps the newer passage when an older request answers late", async () => {
    // The ordinary double-click race: c1's fetch is still in flight when the
    // analyst clicks c2, and c1 answers afterwards.
    let answerFirst!: (c: api.ChunkSource) => void;
    vi.spyOn(api, "chunk")
      .mockImplementationOnce(
        () => new Promise<api.ChunkSource>((res) => (answerFirst = res)),
      )
      .mockResolvedValue({ ...PDF_CHUNK, chunk_id: "c2", text: "SECOND passage" });

    const props = { docTitle: "AHCCCS", onClose: () => {} };
    const view = render(<SourcePanel chunkId="c1" {...props} />);
    // Same mounted panel, new chunk — the shape a caller that does NOT re-key
    // the component would produce (Search.tsx does re-key; the component must
    // be correct either way).
    view.rerender(<SourcePanel chunkId="c2" {...props} />);
    await screen.findByText(/SECOND passage/);

    await act(async () => {
      answerFirst({ ...PDF_CHUNK, chunk_id: "c1", text: "STALE passage" });
    });
    expect(view.container.textContent).not.toContain("STALE passage");
    expect(view.container.textContent).toContain("SECOND passage");
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
