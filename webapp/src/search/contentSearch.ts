// Pure helpers for the Budget Documents page's CONTENT search mode — the
// retrieval-backed half. No React, no fetch: everything here is input ->
// output so it can be tested exhaustively without mounting a page.
//
// Content mode calls the existing POST /api/search. Nothing in retrieval/
// changes; this module only translates between the page's vocabulary (report
// FAMILIES, a "fiscal year unknown" bucket) and the API's (doc_type SLUGS,
// real fiscal years).

import type { SearchFilters, SearchResult } from "../api";
import { slugsForFamily } from "../reportFamilies";

/** Translate the rail's two multi-selects into the API's filter object.
 *
 *  Two translations, each load-bearing:
 *
 *  1. The rail holds FAMILY names ("Baseline"); the API wants doc_type SLUGS
 *     ("baseline-per-agency", "baseline-cross-cut"). One family is many slugs.
 *  2. Year 0 is this page's bucket for documents whose fiscal_year is null. It
 *     is not a fiscal year the backend has ever heard of, so it is dropped —
 *     sending it would filter every result out.
 *
 *  An emptied dimension is OMITTED, never sent as `[]`: the backend reads an
 *  explicit empty list as "match nothing", while an absent key means "any". */
export function toSearchFilters(
  types: ReadonlySet<string>,
  years: ReadonlySet<number>,
): SearchFilters {
  const filters: SearchFilters = {};
  if (types.size) {
    // No length guard needed: slugsForFamily always returns at least one
    // slug (an unrecognised family falls back to itself), and this branch
    // only runs when `types.size > 0`, so `slugs` can never be empty — the
    // old `if (slugs.length)` here could never be false (MINOR, 2026-08-10).
    filters.doc_type = [...types].flatMap(slugsForFamily);
  }
  if (years.size) {
    const real = [...years].filter((y) => y !== 0);
    if (real.length) filters.fiscal_year = real;
  }
  return filters;
}

/** One document's worth of matching passages — the unit the result card
 *  renders. ONE card per document: two documents from the same report in the
 *  same year are two cards, but one document is never two cards. */
export interface PassageDoc {
  doc_id: string;
  doc_title: string;
  publisher: string;
  /** Best passage first. */
  passages: SearchResult[];
}

/** Collapse a flat result list into one entry per document.
 *
 *  ONE posture for both orderings — passages within a document, and documents
 *  against each other — rather than trusting the provider's insertion order
 *  for groups while re-sorting passages. A provider that returns rows
 *  ungrouped, or a future one that re-ranks, then still produces
 *  best-document-first, which is the only order this page claims to show. */
export function groupPassages(results: SearchResult[]): PassageDoc[] {
  const byDoc = new Map<string, PassageDoc>();
  for (const r of results) {
    let group = byDoc.get(r.doc_id);
    if (!group) {
      group = {
        doc_id: r.doc_id,
        doc_title: r.doc_title,
        publisher: r.publisher,
        passages: [],
      };
      byDoc.set(r.doc_id, group);
    }
    group.passages.push(r);
  }
  const groups = [...byDoc.values()];
  for (const g of groups) g.passages.sort((a, b) => b.score - a.score);
  groups.sort((a, b) => b.passages[0].score - a.passages[0].score);
  return groups;
}

/** Escape a term so it is matched literally inside a RegExp. A query is
 *  reader input; "(b)" must find "(b)", never compile as a group. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The words to mark: every word the analyst typed, lowercased and deduped,
 *  longest first.
 *
 *  WHY no stopword list, no length rule, no vocabulary of any kind (spec H1):
 *  four candidate rules were measured over 240 real cards and ALL FOUR leave
 *  the share of cards with no mark at 2.9%. Dropping function words rescues
 *  nothing; it only moves mark density from 6.0 to 4.8 in a window of about
 *  45 words. Meanwhile a `length >= 4` rule silently loses "aid" (basic state
 *  aid) and "des" — the terms this domain is actually about. So the cheap,
 *  explainable rule wins: we underline the words you typed.
 *
 *  The ONE exclusion is EMPTY tokens — the blank strings `split` leaves at a
 *  leading/trailing delimiter (`"(b)".split(...)` yields `["", "b", ""]`).
 *  It is not a length rule and it is not a stopword rule: a possessive's
 *  trailing "s" is stripped a line above by matching "'s" as one unit, so it
 *  never reaches the split as a lone letter needing a separate filter — and a
 *  single typed CHARACTER still marks (verified by the "(b)" escaping test
 *  below: the query "(b)" must mark literal "b", so a `length > 1` guard,
 *  which was tried, silently breaks it). Three-character domain terms are
 *  deliberately kept too — there is a test for exactly that.
 *
 *  Longest-first because the alternation below is ordered: with "child" and
 *  "childcare" both typed, the shorter one would otherwise win the prefix. */
export function queryTerms(query: string): string[] {
  const seen = new Set<string>();
  for (const raw of query.toLowerCase().replace(/[’']s\b/g, "").split(/[^a-z0-9]+/)) {
    if (raw.length > 0) seen.add(raw);
  }
  return [...seen].sort((a, b) => b.length - a.length);
}

function termsPattern(terms: string[]): RegExp | null {
  if (!terms.length) return null;
  // Word boundaries, not substrings (spec H2): substring matching measured
  // 8.3 marks per card and peaked at 31, because short words match inside
  // longer ones ("aid" in "said"/"paid").
  return new RegExp(`\\b(?:${terms.map(escapeRegExp).join("|")})\\b`, "gi");
}

/** Split text into matched / unmatched runs for a set of already-tokenised
 *  terms. Each run carries the ORIGINAL casing — an analyst reading "AHCCCS"
 *  must not be shown "ahcccs" because that is what they typed. */
export function highlightTerms(
  text: string,
  terms: string[],
): { text: string; hit: boolean }[] {
  const re = termsPattern(terms);
  if (!re) return [{ text, hit: false }];
  const runs: { text: string; hit: boolean }[] = [];
  let i = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > i) runs.push({ text: text.slice(i, at), hit: false });
    runs.push({ text: m[0], hit: true });
    i = at + m[0].length;
  }
  if (i < text.length) runs.push({ text: text.slice(i), hit: false });
  return runs.length ? runs : [{ text, hit: false }];
}

/** Split a snippet into matched / unmatched runs for the query.
 *
 *  WHY this returns runs instead of an HTML string: the snippet is corpus
 *  text, and building `<mark>` markup from it would mean
 *  dangerouslySetInnerHTML on data this app does not control. The component
 *  renders these runs as real elements instead. */
export function highlight(text: string, query: string): { text: string; hit: boolean }[] {
  return highlightTerms(text, queryTerms(query));
}
