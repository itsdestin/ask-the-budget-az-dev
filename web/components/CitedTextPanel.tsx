"use client";

// Always-visible panel below the PDF page showing the cited span
// in-context within the chunk text. The PDF highlight is the
// primary affordance, but when the text-layer search misses (or
// when the analyst wants to verify by eye anyway) this panel is
// the trust signal: the verbatim source text with the cited span
// underlined.
//
// To keep the panel from crowding the PDF (2026-05-20 dogfood report:
// the full-chunk default was so tall it covered the page), we render
// only a CONTEXT_CHARS-sized window around the cited span by default
// and offer a "Show full chunk" toggle for the rare case the analyst
// wants the whole thing.
//
// Empty / sentinel states:
//   - chunkText empty → "Source text unavailable in this turn."
//   - spanStart === spanEnd → render whole chunk text without
//     underline (legacy sentinel from pre-resolved-offsets cites).

import { useState } from "react";

interface Props {
  chunkText: string;
  /** Resolved span start in chunk.text (inclusive). */
  spanStart: number;
  /** Resolved span end in chunk.text (exclusive). */
  spanEnd: number;
  /** Display label for the source ("JLBC FY26 Baseline, p. 47"). */
  sourceLabel: string;
}

/** Characters of context to keep on each side of the cited span when
 *  the panel is collapsed. ~200 chars ≈ 2-3 lines at the panel's
 *  text-xs size, which is enough to recognize the surrounding sentence
 *  without crowding the PDF page above. Tune later if dogfood shows
 *  too much or too little. */
const CONTEXT_CHARS = 200;
/** Word-boundary snap-distance — when rounding the window edge to the
 *  nearest space, only move if it's within this many chars; otherwise
 *  accept the mid-word cut. */
const WORD_SNAP_DISTANCE = 30;

export default function CitedTextPanel({
  chunkText,
  spanStart,
  spanEnd,
  sourceLabel,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!chunkText) {
    return (
      <div className="border-t border-edge bg-panel/40 px-3 py-3 text-xs">
        <div className="font-bold text-fg-2 mb-1">Cited text from this chunk</div>
        <p className="text-fg-muted italic">
          Source text unavailable in this turn.
        </p>
      </div>
    );
  }
  const hasValidSpan =
    spanEnd > spanStart && spanEnd <= chunkText.length && spanStart >= 0;

  // Collapsed-window bounds. Computed even when expanded so we can
  // decide whether the toggle button is needed (no point showing a
  // toggle if the chunk fits in the window anyway).
  let collapsedStart = 0;
  let collapsedEnd = chunkText.length;
  if (hasValidSpan) {
    collapsedStart = Math.max(0, spanStart - CONTEXT_CHARS);
    collapsedEnd = Math.min(chunkText.length, spanEnd + CONTEXT_CHARS);
    // Word-boundary rounding: walk forward from collapsedStart to the
    // next space (without crossing into the cited span), walk backward
    // from collapsedEnd to the previous space (without crossing back
    // into the cited span). Keeps the snippet from starting/ending
    // mid-word in the common case.
    if (collapsedStart > 0) {
      const nextSpace = chunkText.indexOf(" ", collapsedStart);
      if (
        nextSpace !== -1 &&
        nextSpace - collapsedStart < WORD_SNAP_DISTANCE &&
        nextSpace < spanStart
      ) {
        collapsedStart = nextSpace + 1;
      }
    }
    if (collapsedEnd < chunkText.length) {
      const prevSpace = chunkText.lastIndexOf(" ", collapsedEnd);
      if (
        prevSpace > spanEnd &&
        collapsedEnd - prevSpace < WORD_SNAP_DISTANCE
      ) {
        collapsedEnd = prevSpace;
      }
    }
  }
  const wouldTruncate =
    collapsedStart > 0 || collapsedEnd < chunkText.length;

  const windowStart = expanded ? 0 : collapsedStart;
  const windowEnd = expanded ? chunkText.length : collapsedEnd;
  const showLeadingEllipsis = windowStart > 0;
  const showTrailingEllipsis = windowEnd < chunkText.length;

  const before = hasValidSpan
    ? chunkText.slice(windowStart, spanStart)
    : chunkText.slice(windowStart, windowEnd);
  const cited = hasValidSpan ? chunkText.slice(spanStart, spanEnd) : "";
  const after = hasValidSpan ? chunkText.slice(spanEnd, windowEnd) : "";

  return (
    <div className="border-t border-edge bg-panel/40 px-3 py-3 text-xs">
      <div className="flex items-center justify-between mb-1">
        <div className="font-bold text-fg-2">Cited text from this chunk</div>
        {wouldTruncate ? (
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="text-fg-faint hover:text-fg-2 text-[11px] underline-offset-2 hover:underline"
            aria-expanded={expanded}
          >
            {expanded ? "Show less" : "Show full chunk"}
          </button>
        ) : null}
      </div>
      <p className="text-fg whitespace-pre-wrap">
        {showLeadingEllipsis && <span className="text-fg-faint">… </span>}
        <span className="text-fg-muted">{before}</span>
        {hasValidSpan && (
          <mark className="bg-amber-300/30 text-fg border-b border-amber-500 rounded-sm">
            {cited}
          </mark>
        )}
        <span className="text-fg-muted">{after}</span>
        {showTrailingEllipsis && <span className="text-fg-faint"> …</span>}
      </p>
      {sourceLabel && (
        <div className="text-fg-faint mt-2">Source: {sourceLabel}</div>
      )}
    </div>
  );
}
