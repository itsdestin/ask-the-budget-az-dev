// Side-panel PDF viewer for AI Mode. Subscribes to citation-bus selections
// and renders the cited page (SourceView -> PdfPage) with the highlight
// overlay, per spec §10.2.
//
// This component IS the mechanism behind the promise the system prompt makes
// to the model — "The interface parses every cite() call and renders a marker
// on the claim, linking it to its source page in the document viewer."
// Task 10 wired the chip to `bus.select(citation)`; the subscription below is
// the other end of that wire, and the only integration point between the chat
// surface and this one.
//
// Ported from web/components/PdfViewer.tsx (Plan 4 Task 11). Deltas: the
// `Loaded` body moved into SourceView so the search page can reuse it,
// next/dynamic became React.lazy (inside SourceView), and the Tailwind
// classes became `pdf-`-prefixed semantic ones.
//
// Task 15: `onClose` is threaded through from AiModePanel, which used to
// float its own close button on top of this whole panel. That button now
// lives INSIDE SourceView's merged header for the loaded state; the empty
// and unresolved states below have no header row, so they keep a floating
// variant (`FloatingClose`) — the panel must be closable in every state.

import { useState } from "react";

import type { Citation } from "../chat/citation-extract";
import { formatCopyCitation } from "../chat/citation-extract";
import { useCitationSelected } from "../chat/citation-context";
import Mascot from "../chat/mascot/Mascot";
import { SourceView } from "./SourceView";

export default function PdfViewer({ onClose }: { onClose?: () => void } = {}) {
  const [selected, setSelected] = useState<Citation | null>(null);
  // Track the last-clicked unresolved citation so we can show
  // *which* citation we couldn't load, instead of looking
  // identical to the no-clicks-yet state.
  const [unresolvedClick, setUnresolvedClick] = useState<Citation | null>(null);

  useCitationSelected((citation) => {
    if (!citation.resolved?.docId || citation.resolved.pageStart == null) {
      // No source metadata for this chunk — likely the retrieve()
      // result didn't carry doc_id/page_start, or the chunk_id
      // came from a previous turn the renderer doesn't have on hand.
      // Surface that explicitly so the user knows the click landed.
      setUnresolvedClick(citation);
      setSelected(null);
      return;
    }
    setUnresolvedClick(null);
    setSelected(citation);
  });

  if (selected) return <Loaded citation={selected} onClose={onClose} />;
  if (unresolvedClick)
    return <UnresolvedState citation={unresolvedClick} onClose={onClose} />;
  return <EmptyState onClose={onClose} />;
}

/** Floating × — the same class + markup AiModePanel used to render directly
 *  over this whole panel before Task 15 moved the loaded-state close button
 *  into SourceView's merged header. The empty and unresolved states have no
 *  header row to put a close button in, so they keep this absolutely
 *  positioned variant instead (`.ai-source-close`'s own CSS positions it
 *  top-right of `.pdf-empty`, which Task 15 gave `position: relative`). */
function FloatingClose({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      className="ai-source-close"
      aria-label="Close source panel"
      onClick={onClose}
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path
          d="M3 3l10 10M13 3L3 13"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    </button>
  );
}

function EmptyState({ onClose }: { onClose?: () => void }) {
  return (
    <div className="pdf-empty">
      {onClose && <FloatingClose onClose={onClose} />}
      <div className="pdf-empty-inner">
        {/* Mascot with clipboard pose — welcoming prompt to click a citation. */}
        <Mascot pose="clipboard" size="hero" />
        <p>Click a citation to see its source.</p>
      </div>
    </div>
  );
}

function UnresolvedState({
  citation,
  onClose,
}: {
  citation: Citation;
  onClose?: () => void;
}) {
  return (
    <div className="pdf-empty">
      {onClose && <FloatingClose onClose={onClose} />}
      <div className="pdf-unresolved">
        {/* Task 15: plain-language headline first; the raw chunk_id and chip
            index used to lead the copy, which reads as an internal error
            message rather than something a non-developer analyst can act
            on. They still appear below — an analyst reporting a bad
            citation needs something concrete to quote. */}
        <h2>Couldn&rsquo;t find the source page</h2>
        <p>
          This citation points at a passage the current view can&rsquo;t
          locate — usually because it comes from an earlier question, or
          because the source is a Word document rather than a PDF.
        </p>
        {citation.claimSpan && (
          <blockquote className="pdf-unresolved-quote">
            {citation.claimSpan}
          </blockquote>
        )}
        <p className="pdf-unresolved-note">
          Ask the question again to refresh the sources. Reference: chip{" "}
          <span className="pdf-mono">[{citation.index}]</span>, passage{" "}
          <span className="pdf-mono">{citation.chunkId}</span>.
        </p>
      </div>
    </div>
  );
}

function Loaded({
  citation,
  onClose,
}: {
  citation: Citation;
  onClose?: () => void;
}) {
  const r = citation.resolved!;
  return (
    <SourceView
      docId={r.docId}
      page={r.pageStart!}
      bbox={r.bbox}
      chunkText={r.text ?? ""}
      spanStart={citation.spanStart}
      spanEnd={citation.spanEnd}
      sourceText={citation.sourceText}
      docTitle={r.docTitle || r.docId}
      fiscalYear={r.fiscalYear}
      sourceLabel={formatCopyCitation(citation)}
      onClose={onClose}
    />
  );
}
