"use client";

// Per-tool body view for the budget Budget MCP `retrieve` tool. The
// tool's output is the JSON RetrieveResponse from
// `retrieval/api.py::http_retrieve` (shape locked in
// citation-tool-schema.md): { chunks, top_score, retrieval_id,
// bm25_count, dense_count, fused_count }. We render a compact list
// preview the analyst can scan to audit which chunks fed the LLM.

import { useState } from "react";

import type { AssistantBlock } from "@/state/chat-types";
import { Chip, ErrorBlock } from "./primitives";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface ChunkPreview {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  text: string;
  score: number;
}

interface RetrieveOutput {
  chunks: ChunkPreview[];
  top_score: number;
  retrieval_id: string;
  bm25_count: number;
  dense_count: number;
  fused_count: number;
}

const PREVIEW_CHARS = 240;
const VISIBLE_CHUNKS_DEFAULT = 5;

function parseRetrieveOutput(raw: string | undefined): RetrieveOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "chunks" in parsed &&
      Array.isArray((parsed as { chunks: unknown }).chunks)
    ) {
      return parsed as RetrieveOutput;
    }
    return null;
  } catch {
    return null;
  }
}

export default function RetrieveView({ tool }: { tool: ToolBlock }) {
  // The card header already shows the query string; we don't echo
  // it again here. We DO surface filters (they're the most decision-
  // shaping input the model chose) and the pipeline counters (which
  // tell the user how the corpus narrowed the result).
  const filters = tool.input.filters as Record<string, unknown> | undefined;
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseRetrieveOutput(tool.output);
  const [showAll, setShowAll] = useState(false);

  const filterChips: { label: string; value: string }[] = [];
  if (filters && typeof filters === "object") {
    for (const [k, v] of Object.entries(filters)) {
      if (v == null) continue;
      const label = Array.isArray(v) ? v.join(",") : String(v);
      if (label.length === 0) continue;
      filterChips.push({ label: k, value: label });
    }
  }

  return (
    <div className="space-y-2">
      {filterChips.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-xs">
          <span className="text-fg-muted text-[10px] uppercase tracking-wider">
            Filters
          </span>
          {filterChips.map((c) => (
            <Chip key={c.label} tone="info">
              {c.label}: {c.value}
            </Chip>
          ))}
        </div>
      )}

      {parsed && (
        <div className="flex items-center gap-2 flex-wrap text-[11px] text-fg-muted">
          <span>
            {parsed.chunks.length} chunk
            {parsed.chunks.length === 1 ? "" : "s"}
          </span>
          <span>·</span>
          <span>top score {parsed.top_score.toFixed(2)}</span>
          <span className="text-fg-faint">
            ({parsed.bm25_count} bm25 / {parsed.dense_count} dense /{" "}
            {parsed.fused_count} fused)
          </span>
        </div>
      )}

      {parsed && parsed.chunks.length > 0 && (
        <ul className="flex flex-col gap-2">
          {parsed.chunks
            .slice(0, showAll ? undefined : VISIBLE_CHUNKS_DEFAULT)
            .map((c, i) => (
              <ChunkRow key={c.chunk_id} chunk={c} rank={i + 1} />
            ))}
          {parsed.chunks.length > VISIBLE_CHUNKS_DEFAULT && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2 self-start"
            >
              {showAll
                ? "Collapse"
                : `Show ${parsed.chunks.length - VISIBLE_CHUNKS_DEFAULT} more chunks`}
            </button>
          )}
        </ul>
      )}

      {parsed && parsed.chunks.length === 0 && (
        <div className="text-xs text-fg-muted italic">
          No chunks returned (top_score below the refusal threshold or no
          matches).
        </div>
      )}

      {!parsed && !error && tool.output && (
        // Output present but not parseable as the expected shape — show
        // the raw text so the analyst can still see what came back.
        <pre className="text-xs text-fg-dim bg-panel rounded-sm p-2 overflow-auto whitespace-pre-wrap font-mono max-h-48">
          {tool.output}
        </pre>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}

function ChunkRow({ chunk, rank }: { chunk: ChunkPreview; rank: number }) {
  const snippet =
    chunk.text.length > PREVIEW_CHARS
      ? chunk.text.slice(0, PREVIEW_CHARS).trimEnd() + "…"
      : chunk.text;
  const pageLabel =
    chunk.page_start != null
      ? chunk.page_end != null && chunk.page_end !== chunk.page_start
        ? `pp. ${chunk.page_start}–${chunk.page_end}`
        : `p. ${chunk.page_start}`
      : null;
  return (
    <li className="rounded-sm border border-edge-dim bg-canvas p-2 text-xs">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span className="text-fg-muted font-mono shrink-0">#{rank}</span>
        <span className="text-fg-2 font-medium truncate">
          {chunk.doc_title || chunk.doc_id}
        </span>
        {pageLabel && <Chip>{pageLabel}</Chip>}
        {chunk.fiscal_year != null && <Chip>FY{chunk.fiscal_year}</Chip>}
        <Chip tone="info">{chunk.publisher}</Chip>
        <span className="text-fg-muted ml-auto shrink-0">
          score {chunk.score.toFixed(3)}
        </span>
      </div>
      {chunk.section_path.length > 0 && (
        <div className="text-[10px] text-fg-muted mb-1 truncate">
          {chunk.section_path.join(" › ")}
        </div>
      )}
      <div className="text-fg-dim whitespace-pre-wrap">{snippet}</div>
    </li>
  );
}
