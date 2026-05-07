"use client";

// Side-panel PDF viewer. Subscribes to citation-bus selections and
// renders the cited page via PdfPage (pdfjs-dist + canvas) with a
// bbox highlight overlay matching spec §10.2.
//
// PdfPage is dynamically imported so pdfjs-dist (which references
// `window` at module load) doesn't bleed into the SSR pass. The
// breadcrumb + empty state are SSR-safe and stay statically
// imported.

import dynamic from "next/dynamic";
import { useState } from "react";

import type { Citation } from "@/lib/citation-extract";
import { useCitationSelected } from "@/state/citation-context";

const PdfPage = dynamic(() => import("./PdfPage"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center text-fg-muted text-sm py-12">
      Loading PDF viewer…
    </div>
  ),
});

interface SelectedDoc {
  citation: Citation;
}

export default function PdfViewer() {
  const [selected, setSelected] = useState<SelectedDoc | null>(null);
  // Track the last-clicked unresolved citation so we can show
  // *which* citation we couldn't load, instead of looking
  // identical to the no-clicks-yet state.
  const [unresolvedClick, setUnresolvedClick] = useState<Citation | null>(
    null,
  );

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
    setSelected({ citation });
  });

  if (selected) {
    return <Loaded selected={selected} />;
  }
  if (unresolvedClick) {
    return <UnresolvedState citation={unresolvedClick} />;
  }
  return <EmptyState />;
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-fg-muted text-sm px-6 py-12 bg-canvas">
      <div className="max-w-sm text-center space-y-2">
        <h2 className="text-base font-bold text-fg">Source viewer</h2>
        <p>
          Click a citation chip in the chat to load the source PDF here. The
          viewer will jump to the cited page and highlight the cited region.
        </p>
        <p className="text-xs text-fg-faint">
          DOCX-source citations (legislative bills) will get their own viewer
          in Phase 2.
        </p>
      </div>
    </div>
  );
}

function UnresolvedState({ citation }: { citation: Citation }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-fg-muted text-sm px-6 py-12 bg-canvas">
      <div className="max-w-md text-left space-y-3">
        <h2 className="text-base font-bold text-fg">
          Couldn't open source PDF
        </h2>
        <p>
          The citation Claude emitted (chip{" "}
          <span className="font-mono text-fg-2">[{citation.index}]</span>)
          references chunk{" "}
          <span className="font-mono text-fg-2">{citation.chunkId}</span>, but
          the retrieve() call in this turn didn't surface a doc_id or
          page_start for it.
        </p>
        <p className="text-xs text-fg-faint">
          Common causes: the model is citing a chunk_id from prior context, or
          the chunk's source isn't a PDF (legislative bills are DOCX, viewer
          comes in Phase 2). Open the cite tool card in the chat for the raw
          chunk_id and re-ask if you want a fresh retrieve().
        </p>
        {citation.claimSpan && (
          <blockquote className="mt-3 border-l-2 border-edge pl-3 text-fg-dim italic text-xs">
            {citation.claimSpan}
          </blockquote>
        )}
      </div>
    </div>
  );
}

function Loaded({ selected }: { selected: SelectedDoc }) {
  const { citation } = selected;
  const r = citation.resolved!;
  const docId = r.docId;
  const page = r.pageStart!;
  const docTitle = r.docTitle || docId;
  const bbox = r.bbox;

  return (
    <div className="h-full flex flex-col bg-canvas">
      <Breadcrumb docTitle={docTitle} page={page} citation={citation} />
      <div className="flex-1 min-h-0 overflow-auto">
        <PdfPage docId={docId} pageNumber={page} bbox={bbox} />
      </div>
    </div>
  );
}

function Breadcrumb({
  docTitle,
  page,
  citation,
}: {
  docTitle: string;
  page: number;
  citation: Citation;
}) {
  const r = citation.resolved!;
  return (
    <div className="border-b border-edge bg-panel/60 px-3 py-2 text-xs flex items-center gap-2">
      <span className="text-fg-muted shrink-0">Page</span>
      <span className="text-fg font-bold">{page}</span>
      <span className="text-fg-muted">of</span>
      <span className="text-fg-2 font-medium truncate" title={docTitle}>
        {docTitle}
      </span>
      {r.fiscalYear != null && (
        <span className="text-fg-faint ml-auto shrink-0">
          FY{r.fiscalYear}
        </span>
      )}
    </div>
  );
}
