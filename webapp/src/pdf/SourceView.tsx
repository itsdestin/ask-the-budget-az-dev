// The provenance surface itself: one merged header (crumb + zoom + open +
// close) + the rendered PDF page + the always-visible cited-text panel
// underneath.
//
// Extracted from web/components/PdfViewer.tsx's `Loaded` sub-component (Plan 4
// Task 11) so BOTH entry points share one implementation:
//
//   - PdfViewer   — AI Mode. A citation chip is clicked, the citation bus
//                   fires, and the cited chunk's page is shown.
//   - SourcePanel — search-only mode. A matching-passage row is clicked and
//                   the same page is shown. This is the other half of the G3
//                   findability check: search without AI still has to answer
//                   "where does this come from?".
//
// Both promises the shipped system prompt makes are kept here: a citation
// links to its source page, and a source with no page image (DOCX bills,
// Plan 3's fiscal notes) still renders its verbatim text so the analyst can
// verify by eye.
//
// Task 15: the breadcrumb and the zoom toolbar used to be two stacked bars
// (`Breadcrumb` then `Toolbar`), which painted two white bands before any
// page pixels appeared. They are now one `SourceHead` row, and the close
// button AiModePanel used to float over this whole panel now lives at the
// right end of that row for the loaded state — see `onClose` below.

import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";

import CitedTextPanel from "./CitedTextPanel";

// pdfjs-dist is ~1 MB of JS that touches `window` at module load, and most
// sessions never open a page. React.lazy keeps it out of the initial bundle;
// the retired Next.js app used next/dynamic({ssr:false}) for the same reason.
const PdfPage = lazy(() => import("./PdfPage"));

// Zoom range — fit-to-width is the floor (1.0). The cap is generous
// for tabular pages where the user wants to read line-item rows.
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

export interface SourceViewProps {
  /** doc_id — the viewer streams `/api/pdf/{docId}`. */
  docId: string;
  /** 1-indexed page the chunk starts on. Null when the corpus recorded no
   *  page for this chunk — there is then nothing to render and the cited-text
   *  panel is the whole surface. */
  page: number | null;
  /** Chunk bbox, or null. Non-null means the text-layer search is STRICTLY
   *  restricted to it (see highlight-strategy.ts). */
  bbox: number[] | null;
  /** Verbatim chunk text stored at index time. */
  chunkText: string;
  /** Cited span within chunkText. Equal values = "no span" (the search
   *  page's passages have no cited span; whole-chunk display, no underline). */
  spanStart: number;
  spanEnd: number;
  /** The figure as the SOURCE renders it, when this view was opened
   *  from a system-linked figure chip. */
  sourceText?: string;
  /** Page the locate endpoint found the cited value on (spec L2). Wins
   *  over `page` when set — a merged chunk's stored page is its first
   *  paragraph's, and 7/137 live figures sat on a later page. */
  serverPage?: number | null;
  /** Exact highlight rects from the locate endpoint, PDF user-space
   *  points. Forwarded to PdfPage, which skips its text-layer search
   *  when they arrive. */
  serverRects?: number[][];
  /** Breadcrumb title. */
  docTitle: string;
  fiscalYear?: number | null;
  /** Label under the cited text ("JLBC FY26 Baseline, p. 47"). */
  sourceLabel: string;
  /** Non-null when the backend says this source has no page image — the
   *  string is the 415 route's own `detail`, not copy invented here. The
   *  PDF canvas is skipped entirely and the cited-text panel carries the
   *  verification burden. */
  pdfUnavailable?: string | null;
  /** Closes the panel. Optional: AI Mode's `PdfViewer` passes this so the
   *  merged header below can render a close button; the search page's
   *  `SourcePanel` passes nothing — it wraps this component in its own
   *  fixed drawer with its own navy header and close button, and rendering
   *  a second one here would be a duplicate. */
  onClose?: () => void;
}

export function SourceView({
  docId,
  page,
  bbox,
  chunkText,
  spanStart,
  spanEnd,
  sourceText,
  serverPage,
  serverRects,
  docTitle,
  fiscalYear,
  sourceLabel,
  pdfUnavailable,
  onClose,
}: SourceViewProps) {
  // The locate endpoint's page wins when it found the value: the stored
  // page is the chunk's FIRST paragraph's page, which is the wrong page
  // for a value cited from a later one (measured 7/137 live figures).
  const shownPage = serverPage ?? page;
  // The exact source text to highlight, most specific first. cite()
  // emits character offsets (span_start, span_end) into the chunk
  // text — chunk.text[start:end] is what was extracted FROM the
  // PDF text layer for this specific assertion. This is what we
  // want to highlight on the PDF, NOT claim_span (which is the
  // model's answer text and rarely appears verbatim in the source).
  // When the offsets are missing or invalid, fall back to the full
  // chunk text.
  const searchTexts = useMemo(() => {
    const texts: string[] = [];
    if (chunkText && spanStart >= 0 && spanEnd > spanStart) {
      const start = Math.max(0, spanStart);
      const end = Math.min(chunkText.length, spanEnd);
      if (end > start) texts.push(chunkText.slice(start, end));
    }
    if (chunkText) texts.push(chunkText);
    return texts;
  }, [chunkText, spanStart, spanEnd]);

  // Zoom multiplier on top of the fit-to-width scale. 1.0 = page
  // exactly fills the container width on first load, which is what
  // the user asked for ("see the full page without scrolling").
  // Reset when navigating to a different doc/page so a new chip
  // click never inherits a zoomed-in state from the prior view.
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    setZoom(1);
  }, [docId, shownPage]);

  // Measure the scrolling container so PdfPage knows what to fit to.
  // ResizeObserver tracks both the side panel resizing and the
  // window changing size mid-session.
  //
  // Must match .pdf-scroller's horizontal padding (12px each side). The seed
  // and the observer MUST measure the same box: the observer reports
  // contentRect (padding excluded), so the clientWidth seed subtracts the
  // padding to match. Mixing the two box models is what used to render the
  // page 24px short of fit-to-width.
  const PDF_SCROLLER_PADDING_PX = 24;
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setContainerWidth(Math.max(0, el.clientWidth - PDF_SCROLLER_PADDING_PX));
    // ResizeObserver isn't available in jsdom (used by vitest); the
    // initial clientWidth read above is enough for tests. In real
    // browsers we observe so a side-panel drag or window resize
    // re-fits the page without a manual reload.
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // contentRect.width excludes scrollbar gutter AND padding — the
        // same content-box measurement as the seed above, so the two never
        // disagree about which box they're measuring.
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

  // Two different reasons there may be no page to draw, kept apart because
  // they are different facts: the SOURCE has no page image (DOCX bill), or
  // this chunk has no page recorded (an extractor gap). Either way the
  // cited-text panel below still renders — Core Invariant 1.
  const noPageReason =
    pdfUnavailable ||
    (shownPage == null
      ? "The corpus records no page number for this passage, so there is no " +
        "page to display. The passage text below is what was indexed."
      : null);

  return (
    <div className="pdf-view">
      {/* Rendered unconditionally — even the no-page-image branch below gets
          a crumb + close button, just no zoom/open controls (showZoom is
          false whenever there's no page to draw). */}
      <SourceHead
        docTitle={docTitle}
        page={shownPage}
        fiscalYear={fiscalYear}
        zoom={zoom}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onResetZoom={resetZoom}
        docId={docId}
        onClose={onClose}
        showZoom={!noPageReason}
      />
      {noPageReason ? (
        // Failure-mode A from the catalog: the source is a DOCX bill (or a
        // Plan 3 fiscal note), so there is no page to draw. Say so in the
        // backend's own words and let the cited-text panel below do the
        // verifying — the citation is still valid.
        <div className="pdf-unavailable">
          <h3>Couldn&rsquo;t open source PDF</h3>
          <p>{noPageReason}</p>
        </div>
      ) : (
        // `shownPage!` is safe in this branch: a null shownPage IS a
        // noPageReason above, so this subtree only renders when one exists.
        <div ref={scrollerRef} className="pdf-scroller">
          {containerWidth > 0 && (
            <Suspense fallback={<PageSkeleton />}>
              <PdfPage
                docId={docId}
                pageNumber={shownPage!}
                bbox={bbox}
                searchTexts={searchTexts}
                sourceText={sourceText}
                serverRects={serverRects}
                containerWidth={containerWidth}
                zoomLevel={zoom}
              />
            </Suspense>
          )}
        </div>
      )}
      {/* CitedTextPanel renders below the PDF scroller — ALWAYS visible so
          the analyst can read the verbatim source text even when the PDF
          text-layer search misses ("couldn't pinpoint") or there is no PDF
          at all. */}
      <CitedTextPanel
        chunkText={chunkText}
        spanStart={spanStart}
        spanEnd={spanEnd}
        sourceLabel={sourceLabel}
      />
    </div>
  );
}

/** Page-shaped pulse while the pdfjs chunk downloads — replaces a spinner
 *  with something the eye reads as "a page is coming". */
function PageSkeleton() {
  return (
    <div className="pdf-skeleton-wrap">
      <div className="pdf-skeleton" />
    </div>
  );
}

/** The merged header row: "Page N of <title>" + zoom controls + "open
 *  original" + close, all in one bar. Replaces the old `Breadcrumb` +
 *  `Toolbar` pair (Task 15) — stacking two bars meant two white bands
 *  painted before any page pixels did. */
function SourceHead({
  docTitle,
  page,
  fiscalYear,
  zoom,
  onZoomIn,
  onZoomOut,
  onResetZoom,
  docId,
  onClose,
  showZoom,
}: {
  docTitle: string;
  page: number | null;
  fiscalYear?: number | null;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetZoom: () => void;
  docId: string;
  onClose?: () => void;
  showZoom: boolean;
}) {
  // pdfjs's URL fragment `#page=N` is the standard PDF Open Parameters
  // syntax; Chrome/Edge/Firefox built-in viewers all honor it. `page ?? 1`
  // is a defensive fallback only — the link itself never renders unless
  // showZoom is true, which requires a real page (see noPageReason above).
  const fullDocHref = `/api/pdf/${encodeURIComponent(docId)}#page=${page ?? 1}`;
  return (
    <div className="pdf-head">
      {/* "Page N of <title>" — dropped entirely when there is no page,
          rather than printing "Page — of", which reads like a rendering
          bug. */}
      {page != null && (
        <>
          <span className="pdf-crumb-label">Page</span>
          <span className="pdf-crumb-page">{page}</span>
          <span className="pdf-crumb-label">of</span>
        </>
      )}
      <span className="pdf-crumb-doc" title={docTitle}>
        {docTitle}
      </span>
      {fiscalYear != null && <span className="pdf-crumb-fy">FY{fiscalYear}</span>}
      <span className="pdf-head-spacer" />
      {showZoom && (
        <>
          <button
            type="button"
            onClick={onZoomOut}
            aria-label="Zoom out"
            className="pdf-zoom-btn"
            disabled={zoom <= MIN_ZOOM + 0.001}
          >
            −
          </button>
          <button
            type="button"
            onClick={onResetZoom}
            aria-label="Reset zoom to fit width"
            className="pdf-zoom-btn pdf-zoom-level"
            title="Click to reset to fit-to-width"
          >
            {`${Math.round(zoom * 100)}%`}
          </button>
          <button
            type="button"
            onClick={onZoomIn}
            aria-label="Zoom in"
            className="pdf-zoom-btn"
            disabled={zoom >= MAX_ZOOM - 0.001}
          >
            +
          </button>
          <a
            href={fullDocHref}
            target="_blank"
            rel="noopener noreferrer"
            className="pdf-open-original"
            title="Open the full PDF in a new browser tab"
          >
            Open ↗
          </a>
        </>
      )}
      {onClose && (
        <button
          type="button"
          className="ai-source-close is-inline"
          aria-label="Close source panel"
          onClick={onClose}
        >
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path
              d="M3 3l10 10M13 3L3 13"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
