// The report-format chooser: JLBC publishes an annual report BOTH as a
// "Linked Table of Contents" index (each agency/section its own smaller PDF)
// and as one complete "Single File PDF". Recovered 2026-08-10 from master's
// components/ResultCard.tsx — markup and copy verbatim — after the
// browse-first rewrite wired "Full report" straight to singleFile and made
// linkedToc unreachable data.
//
// WHY a modal and not two inline pills (Destin, 2026-08-10): most readers do
// not know what a "Linked Table of Contents" PDF is, and "best for jumping
// straight to one agency without downloading the whole report" has nowhere to
// live in a pill. The dialog is the only place that copy fits.
//
// The dialog SHELL — backdrop, focus trap, focus restore, Escape — moved to
// components/Modal.tsx (2026-08-12) when the admin page grew a second dialog.
// This file keeps only the chooser's own header and choices; the markup it
// renders is unchanged.
//
// WHY this component does not pick its own mount point: it renders wherever
// its parent puts it in the tree. The shell's own rules are unscoped, but the
// `.choice` rules below are still scoped `.page-docs .report-modal .choice...`
// (see the CSS block in app.css), so this chooser MUST be mounted somewhere
// inside `<main className="page-docs">` or its two options paint unstyled.
// Task 3 owns the mount point; this note is so that isn't rediscovered the
// hard way a second time.

import { BookIcon, DocIcon, OpenIcon } from "./DocIcons";
import { Modal } from "./Modal";
import type { ReportFormats } from "../reportFamilies";

export function ReportChooser({
  title,
  formats,
  onClose,
}: {
  title: string;
  formats: ReportFormats;
  onClose: () => void;
}) {
  // `initialFocus` is deliberately narrower than the shell's default: the
  // close button sits in `.mhead`, before `.mbody`'s links in DOM order, so
  // the default would land opening focus on "Close" instead of the first
  // format choice — the reader's actual next action. The shell's Tab trap
  // still uses the full focusable list, so Close stays reachable.
  return (
    <Modal
      label="Open the full report"
      initialFocus=".mbody a[href]"
      onClose={onClose}
    >
        <div className="mhead">
          <span className="mic">
            <BookIcon />
          </span>
          <span className="mt">
            <b>{title}</b>
            <span>Choose how you&rsquo;d like to open it</span>
          </span>
          <button className="mx" type="button" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="mbody">
          {formats.linkedToc && (
            <a
              className="choice linked"
              href={formats.linkedToc}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
                  <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
                </svg>
              </span>
              <span className="cc">
                <b>Linked Table of Contents</b>
                <p>An index page where each agency and section is a link that opens its own smaller PDF.</p>
                <span className="best">
                  Best for jumping straight to one agency or section without downloading the whole report.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
          {formats.singleFile && (
            <a
              className="choice single"
              href={formats.singleFile}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                <DocIcon />
              </span>
              <span className="cc">
                <b>Single File PDF</b>
                <p>The complete report as one document — every agency and summary in a single PDF.</p>
                <span className="best">
                  Best for reading start to finish, searching the whole report, or printing. Largest download.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
        </div>
    </Modal>
  );
}
