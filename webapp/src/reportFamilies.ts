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
  // Final-review Finding 2: these two doc_types were added to
  // data/document-types.yaml (Task 6) but never given a family here, so the
  // first Agency Submission or Budget Bill Summary ingested would have grown
  // a family heading and a filter chip reading literally "agency-submission"
  // — the exact "documents under raw machine slugs" defect this project
  // already fixed once (STATUS.md, 647 → 0). Labels match the registry's own
  // `label` field for each row (data/document-types.yaml).
  "agency-submission": "Agency Submission",
  "budget-bill-summary": "Budget Bill Summary",
};

/** The family name for a document.
 *
 *  `sectionOf` wins when present: five doc_types (`s-pdf`, `bd-pdf`,
 *  `bh-pdf`, `detailed-list-pdf`, `topic-pdf`) are not document types at all
 *  but JLBC's own printed page-number prefixes, so which book they belong to
 *  cannot be read off the doc_type — `detailed-list-pdf` splits 255
 *  Appropriations Report / 45 Baseline. The server derives it from the
 *  document's source URL (app/book_sections.py) so there is one
 *  implementation, not one per language.
 *
 *  Otherwise unknown slugs become their own family under the raw slug —
 *  honest (nothing invented) and future-proof (a new doc_type still groups,
 *  it just isn't prettified until someone names it here). */
export function familyOf(docType: string, sectionOf?: string | null): string {
  return sectionOf ?? FAMILY_OF_DOC_TYPE[docType] ?? docType;
}

/** The doc_type slugs that are book SECTIONS, derived from the corpus itself.
 *
 *  WHY derived and not written down: `app/book_sections.py` already owns that
 *  vocabulary (`SECTION_DOC_TYPES`), and a second hand-maintained copy here
 *  would silently stop matching the day a sixth section type is ingested. A
 *  document the server marked with `section_of` HAS a section doc_type, by
 *  definition — so the listing already answers the question. */
export function sectionSlugsFrom(
  docs: readonly { doc_type: string; section_of: string | null }[],
): string[] {
  return [...new Set(docs.filter((d) => d.section_of).map((d) => d.doc_type))];
}

/** Every doc_type slug that belongs to a family — the inverse of `familyOf`.
 *
 *  Derived from FAMILY_OF_DOC_TYPE rather than written out a second time: two
 *  hand-maintained lists of the same slugs is exactly how a filter silently
 *  stops matching a doc_type someone added to only one of them.
 *
 *  A family with no curated slugs maps to ITSELF, because `familyOf` returns
 *  the raw slug for an unrecognised doc_type — so for those, the family name
 *  and the slug are the same string.
 *
 *  `sectionSlugs` (from `sectionSlugsFrom`) joins the two BOOK families:
 *  `detailed-list-pdf` and `topic-pdf` genuinely occur under both, and the
 *  server's `section_family` filter is what makes the result exact. */
export function slugsForFamily(family: string, sectionSlugs: readonly string[] = []): string[] {
  const slugs = Object.entries(FAMILY_OF_DOC_TYPE)
    .filter(([, name]) => name === family)
    .map(([slug]) => slug);
  if (family === "Baseline" || family === "Appropriations Report") {
    return [...slugs, ...sectionSlugs];
  }
  return slugs.length ? slugs : [family];
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
 *  VERIFIED BY DOWNLOAD, not by title match. Every URL below was fetched and
 *  its first pages READ (2026-08-16): the trailing comment on each row is that
 *  file's real page count and size, and the three FY2017–2019 Baseline single
 *  files carry no text layer at all, so their cover pages were rendered to
 *  images and read by eye. A wrong PDF behind a button labelled "Full report"
 *  is a false provenance claim (Invariant 1), and the two cheaper sources both
 *  fail in ways only a download exposes:
 *
 *  - The vendored site index (webapp/reference/assets/search/index-lite.js)
 *    files SLIDESHOWS and single sections under the bare report title —
 *    "FY 2021 Appropriations Report" is also `21H-Sfullappropspres.pdf`, and
 *    "FY 2014 Appropriations Report" is also `14AR/384.pdf`. Title matching
 *    alone would have put a presentation behind six of these buttons.
 *  - `data/jlbc-book-catalog.json` (the ingest side's edition catalog) is
 *    clean but is built for a probe ladder that TOLERATES a 404, so it carries
 *    unverified URLs: its FY2027 Baseline `linked_toc_url` is a different path
 *    from the one shipped here, and `budget/fy2027approprpt.pdf` — the shape
 *    its convention implies — is a 404. The real FY2027 Appropriations Report
 *    is `27ar/...`, and it is in NO committed catalog, because that edition
 *    was published after the 2026-06-16 harvest snapshot.
 *
 *  So this list stays hand-owned rather than derived from either. Re-check it
 *  with `uv run python scripts/verify_report_formats.py`, and extend it the
 *  same way — download the candidate and look at it — when a new edition is
 *  ingested. `reportFamilies.test.ts` holds the offline half of that guard.
 *
 *  Two shapes worth knowing before editing:
 *
 *  - Approps FY2005–FY2010 have a linked TOC and NO single file; JLBC did not
 *    publish one until FY2011 (`both_formats_from` in the book catalog agrees).
 *    One format means the row links straight to it with no chooser, which is
 *    the intended behaviour, not a gap to fill with a guess.
 *  - `Baseline:2014`'s single file is 229 MB — roughly five times its
 *    siblings. It is the right document (cover reads "FY 2014 Baseline Book,
 *    January 2013"); JLBC simply published that one un-optimised.
 *
 *  Years absent here get no button, which is the honest state: a family whose
 *  documents are all sections of a book has nothing safe to fall back to.
 *
 *  Exported ONLY so reportFamilies.test.ts can walk every row. Nothing else
 *  may read it — `reportFormats()` below is the lookup, and it is what applies
 *  the null-year rule. */
export const REPORT_FORMATS: Record<string, ReportFormats> = {
  // ---- Baseline ----
  "Baseline:2027": { singleFile: "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/budget/27baselinelinks.pdf" }, // 620pp/48.0MB, toc 1pp
  "Baseline:2026": { singleFile: "https://www.azjlbc.gov/26baseline/26baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/26baseline/26baselinelinks.pdf" }, // 572pp/43.8MB, toc 1pp
  "Baseline:2025": { singleFile: "https://www.azjlbc.gov/25Baseline/25baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/25Baseline/25baselinelinks.pdf" }, // 600pp/45.4MB, toc 1pp
  "Baseline:2024": { singleFile: "https://www.azjlbc.gov/24baseline/24baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/budget/24baselinelinks.pdf" }, // 591pp/41.2MB, toc 1pp
  "Baseline:2023": { singleFile: "https://www.azjlbc.gov/23baseline/23baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/budget/23baselinelinks.pdf" }, // 547pp/37.6MB, toc 1pp
  "Baseline:2022": { singleFile: "https://www.azjlbc.gov/22baseline/22baselinesinglefile.pdf", linkedToc: "https://www.azjlbc.gov/22baseline/22baselinelinks.pdf" }, // 623pp/49.2MB, toc 2pp
  "Baseline:2021": { singleFile: "https://www.azjlbc.gov/21baseline/21BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/21baseline/21BaselineLinks.pdf" }, // 584pp/45.2MB, toc 2pp
  "Baseline:2020": { singleFile: "https://www.azjlbc.gov/20baseline/20BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/20baseline/20BaselineLinks.pdf" }, // 612pp/46.4MB, toc 2pp
  "Baseline:2019": { singleFile: "https://www.azjlbc.gov/19baseline/19BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/19baseline/19BaselineLinks.pdf" }, // 617pp/42.3MB, toc 2pp
  "Baseline:2018": { singleFile: "https://www.azjlbc.gov/18baseline/18BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/18baseline/18BaselineLinks.pdf" }, // 624pp/43.4MB, toc 2pp
  "Baseline:2017": { singleFile: "https://www.azjlbc.gov/17baseline/17BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/17baseline/17BaselineLinks.pdf" }, // 630pp/43.7MB, toc 2pp
  "Baseline:2016": { singleFile: "https://www.azjlbc.gov/16baseline/16BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/16baseline/16BaselineLinks.pdf" }, // 547pp/34.5MB, toc 2pp
  "Baseline:2015": { singleFile: "https://www.azjlbc.gov/15baseline/15BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/15baseline/15BaselineLinks.pdf" }, // 509pp/38.4MB, toc 2pp
  "Baseline:2014": { singleFile: "https://www.azjlbc.gov/14baseline/14BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/14baseline/14BaselineLinks.pdf" }, // 508pp/229.4MB, toc 3pp
  "Baseline:2013": { singleFile: "https://www.azjlbc.gov/13baseline/13BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/13baseline/13BaselineLinks.pdf" }, // 466pp/3.7MB, toc 3pp
  "Baseline:2012": { singleFile: "https://www.azjlbc.gov/12book1/12BaselineSingleFile.pdf", linkedToc: "https://www.azjlbc.gov/12book1/12BaselineLinks.pdf" }, // 453pp/3.3MB, toc 3pp

  // ---- Appropriations Report ----
  "Appropriations Report:2027": { singleFile: "https://www.azjlbc.gov/27ar/fy2027approprpt.pdf", linkedToc: "https://www.azjlbc.gov/27ar/apprpttoc.pdf" }, // 550pp/43.9MB, toc 1pp
  "Appropriations Report:2026": { singleFile: "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf", linkedToc: "https://www.azjlbc.gov/26ar/apprpttoc.pdf" }, // 569pp/48.0MB, toc 1pp
  "Appropriations Report:2025": { singleFile: "https://www.azjlbc.gov/25ar/fy2025approprpt.pdf", linkedToc: "https://www.azjlbc.gov/25ar/apprpttoc.pdf" }, // 573pp/47.0MB, toc 1pp
  "Appropriations Report:2024": { singleFile: "https://www.azjlbc.gov/24ar/fy2024approprpt.pdf", linkedToc: "https://www.azjlbc.gov/24ar/apprpttoc.pdf" }, // 585pp/44.9MB, toc 1pp
  "Appropriations Report:2023": { singleFile: "https://www.azjlbc.gov/budget/fy2023approprpt.pdf", linkedToc: "https://www.azjlbc.gov/budget/apprpttoc.pdf" }, // 586pp/47.8MB, toc 1pp
  "Appropriations Report:2022": { singleFile: "https://www.azjlbc.gov/22ar/fy2022approprpt.pdf", linkedToc: "https://www.azjlbc.gov/22ar/apprpttoc.pdf" }, // 646pp/51.0MB, toc 1pp
  "Appropriations Report:2021": { singleFile: "https://www.azjlbc.gov/21AR/FY2021AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/21AR/apprpttoc.pdf" }, // 508pp/38.5MB, toc 1pp
  "Appropriations Report:2020": { singleFile: "https://www.azjlbc.gov/20AR/FY2020AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/20AR/apprpttoc.pdf" }, // 580pp/30.9MB, toc 1pp
  "Appropriations Report:2019": { singleFile: "https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/19AR/apprpttoc.pdf" }, // 566pp/29.3MB, toc 1pp
  "Appropriations Report:2018": { singleFile: "https://www.azjlbc.gov/18AR/FY2018AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/18AR/apprpttoc.pdf" }, // 570pp/30.6MB, toc 1pp
  "Appropriations Report:2017": { singleFile: "https://www.azjlbc.gov/17AR/FY2017AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/17AR/apprpttoc.pdf" }, // 606pp/33.2MB, toc 1pp
  "Appropriations Report:2016": { singleFile: "https://www.azjlbc.gov/16AR/FY2016AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/16AR/apprpttoc.pdf" }, // 531pp/27.5MB, toc 1pp
  "Appropriations Report:2015": { singleFile: "https://www.azjlbc.gov/15AR/FY2015AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/15AR/apprpttoc.pdf" }, // 470pp/27.9MB, toc 1pp
  "Appropriations Report:2014": { singleFile: "https://www.azjlbc.gov/14AR/FY2014AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/14AR/apprpttoc.pdf" }, // 448pp/36.3MB, toc 1pp
  "Appropriations Report:2013": { singleFile: "https://www.azjlbc.gov/13AR/FY2013AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/13AR/apprpttoc.pdf" }, // 414pp/3.9MB, toc 1pp
  "Appropriations Report:2012": { singleFile: "https://www.azjlbc.gov/12app/FY2012AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/12app/apprpttoc.pdf" }, // 416pp/3.5MB, toc 1pp
  "Appropriations Report:2011": { singleFile: "https://www.azjlbc.gov/11app/FY2011AppropRpt.pdf", linkedToc: "https://www.azjlbc.gov/11app/apprpttoc.pdf" }, // 528pp/4.3MB, toc 1pp
  "Appropriations Report:2010": { singleFile: null, linkedToc: "https://www.azjlbc.gov/10app/apprpttoc.pdf" }, // toc 4pp
  "Appropriations Report:2009": { singleFile: null, linkedToc: "https://www.azjlbc.gov/09app/apprpttoc.pdf" }, // toc 4pp
  "Appropriations Report:2008": { singleFile: null, linkedToc: "https://www.azjlbc.gov/08app/apprpttoc.pdf" }, // toc 4pp
  "Appropriations Report:2007": { singleFile: null, linkedToc: "https://www.azjlbc.gov/07app/apprpttoc.pdf" }, // toc 4pp
  "Appropriations Report:2006": { singleFile: null, linkedToc: "https://www.azjlbc.gov/06app/apprpttoc.pdf" }, // toc 1pp
  "Appropriations Report:2005": { singleFile: null, linkedToc: "https://www.azjlbc.gov/05app/apprpttoc.pdf" }, // toc 1pp
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
