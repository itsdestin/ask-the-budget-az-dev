// pdfjs-dist–backed renderer for a single PDF page with a highlight
// overlay. Ported from web/components/PdfPage.tsx (Plan 4 Task 11); the
// coordinate math, the strict-bbox rule and the multi-pass search order are
// carried over unchanged. What DID change is listed at the bottom of this
// comment.
//
// Bbox coordinate conventions (verified empirically 2026-05-07):
//
//   - MinerU (~99% of the corpus): bboxes in a 0-1000 normalized
//     space PER AXIS, top-left origin. Verified by ratio-checking
//     "BD-2" page-number and heading bboxes against PyMuPDF
//     ground truth — values match within ~1pt after dividing by
//     1000 and multiplying by page dimensions.
//   - OpenDataLoader (a couple of AGAO docs): bboxes in PDF
//     user-space points, top-left origin. Standard convention.
//
// Both share the top-left origin; the only difference is whether
// the bbox is normalized to [0, 1000] or expressed in PDF points.
// We auto-detect by comparing the bbox max to the page's
// dimensions in points: if any bbox value exceeds the larger page
// dimension, we know we're in MinerU's normalized space.
//
// PDF.js gotchas this component is careful about:
//
//  1. The worker is a real bundled asset (see ensurePdfjsConfigured). The
//     retired Next.js app copied pdf.worker.min.mjs into /public with a
//     postinstall script and pointed workerSrc at the copied path; Vite
//     emits and fingerprints the worker itself, so the copy step is gone.
//  2. PDF.js renders aggressively: starting a render on a canvas
//     that's already rendering throws "Cannot use the same canvas
//     during multiple render() operations." We cancel the previous
//     RenderTask via task.cancel() inside the cleanup branch.
//  3. getDocument().promise resolves once for the whole PDF, but
//     each chip click typically lands on a different page within
//     the same doc — we cache the loaded doc per docId so page-
//     switching doesn't re-download the bytes.
//
// Deltas from the web/ original, all mechanical:
//   - no "use client" (this is a Vite SPA, there is no server pass);
//   - Tailwind utility classes -> `pdf-`-prefixed semantic classes in
//     app.css, per the Task 10 convention documented there;
//   - a failed document load is evicted from the doc cache, so a
//     transient share/network failure can be retried by clicking again
//     instead of being remembered forever as a rejected promise.

import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentProxy,
  RenderTask,
} from "pdfjs-dist/types/src/display/api";
import type { PageViewport } from "pdfjs-dist/types/src/display/display_utils";

import {
  TextLayerSearchStrategy,
  type ChunkCoordMap,
  type HighlightRect,
  type HighlightStrategy,
} from "./highlight-strategy";

interface Props {
  /** doc_id from the chunk; rendered as `/api/pdf/{docId}`. */
  docId: string;
  /** 1-indexed page number from chunk.page_start. */
  pageNumber: number;
  /** [x0, y0, x1, y1]. See coordinate convention notes above. */
  bbox: number[] | null;
  /** Text strings to search the PDF text layer for, in priority
   *  order. The first match wins; the renderer emits one tight
   *  highlight rect per LINE the matched text crosses (so multi-
   *  line passages don't paint over the gutters).
   *
   *  Caller should put the most specific text first — typically
   *  chunk.text[span_start:span_end] (the exact source quote the
   *  cite() emitted span offsets for), then chunk.text (full
   *  chunk) as a fallback when the spanned slice doesn't match
   *  due to PDF text-extraction quirks. There is deliberately NO
   *  bbox fallback: see `notLocated` below. */
  searchTexts?: string[];
  /** The figure as the SOURCE renders it, from the citation linker.
   *  Searched before `searchTexts` — the PDF text layer holds the
   *  source's form, never the answer's. */
  sourceText?: string;
  /** Width of the parent container in CSS pixels. The page is fit-
   *  to-width by default; if 0 or undefined, falls back to a
   *  reasonable default (800px) so the page still renders even
   *  when the parent forgets to measure. */
  containerWidth?: number;
  /** Multiplier applied on top of the fit-to-width scale. 1.0 =
   *  page exactly fills the container width. >1 zooms in, <1 zooms
   *  out. The viewer's +/- buttons drive this. */
  zoomLevel?: number;
  /** Optional per-chunk coord map from a future #57 ingest pipeline.
   *  Today: always undefined. */
  coordMap?: ChunkCoordMap;
  /** Exact highlight rects from the server-side locate endpoint
   *  (spec L2), each [x0,y0,x1,y1] in PDF user-space points. When
   *  non-empty these ARE the ground truth — PyMuPDF found the cited
   *  value on the real page — so the client text-layer strategy is
   *  skipped entirely. Empty/undefined runs today's chain unchanged. */
  serverRects?: number[][];
  /** Optional strategy override — tests pass a fake; production uses
   *  TextLayerSearchStrategy. */
  strategy?: HighlightStrategy;
}

let workerConfigured = false;
async function ensurePdfjsConfigured() {
  // Lazy-init: pdfjs-dist touches `window` at module load, and it is a large
  // dependency, so it is only imported when a page is actually rendered
  // (PdfViewer wraps this component in React.lazy for the same reason).
  // Gated to a single configuration so concurrent mounts don't race.
  if (workerConfigured) return await import("pdfjs-dist");
  const lib = await import("pdfjs-dist");
  if (!workerConfigured) {
    // `new Worker(new URL(..., import.meta.url))` is the form Vite
    // statically analyses: it emits pdf.worker.min.mjs as a real hashed
    // asset in dist/ and rewrites this URL to point at it. Setting
    // `workerSrc` to a bare path instead would work in dev (where the
    // module graph is served from node_modules) and 404 in the production
    // build — the exact failure this shape avoids. `workerPort` is the
    // GlobalWorkerOptions field that accepts an already-constructed
    // Worker; pdfjs reuses the one port for every document it opens.
    lib.GlobalWorkerOptions.workerPort = new Worker(
      new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
      { type: "module" },
    );
    workerConfigured = true;
  }
  return lib;
}

const docCache = new Map<string, Promise<PDFDocumentProxy>>();

const FALLBACK_CONTAINER_WIDTH = 800;
const MIN_FIT_WIDTH = 200;
/** MinerU 3.x normalizes bboxes to a 0–1000 axis space (per-axis,
 *  not preserving aspect). Verified against PyMuPDF ground truth. */
const MINERU_NORMALIZE_DIM = 1000;

export default function PdfPage({
  docId,
  pageNumber,
  bbox,
  searchTexts,
  sourceText,
  containerWidth,
  zoomLevel = 1,
  coordMap,
  serverRects,
  strategy,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Highlights — typically one rect per text line for a multi-line
  // claim. Empty array when nothing to draw. (We previously stored a
  // single bounding-box overlay; the array form is needed because
  // text-layer matches naturally span multiple lines and a single
  // bounding box would over-paint blank gutters.)
  const [highlights, setHighlights] = useState<HighlightRect[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // When all text-layer search strategies fail, we no longer paint
  // the chunk's stored bbox — empirically those bboxes can be wrong
  // or oversized, producing a yellow rectangle over unrelated text
  // (2026-05-12 user-reported regression). Surface a small honest
  // badge instead so the user knows we located the page but not the
  // exact text.
  const [notLocated, setNotLocated] = useState(false);
  // Bumped by the Retry button on the load-failure panel (spec L4): a
  // share blip used to be a red dead end until the analyst re-clicked
  // the chip; Retry re-runs this effect against the same doc/page.
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let renderTask: RenderTask | null = null;

    (async () => {
      setError(null);
      setLoading(true);
      setHighlights([]);
      setNotLocated(false);
      try {
        const pdfjs = await ensurePdfjsConfigured();
        const url = `/api/pdf/${encodeURIComponent(docId)}`;
        let docPromise = docCache.get(docId);
        if (!docPromise) {
          docPromise = pdfjs.getDocument(url).promise;
          docCache.set(docId, docPromise);
          // Don't remember a failure forever: a rejected promise left in
          // the cache would make one offline-share blip permanent for the
          // rest of the session. Attached here (not in the catch below) so
          // eviction happens even if this effect was already cancelled.
          docPromise.catch(() => {
            if (docCache.get(docId) === docPromise) docCache.delete(docId);
          });
        }
        const pdf = await docPromise;
        if (cancelled) return;

        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;

        // Fit-to-width: viewport at scale=1 gives page dimensions in
        // PDF points (1 pt = 1 px at scale=1). Compute the scale
        // that makes the rendered width match the container, then
        // apply the user's zoom multiplier on top.
        const naturalViewport = page.getViewport({ scale: 1 });
        const targetWidth = Math.max(
          MIN_FIT_WIDTH,
          containerWidth || FALLBACK_CONTAINER_WIDTH,
        );
        const fitScale = targetWidth / naturalViewport.width;
        const renderScale = fitScale * zoomLevel;
        const viewport = page.getViewport({ scale: renderScale });

        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        const ctx = canvas.getContext("2d");
        if (!ctx) {
          setError("Canvas 2D context unavailable.");
          setLoading(false);
          return;
        }

        renderTask = page.render({
          canvasContext: ctx,
          viewport,
          // The Render API requires a `canvas` field in v5+; pre-v5
          // ignored it. Pass it for forward-compat — types call it
          // optional but the runtime warns when missing.
          canvas,
        });
        await renderTask.promise;
        if (cancelled) return;

        // Server-side locate first (spec L2): when the locate endpoint
        // found the cited value, its rects are the ground truth —
        // PyMuPDF searched the REAL page — and the client text-layer
        // strategy is skipped entirely. Measured 2026-08-18: the client
        // chain missed 44% of correctly linked figures (stored bbox
        // covered only the chunk's first paragraph, values on later
        // pages, accounting-paren drift); the server answer fixes all
        // three without loosening the strict-bbox rule that exists to
        // prevent wrong-number highlights.
        // The server's rects are PDF user-space points with a TOP-LEFT
        // origin (PyMuPDF's convention — the same one the stored bboxes
        // use, see the notes at the top of this file), so viewport
        // pixels are a plain multiply by renderScale, exactly like
        // bboxToViewportRect's points branch. NOT convertToViewportRectangle:
        // that pdfjs helper expects a BOTTOM-LEFT-origin rect and would
        // flip every box vertically — the 2026-08-18 browser pass caught
        // boxes mirrored to the wrong half of the page.
        const server = (serverRects ?? [])
          .filter((r) => Array.isArray(r) && r.length >= 4)
          .map((r) => ({
            left: Math.min(r[0]!, r[2]!) * renderScale,
            top: Math.min(r[1]!, r[3]!) * renderScale,
            width: Math.max(1, Math.abs(r[2]! - r[0]!) * renderScale),
            height: Math.max(1, Math.abs(r[3]! - r[1]!) * renderScale),
          }));
        let computed: HighlightRect[];
        if (server.length > 0) {
          computed = server;
        } else {
          // Highlight strategy. Default is TextLayerSearchStrategy
          // (text-layer search restricted to the chunk's bbox if any);
          // tests + the future #57 path can pass a different strategy.
          // Strict bbox: when a chunk has a stored bbox, the strategy
          // does NOT fall back to whole-page search on miss — we want
          // an honest "couldn't pinpoint" badge instead of a yellow
          // rectangle on the wrong text.
          const activeStrategy = strategy ?? new TextLayerSearchStrategy();
          const restrictRect =
            bbox && bbox.length >= 4
              ? bboxToViewportRect(bbox, naturalViewport, renderScale)
              : null;
          const quote = (searchTexts ?? [])[0] ?? "";
          const fullChunkText = (searchTexts ?? [])[1] ?? "";
          computed = await activeStrategy.resolve({
            page,
            viewport,
            quote,
            sourceText,
            fullChunkText,
            bbox: restrictRect,
            coordMap,
          });
        }
        if (cancelled) return;
        if (computed.length === 0) setNotLocated(true);
        setHighlights(computed);
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        // RenderingCancelledException is normal during fast chip-
        // switching — don't surface it as an error to the user.
        if (msg.includes("Rendering cancelled")) return;
        setError(msg);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      // cancel() throws synchronously inside RenderTask if it has
      // already settled — try/catch keeps unmounts from logging.
      try {
        renderTask?.cancel();
      } catch {
        // ignore
      }
    };
    // searchTexts is an array — use a serialized form for the deps
    // so a freshly-allocated array with identical contents doesn't
    // re-trigger the effect on every render.
  }, [
    docId,
    pageNumber,
    bbox,
    (searchTexts ?? []).join(" "),
    sourceText,
    containerWidth,
    zoomLevel,
    coordMap,
    JSON.stringify(serverRects ?? []),
    retryNonce,
    strategy,
  ]);

  return (
    <div className="pdf-page">
      <canvas ref={canvasRef} aria-label={`PDF page ${pageNumber}`} />
      {highlights.map((h, i) => (
        <div
          key={`hl-${i}`}
          className="pdf-highlight"
          style={{
            left: h.left,
            top: h.top,
            width: h.width,
            height: h.height,
          }}
          aria-hidden
        />
      ))}
      {loading && !error && <div className="pdf-page-overlay">Loading page…</div>}
      {error && (
        // Spec L4 (Destin 2026-08-18): a PDF load failure used to be a
        // red overlay with a raw exception and no way out. The raw file
        // link is ALWAYS accurate — it is the document itself — so the
        // failure surface leads with it, says the verbatim passage is
        // still below, and offers Retry for the transient-share case.
        <div className="pdf-load-failed" role="alert">
          <h3>Couldn&rsquo;t open this page</h3>
          <p>
            The source file didn&rsquo;t load. The cited text below is
            still the verbatim passage from the document.
          </p>
          <div className="pdf-load-failed-actions">
            <a
              href={`/api/pdf/${encodeURIComponent(docId)}#page=${pageNumber}`}
              target="_blank"
              rel="noopener noreferrer"
              className="pdf-open-original"
              title="Open the full PDF in a new browser tab"
            >
              Open document ↗
            </a>
            <button
              type="button"
              className="pdf-retry-btn"
              onClick={() => setRetryNonce((n) => n + 1)}
            >
              Retry
            </button>
          </div>
          <p className="pdf-load-failed-detail">page {pageNumber}: {error}</p>
        </div>
      )}
      {notLocated && !loading && !error && (
        // Honest "we know the page, not the exact text" badge. Sits
        // at the top of the rendered page so it doesn't obscure
        // content; click-through is fine (pointer-events default).
        <div className="pdf-not-located">
          Citation is on this page — exact text couldn&rsquo;t be pinpointed.
        </div>
      )}
    </div>
  );
}

/** Convert a chunk bbox (MinerU normalized OR ODL points) to a single
 *  viewport-pixel rect. Pulled out of the main effect so the
 *  text-layer fallback path can share it. */
function bboxToViewportRect(
  bbox: number[],
  naturalViewport: PageViewport,
  renderScale: number,
): HighlightRect {
  const pageWidthPts = naturalViewport.width;
  const pageHeightPts = naturalViewport.height;
  const bboxMax = Math.max(bbox[0]!, bbox[1]!, bbox[2]!, bbox[3]!);
  const pageMaxDim = Math.max(pageWidthPts, pageHeightPts);
  const isMineruNormalized = bboxMax > pageMaxDim;
  let left: number;
  let top: number;
  let right: number;
  let bottom: number;
  if (isMineruNormalized) {
    left = (bbox[0]! / MINERU_NORMALIZE_DIM) * pageWidthPts * renderScale;
    top = (bbox[1]! / MINERU_NORMALIZE_DIM) * pageHeightPts * renderScale;
    right = (bbox[2]! / MINERU_NORMALIZE_DIM) * pageWidthPts * renderScale;
    bottom = (bbox[3]! / MINERU_NORMALIZE_DIM) * pageHeightPts * renderScale;
  } else {
    left = bbox[0]! * renderScale;
    top = bbox[1]! * renderScale;
    right = bbox[2]! * renderScale;
    bottom = bbox[3]! * renderScale;
  }
  return {
    left: Math.min(left, right),
    top: Math.min(top, bottom),
    width: Math.abs(right - left),
    height: Math.abs(bottom - top),
  };
}
