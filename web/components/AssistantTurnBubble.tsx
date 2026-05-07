"use client";

// Renders one assistant turn — interleaved text + tool blocks, plus
// a citation row under each text block listing the cite() calls
// whose `claim_span` was emitted while that text was visible.
//
// Citation chips inline-underline-then-chip rendering (spec §10.1)
// is the long-term goal; v1 of WS4b renders chips at the end of the
// text block they belong to. Hover tooltip + click-to-bus work the
// same either way; per-character span underlining can come during
// WS4c polish once the PdfViewer is wired and we can verify the
// spans are correct end-to-end.

import { useMemo } from "react";

import { extractCitations, type Citation } from "@/lib/citation-extract";
import type { AssistantBlock, AssistantTurn } from "@/state/chat-types";
import CitationChip from "./CitationChip";
import MarkdownContent from "./MarkdownContent";
import ToolCard from "./ToolCard";

interface Props {
  turn: AssistantTurn;
}

const STOP_NOTE: Record<string, string> = {
  max_tokens: "Response cut off — token limit reached.",
  refusal: "Claude refused to answer this turn.",
  stop_sequence: "Hit a stop sequence.",
  pause_turn: "Paused — partial response.",
  session_died: "YouCoded session exited mid-turn.",
  aborted: "Stopped by user.",
};

export default function AssistantTurnBubble({ turn }: Props) {
  const citations = useMemo(() => extractCitations(turn), [turn]);
  const citationsByTextBlock = useMemo(
    () => assignCitationsToTextBlocks(turn.blocks, citations),
    [turn.blocks, citations],
  );

  return (
    <div className="flex flex-col gap-1">
      {turn.blocks.map((block) => {
        if (block.kind === "text") {
          const blockCitations = citationsByTextBlock.get(block.uuid) ?? [];
          return (
            <div
              key={block.uuid}
              className="rounded-md bg-well border border-edge-dim p-3 text-fg text-sm"
            >
              <MarkdownContent content={block.text} />
              {blockCitations.length > 0 && (
                <div className="mt-2 pt-2 border-t border-edge-dim flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] uppercase tracking-wider text-fg-muted">
                    Sources
                  </span>
                  {blockCitations.map((c) => (
                    <CitationChip key={c.index} citation={c} />
                  ))}
                </div>
              )}
            </div>
          );
        }
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

/**
 * Bucket each citation under a text block: prefer the text block
 * whose content contains the citation's `claim_span` as a substring;
 * if none does (e.g. claim_span lost a character to formatting),
 * fall back to the most recent text block emitted before the cite()
 * tool call.
 *
 * Handles edge cases: turn has no text blocks (returns empty), all
 * citations attach to the lone text block, etc.
 */
function assignCitationsToTextBlocks(
  blocks: AssistantBlock[],
  citations: Citation[],
): Map<string, Citation[]> {
  const out = new Map<string, Citation[]>();
  if (citations.length === 0) return out;

  const textBlocks = blocks.filter(
    (b): b is Extract<AssistantBlock, { kind: "text" }> => b.kind === "text",
  );
  if (textBlocks.length === 0) return out;

  // Build, for each cite tool block, which text block came most
  // recently before it in arrival order. The reducer preserves
  // arrival order in `blocks`, so a single forward pass works.
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

  // Now re-walk the `blocks` to pull cite() blocks in the order
  // extractCitations() saw them, and match each Citation to its
  // tool-use-id via index parity (extractCitations preserves order).
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

    // Prefer claim_span substring match — survives mid-turn re-emits
    // where Claude reorders cite() calls relative to text growth.
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
      // Last fallback: the latest text block in the turn.
      const last = textBlocks[textBlocks.length - 1];
      if (last) targetUuid = last.uuid;
    }
    if (!targetUuid) continue;

    if (!out.has(targetUuid)) out.set(targetUuid, []);
    out.get(targetUuid)!.push(citation);
  }
  return out;
}
