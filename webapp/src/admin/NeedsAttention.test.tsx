import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type * as api from "../api";
import { NeedsAttention } from "./NeedsAttention";

// The FY2024 AFR shape (STATUS.md, ingest/coverage.py) is the fixture
// throughout: OpenDataLoader and MinerU both stall at 2%, MinerU (OCR)
// recovers 1%, and the document is held out of search rather than written
// with almost nothing in it.
function held(over: Partial<api.AttentionDocument> = {}): api.AttentionDocument {
  return {
    job_id: "20260812T120000Z-afr24",
    title: "AGAO Annual Financial Report FY2024",
    message:
      "Held out of search — only 2% of this document's text produced any "
      + "content, after 3 extraction methods were tried.",
    best_coverage: 0.02,
    attempts: [
      { extractor: "opendataloader", coverage: 0.02 },
      { extractor: "mineru", coverage: 0.02 },
      { extractor: "mineru-ocr", coverage: 0.01 },
    ],
    ...over,
  };
}

function setup(documents: api.AttentionDocument[]) {
  const onRetry = vi.fn();
  const onDismiss = vi.fn();
  const utils = render(
    <NeedsAttention documents={documents} onRetry={onRetry} onDismiss={onDismiss} />,
  );
  return { onRetry, onDismiss, ...utils };
}

describe("NeedsAttention", () => {
  it("renders nothing at all when no document needs attention", () => {
    const { container } = setup([]);
    // Not an empty-state message, not a "0" badge — literally nothing on
    // the page. An admin should not be shown a box explaining that
    // nothing is wrong (the same rule NoticesPanel already follows).
    expect(container).toBeEmptyDOMElement();
  });

  it("names the symptom, not the mechanism", () => {
    setup([held()]);
    // The job's own honest sentence, verbatim — never rebuilt into
    // internal vocabulary like "coverage ratio below COVERAGE_FLOOR" or
    // "the extractor returned few blocks".
    expect(
      screen.getByText(/only 2% of this document's text produced any content/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/COVERAGE_FLOOR/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/few blocks/i)).not.toBeInTheDocument();
    // All five banned words the honesty rule names (the comment atop this
    // file, and ingest/coverage.py) -- a regex covering only three of them
    // once let the sentence "This document was checked and looks good."
    // through with every one of these ten specs still green.
    expect(
      screen.queryByText(/verified|checked|validated|healthy|good/i),
    ).not.toBeInTheDocument();
  });

  it("labels the attempt list 'Tried:', matching the agreed layout", () => {
    // task-7-brief.md's owner-approved sketch captions the extractor/score
    // rows with "Tried:" -- without it they're three bare pairs with
    // nothing on the page saying what they are.
    setup([held()]);
    const doc = screen.getByTestId("admin-attention-doc");
    expect(within(doc).getByText("Tried:")).toBeInTheDocument();
  });

  it("lists every attempt with its score", () => {
    setup([held()]);
    const doc = screen.getByTestId("admin-attention-doc");
    expect(within(doc).getByText("OpenDataLoader")).toBeInTheDocument();
    expect(within(doc).getByText("MinerU")).toBeInTheDocument();
    expect(within(doc).getByText("MinerU (OCR)")).toBeInTheDocument();
    // Two rungs both scored 2% -- both instances must render, not just one
    // deduplicated pill, or a reader can't tell three rungs were tried.
    expect(within(doc).getAllByText("2%")).toHaveLength(2);
    expect(within(doc).getByText("1%")).toBeInTheDocument();
  });

  it("renders an unmeasured rung honestly, never as 0%", () => {
    setup([
      held({
        attempts: [
          { extractor: "opendataloader", coverage: null },
          { extractor: "mineru", coverage: 0.02 },
        ],
        best_coverage: 0.02,
      }),
    ]);
    const doc = screen.getByTestId("admin-attention-doc");
    expect(within(doc).getByText("not measured")).toBeInTheDocument();
    expect(within(doc).queryByText("0%")).not.toBeInTheDocument();
  });

  it("renders a coverage ratio above 100% honestly, never capped", () => {
    // Real, calibrated behaviour (ingest/coverage.py): a healthy AFR can
    // score up to ~286% because its own text layer undercounts. This
    // panel only ever shows a HELD-BACK document, but the renderer must
    // still never clamp the number if it appears.
    setup([held({ attempts: [{ extractor: "mineru", coverage: 2.86 }] })]);
    expect(screen.getByText("286%")).toBeInTheDocument();
  });

  it("shows the count beside the heading", () => {
    setup([held(), held({ job_id: "job-2", title: "Another document" })]);
    expect(screen.getByTestId("admin-attention-count")).toHaveTextContent("2");
  });

  it("calls onRetry with the job id when Try again is clicked", () => {
    const { onRetry } = setup([held()]);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledWith("20260812T120000Z-afr24");
  });

  it("asks twice before dismissing", () => {
    // Same rule the chat-history delete follows: the armed state is a
    // labelled word, not the same glyph. Dismissing hides a document from
    // the only surface that reports it.
    const { onDismiss } = setup([held()]);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    // The FIRST click must not have dismissed anything yet.
    expect(onDismiss).not.toHaveBeenCalled();

    const confirm = screen.getByRole("button", { name: /Confirm dismiss/i });
    expect(confirm).toHaveTextContent("Dismiss?");
    fireEvent.click(confirm);

    expect(onDismiss).toHaveBeenCalledWith("20260812T120000Z-afr24");
  });

  it("un-arms the confirm state on blur", () => {
    setup([held()]);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    fireEvent.blur(screen.getByRole("button", { name: /Confirm dismiss/i }));
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("arming one document's dismiss does not arm another's", () => {
    const { onDismiss } = setup([
      held(),
      held({ job_id: "job-2", title: "Another document" }),
    ]);
    fireEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);

    // The second document's Dismiss button must still read the unarmed
    // label -- a shared boolean instead of a per-id id would arm both.
    const secondDoc = screen.getAllByTestId("admin-attention-doc")[1];
    expect(within(secondDoc).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();

    fireEvent.click(within(secondDoc).getByRole("button", { name: "Dismiss" }));
    const secondConfirm = within(secondDoc).getByRole("button", { name: /Confirm dismiss/i });
    fireEvent.click(secondConfirm);
    expect(onDismiss).toHaveBeenCalledWith("job-2");
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
