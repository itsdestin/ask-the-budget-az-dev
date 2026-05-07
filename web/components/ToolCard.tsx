"use client";

// Generic ToolCard. v1 (this commit) renders every tool with a simple
// status-dot header + collapsible JSON input/output. WS4b will add
// per-tool body views (Bash terminal-style output, Read/Edit diff
// rendering, retrieve chunk preview, cite chip, etc.) by routing on
// `block.toolName`.

import { useState } from "react";

import type { AssistantBlock } from "@/state/chat-types";

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
  // For known tools we surface the most relevant input field; the
  // generic fallback shows the first stringy value.
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
      return get("file_path");
    case "Write":
      return get("file_path");
    case "Edit":
      return get("file_path");
    case "Glob":
      return get("pattern");
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

function ToolBody({ tool }: Props) {
  return (
    <div className="border-t border-edge px-3 py-2 text-xs">
      <div className="text-fg-dim mb-1">input</div>
      <pre className="bg-canvas border border-edge rounded-sm p-2 overflow-x-auto font-mono text-fg-2 mb-3 max-h-64">
        {prettyJson(tool.input)}
      </pre>
      {tool.output !== undefined ? (
        <>
          <div className="text-fg-dim mb-1">
            {tool.isError ? "error" : "output"}
          </div>
          <pre
            className={`bg-canvas border border-edge rounded-sm p-2 overflow-x-auto font-mono whitespace-pre-wrap max-h-96 ${
              tool.isError ? "text-red-400" : "text-fg-2"
            }`}
          >
            {tryPrettyJson(tool.output) ?? tool.output}
          </pre>
        </>
      ) : tool.status === "running" ? (
        <div className="text-fg-muted italic">running…</div>
      ) : null}
    </div>
  );
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function tryPrettyJson(s: string): string | null {
  // Tool outputs are sometimes JSON (retrieve, cite, MCP tools) and
  // sometimes plain text (Bash, Read). Pretty-print only if parseable.
  const trimmed = s.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return null;
  }
}
