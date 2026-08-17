import { familyOf, reportFormats, slugsForFamily } from "./reportFamilies";
import type { ReportFormatTable } from "./reportFamilies";

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
  // A row with `single_file` MISSING entirely, not set to null — the shape a
  // hand-edited overlay row on the shared drive can genuinely produce (an
  // admin filling in only the URL they have). This is deliberately distinct
  // from "Appropriations Report:2005" above, whose `single_file` is an
  // explicit `null`: `null ?? null` is `null` either way, so that fixture
  // cannot tell `row.single_file ?? null` apart from plain `row.single_file`
  // — both read `null` for it. Only a genuinely ABSENT key makes the two
  // diverge (`undefined` vs `null`), which is what
  // "a null format survives as null rather than becoming undefined" below
  // actually needs to catch its own mutation. Cast is the reviewer's
  // suggested shape: real overlay JSON has no type system to keep it honest.
  "Executive Budget:2010": { linked_toc: "https://x/eb10toc.pdf" } as unknown as {
    single_file: string | null;
    linked_toc: string | null;
  },
  // Reachable ONLY if the `fiscalYear === null` early return in reportFormats
  // is ever removed — the function returns before it ever builds this key, so
  // a real (wrong) answer sitting here is what makes the guard observable.
  // Without this row, `table["Baseline:null"]` is `undefined` regardless of
  // the guard, and the test below would pass whether or not the guard exists.
  "Baseline:null": {
    single_file: "https://x/should-never-resolve.pdf",
    linked_toc: "https://x/should-never-resolve-toc.pdf",
  },
} satisfies ReportFormatTable;

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

test("an explicit null format survives as null", () => {
  // ReportRow branches on `singleFile && linkedToc`; an undefined here reads
  // the same as null today and would stop doing so the moment anything checks
  // for the key's presence. This fixture's `single_file` is an explicit
  // `null`, which the `?? null` guard cannot be told apart from — see the
  // next test for the fixture that actually exercises the guard.
  expect(reportFormats("Appropriations Report", 2005, TABLE)).toEqual({
    singleFile: null,
    linkedToc: "https://x/ar05toc.pdf",
  });
});

test("a MISSING format key resolves to null rather than undefined", () => {
  // Verified by mutation: replacing `row.single_file ?? null` with plain
  // `row.single_file` turns this red (`singleFile` comes back `undefined`)
  // while leaving the test above green — that is why this fixture's
  // `single_file` key is absent rather than set to `null`.
  expect(reportFormats("Executive Budget", 2010, TABLE)).toEqual({
    singleFile: null,
    linkedToc: "https://x/eb10toc.pdf",
  });
});

test("an unknown fiscal year resolves to neither format, even when the table answers for the literal string 'null'", () => {
  // TABLE deliberately carries a row keyed "Baseline:null" with real (wrong)
  // URLs. Without it, `table["Baseline:null"]` is `undefined` regardless of
  // whether the `fiscalYear === null` early return exists, and this test
  // cannot tell the two cases apart — verified by mutation: deleting
  // `if (fiscalYear === null) return NO_FORMATS;` turns this red only because
  // that row is populated.
  expect(reportFormats("Baseline", null, TABLE)).toEqual({ singleFile: null, linkedToc: null });
});
