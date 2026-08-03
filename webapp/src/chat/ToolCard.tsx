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
import { toolGlyph } from "./tool-views/primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tool: ToolBlock;
  /** Rendered inside a ToolGroup — takes the recessed tint so the group
   *  header and its children read as one surface with a lifted inner step. */
  inGroup?: boolean;
}

const STATUS_LABEL: Record<ToolBlock["status"], string> = {
  running: "running",
  complete: "complete",
  failed: "failed",
};

export default function ToolCard({ tool, inGroup = false }: Props) {
  const [open, setOpen] = useState(false);
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
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {/* Status is carried by the glyph's SHAPE plus the pulse — color goes
            neutral so a run of successful tools reads quiet. Only failure
            keeps a color, because failure is the state worth shouting about
            (Core Invariant 3). Tinting moved from inline style to CSS. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          className={
            "chat-tool-glyph" + (tool.status === "running" ? " chat-pulse" : "")
          }
          role="img"
          aria-label={STATUS_LABEL[tool.status]}
        >
          {toolGlyph(tool.toolName)}
        </svg>
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
