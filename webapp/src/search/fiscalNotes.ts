// Pure helpers for the Fiscal Notes page — the four things that are decided
// once and used in several places (spec F4, F10, F11, F16). No React, no
// fetch: input -> output, so the awkward cases can be pinned exhaustively
// without mounting a page.

import type { SearchResult } from "../api";
import { groupPassages, type PassageDoc } from "./contentSearch";

// ---------------------------------------------------------------------------
// F4 — the session label puts the year FIRST
// ---------------------------------------------------------------------------

/** Abbreviations the directory actually uses, expanded through a MAP.
 *
 *  WHY a map and not `.replace("Reg.", "Regular")`: every one of the 28 live
 *  sessions is a Regular session today (spec fact 6), so a blind replace would
 *  look correct forever right up until Arizona holds a special session — and
 *  then produce a half-rewritten name with no error anywhere. An unrecognised
 *  abbreviation passes through untouched, which is wrong in a way a reader can
 *  see and report, rather than wrong invisibly. */
const SESSION_WORDS: Record<string, string> = {
  "Reg.": "Regular",
  "Spec.": "Special",
};

/** `57th Legislature, 2nd Reg. Session (2026)` -> `2026 (57th Legislature, 2nd Regular Session)`
 *
 *  The directory buries the year at the END of a string readers scan BY year.
 *  Used on session card heads and their aria-labels, the result card's session
 *  line, and the source drawer breadcrumb — four places, which is exactly why
 *  the rule lives here instead of being spelled out at each one. */
export function sessionLabel(session: { year: number; name: string }): string {
  // Strip the trailing "(YYYY)" ONLY when it is this session's own year. A
  // name carrying some other year keeps it: a blanket /\(\d{4}\)$/ would
  // silently eat four characters from a name that never had a redundant year.
  let body = session.name.replace(new RegExp(`\\s*\\(${session.year}\\)\\s*$`), "");
  body = body.replace(/\S+\./g, (word) => SESSION_WORDS[word] ?? word);
  return `${session.year} (${body})`;
}

// ---------------------------------------------------------------------------
// F16 — the retrieval title is NOT the browse title
// ---------------------------------------------------------------------------

/** Every fiscal-note `doc_title` arrives from ingest as
 *  `Fiscal Note - <NUMBER>: <title>` — uniformly, 2,104 of 2,104 (spec fact 1).
 *  That is NOT the browse row's `bill.title`, which is the scraped directory
 *  string and carries no prefix. The two identities are close but not the same
 *  string, and the result card has to build its own. */
const TITLE_PREFIX = "Fiscal Note - ";

export interface NoteTitle {
  /** `"HB 2407"`, or null when the string does not have the expected shape. */
  number: string | null;
  /** Everything after the number. May contain raw HTML — see below. */
  title: string;
}

/** Split a retrieval title into the two weights the card renders.
 *
 *  Three rules, and all three are visible defects if skipped:
 *
 *  1. **Strip the prefix.** Every card on a page titled "Fiscal Notes" would
 *     otherwise open with the words "Fiscal Note".
 *  2. **Split on the FIRST colon only.** Titles contain further colons and
 *     semicolons ("corrections; appropriation: FY25"); only the first is the
 *     number boundary. A string that does not match the shape comes back
 *     whole with `number: null`, so it renders unsplit rather than cut in a
 *     wrong place.
 *  3. **Do not touch the HTML.** 241 directory titles carry raw `<strike>`
 *     markup. This function deliberately passes it through as CHARACTERS —
 *     rendering is `BillTitle`'s job, and it is the only safe renderer for it.
 *     Do NOT reach for `dangerouslySetInnerHTML` at the call site; that is
 *     the trap this whole path exists to close. */
export function parseNoteTitle(docTitle: string): NoteTitle {
  const withoutPrefix = docTitle.startsWith(TITLE_PREFIX)
    ? docTitle.slice(TITLE_PREFIX.length)
    : docTitle;
  const colon = withoutPrefix.indexOf(":");
  if (colon === -1) return { number: null, title: withoutPrefix };
  return {
    number: withoutPrefix.slice(0, colon).trim(),
    title: withoutPrefix.slice(colon + 1).trim(),
  };
}

// ---------------------------------------------------------------------------
// F10 / F11 — one card per note, cut at 15
// ---------------------------------------------------------------------------

/** How many NOTES the results list shows (spec F10, Destin 2026-08-13).
 *
 *  Applied HERE, in the browser, after the response arrives — deliberately,
 *  so that nothing under `retrieval/` has to move and no eval run is owed.
 *
 *  WHY a cut is needed at all: retrieval ranks and truncates at 20 PASSAGES
 *  (`FUSED_TOP_K`, a hard ceiling — asking /api/search for 40 returns 20), and
 *  a card shows one passage per note, so how many NOTES a search yields
 *  depends on how concentrated the ranking is. Measured across eight realistic
 *  questions: 17, 16, 13, 13, 13, 12, 9, 9 — mean 12.8, range 9-17. A reader
 *  cannot tell a thin topic from one where a single wordy note took five of
 *  the twenty slots, so the page promises a fixed ceiling instead.
 *
 *  Consequence worth knowing: six of those eight land UNDER 15, so the "all N"
 *  header is the common case and "top 15" is the exception. */
export const SHOW_NOTES = 15;

export interface NoteResults {
  notes: PassageDoc[];
  /** True when the ranking held more notes than fit. The entire difference
   *  between the two header strings, and a fact about THIS RESPONSE — never
   *  about the corpus. */
  cut: boolean;
}

/** Collapse ranked passages into notes, then cut at `SHOW_NOTES`.
 *
 *  Reuses `groupPassages` rather than growing a second grouping rule: the
 *  Budget Documents page already collapses a flat result list into one entry
 *  per document, best passage first, best document first — which is exactly
 *  what a note card needs. Two implementations of one rule drift, and the
 *  symptom would be the two pages disagreeing about which passage is "best".
 *
 *  Nothing filters between the ranking and the cut. Chamber stood down in
 *  content mode (spec F9) precisely so that the ceiling is the ONLY thing that
 *  can remove a ranked note — which is what makes the header honest. */
export function groupNotes(results: SearchResult[]): NoteResults {
  const all = groupPassages(results);
  return { notes: all.slice(0, SHOW_NOTES), cut: all.length > SHOW_NOTES };
}

/** The results header, both halves of spec F10's copy.
 *
 *  Two strings, one comparison. Both are claims about what THIS SEARCH
 *  surfaced; neither is a claim about the corpus, and nothing on this page may
 *  imply one.
 *
 *  ACCEPTED HONESTY COST, recorded so it is not rediscovered as a bug: "all"
 *  means *all that the 20-passage ceiling reached*, not all the corpus holds.
 *  A reader who types `tax`, sees "Showing all 12 matches" and concludes the
 *  corpus holds twelve tax notes has been misled — it holds hundreds. The
 *  pre-approved remedy if that ever bites is one word: drop "all" and render
 *  "Showing 12 matches". Nothing else changes.
 *
 *  Counts name MATCHES, which is the same quantity as notes here (one card is
 *  one note is one match). What must never be counted on screen is PASSAGES —
 *  a number nothing visible corresponds to. */
export function resultsHeader(n: number, cut: boolean): string {
  if (cut) return `Showing top ${SHOW_NOTES} matches`;
  return `Showing all ${n} ${n === 1 ? "match" : "matches"}`;
}
