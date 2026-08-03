// The header's tools menu — Upload, Settings, Admin behind one icon.
//
// Destin, 2026-08-02. Those three were top-level pills competing for width with
// the two things analysts actually came for (Budget Documents, Fiscal Notes),
// and they are not the same KIND of thing: two are places you read, three are
// places you administer. Consolidating them frees the middle of the bar for the
// AI Mode pill and makes the row say what the app is for.
//
// It opens on hover, per the ask — but hover cannot be the only way in. A
// keyboard user has no pointer to hover with, and this is the only route to
// Settings in the app. So the trigger is a real <button> with aria-expanded
// that also opens on click and on focus, and the menu closes on Escape, on
// outside click, and on pointer-leave.
//
// TWO THINGS MAKE THE POINTER TRIP SURVIVABLE, and the menu was unusable
// without them (Destin, 2026-08-02: "i cant reach upload/settings, they
// disappear when i try to scroll to them"):
//
//  1. The popover is absolutely positioned, so the 8px between it and the
//     button belongs to NEITHER element. Crossing that dead space put the
//     pointer over the header, which is outside this component's subtree, so
//     `mouseleave` fired and the menu shut before it could be reached.
//     `.nav-tools-pop::before` bridges it — a transparent strip that is part
//     of the popover, so the subtree is never actually left.
//  2. A short grace period before closing, so a diagonal path toward the last
//     item — which briefly clips outside the popover's box — does not kill it
//     either. Re-entering cancels the pending close.

import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

/** Everything reachable from the menu. `adminOnly` items are filtered by the
 *  caller — this is presentation, not protection (see Header's note on S11). */
const TOOLS = [
  {
    to: "/upload",
    label: "Upload",
    hint: "Add a document to the corpus",
    adminOnly: false,
  },
  {
    to: "/settings",
    label: "Settings",
    hint: "Your preferences and usage",
    adminOnly: false,
  },
  {
    to: "/admin",
    label: "Admin",
    hint: "AI Mode, models, spending, corpus health",
    adminOnly: true,
  },
] as const;

/** Icons drawn to the house/sparkle recipe: 24×24, `fill="none"`,
 *  `stroke="currentColor"`, 2px, round caps and joins. No fills, no gradients —
 *  the set has to read as one hand. */
function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 16V4" />
      <path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
      <path d="M4 16v3h16v-3" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3.2" />
      {/* Eight spokes rather than a traced cog outline: at the 18px this renders
          at, a cog's teeth close up into a ring and the shape stops reading. */}
      <path d="M12 3v2.4M12 18.6V21M21 12h-2.4M5.4 12H3" />
      <path d="m18.4 5.6-1.7 1.7M7.3 16.7l-1.7 1.7M18.4 18.4l-1.7-1.7M7.3 7.3 5.6 5.6" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {/* A shield: this is the seat that can spend money and rebuild the
          corpus, so it should not look like another settings page. */}
      <path d="M12 3.2 19.5 6v6c0 4-3.2 7.2-7.5 8.8C7.7 19.2 4.5 16 4.5 12V6z" />
      <path d="m9 12 2.2 2.2L15.4 10" />
    </svg>
  );
}

const ICONS: Record<string, () => JSX.Element> = {
  "/upload": UploadIcon,
  "/settings": SettingsIcon,
  "/admin": AdminIcon,
};

/** Grace period before a pointer-leave actually closes the menu. Long enough to
 *  forgive a diagonal path across the popover's corner, short enough that it
 *  never feels stuck open. */
const CLOSE_GRACE_MS = 160;

export function ToolsNav({ isAdmin }: { isAdmin: boolean }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<number | null>(null);
  const { pathname } = useLocation();

  const items = TOOLS.filter((t) => !t.adminOnly || isAdmin);
  // The trigger reads as selected whenever the page you are ON lives in here.
  // Without it the header would show NO active pill on /settings, and the app
  // would look like it had lost track of where you are.
  const onToolsPage = items.some(
    (t) => pathname === t.to || pathname.startsWith(`${t.to}/`),
  );

  const cancelPendingClose = useCallback(() => {
    if (closeTimer.current === null) return;
    window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }, []);

  /** Shut it now — Escape, an outside click, a navigation. */
  const close = useCallback(() => {
    cancelPendingClose();
    setOpen(false);
  }, [cancelPendingClose]);

  const openNow = useCallback(() => {
    cancelPendingClose();
    setOpen(true);
  }, [cancelPendingClose]);

  /** Shut it shortly — the pointer left, but it may be on its way back. */
  const closeSoon = useCallback(() => {
    cancelPendingClose();
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      setOpen(false);
    }, CLOSE_GRACE_MS);
  }, [cancelPendingClose]);

  // A pending close outliving the component would call setState on an
  // unmounted one every time the header re-renders during a route change.
  useEffect(() => cancelPendingClose, [cancelPendingClose]);

  useEffect(() => {
    if (!open) return;
    const onDocPointer = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDocPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  // Navigating is the one thing that must always shut it: the menu is
  // position:absolute over the page, so a route change with it still open
  // leaves it floating over content it no longer belongs to.
  useEffect(close, [pathname, close]);

  return (
    <div
      className="nav-tools"
      ref={wrapRef}
      onMouseEnter={openNow}
      onMouseLeave={closeSoon}
    >
      <button
        type="button"
        className={onToolsPage ? "nav-tools-btn is-current" : "nav-tools-btn"}
        aria-label="Menu"
        title="Upload, settings and admin"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="nav-tools-button"
        onClick={() => {
          cancelPendingClose();
          setOpen((v) => !v);
        }}
        onFocus={openNow}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>

      {open && (
        <div className="nav-tools-pop" role="menu" aria-label="Menu">
          {items.map((item) => {
            const Icon = ICONS[item.to];
            return (
              <NavLink
                key={item.to}
                to={item.to}
                role="menuitem"
                // `is-current` rather than leaning on NavLink's own `active`
                // class: the fill has to be able to LEAVE the current item when
                // the pointer moves to another one, and that is a CSS rule
                // keyed on hovering the menu (see .nav-tools-pop:hover in
                // app.css). Keeping our own class keeps the two ideas — "this
                // is where you are" and "this is what you are pointing at" —
                // separable.
                className={({ isActive }) =>
                  isActive ? "nav-tools-item is-current" : "nav-tools-item"
                }
                onClick={close}
              >
                <span className="nav-tools-ic">
                  <Icon />
                </span>
                <span className="nav-tools-body">
                  <span className="nav-tools-label">{item.label}</span>
                  <span className="nav-tools-hint">{item.hint}</span>
                </span>
              </NavLink>
            );
          })}
        </div>
      )}
    </div>
  );
}
