// ToolCard shell. The header (status glyph, tool label, one-line input
// summary, expand toggle) lives here; the expanded body is rendered by
// `tool-views/ToolBody.tsx`, which dispatches per-tool views.
//
// Display logic — friendly labels + summary text — lives in tool-display.ts
// so per-tool views can reuse the same naming without re-deriving it.
//
// Ported from web/components/ToolCard.tsx.

import { useState } from "react";

import { toolDisplayLabel, toolHeaderSummary } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolBody from "./tool-views/ToolBody.js";
import { ToolGlyph } from "./tool-views/primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tool: ToolBlock;
  /** Rendered inside a ToolGroup — takes the recessed tint so the group
   *  header and its children read as one surface with a lifted inner step. */
  inGroup?: boolean;
  /** Optional controlled open state. When the caller doesn't supply one (the
   *  n=1 `tool-card.test.tsx` fixtures render this bare), the component falls
   *  back to its own `useState` — unchanged behaviour for every existing
   *  caller. AssistantTurnBubble supplies both when rendering an in-group
   *  ToolCard, so the open/closed state survives the TC1 move into the
   *  answer bubble instead of resetting on remount — see
   *  docs/superpowers/specs/2026-08-22-tool-card-open-state-design.md. */
  open?: boolean;
  onToggle?: () => void;
}

const STATUS_LABEL: Record<ToolBlock["status"], string> = {
  running: "running",
  complete: "complete",
  failed: "failed",
};

export default function ToolCard({
  tool,
  inGroup = false,
  open: controlledOpen,
  onToggle: controlledToggle,
}: Props) {
  const [localOpen, setLocalOpen] = useState(false);
  // `??` (not `||`) is load-bearing: a controlled `open={false}` must win
  // over the local fallback, not be treated as "no value supplied".
  const open = controlledOpen ?? localOpen;
  const toggle = controlledToggle ?? (() => setLocalOpen((v) => !v));
  const label = toolDisplayLabel(tool.toolName);
  const summary = toolHeaderSummary(tool.toolName, tool.input);
  const isFailed = tool.status === "failed";

  return (
    <div
      className={`chat-tool${isFailed ? " is-failed" : ""}${inGroup ? " is-inset" : ""}`}
    >
      <button
        type="button"
        className="chat-tool-head"
        onClick={toggle}
        aria-expanded={open}
      >
        {/* Status is carried by the glyph's SHAPE plus the pulse — color goes
            neutral so a run of successful tools reads quiet. Only failure
            keeps a color, because failure is the state worth shouting about
            (Core Invariant 3). Tinting moved from inline style to CSS. */}
        <ToolGlyph
          tool={tool.toolName}
          running={tool.status === "running"}
          label={STATUS_LABEL[tool.status]}
        />
        <span className="chat-tool-label">{label}</span>
        {summary && <span className="chat-tool-summary">{summary}</span>}
        <svg
          viewBox="0 0 10 6"
          width={10}
          height={6}
          className={`chat-tool-chevron${open ? " is-open" : ""}`}
          aria-hidden="true"
        >
          <path
            d="M1 1l4 4 4-4"
            stroke="currentColor"
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}
