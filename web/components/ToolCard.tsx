"use client";

// ToolCard shell. The header (status dot, tool label, one-line input
// summary, expand toggle) lives here; the expanded body is rendered
// by `tool-views/ToolBody.tsx`, which dispatches per-tool views.
// Mirrors YouCoded's split between ToolCard.tsx (shell) and
// tool-views/ToolBody.tsx (per-tool dispatcher) per D9.
//
// Display logic — friendly labels + summary text — lives in
// lib/tool-display.ts so per-tool views can reuse the same naming
// without re-deriving from raw MCP names.

import { useState } from "react";

import { toolDisplayLabel, toolHeaderSummary } from "@/lib/tool-display";
import type { AssistantBlock } from "@/state/chat-types";
import ToolBody from "./tool-views/ToolBody";
import { toolGlyph } from "./tool-views/primitives";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tool: ToolBlock;
}

const STATUS_LABEL: Record<ToolBlock["status"], string> = {
  running: "running",
  complete: "complete",
  failed: "failed",
};

// Glyph color encodes status on its own — running uses --warning (amber),
// failed uses --danger (red), complete falls back to --accent (civic blue).
// We dropped the separate colored circle dot that previously sat next to
// the glyph; having two status indicators side-by-side was redundant and
// visually noisy. The square pixel-glyph is now the single source of truth.
const STATUS_GLYPH_COLOR: Record<ToolBlock["status"], string> = {
  running: "var(--warning)",
  complete: "var(--accent)",
  failed: "var(--danger)",
};

export default function ToolCard({ tool }: Props) {
  const [open, setOpen] = useState(false);
  const label = toolDisplayLabel(tool.toolName);
  const summary = toolHeaderSummary(tool.toolName, tool.input);

  // Failed status still drives the left-border accent in addition to the
  // glyph color, because a failed tool is the case worth shouting about
  // and the border picks it up even when the glyph is small.
  const isFailed = tool.status === "failed";
  const glyphColor = STATUS_GLYPH_COLOR[tool.status];

  return (
    <div
      className={`rounded-lg border border-edge bg-panel my-2 overflow-hidden${
        isFailed ? " border-l-2" : ""
      }`}
      style={isFailed ? { borderLeftColor: "var(--danger)" } : undefined}
    >
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-fg-2 bg-panel hover:bg-inset transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        {/* Pixel-art tool glyph — color encodes status (running=warning,
            complete=accent, failed=danger). Pulses while running. This
            single square replaces the previous glyph + colored-circle pair
            so the header has one status indicator instead of two. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          style={{ color: glyphColor, flexShrink: 0 }}
          className={tool.status === "running" ? "animate-pulse" : undefined}
          role="img"
          aria-label={STATUS_LABEL[tool.status]}
        >
          {toolGlyph(tool.toolName)}
        </svg>
        <span className="font-sans font-semibold text-fg shrink-0">{label}</span>
        {summary && (
          <span className="text-fg-dim truncate text-xs min-w-0">
            {summary}
          </span>
        )}
        <span className="ml-auto font-mono text-fg-muted text-xs select-none shrink-0">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}
