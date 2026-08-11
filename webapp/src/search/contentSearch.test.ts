import type { SearchResult } from "../api";
import { groupPassages, highlight, toSearchFilters } from "./contentSearch";
import { slugsForFamily } from "../reportFamilies";

function hit(over: Partial<SearchResult>): SearchResult {
  return {
    chunk_id: "c1", doc_id: "d1", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "text", page: 1, score: 1, doc_type: "baseline-per-agency",
    fiscal_year: 2027, publisher: "jlbc", agencies: [], doc_url: null,
    doc_meta: null, text: "text", ...over,
  };
}

test("a family maps to every doc_type slug that belongs to it", () => {
  expect(slugsForFamily("Baseline").sort())
    .toEqual(["baseline-cross-cut", "baseline-per-agency"]);
  expect(slugsForFamily("Annual Financial Report")).toEqual(["afr"]);
});

test("an unknown family maps to itself — familyOf's own contract", () => {
  // familyOf returns the raw slug for an unrecognised doc_type, so that slug
  // IS the family name and filtering on it must still reach the backend.
  expect(slugsForFamily("some-new-doc-type")).toEqual(["some-new-doc-type"]);
});

test("rail filters become backend filters, expanding families to slugs", () => {
  expect(toSearchFilters(new Set(["Baseline"]), new Set([2027]))).toEqual({
    doc_type: ["baseline-per-agency", "baseline-cross-cut"],
    fiscal_year: [2027],
  });
});

test("no filters means an empty object, never empty arrays", () => {
  // The backend treats an explicit [] as a filter that matches nothing; only
  // an absent key means "any".
  expect(toSearchFilters(new Set(), new Set())).toEqual({});
});

test("the 'fiscal year unknown' bucket is never sent as a real year", () => {
  // Year 0 is this page's own bucket for documents with no fiscal_year. The
  // backend has no such value; sending it would filter everything out.
  expect(toSearchFilters(new Set(), new Set([0]))).toEqual({});
  expect(toSearchFilters(new Set(), new Set([0, 2027]))).toEqual({ fiscal_year: [2027] });
});

test("passages collapse to one entry per document, best passage first", () => {
  const groups = groupPassages([
    hit({ chunk_id: "a", doc_id: "d1", score: 0.2 }),
    hit({ chunk_id: "b", doc_id: "d2", score: 0.9, doc_title: "Other" }),
    hit({ chunk_id: "c", doc_id: "d1", score: 0.7 }),
  ]);
  expect(groups.map((g) => g.doc_id)).toEqual(["d2", "d1"]);
  expect(groups[1].passages.map((p) => p.chunk_id)).toEqual(["c", "a"]);
});

test("one document never yields two cards", () => {
  const groups = groupPassages([
    hit({ chunk_id: "a", doc_id: "d1" }),
    hit({ chunk_id: "b", doc_id: "d1" }),
    hit({ chunk_id: "c", doc_id: "d1" }),
  ]);
  expect(groups).toHaveLength(1);
  expect(groups[0].passages).toHaveLength(3);
});

test("highlight splits a snippet into matched and unmatched runs", () => {
  expect(highlight("The child care subsidy rose", "child care")).toEqual([
    { text: "The ", hit: false },
    { text: "child care", hit: true },
    { text: " subsidy rose", hit: false },
  ]);
});

test("highlight is case-insensitive but preserves the ORIGINAL casing", () => {
  expect(highlight("AHCCCS funding", "ahcccs")).toEqual([
    { text: "AHCCCS", hit: true },
    { text: " funding", hit: false },
  ]);
});

test("highlight with no match, or an empty query, returns one plain run", () => {
  expect(highlight("nothing here", "zzz")).toEqual([{ text: "nothing here", hit: false }]);
  expect(highlight("nothing here", "   ")).toEqual([{ text: "nothing here", hit: false }]);
});
