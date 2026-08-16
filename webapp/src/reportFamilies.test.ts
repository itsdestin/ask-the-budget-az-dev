import { familyOf, REPORT_FORMATS, slugsForFamily } from "./reportFamilies";

// Final-review Finding 2: FAMILY_OF_DOC_TYPE had no entry for either doc_type
// Task 6 added to the registry (data/document-types.yaml), so a document of
// either type would render under its raw machine slug — the exact defect
// STATUS.md records as fixed ("documents under raw machine slugs: 647 → 0").
// These pin the two new entries directly, so a future doc_type addition that
// repeats the omission fails here instead of surfacing as an ugly heading.

test("agency-submission documents group under a human family name, not the raw slug", () => {
  expect(familyOf("agency-submission")).toBe("Agency Submission");
});

test("budget-bill-summary documents group under a human family name, not the raw slug", () => {
  expect(familyOf("budget-bill-summary")).toBe("Budget Bill Summary");
});

// slugsForFamily is familyOf's inverse (used to build filter chips) — pin
// that both new families round-trip, so a filter chip for either family
// actually matches its own documents.
test("both new families round-trip through slugsForFamily", () => {
  expect(slugsForFamily("Agency Submission")).toEqual(["agency-submission"]);
  expect(slugsForFamily("Budget Bill Summary")).toEqual(["budget-bill-summary"]);
});

// ---------------------------------------------------------------------------
// REPORT_FORMATS guards (2026-08-16, when the map went from 3 editions to 39).
//
// These are the checks that can run OFFLINE. Reachability is a separate,
// network-bound concern and lives in `scripts/verify_report_formats.py`; what
// is guarded here is the class of mistake that a green download check would
// happily wave through — a URL that resolves fine and is the WRONG YEAR.
// ---------------------------------------------------------------------------

const CURATED = Object.entries(REPORT_FORMATS);

test("every curated key is a known family and a four-digit year", () => {
  // A typo'd family ("Appropriations report:2019") never matches anything, and
  // the symptom is a button that silently does not appear — indistinguishable
  // from a year nobody has curated yet.
  for (const [key] of CURATED) {
    const idx = key.lastIndexOf(":");
    const family = key.slice(0, idx);
    const year = key.slice(idx + 1);
    expect(familyOf(`__unmapped_${family}`)).toBe(`__unmapped_${family}`); // sanity: familyOf is total
    expect(["Baseline", "Appropriations Report"]).toContain(family);
    expect(year).toMatch(/^\d{4}$/);
  }
});

// JLBC's own filenames carry the fiscal year — "19AR/FY2019AppropRpt.pdf",
// "26baseline/26baselinesinglefile.pdf" — with exactly one exception, so the
// year is checkable without a network call. This is the guard that matters:
// copying the row above and forgetting to bump the URL produces a live,
// downloadable, WRONG report behind a button labelled "Full report", which is
// a false provenance claim (Invariant 1) and the one failure mode a 200 OK
// cannot detect.
const YEARLESS_BY_DESIGN = new Set([
  // JLBC published the FY2023 Appropriations Report out of the undated
  // `/budget/` directory rather than a `23ar/` one, so its table of contents
  // has no year in its path. Verified by download 2026-08-16: this URL serves
  // "FY 2023 APPROPRIATIONS REPORT". If a SECOND entry ever needs listing
  // here, stop and re-read the rule instead of adding it — two exemptions is
  // the signal that the check is measuring the wrong thing.
  "https://www.azjlbc.gov/budget/apprpttoc.pdf",
]);

test("every curated URL names its own fiscal year", () => {
  for (const [key, formats] of CURATED) {
    const year = Number(key.slice(key.lastIndexOf(":") + 1));
    const short = String(year).slice(2); // 2019 -> "19"
    for (const url of [formats.singleFile, formats.linkedToc]) {
      if (url === null || YEARLESS_BY_DESIGN.has(url)) continue;
      const path = url.toLowerCase().replace("https://www.azjlbc.gov/", "");
      expect(
        path.includes(short) || path.includes(String(year)),
        `${key} points at ${url}, which does not mention FY ${year}`,
      ).toBe(true);
    }
  }
});

test("every curated URL is a JLBC PDF", () => {
  // Every one of these is a JLBC publication. A URL on any other host is
  // either a mistake or a decision that deserves its own discussion — the
  // AFR's publisher (gao.az.gov) sits behind bot protection and its documents
  // reach this app by upload, not by link.
  for (const [key, formats] of CURATED) {
    for (const url of [formats.singleFile, formats.linkedToc]) {
      if (url === null) continue;
      expect(url, key).toMatch(/^https:\/\/www\.azjlbc\.gov\/\S+\.pdf$/);
    }
  }
});

test("a curated edition offers at least one format", () => {
  // `{ singleFile: null, linkedToc: null }` is indistinguishable from having
  // no entry at all, so a row like that is dead weight that reads as coverage.
  for (const [key, formats] of CURATED) {
    expect(formats.singleFile ?? formats.linkedToc, key).not.toBeNull();
  }
});
