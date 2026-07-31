// Per-tool body view for `list_filter_values`. The tool returns
//   { field, values: [{ canonical_id, chunk_count, sample_doc_title }] }
// Rendered as a table so the analyst can scan which agency / fund / doc_type
// slugs the corpus actually carries — the raw JSON dump was technically
// correct but impossible to skim.
//
// Ported from web/components/tool-views/ListFilterValuesView.tsx.

import { useState } from "react";

import type { AssistantBlock } from "../chat-types.js";
import { Chip, ErrorBlock } from "./primitives.js";

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
    <div className="chat-stack">
      <div className="chat-row">
        <span className="chat-muted">Field</span>
        <Chip tone="info">{field || "(none)"}</Chip>
        {parsed && (
          <span className="chat-muted">
            {parsed.values.length} value
            {parsed.values.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {parsed && parsed.values.length > 0 && (
        <div className="chat-table-wrap">
          <table className="chat-table">
            <thead>
              <tr>
                <th>canonical_id</th>
                <th className="is-num">chunks</th>
                <th>sample document</th>
              </tr>
            </thead>
            <tbody>
              {parsed.values
                .slice(0, showAll ? undefined : VISIBLE_DEFAULT)
                .map((v) => (
                  <tr key={v.canonical_id}>
                    <td className="chat-mono">{v.canonical_id}</td>
                    <td className="is-num">{v.chunk_count}</td>
                    <td>{v.sample_doc_title}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          {parsed.values.length > VISIBLE_DEFAULT && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="chat-table-more"
            >
              {showAll
                ? "Collapse"
                : `Show ${parsed.values.length - VISIBLE_DEFAULT} more`}
            </button>
          )}
        </div>
      )}

      {parsed && parsed.values.length === 0 && (
        <div className="chat-note">No values found for this field.</div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
