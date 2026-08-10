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
// was already stale and whose whole `db/` tree was deleted 2026-08-01).
// (This used to point at a longer note in components/FilterBar.tsx, deleted
// 2026-08-10 with the chip strip it drew.)

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

/** The two canonical ways JLBC publishes a whole annual report — the mockup's
 *  format-chooser pair (search.js reportFormats): a "linked Table of Contents"
 *  index page whose every agency/section opens its own smaller PDF, and the
 *  complete single-file PDF. */
export interface ReportFormats {
  singleFile: string | null;
  linkedToc: string | null;
}

/** Curated map: family + fiscal year → both whole-report format URLs.
 *
 *  HAND-VERIFIED, exact-match only: each URL was looked up by title in the
 *  vendored site index (webapp/reference/assets/search/index-lite.js —
 *  "FY 2027 Baseline Book (Single File PDF)" / "(Version with Individual
 *  Links)", "FY 2026 Baseline Book (Single File)" / "(with Links)",
 *  "FY 2025 Appropriations Report" / "(Table of Contents)"). No fuzzy
 *  matching: a wrong PDF behind an "open the report" button would violate the
 *  repo's auditability invariants, so families without verified URLs simply
 *  get no button. Extend (and hand-verify) when new report years are
 *  ingested. */
const REPORT_FORMATS: Record<string, ReportFormats> = {
  "Baseline:2027": {
    singleFile: "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
    linkedToc: "https://www.azjlbc.gov/budget/27baselinelinks.pdf",
  },
  "Baseline:2026": {
    singleFile: "https://www.azjlbc.gov/26baseline/26baselinesinglefile.pdf",
    linkedToc: "https://www.azjlbc.gov/26baseline/26baselinelinks.pdf",
  },
  "Appropriations Report:2025": {
    singleFile: "https://www.azjlbc.gov/25ar/fy2025approprpt.pdf",
    linkedToc: "https://www.azjlbc.gov/25ar/apprpttoc.pdf",
  },
};

const NO_FORMATS: ReportFormats = { singleFile: null, linkedToc: null };

export function reportFormats(family: string, fiscalYear: number | null): ReportFormats {
  if (fiscalYear === null) return NO_FORMATS;
  return REPORT_FORMATS[`${family}:${fiscalYear}`] ?? NO_FORMATS;
}

// FILTER_BUCKETS was here — the curated chip strip's doc_type buckets, read
// only by `components/FilterBar.tsx`. Both were deleted 2026-08-10: the browse
// page's rail builds its Document Type options from FAMILY_OF_DOC_TYPE's own
// family names (Search.tsx's `typeOptions`), so a second, parallel list of the
// same slugs was a place for the two to silently disagree. `git log --
// webapp/src/components/FilterBar.tsx` has both if the chip strip ever returns.
