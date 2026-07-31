// Search-page source drawer. A matching-passage row is clicked; this fetches
// that chunk's provenance fields and hands them to the shared SourceView.
//
// WHY a drawer instead of a third column: the search results layout was
// iterated live with Destin (Plan 2's "As shipped" note) and spec S12 says not
// to restructure it. A drawer overlays the page, so the results underneath are
// untouched — the wiring in Search.tsx is a click handler and this component,
// nothing else.
//
// Every request is guarded against its own staleness: click passage A, click
// passage B before A answers, and A's response must not paint over B. Two
// guards, because they answer different questions — a torn-down effect's
// closure flag says "something newer exists", and the echoed chunk_id says
// "this answer is for the chunk I asked about". Only the second one can catch
// a response landing under the wrong title, which on a provenance surface is
// the failure that matters.

import { useEffect, useState } from "react";

import * as api from "../api";
import type { ChunkSource } from "../api";
import { SourceView } from "./SourceView";

export interface SourcePanelProps {
  /** The clicked passage's chunk_id. */
  chunkId: string;
  /** Corpus the search ran against ("budget" | "fiscal_notes"). */
  corpus?: string;
  /** Display title for the breadcrumb. Supplied by the caller because the
   *  search row already renders it — see get_chunk's docstring for why the
   *  route deliberately does not return a second, conflicting title. */
  docTitle: string;
  fiscalYear?: number | null;
  onClose(): void;
}

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; chunk: ChunkSource };

export function SourcePanel({
  chunkId,
  corpus = "budget",
  docTitle,
  fiscalYear,
  onClose,
}: SourcePanelProps) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let ignore = false;
    setState({ kind: "loading" });
    api.chunk(chunkId, corpus).then(
      (chunk) => {
        if (ignore) return;
        // Identity, not just timing. `ignore` catches the ordinary stale case
        // (this effect was torn down before the answer arrived), but it can
        // only ever say "a newer request exists", never "this answer is for
        // the right chunk" — and an answer for the WRONG chunk rendered under
        // the right title is a provenance lie, which is the one failure this
        // whole surface exists to prevent. The route echoes chunk_id back for
        // exactly this comparison; a mismatch is dropped rather than shown.
        if (chunk.chunk_id !== chunkId) return;
        setState({ kind: "ready", chunk });
      },
      (err: unknown) => {
        if (ignore) return;
        // The api client already carries the backend's own `detail`; show it
        // verbatim rather than guessing at the cause.
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      },
    );
    return () => {
      ignore = true;
    };
  }, [chunkId, corpus]);

  // Escape closes, same as the report-format chooser on this page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="pdf-drawer" aria-label="Source passage">
      <div className="pdf-drawer-head">
        <span className="pdf-drawer-title">Source</span>
        <button
          type="button"
          className="pdf-drawer-close"
          aria-label="Close source panel"
          onClick={onClose}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </div>
      {state.kind === "loading" && (
        <p className="pdf-drawer-status" role="status">
          Loading source…
        </p>
      )}
      {state.kind === "error" && (
        <p className="pdf-drawer-status pdf-drawer-error" role="status">
          {state.message}
        </p>
      )}
      {state.kind === "ready" && (
        <SourceView
          docId={state.chunk.doc_id}
          page={state.chunk.page}
          bbox={state.chunk.bbox}
          chunkText={state.chunk.text}
          // A search passage has no cited span — nothing claimed anything
          // about it yet. Equal offsets are CitedTextPanel's documented
          // "no span" sentinel: whole chunk, no underline.
          spanStart={0}
          spanEnd={0}
          docTitle={docTitle}
          fiscalYear={fiscalYear}
          sourceLabel={
            state.chunk.page != null
              ? `${docTitle}, p. ${state.chunk.page}`
              : docTitle
          }
          pdfUnavailable={state.chunk.pdf_unavailable_reason}
        />
      )}
    </aside>
  );
}
