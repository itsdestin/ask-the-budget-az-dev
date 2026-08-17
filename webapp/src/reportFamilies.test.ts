import { familyOf, reportFormats, slugsForFamily } from "./reportFamilies";

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
// The lookup, which is all this module still owns (2026-08-16, spec R1).
//
// The URL TABLE moved to the server — `data/report-formats.json` merged with
// the admin's approvals on the share — because adding a fiscal year used to
// mean editing this file and rebuilding the app, a step a non-developer
// successor cannot perform for a list that gains two rows a year forever.
// The four guards that used to walk every curated row here (key shape, "the
// URL names its own fiscal year", "the URL is a JLBC PDF", "an edition offers
// at least one format") went WITH the data: they now live in
// `tests/test_report_formats_data.py`, against the JSON they guard. Guarding a
// fixture defined three lines above the assertion would prove nothing.
// ---------------------------------------------------------------------------

const TABLE = {
  "Baseline:2027": { single_file: "https://x/b27.pdf", linked_toc: "https://x/b27toc.pdf" },
  "Appropriations Report:2005": { single_file: null, linked_toc: "https://x/ar05toc.pdf" },
};

test("an edition in the table resolves both of its formats", () => {
  expect(reportFormats("Baseline", 2027, TABLE)).toEqual({
    singleFile: "https://x/b27.pdf",
    linkedToc: "https://x/b27toc.pdf",
  });
});

test("an edition the table does not answer resolves to neither format", () => {
  // This is what "no button" looks like, and it must stay distinct from an
  // edition that answers with one format.
  expect(reportFormats("Baseline", 2099, TABLE)).toEqual({ singleFile: null, linkedToc: null });
});

test("a null format survives as null rather than becoming undefined", () => {
  // ReportRow branches on `singleFile && linkedToc`; an undefined here reads
  // the same as null today and would stop doing so the moment anything checks
  // for the key's presence.
  expect(reportFormats("Appropriations Report", 2005, TABLE)).toEqual({
    singleFile: null,
    linkedToc: "https://x/ar05toc.pdf",
  });
});

test("an unknown fiscal year resolves to neither format", () => {
  expect(reportFormats("Baseline", null, TABLE)).toEqual({ singleFile: null, linkedToc: null });
});
