"use client";

// Per-tool body view for the budget Budget MCP `cite` tool. The MCP
// server's input schema (mirrored in citation-tool-schema.md) is:
//   { chunk_id, span_start, span_end, confidence, claim_span }
// The tool result is a small {ok, citation_id?, error?} ack with no
// chunk text — the visible value of the body is the cite-call input
// itself: which claim is being cited, against which chunk, with
// what confidence. Faithfulness verification (WS3) and audit log
// persistence (WS5) happen elsewhere; this is the analyst-facing
// preview inside the tool card.

import type { AssistantBlock } from "@/state/chat-types";
import { Chip, ErrorBlock } from "./primitives";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

const CONFIDENCE_GLYPH: Record<string, { glyph: string; label: string }> = {
  verbatim: { glyph: "✓", label: "Verbatim" },
  paraphrase: { glyph: "≈", label: "Paraphrase" },
};

interface CiteAck {
  ok: boolean;
  citation_id?: string;
  error?: string;
}

function parseAck(raw: string | undefined): CiteAck | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && "ok" in parsed) {
      return parsed as CiteAck;
    }
    return null;
  } catch {
    return null;
  }
}

export default function CiteView({ tool }: { tool: ToolBlock }) {
  const chunkId = (tool.input.chunk_id as string) || "";
  const spanStart = tool.input.span_start as number | undefined;
  const spanEnd = tool.input.span_end as number | undefined;
  const confidence = (tool.input.confidence as string) || "";
  const claimSpan = (tool.input.claim_span as string) || "";

  const ack = parseAck(tool.output);
  const error =
    tool.isError && tool.output
      ? tool.output
      : ack?.ok === false
        ? (ack.error ?? "cite() rejected")
        : undefined;

  const conf = CONFIDENCE_GLYPH[confidence] ?? {
    glyph: "?",
    label: confidence || "unknown",
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <Chip tone={confidence === "verbatim" ? "add" : "info"}>
          {conf.glyph} {conf.label}
        </Chip>
        {spanStart != null && spanEnd != null && (
          <span className="text-fg-muted font-mono">
            span [{spanStart}–{spanEnd}]
          </span>
        )}
      </div>

      {claimSpan && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Claim
          </div>
          <blockquote className="text-sm text-fg border-l-2 border-edge pl-3 italic">
            {claimSpan}
          </blockquote>
        </div>
      )}

      <div className="flex items-center gap-2 text-[10px] font-mono text-fg-muted">
        <span>chunk</span>
        <code className="text-fg-2 bg-panel px-1.5 py-0.5 rounded-sm break-all">
          {chunkId}
        </code>
      </div>

      {ack?.ok && ack.citation_id && (
        <div className="text-[10px] font-mono text-fg-faint">
          citation_id {ack.citation_id}
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
