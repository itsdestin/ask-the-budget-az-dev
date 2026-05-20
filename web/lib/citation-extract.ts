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
  /** doc_id from the chunk; PdfViewer fetches `/api/pdf/{doc_id}` to load the source. */
  docId: string;
  /** Display title from the documents table (denormalized at the API). */
  docTitle: string;
  publisher: string;
  fiscalYear: number | null;
  /** Document type — "jlbc-approps", "executive-budget", etc. Drives copy-citation format. */
  docType: string;
  /** Inclusive 1-indexed PDF page numbers. v1 has page_start === page_end (single-page chunks). */
  pageStart: number | null;
  pageEnd: number | null;
  /** [x1, y1, x2, y2] in PDF points. Null for non-PDF chunks (e.g. DOCX bills) — PdfViewer falls back to page-level highlighting in that case. */
  bbox: number[] | null;
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
  /** Server-side validation error message when the cite() call
   *  returned ok:false. Drives the renderer's red-X chip variant so
   *  the user sees that this claim has no valid citation rather than
   *  silently rendering as plain text. Mutually exclusive with
   *  `citationId` (a successful cite has one, a failed cite has the
   *  other). Undefined when the tool call is still in flight. */
  failureReason?: string;
  /** Source-side metadata pulled from a same-turn retrieve() result.
   *  Undefined when no retrieve in the turn surfaced this chunk_id. */
  resolved?: ResolvedChunk;
  /** When this Citation came from a cite_batch tool_use block, set to
   *  that block's toolUseId. Used by dedup to suppress FIFO-fail-with-
   *  OK pairing across entries of the SAME batch (within one batch
   *  the model emits intentional distinct claims, not retries — the
   *  cross-block retry heuristic shouldn't fire). Undefined for
   *  single-cite() blocks. */
  batchId?: string;
}

interface RetrieveChunk {
  chunk_id: string;
  doc_id?: string;
  doc_title?: string;
  publisher?: string;
  fiscal_year?: number | null;
  doc_type?: string;
  page_start?: number | null;
  page_end?: number | null;
  bbox?: number[] | null;
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

/** Tool names for the batched-citation tool. One tool_use block carries
 *  N citations in input.citations and N parallel responses in
 *  output.citations. Added 2026-05-20 to eliminate per-citation tool
 *  round-trips that were dominating analyze-shaped answer latency. */
const CITE_BATCH_TOOL_NAMES = new Set<string>([
  "cite_batch",
  "mcp__ask-the-budget-az__cite_batch",
]);

/** Extract the "key fact" token from a claim_span — the load-bearing
 *  numeric figure that the citation is really about (e.g. a dollar
 *  amount or percentage). Returned by `planCitationPlacements` as a
 *  secondary placement key so sentences that restate a fact in
 *  different wording still get the citation's chip.
 *
 *  Returns null when there's nothing distinctive enough to safely match
 *  on. We intentionally do NOT match bare years or small integers —
 *  too many false positives in budget prose where years and small
 *  ordinals appear everywhere.
 *
 *  Currency match supports the dollar-amount-with-suffix shorthand
 *  the model often uses ("$5 million", "$5M") in addition to the
 *  long form ("$5,000,000"). Longest match wins so "$3,300,000" beats
 *  "$3,300" within the same claim_span. */
export function extractKeyFact(claimSpan: string): string | null {
  // Currency: $ followed by digits and optional thousand separators,
  // optionally trailed by a "million" / "billion" / "M" / "B" suffix.
  // The /g + reduce(longest) pattern handles "Up from $5M to $123,456,789"
  // by picking $123,456,789.
  const currency = claimSpan.match(
    /\$[\d][\d,.]*(?:\s?(?:million|billion|M|B))?/gi,
  );
  if (currency && currency.length > 0) {
    return currency.reduce((a, b) => (b.length > a.length ? b : a));
  }
  const pct = claimSpan.match(/\d+(?:\.\d+)?\s?%/);
  if (pct) return pct[0];
  return null;
}

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

interface CiteAckResult {
  /** Set when the cite() call returned ok:true. */
  citationId?: string;
  /** Set when the cite() call returned ok:false. Carries a
   *  HUMAN-READABLE reason string so the chip tooltip can show why
   *  the cite failed. Raw MCP zod errors are translated by
   *  humanizeFailureReason; server-side validator errors (which are
   *  already human-readable) pass through unchanged. */
  failureReason?: string;
  /** Sidecar-derived position of the cited text inside chunk.text.
   *  Present on success when the cite tool returns the new
   *  resolved_span_start/resolved_span_end fields (added 2026-05-20
   *  to both cite + cite_batch). Drives the PDF text-layer search;
   *  without this the renderer falls back to a (0, claim_span.length)
   *  sentinel that doesn't actually point at the cited text and
   *  produces "couldn't pinpoint" badges. */
  resolvedSpanStart?: number;
  resolvedSpanEnd?: number;
}

/** Translate a raw cite()-tool failure string into something a user
 *  can actually read. The MCP host emits zod-validation errors as a
 *  JSON-array payload wrapped in "MCP error -32602: Input validation
 *  error: ..." — surfacing that verbatim in the chip tooltip (which
 *  is what the user reported on 2026-05-12) looks like a stack
 *  trace. Validator errors from the FastAPI sidecar are already
 *  drafted for the model, so they pass through; we only intercept
 *  the schema-rejection path. */
function humanizeFailureReason(raw: string): string {
  if (!raw.startsWith("MCP error")) return raw;
  // Try to pull the JSON-array payload after "Invalid arguments for tool X: ".
  const payloadMatch = raw.match(/Invalid arguments for tool \w+: (\[.*\])/s);
  if (!payloadMatch) return raw;
  try {
    const errors = JSON.parse(payloadMatch[1]!);
    if (!Array.isArray(errors) || errors.length === 0) return raw;
    const e = errors[0] as {
      path?: unknown[];
      code?: string;
      message?: string;
      maximum?: number;
      minimum?: number;
    };
    const field = Array.isArray(e.path) ? e.path.join(".") : "field";
    // Known-shape translations for the codes we actually see in
    // production. The fallback is the zod message itself, which is
    // usually friendlier than the wrapper envelope.
    if (e.code === "too_big" && field === "claim_span") {
      return (
        `Claim was too long (over ${e.maximum ?? 500} characters). ` +
        "The model needed to break the claim into smaller pieces."
      );
    }
    if (e.code === "too_small" && field === "claim_span") {
      return "Claim was empty.";
    }
    if (e.code === "invalid_type") {
      return `Invalid type for ${field}: ${e.message ?? "expected a different shape"}.`;
    }
    return `${field}: ${e.message ?? "validation error"}`;
  } catch {
    return raw;
  }
}

/** Parse the cite() tool's ack output. Returns BOTH the success and
 *  failure cases so the renderer can distinguish "validated cite",
 *  "failed cite", and "tool call still in flight" (returns {}). The
 *  raw text may be a JSON envelope from the FastAPI sidecar OR an MCP
 *  protocol-level rejection string ("MCP error -32602: ...") — both
 *  go to the same UI affordance (red-X chip + tooltip). */
function parseCiteAck(raw: string | undefined): CiteAckResult {
  if (!raw) return {};
  // Plain-text MCP schema errors come back as a non-JSON envelope
  // (e.g. claim_span > 500 chars). Translate to a human-readable
  // reason before stashing on the citation.
  if (raw.startsWith("MCP error")) {
    return { failureReason: humanizeFailureReason(raw) };
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      const obj = parsed as {
        ok?: unknown;
        citation_id?: unknown;
        error?: unknown;
        resolved_span_start?: unknown;
        resolved_span_end?: unknown;
      };
      if (obj.ok === true && typeof obj.citation_id === "string") {
        const result: CiteAckResult = { citationId: obj.citation_id };
        if (typeof obj.resolved_span_start === "number") {
          result.resolvedSpanStart = obj.resolved_span_start;
        }
        if (typeof obj.resolved_span_end === "number") {
          result.resolvedSpanEnd = obj.resolved_span_end;
        }
        return result;
      }
      if (obj.ok === false) {
        return {
          failureReason:
            typeof obj.error === "string" ? obj.error : "cite() rejected",
        };
      }
    }
  } catch {
    // fall through — unrecognized output shape; leave as "in flight"
  }
  return {};
}

/** Parse the cite_batch tool's ack output. Returns an array of per-item
 *  ack results parallel to the tool's input.citations. The cite_batch
 *  contract: response shape is `{citations: [{ok, citation_id?, error?}]}`
 *  with order matching the input. If the raw payload doesn't parse, we
 *  return [] and the caller treats every input as in-flight (no chip
 *  fills). Defensive shape check on each item so a malformed entry
 *  becomes an in-flight slot rather than a crash. */
function parseCiteBatchAck(raw: string | undefined): CiteAckResult[] {
  if (!raw) return [];
  if (raw.startsWith("MCP error")) {
    // MCP rejected the whole batch (e.g. schema validation). The
    // single-failure path doesn't tell us which input slot caused it,
    // so we attribute the failure to slot 0 — the renderer's
    // dedup-by-emission-order pass will keep it grouped sensibly.
    return [{ failureReason: humanizeFailureReason(raw) }];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      Array.isArray((parsed as { citations?: unknown }).citations)
    ) {
      const items = (parsed as { citations: unknown[] }).citations;
      return items.map((item) => {
        if (typeof item !== "object" || item === null) return {};
        const obj = item as {
          ok?: unknown;
          citation_id?: unknown;
          error?: unknown;
          resolved_span_start?: unknown;
          resolved_span_end?: unknown;
        };
        if (obj.ok === true && typeof obj.citation_id === "string") {
          const result: CiteAckResult = { citationId: obj.citation_id };
          if (typeof obj.resolved_span_start === "number") {
            result.resolvedSpanStart = obj.resolved_span_start;
          }
          if (typeof obj.resolved_span_end === "number") {
            result.resolvedSpanEnd = obj.resolved_span_end;
          }
          return result;
        }
        if (obj.ok === false) {
          return {
            failureReason:
              typeof obj.error === "string" ? obj.error : "cite() rejected",
          };
        }
        return {};
      });
    }
  } catch {
    // fall through — unrecognized output shape; leave as "in flight"
  }
  return [];
}

function isCitationConfidence(v: unknown): v is CitationConfidence {
  return v === "verbatim" || v === "paraphrase";
}

/** Build a single Citation record from a raw cite() input + its matching
 *  ack. Shared between the single-cite path (one block → one Citation)
 *  and the cite_batch path (one block → N Citations, one per item in
 *  input.citations). Returns null when the input is malformed (missing
 *  chunk_id, missing claim_span, missing both offsets and quote) so the
 *  caller can drop that slot. The caller is responsible for indexing —
 *  pass the running 1-based index for the citation's place in the
 *  rendered list. */
function buildCitationFromInput(
  input: Record<string, unknown>,
  ack: CiteAckResult,
  indexHint: number,
  resolved: Map<string, ResolvedChunk>,
  additionalResolved: Map<string, ResolvedChunk> | undefined,
  batchId: string | undefined,
): Citation | null {
  const chunkId = typeof input.chunk_id === "string" ? input.chunk_id : "";
  const hasOffsets =
    typeof input.span_start === "number" &&
    typeof input.span_end === "number";
  const hasQuote = typeof input.quote === "string" && (input.quote as string).length > 0;
  const claimSpan =
    typeof input.claim_span === "string" ? input.claim_span : "";
  // Resolution order (best → worst):
  //   1. Sidecar-derived offsets echoed back through the ack
  //      (post-2026-05-20 cite + cite_batch contract). These point at
  //      the EXACT cited text in chunk.text, which is what the PDF
  //      text-layer search needs.
  //   2. Explicit offsets the model supplied on the input (legacy
  //      offset path — same semantics, just no quote round-trip).
  //   3. Quote-only with no ack offsets yet (in-flight or older tool
  //      version): fall back to a sentinel (0, claim_span.length). The
  //      chip will render but its PDF highlight will be imprecise; the
  //      "couldn't pinpoint" badge surfaces in that case.
  let spanStart: number;
  let spanEnd: number;
  if (
    typeof ack.resolvedSpanStart === "number" &&
    typeof ack.resolvedSpanEnd === "number"
  ) {
    spanStart = ack.resolvedSpanStart;
    spanEnd = ack.resolvedSpanEnd;
  } else if (hasOffsets) {
    spanStart = input.span_start as number;
    spanEnd = input.span_end as number;
  } else if (hasQuote) {
    spanStart = 0;
    spanEnd = Math.max(1, claimSpan.length);
  } else {
    spanStart = -1;
    spanEnd = -1;
  }
  const confidence = isCitationConfidence(input.confidence)
    ? input.confidence
    : "paraphrase";
  if (!chunkId || !claimSpan || spanStart < 0 || spanEnd <= spanStart) {
    return null;
  }
  const citation: Citation = {
    index: indexHint,
    chunkId,
    spanStart,
    spanEnd,
    confidence,
    claimSpan,
  };
  if (ack.citationId) citation.citationId = ack.citationId;
  if (ack.failureReason) citation.failureReason = ack.failureReason;
  if (batchId) citation.batchId = batchId;
  const meta = resolved.get(chunkId) ?? additionalResolved?.get(chunkId);
  if (meta) citation.resolved = meta;
  return citation;
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
        docId: c.doc_id ?? "",
        docTitle: c.doc_title ?? "",
        publisher: c.publisher ?? "",
        fiscalYear: c.fiscal_year ?? null,
        docType: c.doc_type ?? "",
        pageStart: c.page_start ?? null,
        pageEnd: c.page_end ?? null,
        bbox:
          Array.isArray(c.bbox) && c.bbox.length >= 4
            ? [c.bbox[0]!, c.bbox[1]!, c.bbox[2]!, c.bbox[3]!]
            : null,
        text: c.text ?? "",
      });
    }
  }
  return out;
}

/** Build the renderer-facing Citation list for an assistant turn.
 *  Order: cite() blocks in arrival order; chip index is 1-based.
 *
 *  `additionalResolved` is a fallback chunk-metadata map for cite()
 *  calls that reference a chunk_id not produced by THIS turn's
 *  retrieve(). Claude's system prompt allows citing chunks from
 *  earlier turns in the conversation; without this fallback those
 *  citations would render with `resolved=undefined` and the
 *  PdfViewer would show its "Couldn't open source PDF" state even
 *  though the chunk's metadata is in the conversation history. The
 *  caller (ChatThread) builds the cross-turn map once for the
 *  whole conversation and passes it to every bubble. */
/** Collapse retry chips: when the model retries a failed cite for
 *  the same claim and eventually succeeds (possibly with a different
 *  claim_span shape — e.g. table-row → just `$X` → bare `X` — but
 *  always against the same chunk_id), render only the successful
 *  attempt. If all attempts for a claim failed, keep the LAST one
 *  (it represents the model's final state of the claim).
 *  Re-indexes 1-based so chip numbering reflects the user-visible
 *  list, not the model's tool-call history.
 *
 *  Grouping rule: two cites are retries of the same claim when
 *    (a) they reference the same chunk_id, AND
 *    (b) their normalized claim_spans are equal OR one is a substring
 *        of the other.
 *  Substring linkage handles the 2026-05-12 case where the model
 *  emitted a verbose table-row claim, then retried with just the
 *  dollar amount (`$131,582,200`), then retried with the bare
 *  number (`131,582,200`). All three reference the same chunk and
 *  the bare-number form is a substring of the dollar form which is
 *  a substring of the table row — chain into one group via union-find. */
function dedupCitationRetries(citations: Citation[]): Citation[] {
  if (citations.length === 0) return citations;
  // Pre-normalize claim spans so substring checks are stable across
  // markdown formatting / whitespace / case variants.
  const normSpans = citations.map((c) =>
    normalizeForMatch(c.claimSpan).normalized.trim(),
  );
  // Union-find over citation indices. Initialize each as its own root.
  const parent = citations.map((_, i) => i);
  const find = (i: number): number => {
    let r = i;
    while (parent[r]! !== r) r = parent[r]!;
    // Path-compress for amortized near-constant lookup.
    while (parent[i]! !== r) {
      const next = parent[i]!;
      parent[i] = r;
      i = next;
    }
    return r;
  };
  const union = (a: number, b: number) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  };
  // O(n²) is fine — a single assistant turn rarely emits more than
  // ~40 cite calls, and the inner check is a string-substring test.
  for (let i = 0; i < citations.length; i++) {
    for (let j = i + 1; j < citations.length; j++) {
      if (citations[i]!.chunkId !== citations[j]!.chunkId) continue;
      const ni = normSpans[i]!;
      const nj = normSpans[j]!;
      if (!ni || !nj) continue;
      if (ni === nj || ni.includes(nj) || nj.includes(ni)) {
        union(i, j);
      }
    }
  }
  // Second pass: FIFO pair FAIL → subsequent OK for the same chunk_id.
  // Handles the 2026-05-20 case where the model retries by REWRITING
  // the claim_span entirely (e.g. failed table-row
  //   "FY 2024-25 | $17,337.2M | Includes $962.8M beginning balance"
  // → successful prose retry
  //   "State general fund revenue for fiscal year 2024-2025, including a
  //    beginning balance of...").
  // The two strings share NO substring overlap so the first pass misses
  // them — but they're clearly retries because they hit the same
  // chunk_id in close emission order, and the second one carries an
  // ok:true / citation_id while the first failed.
  // Pairing rule: within a chunk_id, walk in emission order; each
  // pending FAIL gets paired with the next OK for the same chunk_id.
  // Risk: model legitimately cites two distinct facts from one chunk
  // (one fails, one succeeds) — we'd lose the failed chip. Acceptable
  // tradeoff: the common case (retries) was producing 2-3× chip
  // pollution; the false-positive case is rare and the user still sees
  // the OK chip representing real coverage of the chunk.
  const pendingFailIndicesByChunk = new Map<string, number[]>();
  for (let i = 0; i < citations.length; i++) {
    const c = citations[i]!;
    const isOk = c.citationId !== undefined;
    if (!isOk) {
      let pending = pendingFailIndicesByChunk.get(c.chunkId);
      if (!pending) {
        pending = [];
        pendingFailIndicesByChunk.set(c.chunkId, pending);
      }
      pending.push(i);
    } else {
      const pending = pendingFailIndicesByChunk.get(c.chunkId);
      if (pending && pending.length > 0) {
        // Within a single cite_batch the model emits intentional
        // distinct claims, never retries. Skip pairing a FAIL with a
        // sibling OK from the SAME batch — that would silently swallow
        // a failed chip the user is entitled to see. Cross-batch (or
        // cross-block) pairing still fires as before.
        const failIdx = pending[0]!;
        const sameBatch =
          c.batchId !== undefined &&
          citations[failIdx]!.batchId === c.batchId;
        if (!sameBatch) {
          pending.shift();
          union(failIdx, i);
        }
      }
    }
  }
  // Bucket by root.
  const groups = new Map<number, Citation[]>();
  for (let i = 0; i < citations.length; i++) {
    const root = find(i);
    let bucket = groups.get(root);
    if (!bucket) {
      bucket = [];
      groups.set(root, bucket);
    }
    bucket.push(citations[i]!);
  }
  // Pick one representative per group: first ok, else last attempt.
  const chosen = new Set<Citation>();
  for (const bucket of groups.values()) {
    const firstOk = bucket.find((c) => c.citationId !== undefined);
    chosen.add(firstOk ?? bucket[bucket.length - 1]!);
  }
  // Preserve emission order so chips appear in the same sequence as
  // the answer reads, then re-index 1-based.
  return citations
    .filter((c) => chosen.has(c))
    .map((c, i) => ({ ...c, index: i + 1 }));
}

export function extractCitations(
  turn: AssistantTurn,
  additionalResolved?: Map<string, ResolvedChunk>,
): Citation[] {
  const resolved = buildResolvedChunkMap(turn);
  const out: Citation[] = [];
  for (const block of turn.blocks) {
    if (block.kind !== "tool") continue;

    if (CITE_TOOL_NAMES.has(block.toolName)) {
      // Single-cite path: one block → one Citation. Task 4 (2026-05-20)
      // made offsets optional alongside a `quote` field; the helper
      // accepts either shape.
      const ack = parseCiteAck(block.output);
      const citation = buildCitationFromInput(
        block.input,
        ack,
        out.length + 1,
        resolved,
        additionalResolved,
        undefined,
      );
      if (citation) out.push(citation);
      continue;
    }

    if (CITE_BATCH_TOOL_NAMES.has(block.toolName)) {
      // Batched-cite path (cite_batch, added 2026-05-20): one block
      // carries N citations in input.citations and N parallel acks in
      // output.citations. We walk both arrays and build one Citation
      // per item, just as if the model had emitted N separate cite()
      // tool_use blocks — downstream code (placement, dedup, chip
      // rendering) doesn't need to know cite_batch existed.
      // The block's toolUseId becomes each Citation's batchId so the
      // dedup pass can tell same-batch sibling claims (which are NEVER
      // retries of each other) from cross-block retries.
      const batchInput = block.input.citations;
      if (!Array.isArray(batchInput)) continue;
      const acks = parseCiteBatchAck(block.output);
      const batchId = block.toolUseId;
      for (let i = 0; i < batchInput.length; i++) {
        const item = batchInput[i];
        if (typeof item !== "object" || item === null) continue;
        // Per-item ack OR the batch-level failure as a fallback. When
        // the batch transport-failed entirely we get an empty acks[]
        // and the citation appears as "in flight" — same UX as a
        // single cite that hasn't returned yet.
        const ack = acks[i] ?? {};
        const citation = buildCitationFromInput(
          item as Record<string, unknown>,
          ack,
          out.length + 1,
          resolved,
          additionalResolved,
          batchId,
        );
        if (citation) out.push(citation);
      }
      continue;
    }
  }
  // Collapse retry chips: if the model emitted ✗ then ✓ for the
  // same claim, render only the ✓ — the ✗ is internal-state noise
  // the user shouldn't see in the final answer. See dedupCitationRetries
  // for the failed-only fallback (keep last attempt).
  return dedupCitationRetries(out);
}

/** Build a chunk-metadata map covering all retrieve() results across
 *  a sequence of assistant turns. Used by ChatThread to feed every
 *  AssistantTurnBubble with the conversation-wide resolved map.
 *  Order matters: later turns overwrite earlier entries for the
 *  same chunk_id, so updated metadata propagates forward. */
export function buildConversationResolvedChunkMap(
  turns: AssistantTurn[],
): Map<string, ResolvedChunk> {
  const out = new Map<string, ResolvedChunk>();
  for (const turn of turns) {
    const turnMap = buildResolvedChunkMap(turn);
    for (const [k, v] of turnMap) out.set(k, v);
  }
  return out;
}

/** Pull `<cite chunk_id=... span_start=... span_end=... confidence=...
 *  claim_span="...">inner</cite>` tags out of a markdown text body
 *  and return both:
 *
 *    - `strippedText` — the markdown with the tags removed but the
 *      inner content kept. The renderer feeds this to ReactMarkdown
 *      so the answer reads naturally; the citation chip lights up
 *      via the existing claim_span substring match.
 *    - `citations` — synthetic Citation records, one per tag. They
 *      lack tool-validated `citationId` (no cite() ack arrived) but
 *      otherwise look identical to tool-call citations: `claimSpan`
 *      is the inner text, so the inline-underline pass picks them up.
 *
 *  Why this exists: Anthropic's models sometimes emit XML-style
 *  inline citations instead of calling the cite() MCP tool, even
 *  when the system prompt explicitly says to use the tool. This is
 *  defensive — it gives the analyst the same chip UX in either
 *  mode, so a model regression doesn't drop the verifiability story
 *  on the floor. The tool path remains preferred because cite()
 *  validates chunk_id + span server-side; inline XML is unvalidated. */
const INLINE_CITE_RE = /<cite\s+([^>]*?)>([\s\S]*?)<\/cite>/g;

export function extractInlineCiteTags(text: string): {
  strippedText: string;
  citations: Citation[];
} {
  if (!text || !text.includes("<cite")) {
    return { strippedText: text, citations: [] };
  }
  const citations: Citation[] = [];
  let nextIndex = 1;
  const strippedText = text.replace(
    INLINE_CITE_RE,
    (_full, attrs: string, inner: string) => {
      const parsed = parseInlineCiteAttrs(attrs);
      // Always emit the inner text so the prose reads cleanly even
      // when the tag's attrs are malformed; just don't push a
      // citation for that case.
      const innerText = inner.trim();
      if (!parsed) return innerText;
      const claimSpan = parsed.claim_span ?? innerText;
      // span_start / span_end are optional in the inline form; cite()
      // tool calls require them but inline XML often omits. Fall back
      // to (0, claimSpan.length) so the Citation type's contract holds.
      const spanStart = parsed.span_start ?? 0;
      const spanEnd =
        parsed.span_end ?? Math.max(spanStart + 1, claimSpan.length);
      const confidence: CitationConfidence =
        parsed.confidence === "verbatim" || parsed.confidence === "paraphrase"
          ? parsed.confidence
          : "paraphrase";
      const citation: Citation = {
        index: nextIndex++,
        chunkId: parsed.chunk_id ?? "",
        spanStart,
        spanEnd,
        confidence,
        claimSpan,
      };
      citations.push(citation);
      return innerText;
    },
  );
  return { strippedText, citations };
}

interface InlineCiteAttrs {
  chunk_id?: string;
  span_start?: number;
  span_end?: number;
  confidence?: string;
  claim_span?: string;
}

const ATTR_RE = /(\w[\w-]*)\s*=\s*"([^"]*)"/g;

/** Decode the HTML/XML entities that appear inside `<cite>` attribute
 *  values. Models sometimes XML-encode quotes and ampersands inside
 *  the `claim_span="…"` attribute; without decoding, the resulting
 *  Citation.claimSpan won't substring-match the rendered answer text
 *  (which contains literal quotes), and the inline-underline pass
 *  silently falls back to the footer chip. Order matters: `&amp;`
 *  must decode last so we don't double-decode an entity hidden inside
 *  another entity. */
function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&quot;/g, '"')
    .replace(/&#34;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");
}

function parseInlineCiteAttrs(attrs: string): InlineCiteAttrs | null {
  const out: InlineCiteAttrs = {};
  let any = false;
  for (const m of attrs.matchAll(ATTR_RE)) {
    const key = m[1]!;
    const val = decodeHtmlEntities(m[2]!);
    any = true;
    if (key === "chunk_id") out.chunk_id = val;
    else if (key === "span_start") {
      const n = Number.parseInt(val, 10);
      if (!Number.isNaN(n)) out.span_start = n;
    } else if (key === "span_end") {
      const n = Number.parseInt(val, 10);
      if (!Number.isNaN(n)) out.span_end = n;
    } else if (key === "confidence") out.confidence = val;
    else if (key === "claim_span") out.claim_span = val;
  }
  return any ? out : null;
}

/** Normalize a string for lenient claim_span ↔ rendered-text matching.
 *  Models almost never re-type claim_span byte-for-byte identical to
 *  what they wrote in the answer. Two drifts dominate:
 *
 *    1. Cosmetic — collapsed whitespace, smart vs straight quotes,
 *       em/en dashes vs hyphens, NBSP, casing, NFKC ligatures.
 *    2. Markdown formatting tokens — Opus emits claim_span values
 *       like `"about **$501.9 million** of settlements"` but the
 *       rendered DOM strips the asterisks. Without skipping the
 *       markdown tokens during normalization, the claim never
 *       substring-matches the rendered text and every chip falls
 *       to the footer. This was the dominant inline-underline
 *       failure mode in the 2026-05-07 audit.
 *
 *  We strip both. The function returns an `indexMap` parallel to the
 *  normalized string, carrying the ORIGINAL-string index each
 *  normalized char came from — so a match at position N in the
 *  normalized string can be recovered as a substring
 *  `[indexMap[N], indexMap[N+span])` in the original. Skipped
 *  markdown tokens consume original-string positions but contribute
 *  no normalized output (their indices are just absent from
 *  indexMap). Collapsed whitespace runs surface as a single space
 *  pointing at the first whitespace char of the original run.
 *
 *  This is the substrate for both the inline-underline matcher
 *  (CitedMarkdownContent) and the PDF text-layer search. */
export function normalizeForMatch(text: string): {
  normalized: string;
  indexMap: number[];
} {
  let normalized = "";
  const indexMap: number[] = [];
  // Apply NFKC first so compatibility forms collapse (e.g. ﬁ → fi)
  // before our own folds. We then walk the NFKC'd string but record
  // ORIGINAL-string offsets, which means we have to remap backward
  // through the NFKC mapping. NFKC rarely changes index alignment in
  // English text — when it does (rare ligature splits), we fall back
  // to using the original-string offset of the parent code point.
  const nfkc = text.normalize("NFKC");
  const originalIdxForNfkcPos: number[] = [];
  if (nfkc.length === text.length) {
    for (let i = 0; i < nfkc.length; i++) originalIdxForNfkcPos.push(i);
  } else {
    for (let i = 0; i < nfkc.length; i++) {
      originalIdxForNfkcPos.push(
        Math.min(text.length - 1, Math.floor((i * text.length) / nfkc.length)),
      );
    }
  }
  let inWs = false;
  let i = 0;
  // Tracks how many open accounting-negative parens we've collapsed
  // and not yet seen the close for. Incremented when we drop `(` or
  // `$(`; decremented (and the `)` skipped) when we hit the next
  // close paren. Prevents the close-paren skip from firing on
  // unrelated `)` later in the text (e.g., `(Item 9 of Section 116)`).
  let accountingNegDepth = 0;
  while (i < nfkc.length) {
    const ch = nfkc[i]!;
    const origIdx = originalIdxForNfkcPos[i]!;

    // ── Markdown backslash escape: \X means "literal X" ─────────
    // CommonMark §2.4: a backslash before an ASCII punctuation char
    // renders as that char alone. MinerU and other ingest pipelines
    // emit `\$` to prevent `$…$` from rendering as math, plus `\(`
    // / `\)` / `\[` / `\]` in similar contexts. The PDF text layer
    // has the UNESCAPED form, so a chunk-text-to-PDF substring match
    // silently fails unless we strip the backslash here. Skipping
    // the backslash without emitting means the indexMap entry for
    // the following char correctly points at THAT char's original
    // position, not the backslash's. The 2026-05-11 audit's cite-#14
    // wrong-bbox case was this exact pattern.
    if (ch === "\\" && i + 1 < nfkc.length) {
      const next = nfkc[i + 1]!;
      if ("\\`*_{}[]()#+-.!|>~$".includes(next)) {
        i += 1;
        continue;
      }
    }
    // ── Accounting-negative parens around a dollar amount ────────
    // Two equivalent conventions appear in budget PDFs:
    //   `$(10,000,000)` — dollar-first (MinerU's preferred output)
    //   `($10,000,000)` — paren-first (common in pdfjs text-layer
    //     output because that's the visual glyph order)
    // Both indicate a negative / decrease. The sign is in the verb
    // of the claim, not the number, so we collapse the parens here
    // so chunk text and PDF text-layer text normalize to the same
    // `$10,000,000` token. The 2026-05-12 cite-#10 wrong-bbox case
    // was the paren-first form not collapsing.
    if (
      ch === "$" &&
      i + 1 < nfkc.length &&
      nfkc[i + 1] === "(" &&
      /^[0-9]/.test(nfkc[i + 2] ?? "")
    ) {
      // `$(X)` — emit the $ and skip the (. Mark that we owe the
      // matching close paren a skip.
      normalized += "$";
      indexMap.push(origIdx);
      inWs = false;
      accountingNegDepth += 1;
      i += 2;
      continue;
    }
    if (
      ch === "(" &&
      i + 1 < nfkc.length &&
      nfkc[i + 1] === "$" &&
      /^[0-9]/.test(nfkc[i + 2] ?? "")
    ) {
      // `($X)` — skip the leading ( so the next iteration emits the $.
      accountingNegDepth += 1;
      i += 1;
      continue;
    }
    // Close an accounting-negative paren we opened above. Only fires
    // when we have an outstanding open we collapsed — otherwise this
    // `)` is unrelated punctuation and passes through normally.
    if (ch === ")" && accountingNegDepth > 0) {
      accountingNegDepth -= 1;
      i += 1;
      continue;
    }
    // ── Markdown formatting tokens: skip without emitting ────────
    // Bold/strong markers: ** or __  (consume both chars)
    if (
      (ch === "*" || ch === "_") &&
      i + 1 < nfkc.length &&
      nfkc[i + 1] === ch
    ) {
      i += 2;
      continue;
    }
    // Italic/emphasis markers: single * or _
    if (ch === "*" || ch === "_") {
      i += 1;
      continue;
    }
    // Strikethrough markers: ~~  (consume both)
    if (ch === "~" && i + 1 < nfkc.length && nfkc[i + 1] === "~") {
      i += 2;
      continue;
    }
    // Inline-code marker: `  (single backtick — we keep code content,
    // just drop the delimiters so `$5M` matches `$5M` in rendered text)
    if (ch === "`") {
      i += 1;
      continue;
    }
    // Markdown link: [label](url) — emit label, skip the rest. The
    // label may itself contain markdown (rare in claim_span); we
    // recurse implicitly because the loop continues from after the
    // closing ].
    if (ch === "[") {
      const closeBracket = nfkc.indexOf("](", i);
      if (closeBracket > i) {
        const closeParen = nfkc.indexOf(")", closeBracket + 2);
        if (closeParen > closeBracket) {
          // Skip the opening [, fall through to normal processing
          // for the label chars. When we hit ](, jump past the URL.
          i += 1;
          continue;
        }
      }
      // Not a well-formed link — treat [ as literal.
    }
    // The closing portion of a markdown link: ](…)  detected when we
    // see ]( at this position. Skip from ] to the closing ).
    if (
      ch === "]" &&
      i + 1 < nfkc.length &&
      nfkc[i + 1] === "("
    ) {
      const closeParen = nfkc.indexOf(")", i + 2);
      if (closeParen > i) {
        i = closeParen + 1;
        continue;
      }
    }
    // Table cell separator: pipe — treat as whitespace so cells
    // separate cleanly during matching.
    if (ch === "|") {
      if (!inWs) {
        normalized += " ";
        indexMap.push(origIdx);
        inWs = true;
      }
      i += 1;
      continue;
    }

    // ── Whitespace collapse ──────────────────────────────────────
    if (/\s/.test(ch)) {
      if (!inWs) {
        normalized += " ";
        indexMap.push(origIdx);
        inWs = true;
      }
      i += 1;
      continue;
    }
    inWs = false;
    // Smart quotes → straight; em/en/figure dashes → hyphen; NBSP
    // (U+00A0) and friends already covered by \s above.
    let folded: string;
    switch (ch) {
      case "‘":
      case "’":
      case "‚":
      case "‛":
        folded = "'";
        break;
      case "“":
      case "”":
      case "„":
      case "‟":
        folded = '"';
        break;
      case "–":
      case "—":
      case "−":
      case "‐":
      case "‑":
      case "‒":
        folded = "-";
        break;
      default:
        folded = ch.toLowerCase();
    }
    normalized += folded;
    indexMap.push(origIdx);
    i += 1;
  }
  return { normalized, indexMap };
}

/** Lenient substring search. Returns the [start, end) range in the
 *  original `haystack` (NOT the normalized one) where `needle`
 *  appears, after normalizing both via `normalizeForMatch`. Returns
 *  null when no match exists. Used by the inline-underline renderer
 *  and the PDF text-layer highlighter. */
export function findNormalizedMatch(
  haystack: string,
  needle: string,
  fromIndex = 0,
): { start: number; end: number } | null {
  if (!needle) return null;
  const h = normalizeForMatch(haystack);
  const n = normalizeForMatch(needle);
  // Find the normalized-from-index that corresponds to the original
  // `fromIndex` floor — first normalized index whose original >= fromIndex.
  let normFrom = 0;
  while (
    normFrom < h.indexMap.length &&
    h.indexMap[normFrom]! < fromIndex
  ) {
    normFrom++;
  }
  // Trim leading/trailing whitespace + punctuation on the normalized
  // needle so a claim_span captured with a stray period or space at
  // either end still finds its anchor in the haystack. We only fold
  // outer punctuation; interior punctuation (commas, periods, $ signs)
  // must still match.
  const trimmed = n.normalized.replace(/^[\s.,;:!?]+|[\s.,;:!?]+$/g, "");
  if (!trimmed) return null;
  const idx = h.normalized.indexOf(trimmed, normFrom);
  if (idx < 0) return null;
  const startOrig = h.indexMap[idx]!;
  // End is exclusive — point one past the last matched original char.
  const lastNormIdx = idx + trimmed.length - 1;
  const lastOrig = h.indexMap[lastNormIdx]!;
  // Walk forward from lastOrig to consume any trailing chars that
  // collapsed into the same normalized index (e.g. a multi-char
  // whitespace run). This keeps the highlight visually flush.
  let endOrig = lastOrig + 1;
  while (
    endOrig < haystack.length &&
    /\s/.test(haystack[endOrig]!) &&
    lastNormIdx + 1 < h.indexMap.length &&
    h.indexMap[lastNormIdx + 1]! > endOrig
  ) {
    endOrig++;
  }
  return { start: startOrig, end: endOrig };
}

/** Sentinel marker used to ferry chip placement through ReactMarkdown.
 *  Curly braces have no special meaning in CommonMark, so the sentinel
 *  survives the markdown parser intact and lands in a text node where
 *  the renderer can split it out and inject a CitationChip.
 *
 *  Chosen for low collision probability — claim_span text containing
 *  literal `{{cite:0}}` is functionally never seen in budget docs. */
export const CITE_SENTINEL_RE = /\{\{cite:(\d+)\}\}/g;

/** Per-citation placement decision used by the renderer to inject
 *  chip sentinels into the markdown source. A single citation can
 *  produce MULTIPLE placements — one per sentence whose normalized
 *  text contains the citation's claim_span or its key-fact token. */
export interface CitationPlacement {
  /** Index in the citations array we were given. */
  citationIndex: number;
  /** Source-markdown line index this citation will anchor to, or -1
   *  when no line/sentence contained the claim_span (chip drops to
   *  end-of-content). */
  lineIndex: number;
  /** Column offset (in the ORIGINAL, non-normalized line) of the END
   *  of the matched sentence. When null, the sentinel goes at end-of-
   *  line (back-compat for tables and bullet lines where a sentence
   *  isn't a useful anchor). */
  column?: number | null;
}

/** Regex over a single markdown line that captures one sentence per
 *  match. A sentence ends at [.!?]+ followed by whitespace or
 *  end-of-string (possibly with trailing quotes/parens), so decimal
 *  points inside numbers like "$3.3M" or "1.5%" are NOT treated as
 *  sentence terminators. The trailing `|[^\n]+$` catches a tail
 *  fragment with no terminating punctuation (the last segment on the
 *  line, which we still want to consider for matching). */
const SENTENCE_RE = /[^\n]+?(?:[.!?]+["')\]]*(?=\s|$))|[^\n]+$/g;

/** Plan chip placements for each citation. Walks every line, then every
 *  sentence inside that line, and emits a CitationPlacement for any
 *  sentence whose normalized text contains the citation's claim_span.
 *  Table rows and bullet lines are treated as single sentences — we
 *  return one placement at the LINE level (no column) for those so the
 *  existing table-row carve-out in `injectCiteSentinels` keeps working.
 *
 *  Citations whose claim_span doesn't match any sentence on any line
 *  emit a single placement with lineIndex -1 (caller appends them at
 *  end of content as a fallback). */
export function planCitationPlacements(
  content: string,
  citations: { claimSpan: string }[],
): CitationPlacement[] {
  if (!content || citations.length === 0) return [];
  const lines = content.split("\n");
  const out: CitationPlacement[] = [];
  for (let i = 0; i < citations.length; i++) {
    const span = citations[i]!.claimSpan;
    if (!span) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
      continue;
    }
    const normSpan = normalizeForMatch(span).normalized;
    const trimmed = normSpan.replace(/^[\s.,;:!?]+|[\s.,;:!?]+$/g, "");
    if (!trimmed) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
      continue;
    }

    let anyMatched = false;
    for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
      const raw = lines[lineIdx]!;
      const isTableRow =
        /^\s*\|/.test(raw.trim()) && /\|\s*$/.test(raw.trim());
      // Table rows: treat the whole row as one sentence at line-level
      // anchoring (no column). The existing table carve-out in
      // injectCiteSentinels handles closing-pipe injection.
      if (isTableRow) {
        const normalizedLine = normalizeForMatch(raw).normalized;
        if (normalizedLine.includes(trimmed)) {
          out.push({ citationIndex: i, lineIndex: lineIdx, column: null });
          anyMatched = true;
        }
        continue;
      }

      // Walk sentences within this line. Each sentence gets matched
      // against the claim_span; matches emit one placement at the end
      // of the matched sentence.
      const matches = Array.from(raw.matchAll(SENTENCE_RE));
      if (matches.length === 0) continue;
      for (const m of matches) {
        const sentence = m[0];
        const sentenceStart = m.index!;
        const sentenceEndExclusive = sentenceStart + sentence.length;
        const normalizedSentence = normalizeForMatch(sentence).normalized;
        if (normalizedSentence.includes(trimmed)) {
          out.push({
            citationIndex: i,
            lineIndex: lineIdx,
            column: sentenceEndExclusive,
          });
          anyMatched = true;
        }
      }
    }

    if (!anyMatched) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
    }
  }
  return out;
}

/** Apply placements to `content`: append `{{cite:N}}` sentinels at
 *  the end of each matched line, then append unmatched-citation
 *  sentinels at the end of the content. Sentinels separated by a
 *  no-break space so adjacent chips visually cluster as a group.
 *
 *  Returns the augmented markdown text. The renderer (CitedMarkdownContent)
 *  walks rendered text nodes for `{{cite:N}}` patterns and replaces
 *  each with a CitationChip element. */
export function injectCiteSentinels(
  content: string,
  placements: CitationPlacement[],
): string {
  if (placements.length === 0) return content;
  const lines = content.split("\n");
  // Bucket by line — preserves original cite order within each line.
  const perLine = new Map<number, number[]>();
  const unmatched: number[] = [];
  for (const p of placements) {
    if (p.lineIndex < 0 || p.lineIndex >= lines.length) {
      unmatched.push(p.citationIndex);
    } else {
      if (!perLine.has(p.lineIndex)) perLine.set(p.lineIndex, []);
      perLine.get(p.lineIndex)!.push(p.citationIndex);
    }
  }
  for (const [lineIdx, citIdxs] of perLine) {
    const sentinels = citIdxs.map((i) => `{{cite:${i}}}`).join(" ");
    const raw = lines[lineIdx]!;
    const stripped = raw.replace(/\s+$/u, "");
    // Markdown table row: starts with `|` (possibly after whitespace)
    // AND ends with `|`. The GFM parser eats anything between the
    // closing `|` and the newline (or adds it as an extra-column
    // cell that gets truncated to match the header column count),
    // so a sentinel appended AFTER the closing `|` silently
    // disappears. Inject BEFORE the closing `|` instead, which
    // puts the sentinel inside the last cell where the chip can
    // render. The 2026-05-12 audit's invisible cites #1-6 were
    // this case.
    if (/^\s*\|/.test(stripped) && /\|\s*$/.test(stripped)) {
      // Walk back from the end past optional whitespace to find the
      // closing `|`, then insert the sentinel just before it. The
      // cell content typically already has a trailing space before
      // the `|`; strip it so we don't end up with double spacing.
      const closeIdx = stripped.lastIndexOf("|");
      const before = stripped.slice(0, closeIdx).replace(/\s+$/u, "");
      lines[lineIdx] = before + " " + sentinels + " " + stripped.slice(closeIdx);
    } else {
      // Non-table line: append sentinels at the end. Non-breaking
      // space prefix glues chips to the last token visually.
      lines[lineIdx] = stripped + " " + sentinels;
    }
  }
  let result = lines.join("\n");
  if (unmatched.length > 0) {
    const sentinels = unmatched.map((i) => `{{cite:${i}}}`).join(" ");
    // Separate from the answer body with a blank line so the chip
    // group doesn't hug the last paragraph awkwardly.
    result += "\n\n" + sentinels;
  }
  return result;
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
