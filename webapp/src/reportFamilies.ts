// Report families — the vocabulary that turns raw doc_type slugs into the
// reports an analyst actually thinks in.
//
// A JLBC annual report (a Baseline book, an Appropriations Report) is ingested
// as MANY documents: one per agency plus cross-cut summary sections. The
// mockup's search engine collapsed those into one logical report per year for
// grouping and filtering (webapp/reference/assets/search/search.js — familyOf /
// bucketOf), and Destin asked for the same grouping here: results grouped by
// fiscal year + document type, with a button to the full single-file PDF.
//
// Slugs verified against data/ingest-plan.yaml's `doc_type:` values (the live
// vocabulary — NOT db/migrations/0001_initial_schema.sql's enum comment, which
// is stale; see the note in FilterBar.tsx).

/** doc_type slug → the display name of the report family it belongs to. */
const FAMILY_OF_DOC_TYPE: Record<string, string> = {
  "baseline-per-agency": "Baseline",
  "baseline-cross-cut": "Baseline",
  "approps-per-agency": "Appropriations Report",
  "approps-cross-cut": "Appropriations Report",
  afr: "Annual Financial Report",
  "governors-budget": "Executive Budget",
  "budget-bill": "Budget Bill",
};

/** The family name for a doc_type. Unknown slugs become their own family under
 *  the raw slug — honest (nothing invented) and future-proof (a new doc_type
 *  still groups, it just isn't prettified until someone names it here). */
export function familyOf(docType: string): string {
  return FAMILY_OF_DOC_TYPE[docType] ?? docType;
}

/** "FY 2027 Baseline" — or just the family name when the year is unknown. */
export function familyTitle(family: string, fiscalYear: number | null): string {
  return fiscalYear === null ? family : `FY ${fiscalYear} ${family}`;
}

/** Curated map: family + fiscal year → the report's full single-file PDF.
 *
 *  HAND-VERIFIED, exact-match only: each URL was looked up by title in the
 *  vendored site index (webapp/reference/assets/search/index-lite.js — entries
 *  "FY 2027 Baseline Book (Single File PDF)", "FY 2026 Baseline Book (Single
 *  File)", "FY 2025 Appropriations Report"). No fuzzy matching: a wrong PDF
 *  behind an "open the report" button would violate the repo's auditability
 *  invariants, so families without a verified URL simply get no button.
 *  Extend this map (and hand-verify) when new report years are ingested. */
const FULL_PDF_URLS: Record<string, string> = {
  "Baseline:2027": "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
  "Baseline:2026": "https://www.azjlbc.gov/26baseline/26baselinesinglefile.pdf",
  "Appropriations Report:2025": "https://www.azjlbc.gov/25ar/fy2025approprpt.pdf",
};

export function fullPdfUrl(family: string, fiscalYear: number | null): string | null {
  if (fiscalYear === null) return null;
  return FULL_PDF_URLS[`${family}:${fiscalYear}`] ?? null;
}

/** The curated filter buckets shown as chips on the search page — the mockup's
 *  approach (a FIXED, always-visible set; search.js's BUCKET_ORDER) rather than
 *  chips derived from whatever the last search returned. Each bucket toggles
 *  its whole slug list through the API's doc_type[] filter. */
export const FILTER_BUCKETS: { label: string; slugs: string[] }[] = [
  { label: "Baseline Books", slugs: ["baseline-per-agency", "baseline-cross-cut"] },
  { label: "Appropriations Reports", slugs: ["approps-per-agency", "approps-cross-cut"] },
  { label: "Annual Financial Reports", slugs: ["afr"] },
  { label: "Executive Budget", slugs: ["governors-budget"] },
  { label: "Budget Bills", slugs: ["budget-bill"] },
];
