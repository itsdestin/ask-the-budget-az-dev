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
