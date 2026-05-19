"use client";

// Renders one assistant turn — interleaved text + tool blocks, with
// citations rendered as chips inline at the end of the markdown
// line / paragraph / list-item / table-row containing the cited
// claim. Anchoring is done by CitedMarkdownContent via sentinel
// injection (see that file for the full pipeline).
//
// Inline-cite XML tags (`<cite chunk_id=… claim_span="…">…</cite>`)
// that some models emit instead of calling the cite() MCP tool are
// extracted here and folded into the same chip stream — they get
// the same end-of-line placement so the analyst can't tell which
// path the model used.
//
// Tool calls for `cite` itself are hidden because the chip IS the
// user-visible surface for those. Other tool calls (retrieve, Bash,
// Read, …) still render as cards because the analyst wants to see
// what Claude looked at.

import { useMemo } from "react";

import {
  extractCitations,
  extractInlineCiteTags,
  type Citation,
  type ResolvedChunk,
} from "@/lib/citation-extract";
import type { AssistantBlock, AssistantTurn } from "@/state/chat-types";
import CitedMarkdownContent from "./CitedMarkdownContent";
import ToolCard from "./ToolCard";

// Plain boolean predicate — see history note in v1 of this file: the
// `block is …` form narrows the false branch to `never`, breaking
// `block.toolUseId` on the line after.
function isCiteToolBlock(block: AssistantBlock): boolean {
  return (
    block.kind === "tool" &&
    (block.toolName === "cite" ||
      block.toolName === "mcp__ask-the-budget-az__cite")
  );
}

interface Props {
  turn: AssistantTurn;
  /** Conversation-wide chunk lookup so cite() calls referencing a
   *  chunk_id from an earlier turn still resolve to its metadata.
   *  Computed once at the ChatThread level and passed in. */
  conversationResolvedChunks?: Map<string, ResolvedChunk>;
}

const STOP_NOTE: Record<string, string> = {
  max_tokens: "Response cut off — token limit reached.",
  refusal: "Claude refused to answer this turn.",
  stop_sequence: "Hit a stop sequence.",
  pause_turn: "Paused — partial response.",
  session_died: "YouCoded session exited mid-turn.",
  aborted: "Stopped by user.",
};

export default function AssistantTurnBubble({
  turn,
  conversationResolvedChunks,
}: Props) {
  // cite()-tool citations for the turn (resolved against this turn's
  // retrieve() output, with conversation-wide fallback for cross-turn
  // chunk references).
  const toolCitations = useMemo(
    () => extractCitations(turn, conversationResolvedChunks),
    [turn, conversationResolvedChunks],
  );

  // For every text block, also extract any inline `<cite>` XML tags
  // the model emitted in the prose. The renderer feeds the
  // tag-stripped text to ReactMarkdown; the synthetic citations are
  // numbered after the tool-call ones to keep chip indexes stable
  // across the turn. Each gets resolved against the conversation
  // chunk map so the PdfViewer can navigate.
  const blockData = useMemo(() => {
    const out = new Map<
      string,
      { renderText: string; citations: Citation[] }
    >();
    let nextIndex = toolCitations.length + 1;
    for (const block of turn.blocks) {
      if (block.kind !== "text") continue;
      const { strippedText, citations: rawInlines } = extractInlineCiteTags(
        block.text,
      );
      const renumbered = rawInlines.map((c) => {
        const renumbered: Citation = { ...c, index: nextIndex++ };
        const meta = conversationResolvedChunks?.get(renumbered.chunkId);
        if (meta) renumbered.resolved = meta;
        return renumbered;
      });
      out.set(block.uuid, {
        renderText: strippedText,
        citations: renumbered,
      });
    }
    return out;
  }, [turn.blocks, toolCitations.length, conversationResolvedChunks]);

  // Bucket tool-call citations to the text block whose content (or
  // immediate predecessor) carries the claim. We assign by claim_span
  // substring on the raw block text first, then fall back to the
  // most-recent text block before the cite() tool call. Inline-XML
  // citations are already scoped to their host block.
  const toolCitationsByBlock = useMemo(
    () => assignToolCitationsToTextBlocks(turn.blocks, toolCitations),
    [turn.blocks, toolCitations],
  );

  return (
    <div className="flex flex-col gap-1">
      {turn.blocks.map((block) => {
        if (block.kind === "text") {
          const tool = toolCitationsByBlock.get(block.uuid) ?? [];
          const inline = blockData.get(block.uuid);
          const blockCitations = [...tool, ...(inline?.citations ?? [])];
          const renderText = inline?.renderText ?? block.text;
          return (
            <div
              key={block.uuid}
              // speech-bubble: left-pointing tail toward the left-column mascot
              // avatar. relative is needed for the ::before pseudo-element tail.
              // Only text blocks get this — ToolCard interleaved blocks do not.
              className="speech-bubble relative bg-panel rounded-lg px-3.5 py-2 text-fg text-sm font-sans max-w-prose"
            >
              <CitedMarkdownContent
                content={renderText}
                citations={blockCitations}
              />
            </div>
          );
        }
        if (isCiteToolBlock(block)) return null;
        return <ToolCard key={block.toolUseId} tool={block} />;
      })}
      {turn.isComplete && turn.stopReason && STOP_NOTE[turn.stopReason] && (
        <div className="text-xs text-fg-muted italic px-1">
          {STOP_NOTE[turn.stopReason]}
        </div>
      )}
    </div>
  );
}

/** Bucket each tool-call citation under a text block by claim_span
 *  substring (raw text — CitedMarkdownContent will do its own
 *  lenient/markdown-aware match later for line-level placement).
 *  Falls back to the most recent text block emitted before the cite()
 *  tool call. */
function assignToolCitationsToTextBlocks(
  blocks: AssistantBlock[],
  citations: Citation[],
): Map<string, Citation[]> {
  const out = new Map<string, Citation[]>();
  if (citations.length === 0) return out;

  const textBlocks = blocks.filter(
    (b): b is Extract<AssistantBlock, { kind: "text" }> => b.kind === "text",
  );
  if (textBlocks.length === 0) return out;

  // Map each cite() tool block to the most recent preceding text
  // block. Forward pass — `blocks` is in arrival order.
  const citeToText = new Map<string, string>();
  let lastTextUuid: string | null = null;
  for (const block of blocks) {
    if (block.kind === "text") {
      lastTextUuid = block.uuid;
    } else if (
      block.kind === "tool" &&
      (block.toolName === "cite" ||
        block.toolName === "mcp__ask-the-budget-az__cite") &&
      lastTextUuid != null
    ) {
      citeToText.set(block.toolUseId, lastTextUuid);
    }
  }

  const citeBlocksInOrder = blocks.filter(
    (b): b is Extract<AssistantBlock, { kind: "tool" }> =>
      b.kind === "tool" &&
      (b.toolName === "cite" ||
        b.toolName === "mcp__ask-the-budget-az__cite"),
  );

  for (let i = 0; i < citations.length; i++) {
    const citation = citations[i]!;
    const citeBlock = citeBlocksInOrder[i];
    let targetUuid: string | undefined;

    // Prefer claim_span substring match on raw text. This is a coarse
    // first pass — the line-level placement inside CitedMarkdownContent
    // does its own normalization. Here we just want to pick the right
    // text block.
    for (const tb of textBlocks) {
      if (tb.text.includes(citation.claimSpan)) {
        targetUuid = tb.uuid;
        break;
      }
    }
    if (!targetUuid && citeBlock) {
      targetUuid = citeToText.get(citeBlock.toolUseId);
    }
    if (!targetUuid) {
      const last = textBlocks[textBlocks.length - 1];
      if (last) targetUuid = last.uuid;
    }
    if (!targetUuid) continue;

    if (!out.has(targetUuid)) out.set(targetUuid, []);
    out.get(targetUuid)!.push(citation);
  }
  return out;
}
