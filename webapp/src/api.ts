// Typed client for the frozen backend contract (app/routes/*). Paths are
// relative so one build works both behind the vite dev proxy (vite.config.ts)
// and when FastAPI serves webapp/dist directly.

export interface SearchResult {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  snippet: string;
  /** The passage's FULL text (additive, 2026-08-11). The browser picks the
   *  preview window and marks query terms in it — see search/contentSearch.ts.
   *  `snippet` remains the leading 280 chars for the Fiscal Notes page. */
  text: string;
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
  /** The JLBC book this document is a SECTION of ("Baseline",
   *  "Appropriations Report"), or null when it is a document type in its own
   *  right. Derived server-side from source_url — see app/book_sections.py
   *  for why the doc_id is not usable. WHY here too, not just on
   *  CorpusDocument: app/search_provider.py emits this field on every search
   *  row (see search_provider.py:265), so the type was out of date about a
   *  field the backend already sends. */
  section_of: string | null;
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
  /** Which BOOK's sections to keep when `doc_type` names a section slug that
   *  belongs to both books ("Baseline" | "Appropriations Report") — sent only
   *  when exactly one book family is selected (see contentSearch.ts's
   *  `toSearchFilters`). Mirrors app/routes/search.py's `SearchFilters`. */
  section_family?: string;
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

/** Live corpus size (Plan 5 Task 19).
 *
 *  The footer used to hardcode "382 docs". Plan 3's upload queue falsified
 *  that the first time anyone uploaded and nothing in the app noticed, so
 *  the number was removed rather than left to rot. This is what lets it be
 *  stated truthfully again. Not admin-gated — every analyst sees the footer.
 */
export interface CorpusCounts {
  documents: number;
  budget_chunks: number;
  fiscal_note_chunks: number;
}

export async function corpusCounts(): Promise<CorpusCounts> {
  const r = await fetch("/api/corpus/counts");
  if (!r.ok) await fail(r, "corpus counts");
  return r.json();
}

/** One document in the browse listing — everything the Budget Documents page
 *  needs to render a row, and nothing else (see app/routes/corpus.py). */
export interface CorpusDocument {
  doc_id: string;
  /** Display title — the sidecar's own, else the humanized doc_id. */
  title: string;
  publisher: string;
  doc_type: string;
  fiscal_year: number | null;
  /** The document's own source PDF/DOCX URL; null when the sidecar doesn't
   *  know it — the row then renders unlinked rather than guessing. */
  doc_url: string | null;
  /** The JLBC book this document is a SECTION of ("Baseline",
   *  "Appropriations Report"), or null when it is a document type in its own
   *  right. Derived server-side from source_url — see app/book_sections.py
   *  for why the doc_id is not usable. */
  section_of: string | null;
  /** Extra strings the filter box matches by EXACT token equality — the
   *  agency's JLBC URL slug and reviewed aliases, plus this report type's
   *  shorthand ("26ar"). Computed server-side in app/search_terms.py so
   *  JLBC's convention has one implementation, not two. Always present;
   *  empty for a document with neither a known agency nor a shorthand type. */
  terms: string[];
}

/** The whole budget corpus as one flat listing, for the browse-first Budget
 *  Documents page. Fetched once on mount; the page filters, groups and
 *  searches it client-side, so there is no request per keystroke. Not
 *  admin-gated — it's the same corpus catalog the counts endpoint sizes. */
export async function corpusDocuments(): Promise<{ documents: CorpusDocument[] }> {
  const r = await fetch("/api/corpus/documents");
  if (!r.ok) await fail(r, "corpus documents");
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
  resumeFrom?: string,
): Promise<ConversationHandle> {
  const r = await fetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resumeFrom ? { corpus, resume_from: resumeFrom } : { corpus }),
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
  doc_type: string;
  fiscal_year: number;
  title: string;
  /** Ingest anyway when the content hash is already known (spec's explicit
   *  re-process option). */
  reprocess?: boolean;
  /** Which reading of a Budget Bill Summary this is. Required server-side
   *  (422 without it) whenever the row's `stage_field` is true — see
   *  DocTypeCard.stage_field below. */
  stage?: "introduced" | "engrossed";
}

/** One row of `GET /api/document-types` — the upload page's own copy of the
 *  type list is gone (Task 6); every row's copy comes off the wire from
 *  `data/document-types.yaml` via `ingest.doc_types.upload_rows()`, so the
 *  two lists can no longer drift. Field names mirror the registry's own
 *  `DocType` attributes 1:1 (see ingest/doc_types.py). */
export interface DocTypeCard {
  key: string;
  label: string;
  group: string;
  formats: string[];
  where_published: string;
  which_file: string;
  /** Present only for the two JLBC-book rows, which are never uploaded —
   *  see `app/book_sections.py`'s reasoning for why a book is added by the
   *  book tool (one document per agency) rather than as a single PDF.
   *  `which_file` is "" on a redirect row; every other row has `null` here. */
  redirect: { action: string; label: string; detail: string } | null;
  /** True only for budget-bill-summary today — gates whether the row shows
   *  the Introduced/Engrossed picker, and whether the upload route requires
   *  one (422 without it on a staged type). */
  stage_field: boolean;
  order: number;
}

export async function documentTypes(): Promise<DocTypeCard[]> {
  const r = await fetch("/api/document-types");
  if (!r.ok) await fail(r, "document types");
  return (await r.json()).types;
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
  // WHY no `publisher` field: it used to be sent from a hand-maintained
  // client-side map (ROW_PUBLISHERS in Upload.tsx) that could only ever cover
  // the doc_types someone remembered to add to it — the spec's own T4
  // acceptance test ("a seventh row must be a change to the YAML file, not to
  // code") failed silently the moment a new row's publisher wasn't jlbc. The
  // server now derives publisher from the doc_type's registry row, so the
  // form field is gone rather than fixed — there is nothing left for the
  // client to infer. `publisher` is optional server-side for exactly this
  // reason (see the sibling Python change).
  form.append("doc_type", meta.doc_type);
  form.append("fiscal_year", String(meta.fiscal_year));
  form.append("title", meta.title);
  if (meta.stage) form.append("stage", meta.stage);
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

// ---------------------------------------------------------------------------
// Identity + admin (Plan 5)
// ---------------------------------------------------------------------------

/** `GET /api/me` — who the caller is and what the app will let them see.
 *
 *  The admin gate behind these types is SOFT (spec S11): it is keyed on the
 *  Windows username, which anyone can override. It exists so the admin page
 *  isn't advertised office-wide, not to keep anyone out. Nothing behind it is
 *  harmful if bypassed. */
export interface Me {
  user: string;
  is_admin: boolean;
  admin_username: string;
  /** No admin configured yet, OR a RESET-ADMIN.txt is present. */
  admin_claimable: boolean;
  /** A reset file is waiting to be used up by the next claim. */
  admin_reset_pending: boolean;
}

export async function me(): Promise<Me> {
  const r = await fetch("/api/me");
  if (!r.ok) await fail(r, "who am I");
  return r.json();
}

export async function claimAdmin(): Promise<{ admin_username: string }> {
  const r = await fetch("/api/admin/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
  if (!r.ok) await fail(r, "claim admin");
  return r.json();
}

/** The provider block as the server RETURNS it. There is no `api_key` field
 *  and there never will be — `GET /api/admin/settings` never returns the key
 *  (see app/routes/admin.py). `api_key_hint` is the last four characters only,
 *  so it is safe to screenshot. */
export interface AdminProvider {
  provider: "openrouter" | "custom";
  base_url: string;
  api_key_set: boolean;
  api_key_hint: string;
  /** Dollars per million tokens, for a custom service. Required to save one
   *  (2026-07-31): without both, every request lands with no cost, which
   *  makes spending invisible AND silently switches limits off. Null on
   *  OpenRouter, which reports its own exact cost per call. */
  prompt_usd_per_m: number | null;
  completion_usd_per_m: number | null;
}

export interface AdminSettings {
  provider: AdminProvider;
  /** `enabled` is a real setting, not view state: switching an answer mode
   *  off keeps the model it was using, so switching it back on is not a
   *  fresh decision. */
  tiers: Record<string, { model: string; enabled: boolean }>;
  admin_username: string;
  /** The master switch. Distinct from "a key is configured" — an admin
   *  pausing AI Mode must not have to delete the key and re-enter it. */
  ai_enabled: boolean;
  default_monthly_limit_usd: number | null;
  user_limits: Record<string, number>;
  exempt_users: string[];
}

/** The literal a client sends in place of the key to mean "I am not editing
 *  this field". NOT the empty string — "" is a real edit (clearing the key to
 *  turn AI Mode off), and a form that submits every field it rendered has no
 *  other way to say "leave the one I was never shown alone". */
export const UNCHANGED_KEY = "__unchanged__";

export interface AdminSettingsWrite {
  provider?: {
    provider: string;
    base_url: string;
    prompt_usd_per_m?: number | null;
    completion_usd_per_m?: number | null;
  };
  tiers?: Record<string, { model: string; enabled: boolean }>;
  admin_username?: string;
  ai_enabled?: boolean;
  default_monthly_limit_usd?: number | null;
  user_limits?: Record<string, number>;
  exempt_users?: string[];
  api_key?: string;
  confirm_admin_transfer?: boolean;
}

export async function adminSettings(): Promise<AdminSettings> {
  const r = await fetch("/api/admin/settings");
  if (!r.ok) await fail(r, "admin settings");
  return r.json();
}

export async function saveAdminSettings(
  body: AdminSettingsWrite,
): Promise<AdminSettings> {
  const r = await fetch("/api/admin/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) await fail(r, "save settings");
  return r.json();
}

export interface ModelCard {
  id: string;
  name: string;
  context_length: number | null;
  prompt_usd_per_m: number | null;
  completion_usd_per_m: number | null;
  supports_tools: boolean;
  /** False when the live catalog could not confirm the model exists. Such a
   *  model renders greyed and unselectable — the admin needs to SEE that the
   *  one their tier names has gone away. */
  available: boolean;
  tier_hint: string | null;
  blurb: string | null;
  /** Indicators, all straight from OpenRouter's catalog payload. There is
   *  deliberately no speed or latency figure: OpenRouter publishes those
   *  fields but returned null for every shipped recommendation, so there is
   *  nothing real to show. */
  max_output_tokens: number | null;
  is_open_weights: boolean;
  /** Roughly what one question in this mode costs on this model, sized from
   *  a question that was actually measured. An estimate — every surface that
   *  renders it says "about". */
  usd_per_question: number | null;
  /** Artificial Analysis's Intelligence Index, republished by OpenRouter.
   *  Higher is better; a composite of public evaluations, not a mark out of
   *  100. Null when the model has not been scored — such a model shows no
   *  intelligence figure at all rather than a zero.
   *
   *  The RAW index. The picker shows `intelligence_percent`; this survives
   *  for the tooltip that cites where the number came from. */
  intelligence_index: number | null;
  /** `intelligence_index` as a percentage of a fixed ceiling (Opus 5 + 10%
   *  headroom), computed server-side in `harness/catalog.py` so there is one
   *  definition of the scale.
   *
   *  This is what the picker renders. The ceiling sits deliberately above the
   *  best available model, so nothing reaches 100% — a full bar would claim
   *  "as good as models get", which expires the week a better one ships. */
  intelligence_percent: number | null;
  /** The same source's agentic score. AI Mode is a tool loop, so this is the
   *  sub-score closest to the work this app actually asks of a model. */
  agentic_index: number | null;
}

export interface ModelCatalog {
  source: "live" | "cache" | "bundled";
  fetched_at: string | null;
  recommended: ModelCard[];
  catalog: ModelCard[];
  note: string | null;
}

export async function adminModels(refresh = false): Promise<ModelCatalog> {
  const r = await fetch(`/api/admin/models?refresh=${refresh ? 1 : 0}`);
  if (!r.ok) await fail(r, "model catalog");
  return r.json();
}

export interface UsageGroup {
  key: string;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  cached_tokens: number;
  rows: number;
  rows_with_unknown_cost: number;
}

export interface AdminUsage {
  month: string;
  total_usd: number;
  rows: number;
  /** Requests whose cost could not be recorded. Only reachable from rows
   *  written before custom-service pricing became mandatory (2026-07-31);
   *  no new request can produce one. Still surfaced when non-zero, because
   *  a total that silently omits rows understates what was spent. */
  rows_with_unknown_cost: number;
  cached_tokens: number;
  tokens_in: number;
  by_user: UsageGroup[];
  by_model: UsageGroup[];
  by_tier: UsageGroup[];
  limits_active: boolean;
  limits_inactive_reason: string | null;
}

export async function adminUsage(month?: string): Promise<AdminUsage> {
  const r = await fetch(`/api/admin/usage${month ? `?month=${month}` : ""}`);
  if (!r.ok) await fail(r, "usage");
  return r.json();
}

export interface MyUsage {
  month: string;
  month_usd: number | null;
  limit_usd: number | null;
  status: "allowed" | "warn" | "blocked";
  /** The ledger's own sentence, emitted from one place. Never re-typed in the
   *  UI — two subtly different "you're over your limit" messages is worse than
   *  one blunt one. */
  message: string | null;
  reason: string | null;
  rows_with_unknown_cost: number;
}

export async function myUsage(): Promise<MyUsage> {
  const r = await fetch("/api/me/usage");
  if (!r.ok) await fail(r, "my usage");
  return r.json();
}

export interface AdminCorpus {
  data_dir: string;
  budget_chunks: number;
  fiscal_note_chunks: number;
  documents: number;
  lancedb_bytes: number;
  /** An ESTIMATE of the space held by superseded LanceDB versions; null when
   *  it can't be measured. Render it as "about X", never as an exact figure —
   *  see `_reclaimable_bytes` in app/routes/admin.py. */
  dead_version_bytes: number | null;
  last_ingest_at: string | null;
  queue: { queued: number; running: number; failed: number };
  /** Is THIS computer set to process the upload queue? Defaults to false —
   *  one bundle is installed on ~20 office PCs and they must not all start a
   *  worker. See app/machine_config.py::ingest_enabled. */
  ingest_enabled_here: boolean;
  /** Uploads are waiting and no machine is draining them. The server owns
   *  the wording (`MSG_QUEUE_STALLED`) so it cannot drift from the flag's
   *  own semantics; the UI renders `queue_stalled_message` verbatim. */
  queue_stalled: boolean;
  queue_stalled_message: string | null;
}

export async function adminCorpus(): Promise<AdminCorpus> {
  const r = await fetch("/api/admin/corpus");
  if (!r.ok) await fail(r, "corpus health");
  return r.json();
}

/** One extraction method the ladder tried on a held-back document.
 *  `coverage` is null for a rung that crashed, or whose SOURCE could not be
 *  measured — never rendered as 0%, which would claim a worse measurement
 *  than was actually taken. */
export interface AttentionAttempt {
  extractor: string;
  coverage: number | null;
}

/** A document the extraction ladder could not save — every rung scored
 *  below the coverage floor (or crashed), so it was held OUT of search
 *  rather than written with almost nothing in it. This measures
 *  catastrophic TEXT LOSS, never correctness — `message` is the job's own
 *  sentence (`ingest/worker.py::_held_out_message`) and is written to say
 *  only what was measured, never that anything was "verified" or "checked".
 */
export interface AttentionDocument {
  job_id: string;
  title: string;
  /** Server-side `job.error` is `str | None` -- but every job this route
   *  lists is in state `failed`, and the only way a job REACHES `failed` is
   *  `ingest.jobs.advance()`, which raises `ValueError` if `error` is
   *  falsy (see the `if new_state == "failed": if not error: raise ...`
   *  guard there). So a null `message` here would mean a job reached
   *  `failed` some other way, which nothing in this codebase does today. */
  message: string;
  /** The best ratio any rung reached, or null when every rung crashed with
   *  nothing measurable at all. Can exceed 1.0 for a document whose own
   *  text layer undercounts (real AFRs score up to ~286%) — never capped. */
  best_coverage: number | null;
  attempts: AttentionAttempt[];
}

export async function adminAttention(): Promise<{ documents: AttentionDocument[] }> {
  const r = await fetch("/api/admin/attention");
  if (!r.ok) await fail(r, "documents needing attention");
  return r.json();
}

/** Make (or unmake) this computer the one that processes uploads.
 *
 *  Per-machine, not a shared setting — settings.json lives on the share and
 *  every machine reads it. Takes effect on the next restart here, because
 *  the worker starts from the server's lifespan hook; the server says so in
 *  `message` and the UI shows that sentence rather than inventing one. */
export async function adminSetMachineIngest(
  enabled: boolean,
): Promise<{ ingest_enabled_here: boolean; message: string }> {
  const r = await fetch("/api/admin/machine/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) await fail(r, "ingest switch");
  return r.json();
}

export interface Snapshot {
  name: string;
  created_at: string | null;
  bytes: number;
}

export async function adminBackups(): Promise<{ snapshots: Snapshot[] }> {
  const r = await fetch("/api/admin/backups");
  if (!r.ok) await fail(r, "backups");
  return r.json();
}

export async function restoreBackup(
  name: string,
): Promise<{ restored: string; restart_required: boolean }> {
  const r = await fetch(`/api/admin/backups/${encodeURIComponent(name)}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // The literal string is the guard: a mis-click, a double-submit or a stale
    // tab replaying a request cannot produce it.
    body: JSON.stringify({ confirm: "restore" }),
  });
  if (!r.ok) await fail(r, "restore");
  return r.json();
}

export interface Notice {
  at: string;
  kind: string;
  message: string;
}

export async function adminNotices(since?: string): Promise<{ notices: Notice[] }> {
  const r = await fetch(`/api/admin/notices${since ? `?since=${encodeURIComponent(since)}` : ""}`);
  if (!r.ok) await fail(r, "notices");
  return r.json();
}

// ---------------------------------------------------------------------------
// Health ladder + repair (Plan 5 Task 12, spec S18)
// ---------------------------------------------------------------------------

export interface HealthRung {
  name: "server" | "machine_config" | "share" | "corpus" | "models";
  /** null means "not checked" — the ladder short-circuits after the first
   *  failure so an admin isn't sent chasing a second, phantom problem. */
  ok: boolean | null;
  detail: string;
  fix: string | null;
}

export interface HealthReport {
  ok: boolean;
  rungs: HealthRung[];
  data_dir: string | null;
  /** True exactly when the SHARE rung is the first failure — the only case
   *  where "point me at a different folder" can possibly help. */
  can_repair: boolean;
}

export async function healthDetail(): Promise<HealthReport> {
  const r = await fetch("/api/health/detail");
  if (!r.ok) await fail(r, "health check");
  return r.json();
}

export async function setDataDir(
  path: string,
): Promise<{ path: string; restart_required: boolean }> {
  const r = await fetch("/api/config/data-dir", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) await fail(r, "set data folder");
  return r.json();
}

// ---------------------------------------------------------------------------
// Chat history (spec 2026-08-02, H1/H4) — per-device, never on the share.
// ---------------------------------------------------------------------------

export interface HistoryRow {
  id: string;
  title: string;
  corpus: "budget" | "fiscal_notes";
  created_at: string;
  updated_at: string;
  title_is_manual: boolean;
  message_count: number;
  /** Present only on search results. */
  snippet?: string;
}

export async function listHistory(): Promise<{ conversations: HistoryRow[] }> {
  const r = await fetch("/api/history");
  if (!r.ok) await fail(r, "load chat history");
  return r.json();
}

export async function searchHistory(q: string): Promise<{ results: HistoryRow[] }> {
  const r = await fetch(`/api/history/search?q=${encodeURIComponent(q)}`);
  if (!r.ok) await fail(r, "search chat history");
  return r.json();
}

export async function getHistoryChat(id: string): Promise<HistoryRow & { messages: unknown[] }> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`);
  if (!r.ok) await fail(r, "open chat");
  return r.json();
}

export async function renameHistoryChat(id: string, title: string): Promise<HistoryRow> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) await fail(r, "rename chat");
  return r.json();
}

export async function deleteHistoryChat(id: string): Promise<{ deleted: string }> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok) await fail(r, "delete chat");
  return r.json();
}
