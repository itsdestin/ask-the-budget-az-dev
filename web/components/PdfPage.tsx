"use client";

// pdfjs-dist–backed renderer for a single PDF page with a bbox
// highlight overlay. Replaces the slice-2 <embed> stub once the
// worker is in place. The bbox rectangle is the spec §10.2 yellow
// overlay — painted as an absolutely-positioned <div> on top of
// the rendered canvas so we keep crisp text rendering and don't
// have to fight PDF.js's own AnnotationLayer.
//
// PDF.js gotchas this component is careful about:
//
//  1. Worker is loaded from /pdf.worker.min.mjs. The postinstall
//     copy step (web/scripts/copy-pdf-worker.mjs) keeps that file
//     in sync with the version in node_modules.
//  2. PDF coordinate system has the origin at the bottom-left and
//     y-axis growing upward. `viewport.convertToViewportRectangle`
//     does the flip, but its return value isn't necessarily a
//     "left-top-right-bottom" tuple — we normalize after calling.
//  3. PDF.js renders aggressively: starting a render on a canvas
//     that's already rendering throws "Cannot use the same canvas
//     during multiple render() operations." We cancel the previous
//     RenderTask via task.cancel() inside the cleanup branch.
//  4. getDocument().promise resolves once for the whole PDF, but
//     each chip click typically lands on a different page within
//     the same doc — we cache the loaded doc per docId so page-
//     switching doesn't re-download the bytes.

import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentProxy,
  RenderTask,
} from "pdfjs-dist/types/src/display/api";

interface Props {
  /** doc_id from the chunk; rendered as `/api/pdf/{docId}`. */
  docId: string;
  /** 1-indexed page number from chunk.page_start. */
  pageNumber: number;
  /** [x1, y1, x2, y2] in PDF points. Null for non-PDF chunks; the
   *  page renders without an overlay in that case (still scrolls
   *  to the right page so the user can find the cited region). */
  bbox: number[] | null;
  /** CSS scale applied during rendering; 1.5 is a good legibility
   *  sweet spot for typical 8.5x11" pages on a desktop monitor. */
  scale?: number;
}

let workerConfigured = false;
async function ensurePdfjsConfigured() {
  // Lazy-init: pdfjs-dist references `window` at module load. Calling
  // import("pdfjs-dist") from a `"use client"` component is safe
  // because client components don't run on the server during SSR.
  // We still gate to a single configuration to avoid races between
  // concurrent mounts.
  if (workerConfigured) return await import("pdfjs-dist");
  const lib = await import("pdfjs-dist");
  if (!workerConfigured) {
    lib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
    workerConfigured = true;
  }
  return lib;
}

const docCache = new Map<string, Promise<PDFDocumentProxy>>();

export default function PdfPage({
  docId,
  pageNumber,
  bbox,
  scale = 1.5,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [overlay, setOverlay] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let renderTask: RenderTask | null = null;

    (async () => {
      setError(null);
      setLoading(true);
      setOverlay(null);
      try {
        const pdfjs = await ensurePdfjsConfigured();
        const url = `/api/pdf/${encodeURIComponent(docId)}`;
        let docPromise = docCache.get(docId);
        if (!docPromise) {
          docPromise = pdfjs.getDocument(url).promise;
          docCache.set(docId, docPromise);
        }
        const pdf = await docPromise;
        if (cancelled) return;

        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;

        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Match canvas pixel size to the viewport so 1:1 (no DPR
        // upscaling for now — PDF.js does the right thing visually
        // and DPR-aware rendering is a future polish pass).
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

        if (bbox && bbox.length >= 4) {
          // PDF y-axis grows up; convertToViewportRectangle handles
          // the flip but can return [x1,y2,x2,y1] (i.e. y1 > y2).
          // Normalize to (left,top,width,height) for a CSS overlay.
          const rect = viewport.convertToViewportRectangle([
            bbox[0]!,
            bbox[1]!,
            bbox[2]!,
            bbox[3]!,
          ]);
          const left = Math.min(rect[0]!, rect[2]!);
          const top = Math.min(rect[1]!, rect[3]!);
          const width = Math.abs(rect[2]! - rect[0]!);
          const height = Math.abs(rect[3]! - rect[1]!);
          setOverlay({ left, top, width, height });
        }
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
  }, [docId, pageNumber, bbox, scale]);

  return (
    <div className="relative w-fit mx-auto">
      <canvas ref={canvasRef} aria-label={`PDF page ${pageNumber}`} />
      {overlay && (
        <div
          className="absolute pointer-events-none border-2 border-amber-500 bg-amber-300/30 mix-blend-multiply"
          style={{
            left: overlay.left,
            top: overlay.top,
            width: overlay.width,
            height: overlay.height,
          }}
          aria-hidden
        />
      )}
      {loading && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-canvas/50 text-fg-muted text-sm">
          Loading page…
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-red-400/10 text-red-400 text-xs p-4 text-center">
          Couldn&rsquo;t load page {pageNumber}: {error}
        </div>
      )}
    </div>
  );
}
