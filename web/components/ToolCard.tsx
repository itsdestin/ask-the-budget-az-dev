"use client";

// ToolCard shell. The header (status dot, tool name, one-line input
// summary, expand toggle) lives here; the expanded body is rendered
// by `tool-views/ToolBody.tsx`, which dispatches per-tool views.
// Mirrors YouCoded's split between ToolCard.tsx (shell) and
// tool-views/ToolBody.tsx (per-tool dispatcher) per D9.

import { useState } from "react";

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
        <span className="font-bold text-fg shrink-0">{tool.toolName}</span>
        <ToolHeaderSummary tool={tool} />
        <span className="ml-auto text-fg-muted text-xs select-none">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}

function ToolHeaderSummary({ tool }: Props) {
  // One-line summary that hints at what the tool was called with so
  // the user can scan the timeline without expanding every card.
  const summary = summarizeInput(tool.toolName, tool.input);
  if (!summary) return null;
  return (
    <span className="text-fg-dim font-mono truncate text-xs">{summary}</span>
  );
}

function summarizeInput(
  toolName: string,
  input: Record<string, unknown>,
): string | null {
  const get = (k: string): string | null => {
    const v = input[k];
    return typeof v === "string" ? v : null;
  };
  switch (toolName) {
    case "Bash":
      return get("command");
    case "Read":
    case "Write":
    case "Edit":
      return get("file_path");
    case "Glob":
    case "Grep":
      return get("pattern");
    case "WebFetch":
      return get("url");
    case "WebSearch":
      return get("query");
    case "retrieve":
      return get("query");
    case "cite":
      return get("claim_span");
    default: {
      // Generic fallback — first string value in input.
      for (const v of Object.values(input)) {
        if (typeof v === "string" && v.length > 0) return v;
      }
      return null;
    }
  }
}
