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
    const slugs = [...types].flatMap(slugsForFamily);
    if (slugs.length) filters.doc_type = slugs;
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
  /** The document's own source PDF, or null when unknown. */
  doc_url: string | null;
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
        doc_url: r.doc_url,
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

/** Split a snippet into matched / unmatched runs for the query term.
 *
 *  WHY this returns runs instead of an HTML string: the snippet is corpus
 *  text, and building `<mark>` markup from it would mean
 *  dangerouslySetInnerHTML on data this app does not control. The component
 *  renders these runs as real elements instead.
 *
 *  Case-insensitive matching, but each run carries the ORIGINAL casing — an
 *  analyst reading "AHCCCS" must not be shown "ahcccs" because that is what
 *  they typed. */
export function highlight(text: string, query: string): { text: string; hit: boolean }[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [{ text, hit: false }];
  const runs: { text: string; hit: boolean }[] = [];
  const haystack = text.toLowerCase();
  let i = 0;
  while (i < text.length) {
    const at = haystack.indexOf(needle, i);
    if (at === -1) {
      runs.push({ text: text.slice(i), hit: false });
      break;
    }
    if (at > i) runs.push({ text: text.slice(i, at), hit: false });
    runs.push({ text: text.slice(at, at + needle.length), hit: true });
    i = at + needle.length;
  }
  return runs.length ? runs : [{ text, hit: false }];
}
