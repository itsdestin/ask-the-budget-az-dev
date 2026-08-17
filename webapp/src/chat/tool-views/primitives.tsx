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

// Stroked line icons on a 24x24 grid, returned as a bare <g>.
//
// NOT exported. This is the exact shape of the defect this file's callers
// hit on 2026-08-16: the glyph set was redrawn from 12x12 filled rects to
// 24x24 stroked paths, and TWO callers (ToolCard.tsx, ToolGroup.tsx) each
// hand-rolled their own <svg viewBox=...> wrapper around this function's
// return value. One caller's wrapper was updated to match; the other
// (ToolGroup.tsx) was edited in a parallel worktree that never touched this
// file, so git merged both branches clean and every suite stayed green while
// ToolGroup rendered a cropped quarter of each icon on the wrong grid — on
// the single most visible icon in the chat, the collapsed tool card.
//
// The fix is not "remember to update both wrappers" — it is that there is
// now only ONE wrapper. `ToolGlyph` below is the only way to render one of
// these shapes; a caller that wants a tool's icon renders `<ToolGlyph .../>`
// and can no longer choose a viewBox at all, correct or otherwise. Keeping
// this function private is what makes that structural rather than a
// convention — an un-exported binding cannot be imported into ToolCard.tsx
// or ToolGroup.tsx or any future third caller, so `tsc -b` refuses a
// reintroduction of the old shape before any test has to catch it.
// `tool-glyph-contract.test.ts` pins the property anyway, in case a later
// change re-exports this function without reading this comment.
function toolGlyph(toolName: string): ReactNode {
  switch (toolName) {
    case "retrieve":
      // The app's own magnifier, verbatim from components/SearchIcon.tsx.
      return (
        <g>
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </g>
      );
    case "cite":
    case "cite_batch":
      // Never rendered — cite blocks are suppressed (TC7) — but kept so the
      // set is total and a future caller cannot fall through to nothing.
      return (
        <g>
          <path d="M6 3h12v18l-6-4-6 4z" />
        </g>
      );
    case "list_filter_values":
      return (
        <g>
          <path d="M3 5h18l-7 8v6l-4 2v-8z" />
        </g>
      );
    case "create_document":
      return (
        <g>
          <path d="M6 3h8l4 4v14H6z" />
          <path d="M14 3v4h4" />
          <path d="M9 12h6M9 16h6" />
        </g>
      );
    case "document_guide":
      // An open book. This tool had NO case at all and fell through to the
      // square below, which is what left it iconless in the UI.
      return (
        <g>
          <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H19v18H6.5A2.5 2.5 0 0 0 4 22z" />
          <path d="M9 7h6" />
        </g>
      );
    default:
      // Unknown tool — a neutral square outline.
      return <rect x="4" y="4" width="16" height="16" rx="2" />;
  }
}

interface ToolGlyphProps {
  /** The tool call name, e.g. tool.toolName / first.toolName. */
  tool: string;
  /** Pulses the glyph while the call is in flight. Deliberately the only
   *  status this component reads: ToolGroup's shipped decision (TC9) is that
   *  the collapsed header spends no COLOUR on failure, so there is no
   *  "failed" variant here to accidentally wire up. ToolCard's own failure
   *  tint lives on `.chat-tool.is-failed` in the card shell, not the glyph. */
  running?: boolean;
  /** Accessible name for this glyph. Pass the status word (ToolCard: the
   *  button carries no aria-label of its own, so the glyph IS the accessible
   *  name). Omit it — the default — to render `aria-hidden="true"` instead,
   *  for a caller whose own button already carries the full aria-label
   *  (ToolGroup's header sentence). Do not pass an empty string meaning to
   *  label it: `label=""` renders `role="img" aria-label=""`, which is a
   *  worse accessible name than aria-hidden — omit the prop instead. */
  label?: string;
  /** Both current callers render at 13px; kept a prop rather than a fixed
   *  constant only because a size is a legitimate per-caller choice and a
   *  fixed constant would invite exactly the copy-paste this component
   *  exists to prevent. */
  size?: number;
}

// The ONE place a tool glyph is wrapped in an <svg>. See the WHY comment on
// `toolGlyph` above — this component existing at all is the fix.
export function ToolGlyph({
  tool,
  running = false,
  label,
  size = 13,
}: ToolGlyphProps) {
  const a11yProps = label
    ? { role: "img" as const, "aria-label": label }
    : { "aria-hidden": "true" as const };
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinejoin="round"
      strokeLinecap="round"
      className={"chat-tool-glyph" + (running ? " chat-pulse" : "")}
      {...a11yProps}
    >
      {toolGlyph(tool)}
    </svg>
  );
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
