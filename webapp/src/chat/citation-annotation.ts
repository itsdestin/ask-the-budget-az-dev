/**
 * Parse the figure annotation the server attaches to a finished turn.
 *
 * This is the same artifact the eval judge renders as inline markers, so
 * what the analyst sees and what the eval grades come from one source.
 * Parsing is defensive because a turn recorded before citation linking
 * shipped carries no annotation.
 */

export type FigureVerdict = "linked" | "derived" | "unverified";

export interface AnnotationSource {
  chunkId: string;
  sourceText: string;
  start: number;
  end: number;
}

export interface AnnotationFigure {
  text: string;
  start: number;
  end: number;
  index: number;
  verdict: FigureVerdict;
  primary: AnnotationSource | null;
  additional: AnnotationSource[];
  derivedFrom: number[];
}

function toSource(raw: unknown): AnnotationSource | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.chunk_id !== "string") return null;
  return {
    chunkId: r.chunk_id,
    sourceText: typeof r.source_text === "string" ? r.source_text : "",
    start: typeof r.start === "number" ? r.start : 0,
    end: typeof r.end === "number" ? r.end : 0,
  };
}

export function figuresForRender(annotation: unknown): AnnotationFigure[] {
  if (!annotation || typeof annotation !== "object") return [];
  const raw = (annotation as Record<string, unknown>).figures;
  if (!Array.isArray(raw)) return [];

  const figures: AnnotationFigure[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    const verdict = e.verdict;
    if (verdict !== "linked" && verdict !== "derived" && verdict !== "unverified") {
      continue;
    }
    if (typeof e.text !== "string" || typeof e.start !== "number") continue;
    figures.push({
      text: e.text,
      start: e.start,
      end: typeof e.end === "number" ? e.end : e.start,
      index: typeof e.index === "number" ? e.index : figures.length + 1,
      verdict,
      primary: toSource(e.primary),
      additional: Array.isArray(e.additional)
        ? e.additional.map(toSource).filter((s): s is AnnotationSource => s !== null)
        : [],
      derivedFrom: Array.isArray(e.derived_from)
        ? e.derived_from.filter((n): n is number => typeof n === "number")
        : [],
    });
  }
  // Reading order — chip numbering follows the answer, not emission.
  return figures.sort((a, b) => a.start - b.start);
}

/**
 * Where each figure's chip goes in ONE rendered block of markdown.
 *
 * The annotation's offsets index the turn's whole `finalAnswer` — every
 * assistant text block joined with a blank line — but this renderer is
 * handed one block at a time, and that block's text may itself have been
 * rewritten (inline `<cite>` stripping). So an offset taken on faith
 * lands on the wrong characters the moment a turn has more than one text
 * block, which is every turn that narrates before calling a tool.
 *
 * The offset is therefore treated as a HINT that is verified before use:
 * if it really does slice to the figure's own text, it is exact. If not,
 * fall back to finding the figure's text in the block, taking the Nth
 * occurrence for the Nth repeat of that value so restated figures chip
 * distinct places rather than stacking on the first one.
 *
 * A figure that cannot be found at all yields no chip. A missing chip is
 * a visible absence; a chip on the wrong number is a false provenance
 * claim, which is worse.
 */
export function placeFigures(
  content: string,
  figures: AnnotationFigure[],
): { figure: AnnotationFigure; at: number }[] {
  const placements: { figure: AnnotationFigure; at: number }[] = [];
  // How many times each figure's text has already been consumed, so a
  // value stated twice takes its second occurrence the second time.
  const consumed = new Map<string, number>();
  for (const figure of figures) {
    const seen = consumed.get(figure.text) ?? 0;
    if (content.slice(figure.start, figure.end) === figure.text) {
      placements.push({ figure, at: figure.end });
      consumed.set(figure.text, seen + 1);
      continue;
    }
    let from = 0;
    let found = -1;
    for (let i = 0; i <= seen; i += 1) {
      found = content.indexOf(figure.text, from);
      if (found === -1) break;
      from = found + figure.text.length;
    }
    if (found === -1) continue;
    placements.push({ figure, at: found + figure.text.length });
    consumed.set(figure.text, seen + 1);
  }
  return placements;
}
