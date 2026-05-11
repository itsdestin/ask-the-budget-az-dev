"use client";

// Per-tool body view for the budget Budget MCP `cite` tool.
//
// The cite tool's input is { chunk_id, span_start, span_end,
// confidence, claim_span } and its output is a small {ok,
// citation_id?, error?} ack. The visible value of this body is the
// source-side metadata (chunk + confidence + span + ack), NOT the
// claim itself — the claim_span is already underlined inline in the
// assistant turn, and the ToolCard header already shows the
// confidence, so a third repeat in the expanded body adds noise
// without information. The 2026-05-12 readability pass cut this
// redundancy.

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
  cited_text_preview?: string;
}

function parseAck(raw: string | undefined): CiteAck | null {
  if (!raw) return null;
  // MCP schema rejections come back as a non-JSON envelope; surface
  // them as a synthetic failure ack so the same UI affordance shows.
  if (raw.startsWith("MCP error")) {
    return { ok: false, error: raw };
  }
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

  // Show the claim only when this cite failed — there, the model's
  // text is NOT successfully underlined inline (the chip is a red
  // ✗), so the user needs to see what the model intended to cite to
  // make sense of the rejection. Successful cites have their claim
  // visible in the chat; no need to repeat.
  const showClaim = error !== undefined;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <Chip tone={confidence === "verbatim" ? "add" : "info"}>
          {conf.glyph} {conf.label}
        </Chip>
        {spanStart != null && spanEnd != null && (
          <span className="text-fg-muted font-mono text-[10px]">
            chunk offset [{spanStart}–{spanEnd}]
          </span>
        )}
      </div>

      {showClaim && claimSpan && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Intended claim
          </div>
          <blockquote className="text-sm text-fg-dim border-l-2 border-red-600/50 pl-3 italic">
            {claimSpan}
          </blockquote>
        </div>
      )}

      {/* Failed cites carry a cited_text_preview from the validator —
          this is what the model's span actually pointed at, which is
          the most useful piece of feedback for understanding WHY the
          cite was rejected. Show it next to the intended claim so the
          contrast is obvious. */}
      {error && ack?.cited_text_preview && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
            Cited span actually contained
          </div>
          <pre className="text-[11px] text-fg-dim bg-canvas border border-edge-dim rounded-sm p-2 whitespace-pre-wrap break-words font-mono max-h-32 overflow-auto">
            {ack.cited_text_preview}
          </pre>
        </div>
      )}

      <div className="flex items-center gap-2 text-[10px] font-mono text-fg-muted break-all">
        <span className="shrink-0">chunk</span>
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
