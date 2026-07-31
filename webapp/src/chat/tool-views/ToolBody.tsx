// Per-tool body views for the expanded ToolCard: one dispatcher plus a raw
// fallback.
//
// Ported from web/components/tool-views/ToolBody.tsx, which dispatched
// fourteen tools. Nine of those views were DELETED rather than translated —
// EditView, WriteView, DiffView, ShellView, ReadView, GrepView, GlobView,
// WebFetchView, and the MCP-namespaced aliases of the budget tools. They
// rendered file paths, diffs, shell output, and fetched web pages, and Plan
// 4's Invariant 7 states that the model-callable surface has no filesystem
// access at all: harness/tools.py exposes exactly five tools, none of which
// takes a path-shaped argument. A view for a tool the model cannot call is
// not dead code so much as a claim that the tool exists.
//
// The five that remain map 1:1 onto TOOL_NAMES in harness/tools.py.

import type { AssistantBlock } from "../chat-types.js";
import CiteView from "./CiteView.js";
import CreateDocumentView from "./CreateDocumentView.js";
import ListFilterValuesView from "./ListFilterValuesView.js";
import RetrieveView from "./RetrieveView.js";
import { CollapsibleBlock, ErrorBlock, unescapeForDisplay } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

// --- Raw fallback ------------------------------------------------------
//
// Reached by `cite_batch` (whose N-citation payload has no bespoke view —
// the header summary already says "17 citations", and the individual chips
// in the answer are the real surface) and by anything a future task adds to
// TOOLS before it adds a view here.

function RawFallbackView({ tool }: { tool: ToolBlock }) {
  const error = tool.isError && tool.output ? tool.output : undefined;
  const formatted = Object.entries(tool.input).length
    ? JSON.stringify(tool.input, null, 2).replace(
        /"([^"\\]*(?:\\.[^"\\]*)*)"/g,
        (match, str) => {
          if (!str.includes("\\n") && !str.includes('\\"')) return match;
          return '"' + unescapeForDisplay(str) + '"';
        },
      )
    : "";

  return (
    <div className="chat-stack">
      {formatted && (
        <div>
          <div className="chat-label">Input</div>
          <CollapsibleBlock maxLines={15}>{formatted}</CollapsibleBlock>
        </div>
      )}
      {tool.output && !error && (
        <div>
          <div className="chat-label">Output</div>
          <CollapsibleBlock maxLines={20}>
            {prettyIfJson(tool.output)}
          </CollapsibleBlock>
        </div>
      )}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

function prettyIfJson(s: string): string {
  const trimmed = s.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return s;
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

// --- Dispatcher --------------------------------------------------------

export default function ToolBody({ tool }: { tool: ToolBlock }) {
  const inner = (() => {
    switch (tool.toolName) {
      case "retrieve":
        return <RetrieveView tool={tool} />;
      case "cite":
        return <CiteView tool={tool} />;
      case "list_filter_values":
        return <ListFilterValuesView tool={tool} />;
      case "create_document":
        return <CreateDocumentView tool={tool} />;
      default:
        return <RawFallbackView tool={tool} />;
    }
  })();

  return (
    <div className="chat-tool-body">
      {inner}
      {tool.status === "running" && tool.output === undefined && (
        <div className="chat-note" style={{ marginTop: 8 }}>
          running…
        </div>
      )}
    </div>
  );
}
