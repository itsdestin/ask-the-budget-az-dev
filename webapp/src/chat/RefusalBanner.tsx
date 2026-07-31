// RefusalBanner — the surface that makes Core Invariant 3 true.
//
// Ported from web/components/RefusalBanner.tsx, which shipped props-driven and
// was never imported by anything. That mattered more than it looked: the
// shipped system prompt tells the model, on a synthesis refusal, that "the
// interface shows the passages from your search alongside this, so the analyst
// can read them directly". Nothing did. This file is the other half of that
// promise, plus the detector that decides when to show it.
//
// ── HOW A REFUSAL IS DETECTED, AND WHAT THE DETECTOR CANNOT KNOW ────────────
//
// A refusal is prose. "I cannot find this in the indexed documents" is a
// sentence the model paraphrases freely, so matching on wording would be a
// string heuristic of exactly the kind this project already deleted once (the
// `_check_alignment` overlap check, dropped 2026-05-20 at a ~40% false-reject
// rate). The detector below is STRUCTURAL instead:
//
//   a completed turn (stopReason "end_turn")
//   + at least one finished retrieve() call
//   + ZERO surviving citations
//
// Under the constrained-agent contract every grounded claim carries a cite(),
// so "searched, answered, cited nothing" has exactly two explanations: the
// model refused, or the model broke the contract and wrote an uncited answer.
// The banner is right in BOTH cases — either way the analyst is looking at
// prose with no auditable backing and needs the raw passages. That is why the
// copy below was rewritten out of the spec's first person ("I found these
// passages but couldn't synthesize…") into system-authored fact: attributing a
// refusal to the model when it may have simply skipped its cites would be the
// UI inventing a statement the model never made.
//
// What it deliberately does NOT do:
//   - fire on ordinary answers. Every cited answer is excluded by construction.
//   - fire mid-stream. Cites land after the prose; judging an open turn would
//     flash the banner on every single answer.
//   - fire on max_steps / user_interrupt / max_tokens. Those turns end without
//     cites because they were CUT SHORT, not because anything was refused, and
//     AssistantTurnBubble already renders its own notice for them.
//   - detect the spec's `out_of_scope` case at all. A policy-question refusal
//     retrieves nothing and cites nothing — indistinguishable from an ordinary
//     clarifying question. The case stays in the type for a caller that knows,
//     but auto-detection never returns it.

import type { AssistantBlock, AssistantTurn } from "./chat-types.js";
import { extractCitations } from "./citation-extract.js";

export interface RefusalChunkPreview {
  chunkId: string;
  docTitle: string;
  publisher: string;
  fiscalYear: number | null;
  pageStart: number | null;
  pageEnd: number | null;
  text: string;
}

export type RefusalReason =
  | { kind: "no_retrieval"; corpusSummary?: string }
  | { kind: "synthesis"; chunks: RefusalChunkPreview[] }
  | { kind: "out_of_scope" };

/** Same set citation-extract recognizes; duplicated (three strings) rather
 *  than exported from there, because that file is owned by Task 9's port. */
const RETRIEVE_TOOL_NAMES = new Set([
  "retrieve",
  "mcp__ask-the-budget-az__retrieve",
]);

/** Stop reasons that mean "this turn was interrupted", not "this turn
 *  declined". An interrupted turn has no cites for a reason that has nothing
 *  to do with grounding. */
const CUT_SHORT = new Set([
  "max_steps",
  "max_tokens",
  "user_interrupt",
  "content_filter",
  "tool_use",
  "error",
  "duplicate_submit",
]);

const MAX_PREVIEWS = 5;

/**
 * Decide whether this turn needs the raw passages shown. Returns null — the
 * overwhelmingly common answer — for anything that is or might be an ordinary
 * answer.
 */
export function detectRefusal(turn: AssistantTurn): RefusalReason | null {
  if (!turn.isComplete) return null;
  const stopReason = turn.stopReason ?? "end_turn";
  if (CUT_SHORT.has(stopReason)) return null;

  // Any citation that actually validated means the answer is auditable, which
  // is the whole point. A FAILED cite counts as no citation: Invariant 2 says
  // failed citations are visibly stripped, so the claim stands unsupported and
  // the passages are exactly what the analyst needs.
  const cites = extractCitations(turn);
  if (cites.some((c) => c.citationId)) return null;

  // Prose is the thing being flagged. A turn that is nothing but tool calls
  // has no claim to warn about.
  const hasProse = turn.blocks.some(
    (b) => b.kind === "text" && b.text.trim().length > 0,
  );
  if (!hasProse) return null;

  const retrieves = turn.blocks.filter(
    (b): b is Extract<AssistantBlock, { kind: "tool" }> =>
      b.kind === "tool" &&
      RETRIEVE_TOOL_NAMES.has(b.toolName) &&
      b.status === "complete",
  );
  // No search at all: a follow-up question, a clarification, a greeting. There
  // is nothing to show and nothing to warn about.
  if (retrieves.length === 0) return null;

  const chunks = collectChunks(retrieves);
  // The corpus came back empty. The model was instructed to refuse and say
  // what the corpus does cover; there are no passages to display.
  if (chunks.length === 0) return { kind: "no_retrieval" };

  return { kind: "synthesis", chunks: chunks.slice(0, MAX_PREVIEWS) };
}

/** Flatten every retrieve()'s `chunks` array into previews, de-duplicated by
 *  chunk_id (the model often re-retrieves the same passage while narrowing). */
function collectChunks(
  blocks: Extract<AssistantBlock, { kind: "tool" }>[],
): RefusalChunkPreview[] {
  const seen = new Map<string, RefusalChunkPreview>();
  for (const block of blocks) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(block.output ?? "");
    } catch {
      continue;
    }
    const raw = (parsed as { chunks?: unknown })?.chunks;
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      if (typeof item !== "object" || item === null) continue;
      const c = item as Record<string, unknown>;
      const chunkId = typeof c.chunk_id === "string" ? c.chunk_id : "";
      if (!chunkId || seen.has(chunkId)) continue;
      seen.set(chunkId, {
        chunkId,
        docTitle: typeof c.doc_title === "string" ? c.doc_title : "",
        publisher: typeof c.publisher === "string" ? c.publisher : "",
        fiscalYear: typeof c.fiscal_year === "number" ? c.fiscal_year : null,
        pageStart: typeof c.page_start === "number" ? c.page_start : null,
        pageEnd: typeof c.page_end === "number" ? c.page_end : null,
        text: typeof c.text === "string" ? c.text : "",
      });
    }
  }
  return [...seen.values()];
}

// ---------------------------------------------------------------------------
// The banner
// ---------------------------------------------------------------------------

// Third person throughout. See the header note: the detector cannot tell a
// deliberate refusal from a skipped cite(), so every sentence here has to be
// true of both. What IS certain in both cases is the fact these state — the
// answer above carries no citation the system could validate.
const COPY: Record<RefusalReason["kind"], { title: string; body: string }> = {
  no_retrieval: {
    title: "Nothing in the corpus backs this answer.",
    body:
      "The search came back empty and no citation was attached, so there is " +
      "nothing here to verify against. Treat the text above as unsourced.",
  },
  synthesis: {
    title: "This answer carries no citation.",
    body:
      "These passages came back from the search, but nothing above is linked " +
      "to any of them. Read them directly and judge for yourself.",
  },
  out_of_scope: {
    title: "This question is outside the tool's scope.",
    body:
      "This is an editorial or policy question — the kind of judgment call " +
      "the tool isn't designed to make. The system retrieves and cites; you " +
      "decide what to do with the information.",
  },
};

interface Props {
  refusal: RefusalReason;
}

export default function RefusalBanner({ refusal }: Props) {
  const copy = COPY[refusal.kind];
  return (
    // `chat-notice`, the SYSTEM voice: bordered, tinted, no speech bubble, no
    // mascot. Same reasoning as the max_steps notice — a statement about the
    // answer must never be mistakable for part of the answer. role="status"
    // (not "alert") because it accompanies content that is already on screen.
    <div className="chat-notice is-warn chat-refusal" role="status">
      <strong>{copy.title}</strong> {copy.body}
      {refusal.kind === "no_retrieval" && refusal.corpusSummary && (
        <p className="chat-refusal-scope">
          The corpus currently includes: {refusal.corpusSummary}
        </p>
      )}
      {refusal.kind === "synthesis" && refusal.chunks.length > 0 && (
        <ul className="chat-refusal-chunks">
          {refusal.chunks.map((chunk, i) => (
            <ChunkPreviewRow key={chunk.chunkId} chunk={chunk} rank={i + 1} />
          ))}
        </ul>
      )}
    </div>
  );
}

const PREVIEW_CHARS = 280;

function ChunkPreviewRow({
  chunk,
  rank,
}: {
  chunk: RefusalChunkPreview;
  rank: number;
}) {
  const snippet =
    chunk.text.length > PREVIEW_CHARS
      ? chunk.text.slice(0, PREVIEW_CHARS).trimEnd() + "…"
      : chunk.text;
  const pageLabel =
    chunk.pageStart != null
      ? chunk.pageEnd != null && chunk.pageEnd !== chunk.pageStart
        ? `pp. ${chunk.pageStart}–${chunk.pageEnd}`
        : `p. ${chunk.pageStart}`
      : null;
  return (
    <li className="chat-refusal-chunk">
      <div className="chat-refusal-chunk-head">
        <span className="chat-refusal-rank">#{rank}</span>
        <span className="chat-refusal-doc">{chunk.docTitle || chunk.chunkId}</span>
        {pageLabel && <span className="chat-refusal-pill">{pageLabel}</span>}
        {chunk.fiscalYear != null && (
          <span className="chat-refusal-pill">FY{chunk.fiscalYear}</span>
        )}
        {chunk.publisher && (
          <span className="chat-refusal-pill">{chunk.publisher}</span>
        )}
      </div>
      <div className="chat-refusal-text">{snippet}</div>
    </li>
  );
}
