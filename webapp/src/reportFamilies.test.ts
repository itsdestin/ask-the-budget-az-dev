import { familyOf, slugsForFamily } from "./reportFamilies";

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
