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

const STATUS_DOT: Record<ToolBlock["status"], string> = {
  running: "bg-amber-700 animate-pulse",
  complete: "bg-green-400",
  failed: "bg-red-400",
};

const STATUS_LABEL: Record<ToolBlock["status"], string> = {
  running: "running",
  complete: "complete",
  failed: "failed",
};

export default function ToolCard({ tool }: Props) {
  const [open, setOpen] = useState(false);
  const label = toolDisplayLabel(tool.toolName);
  const summary = toolHeaderSummary(tool.toolName, tool.input);

  // Detect error state: status "failed" is the signal in this file.
  // When failed, shift the accent to danger so the glyph and left border
  // call out the problem visually without relying on the subtle red dot alone.
  const isFailed = tool.status === "failed";
  const glyphColor = isFailed ? "var(--danger)" : "var(--accent)";

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
        {/* Pixel-art tool glyph — color follows error state */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          style={{ color: glyphColor, flexShrink: 0 }}
          aria-hidden
        >
          {toolGlyph(tool.toolName)}
        </svg>
        <span
          className={`inline-block w-2 h-2 rounded-full shrink-0 ${
            STATUS_DOT[tool.status]
          }`}
          aria-label={STATUS_LABEL[tool.status]}
        />
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
