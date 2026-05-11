"use client";

// Per-tool body view for the budget Budget MCP `list_filter_values`
// tool. The tool returns:
//   { field, values: [{ canonical_id, chunk_count, sample_doc_title }] }
// Renders as a sortable-feeling table so a user can scan which
// agency / fund / doc_type slugs the corpus actually carries. This
// replaces the RawFallbackView's JSON dump, which was technically
// correct but visually impossible to skim.

import { useState } from "react";

import type { AssistantBlock } from "@/state/chat-types";
import { Chip, ErrorBlock } from "./primitives";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface FilterValue {
  canonical_id: string;
  chunk_count: number;
  sample_doc_title: string;
}

interface ListFilterValuesOutput {
  field: string;
  values: FilterValue[];
}

function parseOutput(raw: string | undefined): ListFilterValuesOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "field" in parsed &&
      "values" in parsed &&
      Array.isArray((parsed as { values: unknown }).values)
    ) {
      return parsed as ListFilterValuesOutput;
    }
  } catch {
    // fall through
  }
  return null;
}

const VISIBLE_DEFAULT = 12;

export default function ListFilterValuesView({ tool }: { tool: ToolBlock }) {
  const field = (tool.input.field as string) || "";
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseOutput(tool.output);
  const [showAll, setShowAll] = useState(false);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-fg-muted">Field</span>
        <Chip tone="info">{field || "(none)"}</Chip>
        {parsed && (
          <span className="text-fg-muted ml-2">
            {parsed.values.length} value
            {parsed.values.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {parsed && parsed.values.length > 0 && (
        <div className="rounded-sm border border-edge-dim bg-canvas overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-fg-muted border-b border-edge-dim">
                <th className="text-left px-2 py-1 font-medium">canonical_id</th>
                <th className="text-right px-2 py-1 font-medium">chunks</th>
                <th className="text-left px-2 py-1 font-medium">
                  sample document
                </th>
              </tr>
            </thead>
            <tbody>
              {parsed.values
                .slice(0, showAll ? undefined : VISIBLE_DEFAULT)
                .map((v) => (
                  <tr
                    key={v.canonical_id}
                    className="border-b border-edge-dim last:border-b-0 hover:bg-inset/50"
                  >
                    <td className="px-2 py-1 font-mono text-fg-2">
                      {v.canonical_id}
                    </td>
                    <td className="px-2 py-1 text-right text-fg-muted tabular-nums">
                      {v.chunk_count}
                    </td>
                    <td className="px-2 py-1 text-fg-dim truncate max-w-[28ch]">
                      {v.sample_doc_title}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {parsed.values.length > VISIBLE_DEFAULT && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="block w-full text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2 py-1 border-t border-edge-dim"
            >
              {showAll
                ? "Collapse"
                : `Show ${parsed.values.length - VISIBLE_DEFAULT} more`}
            </button>
          )}
        </div>
      )}

      {parsed && parsed.values.length === 0 && (
        <div className="text-xs text-fg-muted italic">
          No values found for this field.
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
