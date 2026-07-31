// Per-tool body view for `retrieve`. The tool's output is the JSON
// RetrieveResponse produced by harness/tools.py (same shape the retired
// sidecar returned): { chunks, top_score, retrieval_id, bm25_count,
// dense_count, fused_count }. We render a compact list the analyst can scan
// to audit which chunks fed the model.
//
// Ported from web/components/tool-views/RetrieveView.tsx; Tailwind classes
// became the semantic classes in app.css's chat block, logic unchanged.

import { useState } from "react";

import type { AssistantBlock } from "../chat-types.js";
import { Chip, ErrorBlock } from "./primitives.js";

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
  // The card header already shows the query string; we don't echo it again
  // here. We DO surface filters (the most decision-shaping input the model
  // chose) and the pipeline counters (which say how the corpus narrowed).
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
    <div className="chat-stack">
      {filterChips.length > 0 && (
        <div className="chat-row">
          <span className="chat-label">Filters</span>
          {filterChips.map((c) => (
            <Chip key={c.label} tone="info">
              {c.label}: {c.value}
            </Chip>
          ))}
        </div>
      )}

      {parsed && (
        <div className="chat-row chat-muted">
          <span>
            {parsed.chunks.length} chunk
            {parsed.chunks.length === 1 ? "" : "s"}
          </span>
          <span>·</span>
          <span>top score {parsed.top_score.toFixed(2)}</span>
          <span>
            ({parsed.bm25_count} bm25 / {parsed.dense_count} dense /{" "}
            {parsed.fused_count} fused)
          </span>
        </div>
      )}

      {parsed && parsed.chunks.length > 0 && (
        <ul className="chat-chunks">
          {parsed.chunks
            .slice(0, showAll ? undefined : VISIBLE_CHUNKS_DEFAULT)
            .map((c, i) => (
              <ChunkRow key={c.chunk_id} chunk={c} rank={i + 1} />
            ))}
          {parsed.chunks.length > VISIBLE_CHUNKS_DEFAULT && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="chat-more"
            >
              {showAll
                ? "Collapse"
                : `Show ${parsed.chunks.length - VISIBLE_CHUNKS_DEFAULT} more chunks`}
            </button>
          )}
        </ul>
      )}

      {parsed && parsed.chunks.length === 0 && (
        <div className="chat-note">
          No chunks returned (top_score below the refusal threshold or no
          matches).
        </div>
      )}

      {!parsed && !error && tool.output && (
        // Output present but not parseable as the expected shape — show the
        // raw text so the analyst can still see what came back.
        <div className="chat-block">
          <pre>{tool.output}</pre>
        </div>
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
    <li className="chat-chunk">
      <div className="chat-row" style={{ marginBottom: 4 }}>
        <span className="chat-chunk-rank">#{rank}</span>
        <span className="chat-chunk-title">
          {chunk.doc_title || chunk.doc_id}
        </span>
        {pageLabel && <Chip>{pageLabel}</Chip>}
        {chunk.fiscal_year != null && <Chip>FY{chunk.fiscal_year}</Chip>}
        <Chip tone="info">{chunk.publisher}</Chip>
        <span className="chat-muted chat-spacer">
          score {chunk.score.toFixed(3)}
        </span>
      </div>
      {chunk.section_path.length > 0 && (
        <div className="chat-chunk-path">{chunk.section_path.join(" › ")}</div>
      )}
      <div className="chat-chunk-text">{snippet}</div>
    </li>
  );
}
