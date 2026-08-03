// Shared primitives for the per-tool ToolBody views.
//
// Ported from web/components/tool-views/primitives.tsx. Tailwind utility
// strings became the semantic classes defined in the `/* ===== chat ===== */`
// block of src/styles/app.css; the logic is unchanged.
//
// TWO deliberate API removals, both because their only callers were the
// retired file/shell tool views:
//
//   * `PathHeader` is gone entirely. It rendered a file path, and Plan 4's
//     Invariant 7 removed every filesystem-touching tool, so nothing has a
//     path to show.
//   * `CollapsibleBlock` lost its `className` prop. In `web/` that prop
//     existed solely so ShellView could pass `bg-canvas` to re-tint the
//     output block; styling now lives in app.css and the one tint it carried
//     is the default there. No in-tree caller passes it, so this is a
//     narrowing rather than a breakage — but it IS a narrowing, and a future
//     view that wants a variant should add a named modifier class here rather
//     than reopening a free-form className hole. (Task 12 added exactly one
//     such named modifier — `variant="danger"` — for ErrorBlock; it is still
//     not a className hole, just a second fixed option.)
//
// The pure string helpers below DID come across even though their last
// in-tree caller was one of those retired views — they are dependency-free,
// covered by tests, and Task 11's source panel wants filename display.

import { useState, type ReactNode } from "react";

// Pixel-art SVG glyphs for tool cards. Each glyph is drawn on a
// 0 0 12 12 coordinate space and returned as a <g> element so the
// caller can wrap it in <svg viewBox="0 0 12 12" width=12 height=12>.
// Rects use fill="currentColor" so the caller can tint via CSS color
// (accent normally, danger on error state).
export function toolGlyph(toolName: string): ReactNode {
  switch (toolName) {
    case "retrieve":
      // Magnifier: ring outline (four rects forming the circle) + diagonal handle.
      return (
        <g>
          {/* Ring — top, bottom, left, right arcs approximated as rects */}
          <rect x="3" y="1" width="4" height="1" fill="currentColor" />
          <rect x="3" y="6" width="4" height="1" fill="currentColor" />
          <rect x="1" y="2" width="1" height="4" fill="currentColor" />
          <rect x="7" y="2" width="1" height="4" fill="currentColor" />
          {/* Handle — stepped diagonal going bottom-right */}
          <rect x="8" y="7" width="1" height="2" fill="currentColor" />
          <rect x="9" y="8" width="2" height="1" fill="currentColor" />
        </g>
      );
    case "cite":
    case "cite_batch":
      // Bookmark/page: a rect page with a triangular notch cut from the bottom
      // by leaving a gap — two stacked rects make the bookmark shape.
      return (
        <g>
          {/* Page body */}
          <rect x="2" y="1" width="8" height="1" fill="currentColor" />
          <rect x="2" y="2" width="1" height="8" fill="currentColor" />
          <rect x="9" y="2" width="1" height="8" fill="currentColor" />
          {/* Bottom — two segments with a notch in the middle for bookmark shape */}
          <rect x="2" y="10" width="3" height="1" fill="currentColor" />
          <rect x="7" y="10" width="3" height="1" fill="currentColor" />
          {/* Folded corner mark on page */}
          <rect x="5" y="4" width="3" height="1" fill="currentColor" />
          <rect x="5" y="6" width="3" height="1" fill="currentColor" />
        </g>
      );
    case "list_filter_values":
      // Three stacked horizontal lines — classic list/filter icon.
      return (
        <g>
          <rect x="1" y="2" width="10" height="2" fill="currentColor" />
          <rect x="2" y="5" width="8" height="2" fill="currentColor" />
          <rect x="3" y="8" width="6" height="2" fill="currentColor" />
        </g>
      );
    case "create_document":
      // Down-arrow into a tray — the download idiom, since what this tool
      // produces is a file the analyst clicks to save.
      return (
        <g>
          <rect x="5" y="1" width="2" height="5" fill="currentColor" />
          <rect x="3" y="5" width="6" height="1" fill="currentColor" />
          <rect x="4" y="6" width="4" height="1" fill="currentColor" />
          <rect x="5" y="7" width="2" height="1" fill="currentColor" />
          <rect x="1" y="9" width="10" height="2" fill="currentColor" />
        </g>
      );
    default:
      // Unknown tool — single filled square as a neutral fallback.
      return <rect x="2" y="2" width="8" height="8" fill="currentColor" />;
  }
}

export function basename(fp: string): string {
  const parts = fp.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || fp;
}

export function parentDir(fp: string): string {
  const parts = fp.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

// Reveal literal \n / \" that JSON.stringify would otherwise hide so
// the raw fallback view stays scannable.
export function unescapeForDisplay(s: string): string {
  return s.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\t/g, "\t");
}

// Collapse "\rUpdating files: 42%…\rUpdating files: 91%…" progress
// noise by keeping just the final state of each line group.
export function stripCarriageReturns(s: string): string {
  return s
    .split("\n")
    .map((line) => {
      const parts = line.split("\r");
      return parts[parts.length - 1];
    })
    .join("\n");
}

interface CollapsibleBlockProps {
  children: string;
  maxLines?: number;
  /** Named modifier, not a className hole (see the port note above). "danger"
   *  renders the error tint — this is how ErrorBlock gets a red block without
   *  reopening free-form styling. */
  variant?: "danger";
}

export function CollapsibleBlock({
  children,
  maxLines = 20,
  variant,
}: CollapsibleBlockProps) {
  const [open, setOpen] = useState(false);
  const lines = children.split("\n");
  const overflow = lines.length > maxLines;
  const shown =
    open || !overflow ? children : lines.slice(0, maxLines).join("\n");
  return (
    <div className={`chat-block${variant === "danger" ? " is-danger" : ""}`}>
      <pre>
        {shown}
        {overflow && !open && <span className="chat-muted">{"\n…"}</span>}
      </pre>
      {overflow && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="chat-more"
        >
          {open ? "Show less" : `Show ${lines.length - maxLines} more lines`}
        </button>
      )}
    </div>
  );
}

type ChipTone = "neutral" | "add" | "remove" | "warn" | "info";

// Tinted chips. add/remove/warn keep their own hues because they signal an
// OUTCOME, not brand — see the status-colour note in app.css's chat block.
export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: ChipTone;
}) {
  const toneClass = tone === "neutral" ? "" : ` is-${tone}`;
  return <span className={`chat-chip${toneClass}`}>{children}</span>;
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handle = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be blocked — silently ignore.
    }
  };
  return (
    <button type="button" onClick={handle} className="chat-copy" title="Copy">
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function ErrorBlock({ error }: { error: string }) {
  return (
    <div>
      <div className="chat-error-label">Error</div>
      {/* Collapse, don't scroll: a 192px inner scrollbar inside the thread
          scroller was one of the "scrollbars everywhere" offenders (Task 12).
          Routing through the same CollapsibleBlock every other tool body uses
          also means a long error gets a "Show N more lines" toggle instead of
          a bespoke scroll box — one behavior for long output, not two. */}
      <CollapsibleBlock maxLines={20} variant="danger">
        {error}
      </CollapsibleBlock>
    </div>
  );
}
