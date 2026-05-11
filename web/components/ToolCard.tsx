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

  return (
    <div className="rounded-md border border-edge bg-panel my-2 overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-fg-2 hover:bg-inset transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className={`inline-block w-2 h-2 rounded-full shrink-0 ${
            STATUS_DOT[tool.status]
          }`}
          aria-label={STATUS_LABEL[tool.status]}
        />
        <span className="font-medium text-fg shrink-0">{label}</span>
        {summary && (
          <span className="text-fg-dim truncate text-xs min-w-0">
            {summary}
          </span>
        )}
        <span className="ml-auto text-fg-muted text-xs select-none shrink-0">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}
