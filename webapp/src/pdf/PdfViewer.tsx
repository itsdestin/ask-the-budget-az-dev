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

import { useState } from "react";

import type { Citation } from "../chat/citation-extract";
import { formatCopyCitation } from "../chat/citation-extract";
import { useCitationSelected } from "../chat/citation-context";
import Mascot from "../chat/mascot/Mascot";
import { SourceView } from "./SourceView";

export default function PdfViewer() {
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

  if (selected) return <Loaded citation={selected} />;
  if (unresolvedClick) return <UnresolvedState citation={unresolvedClick} />;
  return <EmptyState />;
}

function EmptyState() {
  return (
    <div className="pdf-empty">
      <div className="pdf-empty-inner">
        {/* Mascot with clipboard pose — welcoming prompt to click a citation. */}
        <Mascot pose="clipboard" size="hero" />
        <p>Click a citation to see its source.</p>
      </div>
    </div>
  );
}

function UnresolvedState({ citation }: { citation: Citation }) {
  return (
    <div className="pdf-empty">
      <div className="pdf-unresolved">
        <h2>Couldn&rsquo;t open source PDF</h2>
        <p>
          The citation the model emitted (chip{" "}
          <span className="pdf-mono">[{citation.index}]</span>) references chunk{" "}
          <span className="pdf-mono">{citation.chunkId}</span>, but the
          retrieve() call in this turn didn&rsquo;t surface a doc_id or
          page_start for it.
        </p>
        <p className="pdf-unresolved-note">
          Common causes: the model is citing a chunk_id from prior context, or
          the chunk&rsquo;s source isn&rsquo;t a PDF (legislative bills are
          DOCX, viewer comes in Phase 2). Open the cite tool card in the chat
          for the raw chunk_id and re-ask if you want a fresh retrieve().
        </p>
        {citation.claimSpan && (
          <blockquote className="pdf-unresolved-quote">
            {citation.claimSpan}
          </blockquote>
        )}
      </div>
    </div>
  );
}

function Loaded({ citation }: { citation: Citation }) {
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
    />
  );
}
