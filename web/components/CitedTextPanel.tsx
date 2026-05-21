// Always-visible panel below the PDF page showing the cited span
// in-context within the chunk text. The PDF highlight is the
// primary affordance, but when the text-layer search misses (or
// when the analyst wants to verify by eye anyway) this panel is
// the trust signal: the verbatim source text with the cited span
// underlined.
//
// Empty / sentinel states:
//   - chunkText empty → "Source text unavailable in this turn."
//   - spanStart === spanEnd → render whole chunk text without
//     underline (legacy sentinel from pre-resolved-offsets cites).

interface Props {
  chunkText: string;
  /** Resolved span start in chunk.text (inclusive). */
  spanStart: number;
  /** Resolved span end in chunk.text (exclusive). */
  spanEnd: number;
  /** Display label for the source ("JLBC FY26 Baseline, p. 47"). */
  sourceLabel: string;
}

export default function CitedTextPanel({
  chunkText,
  spanStart,
  spanEnd,
  sourceLabel,
}: Props) {
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
  const before = hasValidSpan ? chunkText.slice(0, spanStart) : chunkText;
  const cited = hasValidSpan ? chunkText.slice(spanStart, spanEnd) : "";
  const after = hasValidSpan ? chunkText.slice(spanEnd) : "";
  return (
    <div className="border-t border-edge bg-panel/40 px-3 py-3 text-xs">
      <div className="font-bold text-fg-2 mb-1">Cited text from this chunk</div>
      <p className="text-fg whitespace-pre-wrap">
        <span className="text-fg-muted">{before}</span>
        {hasValidSpan && (
          <mark className="bg-amber-300/30 text-fg border-b border-amber-500 rounded-sm">
            {cited}
          </mark>
        )}
        <span className="text-fg-muted">{after}</span>
      </p>
      {sourceLabel && (
        <div className="text-fg-faint mt-2">Source: {sourceLabel}</div>
      )}
    </div>
  );
}
