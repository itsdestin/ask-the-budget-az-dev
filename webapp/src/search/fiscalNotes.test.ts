// Pure helpers for the Fiscal Notes page (spec F4, F10, F11, F16). No React,
// no fetch — every one of these is input -> output, so it can be tested
// exhaustively without mounting a page.
//
// Where a test drives REAL data it says so. That is not decoration: the two
// defects these helpers exist to prevent (the `Fiscal Note - ` prefix on every
// retrieval title, and the 241 titles carrying raw <strike> markup) are
// invisible to invented fixtures, and were found only by querying the corpus.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import type { SearchResult } from "../api";
import {
  SHOW_NOTES,
  groupNotes,
  parseNoteTitle,
  resultsHeader,
  sessionLabel,
} from "./fiscalNotes";

/** The real committed directory snapshot: 28 sessions, 2,126 bills. */
const SNAPSHOT = JSON.parse(
  readFileSync(resolve(__dirname, "../../../app/data/fiscal-notes-snapshot.json"), "utf-8"),
) as { sessions: { year: number; name: string; bills: { bill_number: string; title: string }[] }[] };

// ---------------------------------------------------------------------------
// F4 — the session label puts the year FIRST
// ---------------------------------------------------------------------------

describe("sessionLabel", () => {
  test("puts the year first and expands the abbreviation", () => {
    expect(sessionLabel({ year: 2026, name: "57th Legislature, 2nd Reg. Session (2026)" }))
      .toBe("2026 (57th Legislature, 2nd Regular Session)");
  });

  test("an unrecognised form passes through intact rather than half-rewritten", () => {
    // Every live session is Regular TODAY (spec fact 6) — which is exactly why
    // a blind .replace("Reg.", "Regular") would rot silently the first time
    // Arizona holds a special session.
    expect(sessionLabel({ year: 2027, name: "58th Legislature, 1st Spec. Session (2027)" }))
      .toBe("2027 (58th Legislature, 1st Special Session)");
  });

  test("an abbreviation with no mapping is left alone, not truncated", () => {
    expect(sessionLabel({ year: 2027, name: "58th Legislature, 1st Blah. Session (2027)" }))
      .toBe("2027 (58th Legislature, 1st Blah. Session)");
  });

  test("strips the trailing year ONLY when it is this session's own", () => {
    // A name carrying someone else's year keeps it: stripping any (YYYY) would
    // silently eat four characters of a name that never had a redundant year.
    expect(sessionLabel({ year: 2026, name: "Something (1999)" })).toBe("2026 (Something (1999))");
  });

  test("every real session name survives it", () => {
    for (const s of SNAPSHOT.sessions) {
      const label = sessionLabel(s);
      expect(label.startsWith(`${s.year} (`)).toBe(true);
      // No un-expanded abbreviation and no doubled year left behind.
      expect(label).not.toMatch(/\bReg\.|Spec\./);
      expect(label.match(new RegExp(String(s.year), "g"))!.length).toBe(1);
    }
  });
});

// ---------------------------------------------------------------------------
// F16 — the retrieval title is NOT the browse title
// ---------------------------------------------------------------------------

describe("parseNoteTitle", () => {
  test("strips the ingest prefix and splits on the FIRST colon", () => {
    // All 2,104 corpus titles are prefixed "Fiscal Note - " (spec fact 1). A
    // page called "Fiscal Notes" whose every card opens with the words "Fiscal
    // Note" is the defect this exists to prevent.
    expect(parseNoteTitle("Fiscal Note - HB 2407: victim notification"))
      .toEqual({ number: "HB 2407", title: "victim notification" });
  });

  test("later colons and semicolons belong to the title", () => {
    expect(parseNoteTitle("Fiscal Note - SB 1035: corrections; appropriation: FY25"))
      .toEqual({ number: "SB 1035", title: "corrections; appropriation: FY25" });
  });

  test("a title that does not match the shape renders WHOLE, not cut wrong", () => {
    expect(parseNoteTitle("something unexpected"))
      .toEqual({ number: null, title: "something unexpected" });
  });

  test("a prefix with no colon still loses the prefix", () => {
    expect(parseNoteTitle("Fiscal Note - HB 2407 victim notification"))
      .toEqual({ number: null, title: "HB 2407 victim notification" });
  });

  test("HTML in the title survives the parse as characters, not markup", () => {
    // 241 of the directory's 2,126 titles carry raw <strike> (spec fact 2).
    // The parser must not eat it, strip it, or interpret it — BillTitle
    // handles it downstream, and that is the ONLY safe renderer for it.
    const raw =
      "Fiscal Note - HB 2172: <strike>technology transfer; technical correction</strike> (NOW: solar device; tax credit)";
    expect(parseNoteTitle(raw)).toEqual({
      number: "HB 2172",
      title: "<strike>technology transfer; technical correction</strike> (NOW: solar device; tax credit)",
    });
  });

  test("a struck title whose FIRST colon is inside the markup still splits at the number", () => {
    // Guards the failure mode a naive split has: the number boundary is the
    // first colon AFTER the prefix, and the markup can contain colons of its
    // own further along.
    const raw = "Fiscal Note - SB 1001: <strike>a: b</strike> (NOW: c)";
    expect(parseNoteTitle(raw).number).toBe("SB 1001");
  });

  test("no real bill number parses to something absurdly long", () => {
    // Runs the parser over every real directory title in the shape retrieval
    // produces. A long "number" means the split landed in the wrong place —
    // the cheapest possible check that the rule holds corpus-wide.
    for (const s of SNAPSHOT.sessions) {
      for (const b of s.bills) {
        const { number } = parseNoteTitle(`Fiscal Note - ${b.bill_number}: ${b.title}`);
        expect(number).toBe(b.bill_number);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// F10 / F11 — one card per note, cut at 15
// ---------------------------------------------------------------------------

/** `n` distinct notes, one passage each, descending score. */
function resultsAcross(n: number): SearchResult[] {
  return Array.from({ length: n }, (_, i) => passage({ doc_id: `note-${i}`, score: 10 - i }));
}

function passage(over: Partial<SearchResult>): SearchResult {
  return {
    chunk_id: `c${Math.random()}`,
    doc_id: "note-1",
    doc_title: "Fiscal Note - HB 1000: a title",
    snippet: "",
    text: "",
    page: 1,
    score: 1,
    doc_type: "fiscal-note",
    fiscal_year: 2026,
    publisher: "azleg",
    agencies: [],
    doc_url: null,
    doc_meta: null,
    section_of: null,
    ...over,
  } as SearchResult;
}

describe("groupNotes", () => {
  test("cuts at 15 and reports that it cut", () => {
    const { notes, cut } = groupNotes(resultsAcross(17));
    expect(notes).toHaveLength(SHOW_NOTES);
    expect(cut).toBe(true);
  });

  test("the boundary: exactly 15 is the 'all' case, 16 is the 'top' case", () => {
    // The ONLY place the two header strings can be swapped with no other
    // visible symptom, which is why both sides are pinned.
    expect(groupNotes(resultsAcross(15)).cut).toBe(false);
    expect(groupNotes(resultsAcross(15)).notes).toHaveLength(15);
    expect(groupNotes(resultsAcross(16)).cut).toBe(true);
    expect(groupNotes(resultsAcross(16)).notes).toHaveLength(15);
  });

  test("a thin result set is passed through whole", () => {
    const { notes, cut } = groupNotes(resultsAcross(9));
    expect(notes).toHaveLength(9);
    expect(cut).toBe(false);
  });

  test("one card per note, holding that note's BEST passage first", () => {
    // F11: a card shows ONE passage. Grouping still ranks within a note so the
    // card can take [0]; the rest inform nothing but the ordering.
    const { notes } = groupNotes([
      passage({ doc_id: "same", score: 0.2, chunk_id: "weak" }),
      passage({ doc_id: "same", score: 0.9, chunk_id: "strong" }),
    ]);
    expect(notes).toHaveLength(1);
    expect(notes[0].passages[0].chunk_id).toBe("strong");
  });

  test("notes are ordered by their best passage, not by arrival", () => {
    const { notes } = groupNotes([
      passage({ doc_id: "b", score: 1 }),
      passage({ doc_id: "a", score: 9 }),
    ]);
    expect(notes.map((n) => n.doc_id)).toEqual(["a", "b"]);
  });

  test("a wordy note taking several slots costs the page notes, not cards", () => {
    // The measured cause of the old 9-17 swing: 20 passages do not mean 20
    // notes. Five passages of one note collapse to ONE card.
    const five = Array.from({ length: 5 }, (_, i) => passage({ doc_id: "hog", score: 9 - i }));
    const { notes } = groupNotes([...five, ...resultsAcross(3)]);
    expect(notes).toHaveLength(4);
  });

  test("an empty response is not a cut", () => {
    expect(groupNotes([])).toEqual({ notes: [], cut: false });
  });
});

describe("resultsHeader", () => {
  test("the two strings", () => {
    expect(resultsHeader(15, true)).toBe("Showing top 15 matches");
    expect(resultsHeader(9, false)).toBe("Showing all 9 matches");
  });

  test("singular", () => {
    expect(resultsHeader(1, false)).toBe("Showing all 1 match");
  });

  test("never names passages, and never implies a corpus total", () => {
    // Spec F10: every count on this page names notes/matches, because one card
    // is one note — counting passages would state a quantity nothing on screen
    // corresponds to. And "all" is a claim about THIS SEARCH, never the corpus.
    for (const [n, cut] of [[15, true], [9, false], [1, false]] as const) {
      expect(resultsHeader(n, cut)).not.toMatch(/passage|result|total|of \d/i);
    }
  });
});
