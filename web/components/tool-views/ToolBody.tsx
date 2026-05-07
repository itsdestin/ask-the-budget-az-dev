"use client";

// Per-tool body views for expanded ToolCard. One dispatcher + inline
// view functions; mirrors YouCoded's ToolBody.tsx (replicated, not
// vendored — D9). Falls back to a polished raw view for anything
// the budget app hasn't specialized yet.

import { useState } from "react";

import type { AssistantBlock } from "@/state/chat-types";
import MarkdownContent from "../MarkdownContent";
import CiteView from "./CiteView";
import DiffView from "./DiffView";
import RetrieveView from "./RetrieveView";
import {
  basename,
  Chip,
  CollapsibleBlock,
  CopyButton,
  ErrorBlock,
  PathHeader,
  stripCarriageReturns,
  unescapeForDisplay,
} from "./primitives";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

// --- Edit / Write ------------------------------------------------------

function EditView({ tool }: { tool: ToolBlock }) {
  const fp = (tool.input.file_path as string) || "";
  const oldStr = (tool.input.old_string as string) || "";
  const newStr = (tool.input.new_string as string) || "";
  const replaceAll = tool.input.replace_all as boolean | undefined;
  const error = tool.isError && tool.output ? tool.output : undefined;
  const hasPatch = (tool.structuredPatch?.length ?? 0) > 0;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <PathHeader fp={fp} />
        {replaceAll && <Chip tone="warn">Replace all</Chip>}
      </div>
      {oldStr || newStr || hasPatch ? (
        <DiffView
          oldStr={oldStr}
          newStr={newStr}
          structuredPatch={tool.structuredPatch}
        />
      ) : (
        <div className="text-xs text-fg-muted italic">No change content.</div>
      )}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

function WriteView({ tool }: { tool: ToolBlock }) {
  const fp = (tool.input.file_path as string) || "";
  const content = (tool.input.content as string) || "";
  const lineCount = content ? content.split("\n").length : 0;
  const error = tool.isError && tool.output ? tool.output : undefined;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <PathHeader fp={fp} />
        <Chip tone="add">New file</Chip>
        {lineCount > 0 && (
          <span className="text-[10px] text-fg-muted">{lineCount} lines</span>
        )}
      </div>
      {content ? (
        <div className="rounded-sm overflow-hidden border border-green-600/30 bg-green-600/10">
          <CollapsibleBlock maxLines={20}>{content}</CollapsibleBlock>
        </div>
      ) : (
        <div className="text-xs text-fg-muted italic">Empty file.</div>
      )}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

// --- Bash --------------------------------------------------------------

function ShellView({
  tool,
  commandField,
}: {
  tool: ToolBlock;
  commandField: string;
}) {
  const cmd = (tool.input[commandField] as string) || "";
  const bg = tool.input.run_in_background as boolean | undefined;
  const response = tool.output ? stripCarriageReturns(tool.output) : "";
  const failed = tool.status === "failed";
  const errorOutput = tool.isError && tool.output ? tool.output : undefined;

  const chips: React.ReactNode[] = [];
  if (bg) chips.push(<Chip key="bg" tone="info">Background</Chip>);
  if (failed) chips.push(<Chip key="failed" tone="remove">Failed</Chip>);

  return (
    <div className="space-y-2">
      {chips.length > 0 && (
        <div className="flex items-center gap-1.5">{chips}</div>
      )}
      <div className="relative group">
        <pre className="text-xs font-mono bg-canvas border border-edge rounded-sm px-2 py-1 pr-14 overflow-auto whitespace-pre-wrap break-all text-fg">
          {cmd || (
            <span className="text-fg-muted italic">(no command)</span>
          )}
        </pre>
        {cmd && (
          <div className="absolute top-1 right-1 opacity-70 group-hover:opacity-100 transition-opacity">
            <CopyButton text={cmd} />
          </div>
        )}
      </div>
      {response && !failed && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Output
          </div>
          <CollapsibleBlock maxLines={20} className="bg-canvas">
            {response}
          </CollapsibleBlock>
        </div>
      )}
      {errorOutput && <ErrorBlock error={errorOutput} />}
    </div>
  );
}

// --- Read --------------------------------------------------------------

function parseCatN(resp: string): { lineNo: number; text: string }[] {
  const rows: { lineNo: number; text: string }[] = [];
  for (const line of resp.split("\n")) {
    const m = line.match(/^\s*(\d+)\t(.*)$/);
    if (m) {
      rows.push({ lineNo: parseInt(m[1]!, 10), text: m[2] ?? "" });
    } else if (rows.length > 0) {
      const last = rows[rows.length - 1]!;
      last.text += "\n" + line;
    }
  }
  return rows;
}

const READ_ROW_PX = 20;
const READ_PREVIEW_LINES = 15;

function ReadView({ tool }: { tool: ToolBlock }) {
  const fp = (tool.input.file_path as string) || "";
  const offset = tool.input.offset as number | undefined;
  const limit = tool.input.limit as number | undefined;
  const rows = tool.output ? parseCatN(tool.output) : [];
  const [open, setOpen] = useState(false);
  const overflow = rows.length > READ_PREVIEW_LINES;
  const error = tool.isError && tool.output ? tool.output : undefined;

  let rangeLabel = "";
  if (rows.length > 0) {
    const first = rows[0]!;
    const last = rows[rows.length - 1]!;
    rangeLabel = `lines ${first.lineNo}–${last.lineNo}`;
  } else if (offset != null && limit != null) {
    rangeLabel = `lines ${offset}–${offset + limit}`;
  }

  const containerStyle = open
    ? undefined
    : { maxHeight: `${READ_PREVIEW_LINES * READ_ROW_PX}px` };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <PathHeader fp={fp} />
        {rangeLabel && <Chip>{rangeLabel}</Chip>}
      </div>
      {rows.length > 0 ? (
        <>
          <div
            className="text-xs font-mono rounded-sm border border-edge bg-panel overflow-auto"
            style={containerStyle}
          >
            {rows.map((r) => (
              <div key={r.lineNo} className="flex items-start">
                <span className="w-10 text-right px-1.5 py-0.5 text-fg-muted select-none shrink-0 border-r border-edge">
                  {r.lineNo}
                </span>
                <span className="py-0.5 px-2 text-fg-dim whitespace-pre-wrap break-all flex-1">
                  {r.text || " "}
                </span>
              </div>
            ))}
          </div>
          {overflow && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2"
            >
              {open ? "Collapse" : `Expand (${rows.length} lines)`}
            </button>
          )}
        </>
      ) : tool.output && !error ? (
        <CollapsibleBlock maxLines={40}>{tool.output}</CollapsibleBlock>
      ) : null}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

// --- Grep / Glob -------------------------------------------------------

function GrepView({ tool }: { tool: ToolBlock }) {
  const pattern = (tool.input.pattern as string) || "";
  const mode = (tool.input.output_mode as string) || "files_with_matches";
  const glob = tool.input.glob as string | undefined;
  const path = tool.input.path as string | undefined;
  const resp = tool.output || "";
  const error = tool.isError && tool.output ? tool.output : undefined;
  const lines = resp && !error ? resp.split("\n").filter((l) => l.trim()) : [];

  let body: React.ReactNode;
  if (mode === "content" && lines.length > 0) {
    const byFile = new Map<string, { line: string; text: string }[]>();
    for (const l of lines) {
      const m = l.match(/^(.+?):(\d+):(.*)$/);
      if (m) {
        const file = m[1] ?? "";
        const ln = m[2] ?? "";
        const text = m[3] ?? "";
        if (!byFile.has(file)) byFile.set(file, []);
        byFile.get(file)!.push({ line: ln, text });
      }
    }
    body = (
      <div className="space-y-2">
        {Array.from(byFile.entries()).map(([file, matches]) => (
          <div key={file} className="text-xs font-mono">
            <div className="text-fg-2 font-medium">{file}</div>
            <div className="pl-3 space-y-0.5 text-fg-dim">
              {matches.slice(0, 10).map((m, i) => (
                <div key={i} className="flex gap-2">
                  <span className="text-fg-muted shrink-0">{m.line}:</span>
                  <span className="whitespace-pre-wrap break-all">
                    {m.text}
                  </span>
                </div>
              ))}
              {matches.length > 10 && (
                <div className="text-fg-muted italic">
                  …{matches.length - 10} more in this file
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  } else if (lines.length > 0) {
    body = (
      <ul className="text-xs font-mono space-y-0.5">
        {lines.slice(0, 30).map((l, i) => (
          <li key={i} className="text-fg-dim">
            {l}
          </li>
        ))}
        {lines.length > 30 && (
          <li className="text-fg-muted italic">…{lines.length - 30} more</li>
        )}
      </ul>
    );
  } else if (!error) {
    body = <div className="text-xs text-fg-muted italic">No matches.</div>;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-fg-muted">Pattern</span>
        <code className="text-fg bg-panel px-1.5 py-0.5 rounded-sm font-mono">
          {pattern}
        </code>
        {glob && <Chip>glob: {glob}</Chip>}
        {path && <Chip>in: {basename(path)}/</Chip>}
        <Chip tone="info">{mode}</Chip>
        {lines.length > 0 && (
          <span className="text-fg-muted">
            {lines.length} result{lines.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {body}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

function GlobView({ tool }: { tool: ToolBlock }) {
  const pattern = (tool.input.pattern as string) || "";
  const path = tool.input.path as string | undefined;
  const resp = tool.output || "";
  const error = tool.isError && tool.output ? tool.output : undefined;
  const paths = resp && !error ? resp.split("\n").filter((l) => l.trim()) : [];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <code className="text-fg bg-panel px-1.5 py-0.5 rounded-sm font-mono">
          {pattern}
        </code>
        {path && <Chip>in: {basename(path)}/</Chip>}
        {paths.length > 0 && (
          <span className="text-fg-muted">
            {paths.length} file{paths.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {paths.length > 0 ? (
        <ul className="text-xs font-mono space-y-0.5">
          {paths.slice(0, 30).map((p, i) => (
            <li key={i} className="text-fg-dim">
              {p}
            </li>
          ))}
          {paths.length > 30 && (
            <li className="text-fg-muted italic">…{paths.length - 30} more</li>
          )}
        </ul>
      ) : !error ? (
        <div className="text-xs text-fg-muted italic">No matches.</div>
      ) : null}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

// --- WebFetch / WebSearch ---------------------------------------------

function WebFetchView({ tool }: { tool: ToolBlock }) {
  const url = (tool.input.url as string) || "";
  const prompt = tool.input.prompt as string | undefined;
  const error = tool.isError && tool.output ? tool.output : undefined;
  let domain = "";
  try {
    domain = url ? new URL(url).hostname : "";
  } catch {
    domain = url;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        {domain && <Chip tone="info">{domain}</Chip>}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:text-link-hover truncate max-w-full"
          >
            {url}
          </a>
        )}
      </div>
      {prompt && (
        <div className="text-xs text-fg-dim italic">&ldquo;{prompt}&rdquo;</div>
      )}
      {tool.output && !error && (
        <div className="text-sm text-fg-dim border-t border-edge/60 pt-2">
          <MarkdownContent content={tool.output} />
        </div>
      )}
      {error && <ErrorBlock error={error} />}
    </div>
  );
}

// --- Raw fallback ------------------------------------------------------

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
    <div className="space-y-2">
      {formatted && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Input
          </div>
          <CollapsibleBlock maxLines={15}>{formatted}</CollapsibleBlock>
        </div>
      )}
      {tool.output && !error && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Output
          </div>
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
      case "Edit":
        return <EditView tool={tool} />;
      case "Write":
        return <WriteView tool={tool} />;
      case "Bash":
        return <ShellView tool={tool} commandField="command" />;
      case "Read":
        return <ReadView tool={tool} />;
      case "Grep":
        return <GrepView tool={tool} />;
      case "Glob":
        return <GlobView tool={tool} />;
      case "WebFetch":
      case "WebSearch":
        return <WebFetchView tool={tool} />;
      case "retrieve":
      case "mcp__ask-the-budget-az__retrieve":
        return <RetrieveView tool={tool} />;
      case "cite":
      case "mcp__ask-the-budget-az__cite":
        return <CiteView tool={tool} />;
      default:
        return <RawFallbackView tool={tool} />;
    }
  })();

  return (
    <div className="border-t border-edge px-3 py-2">
      {inner}
      {tool.status === "running" && tool.output === undefined && (
        <div className="text-fg-muted italic text-xs mt-2">running…</div>
      )}
    </div>
  );
}
