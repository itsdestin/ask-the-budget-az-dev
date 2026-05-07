// Pure function: AssistantTurn → Citation[]. Walks the turn's tool
// blocks, pulls cite() inputs into typed Citation records, and
// resolves each citation's chunk metadata against the matching
// retrieve() tool's output (so the chip can show filename + page +
// verbatim chunk text without an extra fetch).
//
// Faithfulness verification (WS3) and answer-stripping happen later;
// the renderer only sees Citations whose `confidence` reflects what
// the model emitted, not the post-verifier verdict.

import type { AssistantTurn } from "@/state/chat-types.js";

export type CitationConfidence = "verbatim" | "paraphrase";

export interface ResolvedChunk {
  /** Display title from the documents table (denormalized at the API). */
  docTitle: string;
  publisher: string;
  fiscalYear: number | null;
  /** Document type — "jlbc-approps", "executive-budget", etc. Drives copy-citation format. */
  docType: string;
  /** Inclusive 1-indexed PDF page numbers. v1 has page_start === page_end (single-page chunks). */
  pageStart: number | null;
  pageEnd: number | null;
  /** Full chunk text — used to render the verbatim quote in the hover tooltip. */
  text: string;
}

export interface Citation {
  /** 1-based index for chip numbering within the turn. */
  index: number;
  /** chunk_id supplied by the model. */
  chunkId: string;
  spanStart: number;
  spanEnd: number;
  confidence: CitationConfidence;
  /** The exact claim text the model said this citation supports. */
  claimSpan: string;
  /** UUID emitted by the cite() tool result when the call succeeded
   *  (validates the chunk_id + span). Undefined when the call failed
   *  or hadn't returned yet. */
  citationId?: string;
  /** Source-side metadata pulled from a same-turn retrieve() result.
   *  Undefined when no retrieve in the turn surfaced this chunk_id. */
  resolved?: ResolvedChunk;
}

interface RetrieveChunk {
  chunk_id: string;
  doc_title?: string;
  publisher?: string;
  fiscal_year?: number | null;
  doc_type?: string;
  page_start?: number | null;
  page_end?: number | null;
  text?: string;
}

interface RetrieveOutputShape {
  chunks?: RetrieveChunk[];
}

/** Tool names that resolve to the budget retrieve tool. The MCP host
 *  may prefix with `mcp__<server>__`; both bare and namespaced names
 *  are recognized. */
const RETRIEVE_TOOL_NAMES = new Set<string>([
  "retrieve",
  "mcp__ask-the-budget-az__retrieve",
]);

const CITE_TOOL_NAMES = new Set<string>([
  "cite",
  "mcp__ask-the-budget-az__cite",
]);

/** Parse a JSON tool result string into the retrieve output shape;
 *  returns null on any failure (silent — non-retrieve tools or
 *  errored retrievals just don't contribute resolved chunks). */
function parseRetrieveOutput(raw: string): RetrieveOutputShape | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "chunks" in parsed &&
      Array.isArray((parsed as { chunks: unknown }).chunks)
    ) {
      return parsed as RetrieveOutputShape;
    }
  } catch {
    // fall through
  }
  return null;
}

/** Pull the citation_id out of the cite() tool's ack output when the
 *  call succeeded. Returns undefined for failed calls or
 *  yet-unfinished tools. */
function parseCiteAck(raw: string | undefined): string | undefined {
  if (!raw) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      (parsed as { ok?: unknown }).ok === true &&
      typeof (parsed as { citation_id?: unknown }).citation_id === "string"
    ) {
      return (parsed as { citation_id: string }).citation_id;
    }
  } catch {
    // fall through
  }
  return undefined;
}

function isCitationConfidence(v: unknown): v is CitationConfidence {
  return v === "verbatim" || v === "paraphrase";
}

/** Walk every retrieve() tool result in the turn and build a map of
 *  chunk_id → resolved metadata. Later cite() lookups index into this. */
function buildResolvedChunkMap(
  turn: AssistantTurn,
): Map<string, ResolvedChunk> {
  const out = new Map<string, ResolvedChunk>();
  for (const block of turn.blocks) {
    if (block.kind !== "tool") continue;
    if (!RETRIEVE_TOOL_NAMES.has(block.toolName)) continue;
    if (!block.output || block.isError) continue;
    const parsed = parseRetrieveOutput(block.output);
    if (!parsed?.chunks) continue;
    for (const c of parsed.chunks) {
      if (!c.chunk_id) continue;
      out.set(c.chunk_id, {
        docTitle: c.doc_title ?? "",
        publisher: c.publisher ?? "",
        fiscalYear: c.fiscal_year ?? null,
        docType: c.doc_type ?? "",
        pageStart: c.page_start ?? null,
        pageEnd: c.page_end ?? null,
        text: c.text ?? "",
      });
    }
  }
  return out;
}

/** Build the renderer-facing Citation list for an assistant turn.
 *  Order: cite() blocks in arrival order; chip index is 1-based. */
export function extractCitations(turn: AssistantTurn): Citation[] {
  const resolved = buildResolvedChunkMap(turn);
  const out: Citation[] = [];
  for (const block of turn.blocks) {
    if (block.kind !== "tool") continue;
    if (!CITE_TOOL_NAMES.has(block.toolName)) continue;
    const input = block.input;
    const chunkId = typeof input.chunk_id === "string" ? input.chunk_id : "";
    const spanStart =
      typeof input.span_start === "number" ? input.span_start : -1;
    const spanEnd =
      typeof input.span_end === "number" ? input.span_end : -1;
    const claimSpan =
      typeof input.claim_span === "string" ? input.claim_span : "";
    const confidence = isCitationConfidence(input.confidence)
      ? input.confidence
      : "paraphrase";
    if (!chunkId || !claimSpan || spanStart < 0 || spanEnd <= spanStart) {
      // Drop malformed cite() calls; the YouCodedSessionProvider
      // already logs these, but defensive here too.
      continue;
    }
    const citation: Citation = {
      index: out.length + 1,
      chunkId,
      spanStart,
      spanEnd,
      confidence,
      claimSpan,
    };
    const ack = parseCiteAck(block.output);
    if (ack) citation.citationId = ack;
    const meta = resolved.get(chunkId);
    if (meta) citation.resolved = meta;
    out.push(citation);
  }
  return out;
}

/** Format a citation for the "Copy citation" button per spec §10.2:
 *  `JLBC Baseline Book FY24, p. 47`. Falls back gracefully when
 *  metadata is missing — the chip still copies *something* useful. */
export function formatCopyCitation(citation: Citation): string {
  const r = citation.resolved;
  if (!r) {
    // No retrieve() metadata in this turn (model called cite() with a
    // chunk it carried over from session memory). Fall back to chunk_id.
    return `chunk ${citation.chunkId}`;
  }
  const parts: string[] = [];
  if (r.docTitle) parts.push(r.docTitle);
  if (r.fiscalYear != null) parts.push(`FY${String(r.fiscalYear).slice(-2)}`);
  const head = parts.join(" ");
  const page =
    r.pageStart != null
      ? r.pageEnd != null && r.pageEnd !== r.pageStart
        ? `pp. ${r.pageStart}–${r.pageEnd}`
        : `p. ${r.pageStart}`
      : "";
  return [head, page].filter(Boolean).join(", ");
}
