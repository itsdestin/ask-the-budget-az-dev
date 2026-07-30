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
