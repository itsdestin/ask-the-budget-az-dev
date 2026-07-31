// Search page -> source drawer integration (Plan 4 Task 11, Step 2).
//
// This is the search-only half of the G3 findability check: with AI Mode off,
// clicking a matching passage still has to answer "where does this come
// from?". Lives here rather than in pages/Search.test.tsx so the whole port
// stays inside src/pdf/.
//
// The click path under test is a DELEGATED listener on `.results` matching
// `[data-chunk-id]` — the attribute Plan 2 left on the passage rows for
// exactly this task — so these tests also pin that the delegation reaches a
// row nested two levels inside ResultCard's tray.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import * as api from "../../api";
import { Search } from "../../pages/Search";

const RESULT = {
  chunk_id: "c1",
  doc_id: "jlbc-baseline-fy2027-ahcccs",
  doc_title: "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
  snippet: "…provider rate increases…",
  page: 14,
  score: 0.91,
  doc_type: "baseline-per-agency",
  fiscal_year: 2027,
  publisher: "jlbc",
  agencies: ["ahcccs"],
  doc_url: "https://www.azjlbc.gov/27baseline/axs.pdf",
  doc_meta: null,
};

const CHUNK: api.ChunkSource = {
  chunk_id: "c1",
  doc_id: "jlbc-baseline-fy2027-ahcccs",
  page: 14,
  bbox: [10, 20, 100, 40],
  text: "AHCCCS provider rate increases total $2,587,400 in FY 2027.",
  source_format: "pdf",
  pdf_unavailable_reason: null,
};

/** Render the search page with one result and open its passages tray. */
async function openPassages(result = RESULT) {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [result],
    total: 1,
    provider: "stub",
  });
  const view = render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}>
      <Search />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByText(/Health Care Cost Containment/)).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: /1 passage/i }));
  return view;
}

describe("search page source drawer", () => {
  it("opens the drawer for the clicked passage's chunk", async () => {
    const chunk = vi.spyOn(api, "chunk").mockResolvedValue(CHUNK);
    const view = await openPassages();

    const row = view.container.querySelector('[data-chunk-id="c1"]')!;
    expect(row).toBeTruthy();
    fireEvent.click(row);

    await waitFor(() => expect(chunk).toHaveBeenCalledWith("c1", "budget"));
    const drawer = await screen.findByLabelText("Source passage");
    // The drawer names the document the row named — the title travels from
    // the search row, so the two can never disagree.
    expect(drawer.textContent).toContain(
      "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
    );
    expect(drawer.textContent).toContain("$2,587,400");

    // …and closes again, leaving the results untouched.
    fireEvent.click(screen.getByRole("button", { name: /close source panel/i }));
    expect(screen.queryByLabelText("Source passage")).toBeNull();
    expect(screen.getByText(/Health Care Cost Containment/)).toBeInTheDocument();
  });

  it("never opens the viewer for a stub- chunk id", async () => {
    // StubSearchProvider's fixture rows exist in no corpus. Opening one would
    // show a 404 and imply the corpus is broken when the truth is that this
    // machine has no corpus at all.
    const chunk = vi.spyOn(api, "chunk").mockResolvedValue(CHUNK);
    const view = await openPassages({ ...RESULT, chunk_id: "stub-001" });

    fireEvent.click(view.container.querySelector('[data-chunk-id="stub-001"]')!);

    expect(chunk).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Source passage")).toBeNull();
  });

  it("falls back to the text panel when the passage's source is a DOCX bill", async () => {
    const reason =
      "This source is a docx file, not a PDF, so there is no page to display. " +
      "Show the cited text panel instead — the passage and its citation are still valid.";
    vi.spyOn(api, "chunk").mockResolvedValue({
      ...CHUNK,
      source_format: "docx",
      pdf_unavailable_reason: reason,
      page: null,
      bbox: null,
    });
    const view = await openPassages();
    fireEvent.click(view.container.querySelector('[data-chunk-id="c1"]')!);

    const drawer = await screen.findByLabelText("Source passage");
    await waitFor(() =>
      expect(drawer.textContent).toContain("Couldn’t open source PDF"),
    );
    expect(drawer.textContent).toContain(reason);
    expect(screen.queryByRole("link", { name: /open original/i })).toBeNull();
    // The passage text is still there to verify against.
    expect(drawer.textContent).toContain("$2,587,400");
  });

  it("leaves the results presentation alone (no new rows, no page navigation)", async () => {
    vi.spyOn(api, "chunk").mockResolvedValue(CHUNK);
    const view = await openPassages();
    const before = view.container.querySelector(".results")!.innerHTML;
    fireEvent.click(view.container.querySelector('[data-chunk-id="c1"]')!);
    await screen.findByLabelText("Source passage");
    // The drawer is a sibling overlay; the results markup is byte-identical.
    expect(view.container.querySelector(".results")!.innerHTML).toBe(before);
  });
});
