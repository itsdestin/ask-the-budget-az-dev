// Shared display helpers for the three admin panels that report on
// extraction (NeedsAttention, ExtractionChanges, PoorlyRead).
//
// Extracted when the third panel arrived, not before: two copies is a
// coincidence, three is a rule that will drift. Both functions had already
// been transcribed once verbatim, comments included, which is the shape
// that ends with two panels rendering the same number differently.

// Display names for the ladder's rungs (`ingest/ladder.py::_PDF_LADDER`).
// A name this map doesn't know (a rung added later) falls back to the raw
// slug rather than disappearing — an unfamiliar name beats a blank one.
const EXTRACTOR_LABELS: Record<string, string> = {
  opendataloader: "OpenDataLoader",
  mineru: "MinerU",
  "mineru-ocr": "MinerU (OCR)",
};

export function extractorLabel(name: string): string {
  return EXTRACTOR_LABELS[name] ?? name;
}

/** A ratio as a percentage. Never capped at 100% — a coverage above 1.0 is
 *  a real, normal reading for some document shapes (healthy AFRs score
 *  278–286%, because their text layer undercounts against the denominator;
 *  see ingest/coverage.py) and rendering it honestly is the whole point of
 *  showing a raw measurement instead of a verdict. `null`/undefined (a rung
 *  that crashed, or a reading with too few judgeable passages) reads as
 *  "not measured" — never as 0%, which would claim the best possible
 *  reading was taken when in fact none was. */
export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not measured";
  return `${Math.round(value * 100)}%`;
}
