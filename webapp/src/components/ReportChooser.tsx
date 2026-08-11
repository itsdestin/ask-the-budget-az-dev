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
// It is the ONLY modal on this page — every other control is inline — so it
// owes the two things a lone dialog usually forgets: focus goes IN on open and
// is RESTORED on close, and focus cannot Tab back out to the page behind it.
//
// WHY this component does not pick its own mount point: it renders wherever
// its parent puts it in the tree, but every declaration below is scoped
// `.page-docs .report-modal...` (see the CSS block at the end of app.css) —
// this `position:fixed` overlay MUST be mounted somewhere inside
// `<main className="page-docs">`, or none of its rules match and it paints as
// an unstyled block. Task 3 owns the mount point; this note is so that isn't
// rediscovered the hard way a second time.

import { useEffect, useRef } from "react";

import { BookIcon, DocIcon, OpenIcon } from "./DocIcons";
import type { ReportFormats } from "../reportFamilies";

/** Everything focusable the sheet can contain. Queried live on each Tab
 *  rather than cached: a one-format chooser has fewer nodes than a
 *  two-format one, and caching would trap focus on a stale list. */
const FOCUSABLE = 'a[href], button:not([disabled])';

export function ReportChooser({
  title,
  formats,
  onClose,
}: {
  title: string;
  formats: ReportFormats;
  onClose: () => void;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  // Move focus in, and put it back where it came from on close. Without the
  // restore, closing the dialog drops focus onto <body> and a keyboard user
  // has to Tab from the top of the page to get back to the report they were
  // reading.
  //
  // Deliberately narrower than FOCUSABLE: the close button sits in `.mhead`,
  // before `.mbody`'s links in DOM order, so querying the full FOCUSABLE list
  // here would land opening focus on "Close" instead of the first format
  // choice — the reader's actual next action. The Tab trap below still uses
  // the full list, so the button stays reachable and wrap-around still works.
  useEffect(() => {
    restoreTo.current = document.activeElement as HTMLElement | null;
    // Fall back to the first FOCUSABLE node (the Close button) when neither
    // format is present: formats={singleFile: null, linkedToc: null} is a
    // value the ReportFormats type explicitly allows, and .mbody renders zero
    // <a> elements in that case. An unguarded ".mbody a[href]" query then
    // returns null, .focus() silently never runs, and focus is left outside
    // the dialog — which also disarms the Tab trap below, since its wrap
    // logic only fires once document.activeElement is already the trap's
    // first/last node.
    (
      sheet.current?.querySelector<HTMLElement>(".mbody a[href]") ??
      sheet.current?.querySelector<HTMLElement>(FOCUSABLE)
    )?.focus();
    return () => restoreTo.current?.focus?.();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const nodes = sheet.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!nodes?.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      // Wrap at both ends. jsdom does not move focus on Tab, so the test for
      // this asserts the wrap, not the browser's own default step.
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="report-modal open"
      role="dialog"
      aria-modal="true"
      aria-label="Open the full report"
      // Backdrop click only — currentTarget is the backdrop, so a click that
      // started inside the sheet never closes it.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" ref={sheet}>
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
      </div>
    </div>
  );
}
