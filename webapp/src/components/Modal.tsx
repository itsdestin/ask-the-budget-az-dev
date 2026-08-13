// The app's one dialog shell — backdrop, sheet, and the three things a
// hand-rolled modal forgets.
//
// Extracted 2026-08-12 from components/ReportChooser.tsx, unchanged in
// behaviour, when a second dialog arrived (the admin page's "See System
// Guidance" window). WHY extracted rather than copied: what lives here is
// the focus trap, the focus restore and the Escape handler — subtle
// keyboard-accessibility code whose failures are invisible to anyone using
// a mouse. Two copies of it would drift, and the drift would be silent.
//
// Markup is deliberately identical to what ReportChooser drew before the
// extraction, down to the class names, so its own specs and the shipped
// CSS both still apply.
//
// The consumer supplies `.mhead` and `.mbody` itself: the two dialogs put
// different things in the header, and pushing that through props would be
// a bigger interface than the markup it replaces.

import { useEffect, useRef } from "react";

/** Everything focusable a sheet can contain. Queried live on each Tab
 *  rather than cached: a sheet's contents change (a section opens, a list
 *  loads), and a cached list would trap focus on nodes that are gone. */
const FOCUSABLE = 'a[href], button:not([disabled])';

export function Modal({
  label,
  initialFocus,
  sheetClassName,
  onClose,
  children,
}: {
  /** What a screen reader announces the dialog as. */
  label: string;
  /** CSS selector for the node opening focus should land on. Defaults to
   *  the first focusable node, which is normally the Close button — pass
   *  something else when the reader's real next action is further down. */
  initialFocus?: string;
  /** Extra classes for the sheet itself (e.g. a wide variant). */
  sheetClassName?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  // Move focus in, and put it back where it came from on close. Without the
  // restore, closing drops focus onto <body> and a keyboard user has to Tab
  // from the top of the page to get back to where they were.
  useEffect(() => {
    restoreTo.current = document.activeElement as HTMLElement | null;
    // Falls back to the first FOCUSABLE node when `initialFocus` matches
    // nothing — a sheet whose body is still loading has none of its own
    // content yet, and an unguarded query would leave focus OUTSIDE the
    // dialog, which also disarms the Tab trap below (its wrap only fires
    // once activeElement is already the trap's first or last node).
    (
      (initialFocus
        ? sheet.current?.querySelector<HTMLElement>(initialFocus)
        : null) ?? sheet.current?.querySelector<HTMLElement>(FOCUSABLE)
    )?.focus();
    return () => restoreTo.current?.focus?.();
  }, [initialFocus]);

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
      // Wrap at both ends. jsdom does not move focus on Tab, so the specs
      // for this assert the wrap, not the browser's own default step.
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
      aria-label={label}
      // Backdrop click only — currentTarget is the backdrop, so a click that
      // started inside the sheet never closes it.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={sheetClassName ? `modal ${sheetClassName}` : "modal"} ref={sheet}>
        {children}
      </div>
    </div>
  );
}
