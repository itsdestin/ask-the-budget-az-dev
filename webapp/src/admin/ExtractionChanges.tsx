import * as api from "../api";
import { extractorLabel, pct } from "./extractionDisplay";

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
//
// `extractorLabel` and `pct` moved to ./extractionDisplay when the third
// extraction panel arrived — they were byte-identical copies here and in
// NeedsAttention, and a third would have made drift inevitable.

export function ExtractionChanges({
  documents,
}: {
  documents: api.SwappedDocument[];
}) {
  if (documents.length === 0) return null;

  return (
    // `card adm-panel` + `.adm-attention-list`'s flex/gap are REUSED, not
    // re-authored: this panel was the only admin panel with no card chrome
    // at all (no siblings' background/border/padding, and no gap between
    // one swapped document's rows and the next document's title). Every
    // other rule this component needs (`.adm-attention-title`,
    // `.adm-attention-tried-label`, `.adm-attention-tried`) already exists
    // and is unchanged below.
    <div className="adm-swaps card adm-panel adm-attention-list" data-testid="adm-swaps">
      {documents.map((doc) => (
        <div className="adm-swap adm-attention-item" key={doc.job_id} data-testid="adm-swap">
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
