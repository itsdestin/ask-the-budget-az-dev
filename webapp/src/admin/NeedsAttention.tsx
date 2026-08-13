import { useState } from "react";
import * as api from "../api";

// Documents the extraction ladder could not save (Plan B Task 7 / spec T8).
//
// Renders NOTHING at all when the list is empty — same rule as
// NoticesPanel just below it, and the same reasoning: a box that is on
// screen every day teaches an admin to scroll past it, which is exactly
// the habit that makes it useless the one day it has something to say.
// A "0 documents need attention" line would be restating what the
// interface already shows by not showing anything.
//
// The check this panel reports on detects CATASTROPHIC TEXT LOSS, not
// correctness — it cannot see a document that produced the right AMOUNT of
// the WRONG text (see ingest/coverage.py). So nothing here may say a
// document was verified, checked, validated, healthy or good. Every
// sentence says only what was MEASURED: how much of the page's text
// produced any content at all. The main message line is the job's OWN
// sentence from the server (`ingest/worker.py::_held_out_message`) rather
// than one rebuilt here, so there is exactly one place in the whole system
// that has to get that wording right.

// Display names for the ladder's rungs (`ingest/ladder.py::_PDF_LADDER`).
// A name this map doesn't know (a rung added later) falls back to the raw
// slug rather than disappearing — an unfamiliar name beats a blank one.
const EXTRACTOR_LABELS: Record<string, string> = {
  opendataloader: "OpenDataLoader",
  mineru: "MinerU",
  "mineru-ocr": "MinerU (OCR)",
};

function extractorLabel(name: string): string {
  return EXTRACTOR_LABELS[name] ?? name;
}

/** A coverage ratio as a percentage. Never capped at 100% — a ratio above
 *  1.0 is a real, normal reading for some document shapes (healthy AFRs
 *  score 278–286%, because their text layer undercounts against the
 *  denominator; see ingest/coverage.py) and rendering it honestly is the
 *  whole point of showing a raw measurement instead of a verdict. `null`
 *  (a rung that crashed, or whose source coverage could not be measured)
 *  reads as "not measured" — never as 0%, which would claim a worse
 *  reading than was actually taken. */
function pct(value: number | null): string {
  if (value === null) return "not measured";
  return `${Math.round(value * 100)}%`;
}

export function NeedsAttention({
  documents,
  onRetry,
  onDismiss,
}: {
  documents: api.AttentionDocument[];
  onRetry: (jobId: string) => void;
  onDismiss: (jobId: string) => void;
}) {
  // Which document's Dismiss button is armed. Dismissing hides a document
  // from the only surface that reports it exists at all — the same stakes
  // as the chat-history delete this pattern is copied from — so it is a
  // labelled second click ("Dismiss?"), not a same-glyph double-click that
  // a reflexive second tap could trigger by accident.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  if (documents.length === 0) return null;

  return (
    <section
      className="card adm-panel adm-panel-alert"
      aria-labelledby="adm-attention-h"
      data-testid="admin-attention"
    >
      <div className="adm-panel-head">
        <h2 id="adm-attention-h">Needs attention</h2>
        <span className="adm-attention-count" data-testid="admin-attention-count">
          {documents.length}
        </span>
      </div>

      <ul className="adm-attention-list">
        {documents.map((doc) => (
          <li
            key={doc.job_id}
            className="adm-attention-item"
            data-testid="admin-attention-doc"
          >
            <p className="adm-attention-title">{doc.title}</p>
            <p className="adm-warn">{doc.message}</p>

            <ul className="adm-attention-tried">
              {doc.attempts.map((attempt, i) => (
                <li key={`${attempt.extractor}-${i}`}>
                  <span>{extractorLabel(attempt.extractor)}</span>
                  <span>{pct(attempt.coverage)}</span>
                </li>
              ))}
            </ul>

            <div className="adm-attention-actions">
              <button
                type="button"
                className="adm-btn adm-btn-quiet"
                onClick={() => {
                  setConfirmingId(null);
                  onRetry(doc.job_id);
                }}
              >
                Try again
              </button>
              {confirmingId === doc.job_id ? (
                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  aria-label={`Confirm dismiss ${doc.title}`}
                  onBlur={() => setConfirmingId(null)}
                  onClick={() => {
                    setConfirmingId(null);
                    onDismiss(doc.job_id);
                  }}
                >
                  Dismiss?
                </button>
              ) : (
                <button
                  type="button"
                  className="adm-btn adm-btn-quiet"
                  onClick={() => setConfirmingId(doc.job_id)}
                >
                  Dismiss
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
