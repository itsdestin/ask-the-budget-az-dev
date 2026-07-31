// Typed client for the frozen backend contract (app/routes/*). Paths are
// relative so one build works both behind the vite dev proxy (vite.config.ts)
// and when FastAPI serves webapp/dist directly.

export interface SearchResult {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  snippet: string;
  page: number | null;
  score: number;
  doc_type: string;
  fiscal_year: number | null;
  publisher: string;
  agencies: string[];
  /** The document's own source PDF/DOCX URL (additive contract field,
   *  2026-07-30 — from Plan 1's documents.json sidecar); null when unknown. */
  doc_url: string | null;
  /** The website mockup index's meta line for this document ("Agency Budget
   *  Detail · Appropriations Report · FY 2025"); additive, null when the doc
   *  isn't in the mockup index. */
  doc_meta: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  provider: string;
}

export interface SearchFilters {
  fiscal_year?: number[];
  publisher?: string[];
  doc_type?: string[];
  agency?: string[];
}

// Surface FastAPI's `detail` field in thrown errors — the backend goes out of
// its way to emit specific JSON messages ("query is empty", "Unknown API
// route"); a bare status code would discard them and the UI could only show a
// vague failure.
async function fail(r: Response, what: string): Promise<never> {
  const detail = await r
    .json()
    .then((b) => (typeof b?.detail === "string" ? b.detail : null))
    .catch(() => null);
  throw new Error(detail ? `${what}: ${detail}` : `${what} failed: ${r.status}`);
}

export async function search(
  query: string,
  filters: SearchFilters = {},
  corpus = "budget",
): Promise<SearchResponse> {
  const r = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters, corpus }),
  });
  if (!r.ok) await fail(r, "search");
  return r.json();
}

export interface Bill {
  bill_number: string;
  title: string;
  chamber: "H" | "S";
  fiscal_note_url: string;
}

export interface Session {
  year: number;
  name: string;
  bills: Bill[];
}

export async function fiscalNotes(): Promise<{ sessions: Session[] }> {
  const r = await fetch("/api/fiscal-notes");
  if (!r.ok) await fail(r, "fiscal-notes");
  return r.json();
}

/** One chunk's provenance fields — everything the source viewer needs to open
 *  a passage, and nothing else (see app/routes/pdf.py's get_chunk). */
export interface ChunkSource {
  chunk_id: string;
  doc_id: string;
  /** 1-indexed PDF page; null when the chunk has no page. */
  page: number | null;
  /** [x0,y0,x1,y1]; null means "search the whole page" (see the strict-bbox
   *  rule in pdf/highlight-strategy.ts). */
  bbox: number[] | null;
  /** Verbatim chunk text — the highlight target AND the cited-text panel. */
  text: string;
  source_format: string | null;
  /** Non-null when this source has no page image (DOCX bills, fiscal notes).
   *  The string is the backend's own 415 wording; render it, don't rewrite it. */
  pdf_unavailable_reason: string | null;
}

/** Fetch one chunk by id. Used by the search page's source panel, where a
 *  click carries only the chunk_id the row was rendered with. */
export async function chunk(
  chunkId: string,
  corpus = "budget",
): Promise<ChunkSource> {
  const r = await fetch(
    `/api/chunks/${encodeURIComponent(chunkId)}?corpus=${encodeURIComponent(corpus)}`,
  );
  if (!r.ok) await fail(r, "chunk");
  return r.json();
}

/** How many fiscal-note passages are actually searchable. The page's semantic
 *  search stays disabled at 0 — offering a search that can only return nothing
 *  is worse than saying it isn't ready. */
export async function fiscalNotesStatus(): Promise<{ chunks: number }> {
  const r = await fetch("/api/fiscal-notes/status");
  if (!r.ok) await fail(r, "fiscal-notes status");
  return r.json();
}

// ---- AI Mode (Plan 4) ------------------------------------------------------

/** One answer tier as `GET /api/ai/status` reports it.
 *
 *  `description` and `examples` are the spec's S16 explainer sentences and they
 *  live SERVER-SIDE on purpose (app/routes/conversations.py::TIER_COPY): the
 *  admin surface in Plan 5 renders the same strings, and two copies of a
 *  sentence is two places for it to drift. Nothing in the webapp may retype
 *  them — the tier explainer reads these fields. */
export interface AiTierInfo {
  label: string;
  default: boolean;
  description: string;
  examples: string[];
  /** Per-tier availability. An admin can wire up Standard and leave Deep
   *  Research unconfigured, so this is NOT the same answer as the top-level
   *  `available` flag. */
  available: boolean;
  reason: string | null;
}

export interface AiStatus {
  /** "Is ANY tier usable" — this is what gates the AI Mode toggle. */
  available: boolean;
  /** Present only when nothing is usable; explains the default tier's failure. */
  reason?: string;
  tiers: Record<string, AiTierInfo>;
  user_usage: {
    month_usd: number | null;
    limit_usd: number | null;
    warned: boolean;
  };
}

export async function aiStatus(): Promise<AiStatus> {
  const r = await fetch("/api/ai/status");
  if (!r.ok) await fail(r, "ai status");
  return r.json();
}

export interface ConversationHandle {
  conversation_id: string;
  /** Inline availability probe for the DEFAULT tier, so the UI can show the
   *  problem before the analyst types (see SystemHealthBanner). */
  health: { ok: boolean; reason?: string };
  tier_default: string;
}

export async function createConversation(
  corpus: "budget" | "fiscal_notes",
): Promise<ConversationHandle> {
  const r = await fetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corpus }),
  });
  if (!r.ok) await fail(r, "start conversation");
  return r.json();
}

/** Ask the running turn to stop. This is what produces the DESIGNED abort
 *  server-side (`stopReason: "user_interrupt"` plus cancelled-tool back-fill);
 *  merely closing the stream leaves the harness to clean up via GeneratorExit
 *  with no terminal frame. */
export async function stopConversation(
  conversationId: string,
): Promise<{ stopped: boolean }> {
  const r = await fetch(
    `/api/conversations/${encodeURIComponent(conversationId)}/stop`,
    { method: "POST" },
  );
  if (!r.ok) await fail(r, "stop");
  return r.json();
}

// ---- ingest queue (Plan 3) -------------------------------------------------

export type JobState =
  | "queued"
  | "extracting"
  | "chunking"
  | "embedding"
  | "writing"
  | "live"
  | "failed"
  | "cancelled";

export interface Job {
  job_id: string;
  doc_id: string;
  title: string;
  corpus: string;
  state: JobState;
  /** Progress within the CURRENT stage, 0-100 — not overall completion. */
  pct: number;
  /** Human detail for the current stage, e.g. "page 34/210". */
  stage_detail: string;
  error: string | null;
  machine: string;
  user: string;
  created_at: string;
  updated_at: string;
}

export interface UploadMeta {
  corpus: string;
  publisher: string;
  doc_type: string;
  fiscal_year: number;
  title: string;
  /** Ingest anyway when the content hash is already known (spec's explicit
   *  re-process option). */
  reprocess?: boolean;
}

export interface DuplicateDocument {
  detail: string;
  existing_doc_id: string;
  added_at: string | null;
  added_by: string | null;
}

/** Thrown on 409 so the page can offer re-process instead of a dead error.
 *  A plain Error would flatten the provenance the user needs to decide. */
export class DuplicateDocumentError extends Error {
  constructor(readonly info: DuplicateDocument) {
    super("already in corpus");
    this.name = "DuplicateDocumentError";
  }
}

export async function uploadDocument(
  file: File,
  meta: UploadMeta,
): Promise<{ job_id: string; doc_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("corpus", meta.corpus);
  form.append("publisher", meta.publisher);
  form.append("doc_type", meta.doc_type);
  form.append("fiscal_year", String(meta.fiscal_year));
  form.append("title", meta.title);
  // Invariant 8: the server rejects the upload without this. The page only
  // sends it once the user has actually ticked the box.
  form.append("is_public_record", "true");
  if (meta.reprocess) form.append("reprocess", "true");

  const r = await fetch("/api/upload", { method: "POST", body: form });
  if (r.status === 409) {
    throw new DuplicateDocumentError(await r.json());
  }
  if (!r.ok) await fail(r, "upload");
  return r.json();
}

export async function jobs(): Promise<{ jobs: Job[] }> {
  const r = await fetch("/api/jobs");
  if (!r.ok) await fail(r, "jobs");
  return r.json();
}

export async function retryJob(jobId: string): Promise<{ job: Job }> {
  const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
  if (!r.ok) await fail(r, "retry");
  return r.json();
}

export async function cancelJob(jobId: string): Promise<{ job: Job }> {
  const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  if (!r.ok) await fail(r, "cancel");
  return r.json();
}

// ---- JLBC books (Plan 3, Task 15) ------------------------------------------

export interface BookEdition {
  key: string;
  family: "approps" | "baseline";
  fiscal_year: number;
  /** False for pre-FY2005 approps / pre-FY2012 baseline: JLBC published those
   *  as one scanned book with no per-agency pages to ingest. */
  ingestable: boolean;
  /** Published under the rolling /budget/ directory, which JLBC repurposes. */
  rolling: boolean;
  era_note: string;
  single_file_url: string | null;
  linked_toc_url: string | null;
  document_count: number;
}

export interface BookPlan {
  source: "catalog" | "probed";
  count: number;
  documents: { url: string; title: string; doc_type: string; code: string }[];
  unreachable: string[];
  notes: string[];
  single_file_url: string | null;
  linked_toc_url: string | null;
}

export async function bookCatalog(): Promise<{ editions: BookEdition[] }> {
  const r = await fetch("/api/books/catalog");
  if (!r.ok) await fail(r, "book catalog");
  return r.json();
}

export async function discoverBook(
  family: string,
  fiscal_year: number,
): Promise<BookPlan> {
  const r = await fetch("/api/books/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ family, fiscal_year }),
  });
  if (!r.ok) await fail(r, "discover");
  return r.json();
}

export async function ingestBook(
  family: string,
  fiscal_year: number,
): Promise<{ queued: number; skipped_existing: number; unreachable: string[] }> {
  const r = await fetch("/api/books/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ family, fiscal_year }),
  });
  if (!r.ok) await fail(r, "add book");
  return r.json();
}
