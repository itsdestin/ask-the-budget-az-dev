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
}

const STATUS_LABEL: Record<ToolBlock["status"], string> = {
  running: "running",
  complete: "complete",
  failed: "failed",
};

// Glyph colour encodes status on its own — running amber, failed red,
// complete the accent blue. The separate coloured circle dot that used to sit
// next to the glyph was dropped: two status indicators side by side were
// redundant and visually noisy. The square pixel-glyph is the single source
// of truth.
const STATUS_GLYPH_COLOR: Record<ToolBlock["status"], string> = {
  running: "var(--chat-warn)",
  complete: "var(--az-gold)",
  failed: "var(--chat-danger)",
};

export default function ToolCard({ tool }: Props) {
  const [open, setOpen] = useState(false);
  const label = toolDisplayLabel(tool.toolName);
  const summary = toolHeaderSummary(tool.toolName, tool.input);

  // Failed status also drives the left-border accent, because a failed tool
  // is the case worth shouting about and the border picks it up even when the
  // 12px glyph does not.
  const isFailed = tool.status === "failed";

  return (
    <div className={`chat-tool${isFailed ? " is-failed" : ""}`}>
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {/* Pixel-art tool glyph — colour encodes status. Pulses while running. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          style={{ color: STATUS_GLYPH_COLOR[tool.status] }}
          className={
            "chat-tool-glyph" +
            (tool.status === "running" ? " chat-pulse" : "")
          }
          role="img"
          aria-label={STATUS_LABEL[tool.status]}
        >
          {toolGlyph(tool.toolName)}
        </svg>
        <span className="chat-tool-label">{label}</span>
        {summary && <span className="chat-tool-summary">{summary}</span>}
        <span className="chat-tool-toggle">{open ? "−" : "+"}</span>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}
