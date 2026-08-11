import type { SearchResult } from "../api";
import { groupPassages, highlight, queryTerms, toSearchFilters } from "./contentSearch";
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

test("every typed word marks independently, not the whole query as one string", () => {
  // The shipped behaviour searched for the entire query as one literal
  // substring. Measured: 0 of 200 real cards produced a single mark.
  const runs = highlight("Child care subsidy waiting list rose", "child care waiting");
  expect(runs.filter((r) => r.hit).map((r) => r.text)).toEqual(["Child", "care", "waiting"]);
});

test("marks are case-insensitive but keep the ORIGINAL casing", () => {
  expect(highlight("AHCCCS funding", "ahcccs")).toEqual([
    { text: "AHCCCS", hit: true },
    { text: " funding", hit: false },
  ]);
});

test("matching is on WORD BOUNDARIES, not substrings", () => {
  // Substring matching measured 8.3 marks per card peaking at 31, because
  // short words match inside longer ones. Boundaries: 6.0, capped at 14.
  expect(highlight("He said the aid was paid", "aid").filter((r) => r.hit))
    .toEqual([{ text: "aid", hit: true }]);
});

test("three-letter domain terms are NOT dropped", () => {
  // A length>=4 rule was measured and rejected: it silently loses "aid"
  // (basic state aid) and "des", the terms this domain is about (spec H1).
  expect(highlight("DES basic state aid", "des aid").filter((r) => r.hit).length).toBe(2);
});

test("no stopword list — function words mark like any other word", () => {
  // Four rules were measured and all four leave the blank rate at 2.9%, so
  // dropping function words is cosmetic. "We underline the words you typed."
  expect(highlight("the fund for schools", "the for").filter((r) => r.hit).map((r) => r.text))
    .toEqual(["the", "for"]);
});

test("a possessive contributes its stem, not a stray one-letter term", () => {
  expect(queryTerms("the state's share")).toEqual(
    expect.arrayContaining(["state", "share", "the"]),
  );
  expect(queryTerms("the state's share")).not.toContain("s");
});

test("longer terms win over shorter ones that start inside them", () => {
  const runs = highlight("childcare and child care", "child childcare");
  expect(runs.filter((r) => r.hit).map((r) => r.text)).toEqual(["childcare", "child"]);
});

test("regex metacharacters in the query are literal, not patterns", () => {
  expect(highlight("a (b) c", "(b)").filter((r) => r.hit).map((r) => r.text)).toEqual(["b"]);
});

test("no match, or an empty query, returns one plain run", () => {
  expect(highlight("nothing here", "zzz")).toEqual([{ text: "nothing here", hit: false }]);
  expect(highlight("nothing here", "   ")).toEqual([{ text: "nothing here", hit: false }]);
});
