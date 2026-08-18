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
//   + ZERO figures linked by the system's citation linker (2026-08-02)
//
// `extractCitations` walks TOOL blocks, so what the condition really tests is
// "did any citation pass server-side validation" — a `citation_id` in a cite()
// ack. FOUR distinct situations satisfy it, and the copy has to be true in all
// four:
//
//   1. a deliberate refusal            — no chips on screen
//   2. a skipped cite() (contract violation) — no chips on screen
//   3. every cite() returned ok:false  — RED-X chips on screen (Invariant 2
//      working: the citation was checked and rejected)
//   4. inline `<cite>` XML tags only   — ORDINARY-LOOKING chips on screen.
//      AssistantTurnBubble extracts those tags and renders them as chips, and
//      citation-extract.ts documents why the path exists: models sometimes
//      emit XML instead of calling the tool. S16 targets open-weight models
//      that are weaker at tool-call discipline, so this is MORE likely here
//      than it was in the old stack, not less.
//
// Cases 3 and 4 mean the banner can sit under visible chips, so it must never
// say "carries no citation" — it says no VERIFIED citation, which is precisely
// the thing all four states share.
//
// WHY case 4 still fires rather than being suppressed: an inline tag is the
// model's unchecked assertion. It never reached the validator, so nothing
// confirmed the chunk exists or that the quote is in it — strictly weaker than
// case 3, which at least got checked. Suppressing the passages in the state
// with the LEAST verification would invert the invariant this banner exists to
// serve. If inline-only answers become the norm for a given model, this banner
// firing constantly is the correct signal (Invariant 2: citations are
// verified, not just emitted), not noise to tune out.
//
// The copy was also rewritten out of the spec's first person ("I found these
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
import { figuresForRender } from "./citation-annotation.js";
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

/** Same set as citation-extract recognizes; duplicated rather than
 *  exported from there, because that file is owned by Task 9's port. The
 *  `mcp__ask-the-budget-az__retrieve` legacy name stays so old saved
 *  transcripts still render their refusal banner. */
const RETRIEVE_TOOL_NAMES = new Set([
  "retrieve",
  "mcp__jlbc-search__retrieve",
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

  // A `citationId` means a cite() ack came back ok:true — the chunk exists and
  // the quote was found in it. That, and only that, makes the answer
  // auditable. A failed cite (ok:false) and an inline `<cite>` XML tag both
  // leave chips on screen but neither passed validation, so neither silences
  // this; see the four cases in the header for why, and for why the copy below
  // says "verified" rather than "no citation".
  const cites = extractCitations(turn);
  if (cites.some((c) => c.citationId)) return null;

  // A figure the SYSTEM linked is verification too, and stronger verification
  // than a cite() ack: an ack validates a quote the MODEL retyped, whereas a
  // linked figure is a value the system located itself in a chunk this turn
  // actually retrieved, carrying the source's own rendering and offsets.
  //
  // This is not a nicety. Citation linking told the model to stop calling
  // cite() for figures, so a fully-linked numeric answer has ZERO citationIds
  // — and without this the banner fired on exactly those answers, announcing
  // "no verified citation" over an answer in which every number was linked,
  // and burying it under five raw passages. Seen in a browser 2026-08-02.
  //
  // `linked` only. `derived` is arithmetic and `unverified` is the honest
  // failure this banner exists to report; neither can stand in for a source.
  // An answer whose figures are ALL unverified still fires, correctly.
  if (figuresForRender(turn.annotation).some((f) => f.verdict === "linked")) {
    return null;
  }

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

// Third person throughout, and every sentence has to hold in all four firing
// states listed in the header — including the two where chips ARE on screen.
// Hence "verified" and "passed validation": a red-X chip and an inline `<cite>`
// tag are both citations in the visual sense, and neither is a validated one.
// Saying "no citation" while the analyst is looking at chips would make the
// notice the thing that is wrong.
const COPY: Record<RefusalReason["kind"], { title: string; body: string }> = {
  no_retrieval: {
    title: "This answer carries no verified citation.",
    body:
      "The search came back empty, and nothing above carries a citation that " +
      "passed validation — so there is nothing here to check the text " +
      "against. Treat it as unsourced.",
  },
  synthesis: {
    title: "This answer carries no verified citation.",
    body:
      "These passages came back from the search, but nothing above carries a " +
      "citation that passed validation against them. Read them directly and " +
      "judge for yourself.",
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
