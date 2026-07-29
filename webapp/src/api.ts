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
  if (!r.ok) throw new Error(`search failed: ${r.status}`);
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
  if (!r.ok) throw new Error(`fiscal-notes failed: ${r.status}`);
  return r.json();
}
