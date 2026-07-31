// Renders one assistant turn — interleaved text + tool blocks, with citations
// rendered as chips inline at the end of the markdown line / paragraph /
// list-item / table-row containing the cited claim. Anchoring is done by
// CitedMarkdownContent via sentinel injection.
//
// Inline-cite XML tags (`<cite chunk_id=… claim_span="…">…</cite>`) that some
// models emit instead of calling the cite() tool are extracted here and folded
// into the same chip stream, so the analyst can't tell which path was used.
//
// Tool calls for `cite` itself are hidden because the chip IS the user-visible
// surface for those. Other tool calls still render as cards, because the
// analyst wants to see what the model looked at.
//
// Ported from web/components/AssistantTurnBubble.tsx. Two changes:
//   - the `mcp__ask-the-budget-az__cite` alias is gone (no MCP server);
//   - the stop-reason line was split into a quiet note and a loud SYSTEM
//     NOTICE — see STOP_NOTE / the max_steps branch below.

import { useMemo } from "react";

import {
  extractCitations,
  extractInlineCiteTags,
  type Citation,
  type ResolvedChunk,
} from "./citation-extract.js";
import type { AssistantBlock, AssistantTurn } from "./chat-types.js";
import CitedMarkdownContent from "./CitedMarkdownContent.js";
import ToolCard from "./ToolCard.js";

// Plain boolean predicate — the `block is …` form narrows the false branch to
// `never`, which breaks `block.toolUseId` on the line after.
//
// KNOWN ASYMMETRY, carried over from `web/` unchanged and left for Task 12 to
// decide on: this matches `cite` but NOT `cite_batch`. So a turn whose model
// cited one claim at a time shows no tool cards, while a turn that batched
// its citations shows one raw JSON card — same information, two presentations,
// chosen by a model-side call the analyst can't see. Both are "correct" (the
// chips are the real surface either way), but the inconsistency is visible.
// Adding cite_batch here is a one-word change; it was NOT made in this port
// because suppressing a card is a product decision about what the analyst is
// entitled to audit, not a styling one.
function isCiteToolBlock(block: AssistantBlock): boolean {
  return block.kind === "tool" && block.toolName === "cite";
}

interface Props {
  turn: AssistantTurn;
  /** Conversation-wide chunk lookup so a cite() referencing a chunk_id from
   *  an earlier turn still resolves to its metadata. Computed once at the
   *  ChatThread level and passed in. */
  conversationResolvedChunks?: Map<string, ResolvedChunk>;
  /** True only for the most-recent assistant turn. Drives whether the
   *  speech-bubble tail renders — older bubbles stay tail-less so a single
   *  tail "points" from the mascot to the current message. */
  isLatest?: boolean;
}

// Quiet italic one-liner. These stop reasons are unusual but self-explanatory
// once stated, and none of them means "the answer you are reading is wrong".
const STOP_NOTE: Record<string, string> = {
  max_tokens: "Response cut off — the model hit its output-length limit.",
  content_filter: "The model's provider blocked this response.",
  user_interrupt: "Stopped by you.",
  tool_use: "The model stopped mid-tool-call.",
  error: "The turn ended with an error.",
};

// The loud one. `max_steps` means the model ran out of tool-call budget
// BEFORE it finished answering, so what the analyst is reading is a partial
// answer that ends mid-thought — and an answer that just stops is
// indistinguishable from a finished one (Core Invariant 3's failure mode).
//
// The harness used to announce this by injecting a synthetic assistant
// message. That was removed in Task 6 precisely so the fact would NOT be
// system-authored first-person prose sitting in the audit record's
// `finalAnswer`. It now arrives as `stopReason: "max_steps"`, and this
// notice is the UI half of that bargain: rendered as a system notice —
// bordered, tinted, outside the speech bubble, no mascot, no tail — so it
// cannot be mistaken for something the model said.
//
// The wording deliberately mirrors the harness's `incompleteNote` (which
// rides on the `_done` frame for the audit trail) without depending on it:
// `_done` is the transport's own frame, not part of the ProviderEvent union
// the reducer consumes, so `stopReason` is what actually reaches this
// component. If a later task threads incompleteNote through to chat state,
// prefer it over this constant.
const INCOMPLETE_NOTICE =
  "This answer is incomplete. The assistant used up its tool-call budget " +
  "for this turn before it finished. Ask a narrower question, or ask it to " +
  "continue.";

export default function AssistantTurnBubble({
  turn,
  conversationResolvedChunks,
  isLatest = false,
}: Props) {
  // cite()-tool citations for the turn (resolved against this turn's
  // retrieve() output, with conversation-wide fallback for cross-turn chunk
  // references).
  const toolCitations = useMemo(
    () => extractCitations(turn, conversationResolvedChunks),
    [turn, conversationResolvedChunks],
  );

  // For every text block, also extract any inline `<cite>` XML tags the model
  // emitted in prose. The renderer feeds the tag-stripped text to
  // ReactMarkdown; the synthetic citations are numbered after the tool-call
  // ones to keep chip indexes stable across the turn.
  const blockData = useMemo(() => {
    const out = new Map<string, { renderText: string; citations: Citation[] }>();
    let nextIndex = toolCitations.length + 1;
    for (const block of turn.blocks) {
      if (block.kind !== "text") continue;
      const { strippedText, citations: rawInlines } = extractInlineCiteTags(
        block.text,
      );
      const renumbered = rawInlines.map((c) => {
        const next: Citation = { ...c, index: nextIndex++ };
        const meta = conversationResolvedChunks?.get(next.chunkId);
        if (meta) next.resolved = meta;
        return next;
      });
      out.set(block.uuid, { renderText: strippedText, citations: renumbered });
    }
    return out;
  }, [turn.blocks, toolCitations.length, conversationResolvedChunks]);

  // Bucket tool-call citations to the text block whose content (or immediate
  // predecessor) carries the claim. Inline-XML citations are already scoped
  // to their host block.
  const toolCitationsByBlock = useMemo(
    () => assignToolCitationsToTextBlocks(turn.blocks, toolCitations),
    [turn.blocks, toolCitations],
  );

  const stopReason = turn.isComplete ? turn.stopReason : undefined;

  return (
    <div className="chat-turn">
      {turn.blocks.map((block) => {
        if (block.kind === "text") {
          const tool = toolCitationsByBlock.get(block.uuid) ?? [];
          const inline = blockData.get(block.uuid);
          const blockCitations = [...tool, ...(inline?.citations ?? [])];
          const renderText = inline?.renderText ?? block.text;
          return (
            <div
              key={block.uuid}
              // The tail (`has-tail`) is applied ONLY on the most-recent
              // assistant turn, so one tail anchors the conversation to the
              // mascot. Older turns keep the bubble look without it.
              className={`chat-bubble${isLatest ? " has-tail" : ""}`}
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
      {stopReason === "max_steps" && (
        <div className="chat-notice is-warn" role="status">
          <strong>Incomplete answer.</strong> {INCOMPLETE_NOTICE}
        </div>
      )}
      {stopReason && STOP_NOTE[stopReason] && (
        <div className="chat-stop-note">{STOP_NOTE[stopReason]}</div>
      )}
    </div>
  );
}

/** Bucket each tool-call citation under a text block by claim_span substring
 *  (raw text — CitedMarkdownContent does its own lenient, markdown-aware match
 *  later for line-level placement). Falls back to the most recent text block
 *  emitted before the cite() tool call. */
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

  // Map each cite() tool block to the most recent preceding text block.
  // Forward pass — `blocks` is in arrival order.
  const citeToText = new Map<string, string>();
  let lastTextUuid: string | null = null;
  for (const block of blocks) {
    if (block.kind === "text") {
      lastTextUuid = block.uuid;
    } else if (isCiteToolBlock(block) && lastTextUuid != null) {
      citeToText.set(
        (block as Extract<AssistantBlock, { kind: "tool" }>).toolUseId,
        lastTextUuid,
      );
    }
  }

  const citeBlocksInOrder = blocks.filter(
    (b): b is Extract<AssistantBlock, { kind: "tool" }> => isCiteToolBlock(b),
  );

  for (let i = 0; i < citations.length; i++) {
    const citation = citations[i]!;
    const citeBlock = citeBlocksInOrder[i];
    let targetUuid: string | undefined;

    // Prefer a claim_span substring match on the raw text. Coarse first pass
    // — the line-level placement inside CitedMarkdownContent normalizes
    // properly. Here we only need to pick the right text block.
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
