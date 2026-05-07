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

  useCitationSelected((citation) => {
    if (!citation.resolved?.docId || citation.resolved.pageStart == null) {
      // No source metadata in this turn — chip click can't navigate
      // to a file. Surface the empty state with a hint instead of
      // dropping the click silently.
      setSelected(null);
      return;
    }
    setSelected({ citation });
  });

  if (!selected) {
    return <EmptyState />;
  }
  return <Loaded selected={selected} />;
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
