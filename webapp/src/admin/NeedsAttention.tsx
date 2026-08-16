import { useState } from "react";
import * as api from "../api";
import { extractorLabel, pct } from "./extractionDisplay";

// Documents the extraction ladder could not save (Plan B Task 7 / spec T8).
//
// Renders NOTHING at all when the list is empty — same rule as
// NoticesPanel, which sits just above it on the page, and the same
// reasoning: a box that is on screen every day teaches an admin to scroll
// past it, which is exactly the habit that makes it useless the one day it
// has something to say.
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

// `extractorLabel` and `pct` moved to ./extractionDisplay when the third
// extraction panel arrived — they were byte-identical copies here and in
// ExtractionChanges, and a third would have made drift inevitable.

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
        {/* "Held out of search", not "Needs attention" (merge with master,
            2026-08-13): master added a Group whose title is already "Needs
            attention", and this panel now sits inside it. Two identical
            headings, one nested in the other, would read as a bug. This
            wording is also what the document's own failure sentence says
            ("Held out of search -- only 2% of this document's text produced
            any content"), so the panel and the row agree. */}
        <h2 id="adm-attention-h">Held out of search</h2>
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

            {/* doc.best_coverage is part of the route's contract
                (task-7-brief.md) but is deliberately not rendered here --
                the "Tried:" list just below already shows every rung's own
                score, so repeating their max as a fourth number would say
                nothing a reader can't already see. Left in the API for a
                future consumer that wants the single number (e.g. sorting
                the panel by severity) without re-deriving it. */}

            {/* The agreed layout (task-7-brief.md) labels this list so the
                reader knows what the name/percent pairs below it are --
                without a caption they're bare rows with two numbers pointing
                in OPPOSITE directions (higher coverage is better, higher
                unlabelled is worse) and nothing saying which is which.
                Wording matches ExtractionChanges.tsx's identical list --
                one caption, not two near-duplicates. */}
            <p className="adm-attention-tried-label">
              Tried, with how much text came out and how much of it was
              figures with no words:
            </p>
            <ul className="adm-attention-tried">
              {doc.attempts.map((attempt, i) => (
                <li key={`${attempt.extractor}-${i}`}>
                  <span>{extractorLabel(attempt.extractor)}</span>
                  <span>{pct(attempt.coverage)}</span>
                  {/* The second number is how much of what came out was
                      figures with no words. It is shown beside coverage
                      rather than instead of it because the two DISAGREE:
                      the document this feature exists for read 49% on
                      coverage and 31% bare on structure. `pct` renders an
                      absent value as "not measured" -- job files written
                      before this field existed have no such key. */}
                  <span>{pct(attempt.unlabelled)}</span>
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
