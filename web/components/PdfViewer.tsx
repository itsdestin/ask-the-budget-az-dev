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
import { useEffect, useMemo, useRef, useState } from "react";

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

// Zoom range — fit-to-width is the floor (1.0). The cap is generous
// for tabular pages where the user wants to read line-item rows.
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

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

  // The exact source text the model said supports this claim. cite()
  // emits character offsets (span_start, span_end) into the chunk
  // text — chunk.text[start:end] is what was extracted FROM the
  // PDF text layer for this specific assertion. This is what we
  // want to highlight on the PDF, NOT claim_span (which is the
  // model's answer text and rarely appears verbatim in the source).
  // When the offsets are missing or invalid, fall back to the full
  // chunk text. The PdfPage tries each search target in order and
  // falls back to the chunk bbox as a last resort.
  const searchTexts = useMemo(() => {
    const texts: string[] = [];
    if (
      r.text &&
      citation.spanStart >= 0 &&
      citation.spanEnd > citation.spanStart
    ) {
      const start = Math.max(0, citation.spanStart);
      const end = Math.min(r.text.length, citation.spanEnd);
      if (end > start) texts.push(r.text.slice(start, end));
    }
    if (r.text) texts.push(r.text);
    return texts;
  }, [r.text, citation.spanStart, citation.spanEnd]);

  // Zoom multiplier on top of the fit-to-width scale. 1.0 = page
  // exactly fills the container width on first load, which is what
  // the user asked for ("see the full page without scrolling").
  // Reset when navigating to a different doc/page so a new chip
  // click never inherits a zoomed-in state from the prior view.
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    setZoom(1);
  }, [docId, page]);

  // Measure the scrolling container so PdfPage knows what to fit to.
  // ResizeObserver tracks both the side panel resizing and the
  // window changing size mid-session.
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setContainerWidth(el.clientWidth);
    // ResizeObserver isn't available in jsdom (used by vitest); the
    // initial clientWidth read above is enough for tests. In real
    // browsers we observe so a side-panel drag or window resize
    // re-fits the page without a manual reload.
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // contentRect.width excludes scrollbar gutter — the right
        // measurement when the canvas is the only flow child.
        setContainerWidth(entry.contentRect.width);
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const zoomIn = () =>
    setZoom((z) => Math.min(MAX_ZOOM, Math.round((z + ZOOM_STEP) * 100) / 100));
  const zoomOut = () =>
    setZoom((z) => Math.max(MIN_ZOOM, Math.round((z - ZOOM_STEP) * 100) / 100));
  const resetZoom = () => setZoom(1);

  return (
    <div className="h-full flex flex-col bg-canvas">
      <Breadcrumb docTitle={docTitle} page={page} citation={citation} />
      <Toolbar
        zoom={zoom}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onResetZoom={resetZoom}
        docId={docId}
        page={page}
      />
      <div
        ref={scrollerRef}
        className="flex-1 min-h-0 overflow-auto p-3 bg-inset"
      >
        {containerWidth > 0 && (
          <PdfPage
            docId={docId}
            pageNumber={page}
            bbox={bbox}
            searchTexts={searchTexts}
            // Subtract horizontal padding (12px each side from p-3)
            // so the canvas actually fits without forcing a
            // horizontal scrollbar at zoom=1.
            containerWidth={Math.max(0, containerWidth - 24)}
            zoomLevel={zoom}
          />
        )}
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

/** Bar above the rendered page: zoom controls + "open original PDF"
 *  link. The link target opens the API's full-PDF response in a
 *  new tab — Range-streamed, so opening the full doc is cheap. */
function Toolbar({
  zoom,
  onZoomIn,
  onZoomOut,
  onResetZoom,
  docId,
  page,
}: {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetZoom: () => void;
  docId: string;
  page: number;
}) {
  // pdfjs's URL fragment `#page=N` is the standard PDF Open Parameters
  // syntax; Chrome/Edge/Firefox built-in viewers all honor it.
  const fullDocHref = `/api/pdf/${encodeURIComponent(docId)}#page=${page}`;
  const zoomLabel = `${Math.round(zoom * 100)}%`;
  return (
    <div className="border-b border-edge bg-panel/40 px-3 py-1.5 text-xs flex items-center gap-1">
      <button
        type="button"
        onClick={onZoomOut}
        aria-label="Zoom out"
        className="px-2 py-1 rounded-sm border border-edge bg-inset hover:bg-canvas text-fg-2 disabled:opacity-40"
        disabled={zoom <= MIN_ZOOM + 0.001}
      >
        −
      </button>
      <button
        type="button"
        onClick={onResetZoom}
        aria-label="Reset zoom to fit width"
        className="px-2 py-1 rounded-sm border border-edge bg-inset hover:bg-canvas text-fg-2 min-w-[3.5rem] tabular-nums"
        title="Click to reset to fit-to-width"
      >
        {zoomLabel}
      </button>
      <button
        type="button"
        onClick={onZoomIn}
        aria-label="Zoom in"
        className="px-2 py-1 rounded-sm border border-edge bg-inset hover:bg-canvas text-fg-2 disabled:opacity-40"
        disabled={zoom >= MAX_ZOOM - 0.001}
      >
        +
      </button>
      <a
        href={fullDocHref}
        target="_blank"
        rel="noopener noreferrer"
        className="ml-auto px-2 py-1 rounded-sm border border-edge bg-inset hover:bg-canvas text-fg-2"
        title="Open the full PDF in a new browser tab"
      >
        Open original ↗
      </a>
    </div>
  );
}
