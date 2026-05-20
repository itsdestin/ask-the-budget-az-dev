// Highlight resolution strategy interface. Today's only implementation
// is `TextLayerSearchStrategy`, which performs the same text-layer
// search that used to live inline in PdfPage.tsx. The seam is here
// so the future #57 follow-up (chunk→PDF coord map captured at
// ingest) can swap in a `CoordMapStrategy` without rewriting the
// component.
//
// The strict-bbox-only behavior is the spec's correctness change:
// when a chunk has a stored bbox, we never search outside it. A miss
// surfaces as an empty result so the viewer can show the "couldn't
// pinpoint" badge — honest miss instead of silent wrong highlight.

import type {
  PDFPageProxy,
  TextItem,
  TextMarkedContent,
} from "pdfjs-dist/types/src/display/api";
import type { PageViewport } from "pdfjs-dist/types/src/display/display_utils";

import { findNormalizedMatch } from "./citation-extract.js";

/** A single highlight rectangle in viewport (canvas) pixel space. */
export interface HighlightRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Future-shape placeholder for #57. Per-chunk list of
 *  (text-slice, page, rect) tuples captured at ingest from the
 *  per-line bboxes the extractor produces. Today: always undefined. */
export interface ChunkCoordMap {
  /** Per-line text + viewport-space rect. */
  entries: Array<{ text: string; page: number; rect: HighlightRect }>;
}

export interface ResolveArgs {
  page: PDFPageProxy;
  viewport: PageViewport;
  /** Cited substring of chunk.text. */
  quote: string;
  /** Full chunk text — used as a wider fallback search target when
   *  the quote can't be matched. */
  fullChunkText: string;
  /** Chunk-stored bbox in VIEWPORT-PIXEL space, OR null when the
   *  chunk has no stored bbox (OpenDataLoader). When non-null the
   *  search is strictly restricted to the bbox; on miss we return
   *  [] rather than falling back to whole-page. */
  bbox: HighlightRect | null;
  /** Forwarded for the future CoordMapStrategy. Today: undefined. */
  coordMap?: ChunkCoordMap;
}

export interface HighlightStrategy {
  resolve(args: ResolveArgs): Promise<HighlightRect[]>;
}

/** Default strategy: searches the pdfjs text layer for the quote
 *  (then full chunk text, then currency tokens) inside the chunk's
 *  bbox if present. */
export class TextLayerSearchStrategy implements HighlightStrategy {
  async resolve(args: ResolveArgs): Promise<HighlightRect[]> {
    const { page, viewport, quote, fullChunkText, bbox } = args;
    const targets = [quote, fullChunkText].filter(
      (t): t is string => typeof t === "string" && t.length > 0,
    );
    for (const target of targets) {
      const rects = await findTextRects(page, target, viewport, bbox);
      if (rects.length > 0) return rects;
    }
    // Currency-token fallback for the common case where formatting
    // drift between chunk text and PDF text layer defeats the full
    // match but the dollar amount survives.
    const currencyMatches = quote.match(/\$[\d][\d,.]*/g) ?? [];
    const uniq = Array.from(new Set(currencyMatches));
    for (const tok of uniq) {
      const rects = await findTextRects(page, tok, viewport, bbox);
      if (rects.length > 0) return rects;
    }
    return [];
  }
}

/** Placeholder for the future #57 strategy. Today this throws so we
 *  never silently swap to a no-op. Replace the body when #57 ships. */
export class CoordMapStrategy implements HighlightStrategy {
  async resolve(_args: ResolveArgs): Promise<HighlightRect[]> {
    throw new Error(
      "CoordMapStrategy not implemented yet — see plan #57 follow-up",
    );
  }
}

function isTextItem(item: TextItem | TextMarkedContent): item is TextItem {
  return typeof (item as { str?: unknown }).str === "string";
}

/** Search the page's text layer for `searchText` and return one
 *  highlight rect PER LINE the match crosses. Strict-bbox: when
 *  `restrictTo` is non-null, items outside it (with 8pt of slack)
 *  are dropped from the search; if the match isn't inside the
 *  restricted region we return [] WITHOUT a whole-page fallback. */
async function findTextRects(
  page: PDFPageProxy,
  searchText: string,
  viewport: PageViewport,
  restrictTo: HighlightRect | null,
): Promise<HighlightRect[]> {
  if (!searchText) return [];
  const content = await page.getTextContent();
  let items = content.items.filter(isTextItem);
  if (items.length === 0) return [];

  if (restrictTo) {
    const slack = 8 * (viewport.scale ?? 1);
    const rx1 = restrictTo.left - slack;
    const ry1 = restrictTo.top - slack;
    const rx2 = restrictTo.left + restrictTo.width + slack;
    const ry2 = restrictTo.top + restrictTo.height + slack;
    items = items.filter((item) => {
      const x1 = item.transform[4]!;
      const y1 = item.transform[5]!;
      const x2 = x1 + item.width;
      const y2 = y1 + item.height;
      const [vx1, vy1, vx2, vy2] = viewport.convertToViewportRectangle([
        x1,
        y1,
        x2,
        y2,
      ]);
      const ix1 = Math.min(vx1, vx2);
      const iy1 = Math.min(vy1, vy2);
      const ix2 = Math.max(vx1, vx2);
      const iy2 = Math.max(vy1, vy2);
      return ix1 < rx2 && ix2 > rx1 && iy1 < ry2 && iy2 > ry1;
    });
    if (items.length === 0) return [];
  }

  let flat = "";
  const itemForChar: number[] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!;
    const start = flat.length;
    flat += item.str;
    for (let k = start; k < flat.length; k++) itemForChar.push(i);
    if (i + 1 < items.length) {
      const endsInSpace = item.str.endsWith(" ");
      if (!endsInSpace) {
        flat += " ";
        itemForChar.push(i);
      }
      if (item.hasEOL) {
        flat += "\n";
        itemForChar.push(i);
      }
    }
  }

  const match = findNormalizedMatch(flat, searchText, 0);
  if (!match) return [];

  const involved = new Set<number>();
  for (let i = match.start; i < match.end && i < itemForChar.length; i++) {
    involved.add(itemForChar[i]!);
  }
  if (involved.size === 0) return [];

  // Bucket items by baseline y to emit one rect per text line.
  const buckets = new Map<number, number[]>();
  for (const idx of involved) {
    const item = items[idx]!;
    const yKey = Math.round(item.transform[5]! * 2) / 2;
    if (!buckets.has(yKey)) buckets.set(yKey, []);
    buckets.get(yKey)!.push(idx);
  }

  const rects: HighlightRect[] = [];
  for (const [, idxs] of buckets) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const idx of idxs) {
      const item = items[idx]!;
      const x1 = item.transform[4]!;
      const y1 = item.transform[5]!;
      const x2 = x1 + item.width;
      const y2 = y1 + item.height;
      const [vx1, vy1, vx2, vy2] = viewport.convertToViewportRectangle([
        x1,
        y1,
        x2,
        y2,
      ]);
      minX = Math.min(minX, vx1, vx2);
      maxX = Math.max(maxX, vx1, vx2);
      minY = Math.min(minY, vy1, vy2);
      maxY = Math.max(maxY, vy1, vy2);
    }
    rects.push({
      left: minX,
      top: minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    });
  }
  rects.sort((a, b) => a.top - b.top);
  return rects;
}
