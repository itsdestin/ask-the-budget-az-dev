import * as api from "../api";

// Documents where the extraction ladder kept a LATER method than the one
// it started with (spec X7).
//
// Renders NOTHING when the list is empty — the same rule as NoticesPanel
// and NeedsAttention above it, and the same reasoning: a box that is on
// screen every day teaches an admin to scroll past it.
//
// This is a RECORD, not an alert. Nothing here may say a document was
// verified, checked, validated, healthy or good: the measure behind these
// numbers detects one failure shape and certifies nothing. A passage
// scoring a perfect 0% has been observed carrying a units label wrong by a
// factor of 1,000.
const EXTRACTOR_LABELS: Record<string, string> = {
  opendataloader: "OpenDataLoader",
  mineru: "MinerU",
  "mineru-ocr": "MinerU (OCR)",
};

function extractorLabel(name: string): string {
  return EXTRACTOR_LABELS[name] ?? name;
}

/** A ratio as a percentage. Never capped at 100% — a coverage above 1.0 is
 *  a real, normal reading (healthy AFRs score 278–286%). `null`/undefined
 *  reads as "not measured", never as 0%. */
function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not measured";
  return `${Math.round(value * 100)}%`;
}

export function ExtractionChanges({
  documents,
}: {
  documents: api.SwappedDocument[];
}) {
  if (documents.length === 0) return null;

  return (
    <div className="adm-swaps" data-testid="adm-swaps">
      {documents.map((doc) => (
        <div className="adm-swap" key={doc.job_id} data-testid="adm-swap">
          <p className="adm-attention-title">{doc.title}</p>
          <p className="adm-swap-kept" data-testid="adm-swap-kept">
            Read with {extractorLabel(doc.kept)}
          </p>
          <p className="adm-attention-tried-label">
            Tried, with how much text came out and how much of it was
            figures with no words:
          </p>
          <ul className="adm-attention-tried">
            {doc.attempts.map((attempt, i) => (
              <li
                key={`${attempt.extractor}-${i}`}
                data-testid="adm-swap-attempt"
              >
                <span>{extractorLabel(attempt.extractor)}</span>
                <span>{pct(attempt.coverage)}</span>
                <span>{pct(attempt.unlabelled)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
