import type { SearchResult } from "../api";
import { groupPassages, highlight, highlightTerms, previewWindow, queryTerms, toSearchFilters } from "./contentSearch";
import { sectionSlugsFrom, slugsForFamily } from "../reportFamilies";

function hit(over: Partial<SearchResult>): SearchResult {
  return {
    chunk_id: "c1", doc_id: "d1", doc_title: "FY 2027 Baseline — AHCCCS",
    snippet: "text", page: 1, score: 1, doc_type: "baseline-per-agency",
    fiscal_year: 2027, publisher: "jlbc", agencies: [], doc_url: null,
    doc_meta: null, text: "text", section_path: [], section_of: null, ...over,
  };
}

test("a family maps to every doc_type slug that belongs to it, plus section slugs for a BOOK family", () => {
  // Baseline and Appropriations Report also fold in whatever section slugs
  // are passed (Task 8) -- the corpus-derived list, never a second
  // hand-maintained copy of ingest/section_types.py's SECTION_DOC_TYPES.
  expect(slugsForFamily("Baseline", ["s-pdf", "detailed-list-pdf"]).sort())
    .toEqual(["baseline-cross-cut", "baseline-per-agency", "detailed-list-pdf", "s-pdf"]);
  // A non-book family ignores sectionSlugs even when some are passed -- only
  // Baseline/Appropriations Report have sections at all.
  expect(slugsForFamily("Annual Financial Report", ["s-pdf"])).toEqual(["afr"]);
});

test("an unknown family maps to itself — familyOf's own contract", () => {
  // familyOf returns the raw slug for an unrecognised doc_type, so that slug
  // IS the family name and filtering on it must still reach the backend.
  expect(slugsForFamily("some-new-doc-type")).toEqual(["some-new-doc-type"]);
});

test("rail filters become backend filters, expanding families to slugs", () => {
  // A single book family selected also sends `section_family` (Task 8), so
  // Task 7's exact post-rank filter can tell a Baseline section from an
  // Appropriations Report section sharing the same doc_type (detailed-list-pdf,
  // topic-pdf occur under both).
  expect(toSearchFilters(new Set(["Baseline"]), new Set([2027]))).toEqual({
    doc_type: ["baseline-per-agency", "baseline-cross-cut"],
    fiscal_year: [2027],
    section_family: "Baseline",
  });
});

test("section_family is omitted when both book families are selected -- nothing to exclude", () => {
  // sectionSlugs is deliberately NON-EMPTY here (derived through
  // sectionSlugsFrom, same as production, never hand-typed) so this test
  // proves two things at once: doc_type folds the section slugs into BOTH
  // book families, and section_family is genuinely absent -- not just that
  // an empty sectionSlugs list happened to look the same as the
  // pre-Task-8 two-argument toSearchFilters, which had no section_family
  // logic at all and would pass this test unchanged (Finding 1, 2026-08-11).
  const sectionSlugs = sectionSlugsFrom([
    { doc_type: "detailed-list-pdf", section_of: "Baseline" },
    { doc_type: "topic-pdf", section_of: "Appropriations Report" },
  ]);
  const filters = toSearchFilters(
    new Set(["Baseline", "Appropriations Report"]),
    new Set(),
    sectionSlugs,
  );
  expect(filters).toEqual({
    doc_type: [
      "baseline-per-agency",
      "baseline-cross-cut",
      "detailed-list-pdf",
      "topic-pdf",
      "approps-per-agency",
      "approps-cross-cut",
    ],
  });
  // Each book family would otherwise append the WHOLE sectionSlugs list, so
  // with two books selected detailed-list-pdf/topic-pdf would appear twice
  // (Finding 2, 2026-08-11).
  expect(new Set(filters.doc_type).size).toBe(filters.doc_type!.length);
});

test("section slugs come from the corpus, never from a hardcoded list", () => {
  const docs = [
    { doc_type: "s-pdf", section_of: "Baseline" },
    { doc_type: "brand-new-section-pdf", section_of: "Baseline" },
    { doc_type: "baseline-per-agency", section_of: null },
  ];
  // A section type nobody has written down anywhere still reaches the filter.
  expect(sectionSlugsFrom(docs).sort()).toEqual(["brand-new-section-pdf", "s-pdf"]);
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

test("highlightTerms filters out empty strings to prevent spurious zero-length matches", () => {
  // A direct call to highlightTerms with an empty string in the terms array
  // must not produce empty-text runs or spurious hits. This enforces the
  // precondition at the function boundary for future callers that build term
  // arrays directly.
  const runs = highlightTerms("the fund for schools", ["the", "", "fund"]);

  // No run should have empty text
  expect(runs.every((r) => r.text.length > 0)).toBe(true);

  // Verify that the correct matches still occur (the two non-empty terms)
  expect(runs.filter((r) => r.hit).map((r) => r.text)).toEqual(["the", "fund"]);
});

const LEAD = "Florence Replacement Beds. The Baseline includes an increase of $22,500,000 ";

test("short passages are shown whole, with no ellipsis", () => {
  expect(previewWindow("A short passage about beds.", queryTerms("beds"))).toEqual({
    text: "A short passage about beds.",
    ellipsisStart: false,
    ellipsisEnd: false,
  });
});

test("the LEADING text is the default preview, even when a later window holds more terms", () => {
  // Measured and deliberate (spec H3): JLBC front-loads these documents --
  // heading, then "The Baseline includes $X for Y", then background. A
  // match-centred window scores higher on terms visible and reads worse,
  // dropping the heading AND the dollar figure. Median first match: char 5.
  const text = LEAD + "x".repeat(400) + " beds beds beds beds";
  const p = previewWindow(text, queryTerms("beds"), 280);
  expect(p.text.startsWith("Florence Replacement Beds.")).toBe(true);
  expect(p.ellipsisStart).toBe(false);
  expect(p.ellipsisEnd).toBe(true);
});

test("it slides to the first match ONLY when the leading text has no typed word", () => {
  // The 3.5% case (spec H4). Falling back is explainable in one sentence;
  // defaulting to it is not.
  const text = "z".repeat(400) + " the waiting list grew " + "z".repeat(400);
  const p = previewWindow(text, queryTerms("waiting"), 280);
  expect(p.text).toContain("waiting");
  expect(p.ellipsisStart).toBe(true);
  expect(p.ellipsisEnd).toBe(true);
});

test("a slid window snaps to word boundaries and never cuts mid-word", () => {
  const pad = "filler words repeated to push the match far down the passage ";
  const text = pad.repeat(8) + "extraordinary waiting list " + pad.repeat(8);
  const p = previewWindow(text, queryTerms("waiting"), 120);

  expect(p.text).toContain("waiting");
  const at = text.indexOf(p.text);
  expect(at).toBeGreaterThan(0);
  // The characters on either side of the window are spaces, so the window
  // begins at a word start and ends at a word end.
  expect(text[at - 1]).toBe(" ");
  expect(text[at + p.text.length]).toBe(" ");
});

test("an unbroken run with no nearby spaces is cut without overshooting", () => {
  // The original snapping jumped `end` to text.length here — 231 characters
  // past the requested window — and then reported ellipsisEnd:false on it.
  const text = "z".repeat(400) + " the waiting list grew " + "z".repeat(400);
  const p = previewWindow(text, queryTerms("waiting"), 280);

  expect(p.text).toContain("waiting");
  expect(p.text.length).toBeLessThanOrEqual(280);
  expect(p.ellipsisStart).toBe(true);
  expect(p.ellipsisEnd).toBe(true);
});

test("a passage with no typed word anywhere still previews its leading text", () => {
  // ~3% of cards ranked on the dense leg alone and contain none of the
  // reader's words. They render with no marks -- an honest absence beats a
  // guess (spec H6) -- but they still show the start of the passage.
  const text = LEAD + "y".repeat(400);
  const p = previewWindow(text, queryTerms("nothingmatcheshere"), 280);
  expect(p.text.startsWith("Florence Replacement Beds.")).toBe(true);
  expect(p.ellipsisStart).toBe(false);
});

test("an empty term list previews the leading text", () => {
  const text = LEAD + "y".repeat(400);
  expect(previewWindow(text, [], 280).text.startsWith("Florence")).toBe(true);
});

test("a snap that would land before start falls back to the unsnapped edge, not an empty window", () => {
  // A prior fixture for this guard ("a ".repeat(50) + "word " + ... at
  // size=35) does NOT discriminate: with a space every two characters,
  // snapEnd's backward search from rawEnd never has to walk past `start`, so
  // the guarded line never runs and old and new code return the identical
  // 34-character slice. It passed before this guard existed and after, which
  // means it was pinning nothing.
  //
  // This text instead builds one long, genuinely unbroken run: 60 "z"s, ONE
  // space, 5 more "z"s, then "-word-" (the hyphens give the regex a match
  // boundary without adding another space), then 200 more "z"s. With
  // size=10, the match is found far enough past the lone space that `start`
  // snaps forward to just after it -- but the backward search for `end`
  // finds no OTHER space before rawEnd, so it walks back to that same lone
  // space too, landing at start-1. Verified against the pre-guard code
  // (temporarily reverting `snapped > start ? snapped : rawEnd` to plain
  // `snapEnd(text, rawEnd)`): that reproduces the exact reported defect, an
  // empty window even though "word" is right there in the text.
  const text = "z".repeat(60) + " " + "z".repeat(5) + "-word-" + "z".repeat(200);
  const p = previewWindow(text, queryTerms("word"), 10);

  expect(p.text.length).toBeGreaterThan(0);
  expect(p.text).toContain("word");
});
