"use client";

// Side-panel PDF viewer. Subscribes to citation-bus selections and
// loads the corresponding PDF via /api/pdf/[doc_id], scrolling to
// the cited page through the standard PDF Open Parameters fragment
// (`#page=N`), which Chrome/Firefox/Edge native viewers honor and
// PDF.js itself supports as a fallback.
//
// v1 of WS4c uses a plain <embed> for the viewer surface — a 50-line
// shippable that gives us page-jumping, the breadcrumb, the empty
// state, and the bus wire-up. WS4c slice-3 upgrades the embed to a
// pdfjs-dist + canvas renderer so we can paint the spec §10.2
// bbox-highlight rectangle on top of the cited region. The
// component contract (props, bus subscription, breadcrumb) stays
// the same across the upgrade — only the renderer surface changes.

import { useEffect, useState } from "react";

import type { Citation } from "@/lib/citation-extract";
import { useCitationSelected } from "@/state/citation-context";

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
          viewer will jump to the cited page.
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

  // The <embed> element doesn't react to a fragment-only change in
  // its src — switching pages within the same doc requires a key
  // change so React unmounts and re-mounts. We key on docId + page;
  // same chip clicked twice replays the load, which is intended
  // (re-scrolls to page if the user has scrolled away).
  const [reloadCount, setReloadCount] = useState(0);
  useEffect(() => {
    setReloadCount((n) => n + 1);
  }, [docId, page]);

  // PDF Open Parameters: #page=N (standard, supported by Chrome,
  // Firefox, Edge, and PDF.js). zoom + view modes vary by viewer
  // and aren't load-bearing for the spec UX.
  const src = `/api/pdf/${encodeURIComponent(docId)}#page=${page}&toolbar=1&navpanes=0`;

  return (
    <div className="h-full flex flex-col bg-canvas">
      <Breadcrumb docTitle={docTitle} page={page} citation={citation} />
      <div className="flex-1 min-h-0">
        <embed
          key={`${docId}:${page}:${reloadCount}`}
          src={src}
          type="application/pdf"
          className="w-full h-full"
          aria-label={`PDF: ${docTitle} at page ${page}`}
        />
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
