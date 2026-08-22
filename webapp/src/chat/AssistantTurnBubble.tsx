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
//     the legacy name is still recognized in citation-extract so saved
//     transcripts from before the JLBC Search rename keep rendering;
//   - the stop-reason line was split into a quiet note and a loud SYSTEM
//     NOTICE — see STOP_NOTE / the max_steps branch below.

import { useMemo, useState } from "react";

import {
  extractCitations,
  extractInlineCiteTags,
  type Citation,
  type ResolvedChunk,
} from "./citation-extract.js";
import type { AssistantBlock, AssistantTurn } from "./chat-types.js";
import CitedMarkdownContent from "./CitedMarkdownContent.js";
import ToolGroup from "./ToolGroup.js";

// Plain boolean predicate — the `block is …` form narrows the false branch to
// `never`, which breaks `block.toolUseId` on the line after.
//
// RULING (Plan 4 Task 12) on the asymmetry Task 10 flagged: `cite_batch` is
// suppressed too. The port matched `cite` only, so a turn whose model batched
// its citations grew one raw-JSON tool card while an otherwise identical turn
// that cited serially grew none — the same information in two presentations,
// chosen by a model-side call the analyst cannot see or influence.
//
// Suppression is the right side of that, not because cards are clutter but
// because the card would be the WORSE audit surface of the two. Everything a
// cite_batch card could show, the chips already show better: each chip carries
// its own claim, its verbatim quote, its pass/fail state, and a click through
// to the highlighted source page. The card shows the same payload as escaped
// JSON with no link to anything. Keeping it would also mean batching
// visibly costs the analyst — which is backwards, since batching exists to
// make answers arrive faster.
//
// What is NOT lost: a cite_batch that FAILS still surfaces, because a failed
// citation renders as a red-X chip with the server's reason in its tooltip
// (Invariant 2 — failures are visible, not silently dropped). The card was
// never the mechanism for that.
const CITE_TOOL_NAMES = new Set(["cite", "cite_batch"]);

function isCiteToolBlock(block: AssistantBlock): boolean {
  return block.kind === "tool" && CITE_TOOL_NAMES.has(block.toolName);
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

  // Open/closed state for tool-call cards, hoisted here from ToolGroup /
  // ToolCard's own local `useState`. TC1 moves a run of tool calls from a
  // standalone `.chat-turn` child (while a search is running, TC6) to a
  // `.chat-bubble` child once the first answer text block exists — the
  // parent DOM element genuinely changes, so React unmounts and remounts the
  // ToolGroup subtree. AssistantTurnBubble is keyed by `turn.id`
  // (ChatThread.tsx) and stays mounted across that transition, so a map
  // owned HERE survives where the subtree's own local state cannot.
  //
  // Keys are namespaced so a run's identifying tool ("g:" + tools[0]'s
  // toolUseId) can never collide with that same tool's entry as the first
  // CHILD card inside an expanded n>=2 group ("c:" + that child's own
  // toolUseId) — both would otherwise be the same string.
  //
  // Not memoized: entries are created only on click (bounded by tool calls a
  // person actually toggled this turn, freed when the bubble unmounts), and
  // this component isn't memoized today, so recreating the per-row toggle
  // closures on every render costs nothing observable. If AssistantTurnBubble
  // is ever wrapped in React.memo, revisit this.
  const [openCards, setOpenCards] = useState<Record<string, boolean>>({});
  const toggleCard = (key: string) =>
    setOpenCards((m) => ({ ...m, [key]: !m[key] }));

  // TC1 — a run of tool calls attaches DOWNWARD, to the bubble that follows
  // it, and renders as that bubble's FIRST CHILD rather than as a sibling
  // above it. Reading order is the point: a turn that searched, wrote a
  // paragraph, searched again and wrote more produces two bubbles each wearing
  // its own card, never one card at the top claiming all the work.
  //
  // A run with no text after it renders standalone (TC6) — that covers both
  // mid-search, where no text block exists yet, and a turn that ended on a
  // tool call. Withholding it would leave the analyst watching nothing through
  // a multi-second search.
  //
  // Cite tools stay invisible (see the ruling above CITE_TOOL_NAMES) and,
  // because they are SKIPPED rather than treated as a boundary, do not split a
  // run: retrieve, cite, retrieve is still one run of two searches (TC7).
  type ToolBlockT = Extract<AssistantBlock, { kind: "tool" }>;
  type TextBlockT = Extract<AssistantBlock, { kind: "text" }>;
  type Row = { tools: ToolBlockT[]; block?: TextBlockT };

  const rows: Row[] = [];
  let pendingTools: ToolBlockT[] = [];
  for (const block of turn.blocks) {
    if (block.kind === "text") {
      rows.push({ tools: pendingTools, block });
      pendingTools = [];
    } else if (!isCiteToolBlock(block)) {
      pendingTools.push(block);
    }
  }
  if (pendingTools.length > 0) rows.push({ tools: pendingTools });

  // A run's own open/closed state, keyed off its identifying tool — the
  // run's FIRST tool's toolUseId — so the same run resolves to the same
  // entry in `openCards` whether it is currently rendered standalone (TC6)
  // or nested inside the bubble that follows it (TC1). Built once per row
  // rather than hoisted to a `useCallback`: it is plain data, not a hook, and
  // recomputing it per render/row is the cheap, obviously-correct choice
  // over threading a memoized closure through two render sites.
  function toolGroupProps(runTools: ToolBlockT[]) {
    const groupKey = `g:${runTools[0]!.toolUseId}`;
    return {
      open: openCards[groupKey] ?? false,
      onToggle: () => toggleCard(groupKey),
      cardOpen: (id: string) => openCards[`c:${id}`] ?? false,
      onCardToggle: (id: string) => toggleCard(`c:${id}`),
    };
  }

  return (
    <div className="chat-turn">
      {rows.map((row) => {
        if (!row.block) {
          return (
            <ToolGroup
              key={row.tools[0]!.toolUseId}
              tools={row.tools}
              {...toolGroupProps(row.tools)}
            />
          );
        }
        const block = row.block;
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
            {row.tools.length > 0 && (
              <ToolGroup tools={row.tools} {...toolGroupProps(row.tools)} />
            )}
            <CitedMarkdownContent
              content={renderText}
              citations={blockCitations}
              annotation={turn.annotation}
            />
          </div>
        );
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
