import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
// Namespace import, and every call goes through `api.search(...)`: the page's test
// intercepts the request with vi.spyOn(api, "search"), which can only see calls
// made through the module object.
import * as api from "../api";
import type { SearchFilters, SearchResponse, SearchResult } from "../api";
import { FilterBar, type FilterKey } from "../components/FilterBar";
import { ResultCard, type DocGroup } from "../components/ResultCard";
import { SearchIcon } from "../components/SearchIcon";

// Budget Search — ported from the approved mockup's search page
// (webapp/reference/subpage-search_jlbc.html), keeping its class names so its CSS
// applies unmodified (spec S12: port, don't redesign). Top to bottom, the mockup's
// own structure: `.subhero` title band → `.search-wrap` → the `.card.big-search-card`
// holding the `.big-search` pill and the `.filters` chip strip → `.search-status`
// line → the `.card` results panel (`.card-head`/`.head-row` + grouped `.grp` tiles).
//
// Dropped from the mockup, with reasons:
//   - `.examples-row` (its "try one of these" query pills): the example queries were
//     written for JLBC's own document index; inventing four for this corpus would be
//     making up content.
//   - `#reportModal`, `.grp-full` / `.grp-more` (its "open the full report" chooser
//     and per-group collapse): both open PDFs, which is Plan 4's viewer panel.
//   - `select.fyear`: replaced by fiscal-year chips per the plan — see FilterBar.tsx.
//   - `.acc*` (the year accordion) and the sidebar/footer blocks: not part of this page.

/** What the page is currently showing. One state, so "loading" and "error" and
 *  "results" can never be true at the same time. */
type Phase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; res: SearchResponse }
  | { kind: "error"; message: string };

/** Chip options harvested from results, remembered per query (see mergeFacets). */
interface Facets {
  q: string;
  years: number[];
  docTypes: string[];
}

/** Collapse a flat result list into one entry per document, best chunk first.
 *  Exported for readability of the page below, not used elsewhere. */
export function groupByDoc(results: SearchResult[]): DocGroup[] {
  const byDoc = new Map<string, DocGroup>();
  for (const r of results) {
    let group = byDoc.get(r.doc_id);
    if (!group) {
      group = {
        doc_id: r.doc_id,
        doc_title: r.doc_title,
        publisher: r.publisher,
        fiscal_year: r.fiscal_year,
        doc_type: r.doc_type,
        chunks: [],
      };
      byDoc.set(r.doc_id, group);
    }
    group.chunks.push(r);
  }
  // A Map iterates in insertion order, so documents come out in the order the
  // provider first mentioned them — i.e. still ranked by their best hit. Chunks
  // are re-sorted by score anyway so a provider that returns them ungrouped or
  // unordered still reads correctly.
  for (const group of byDoc.values()) group.chunks.sort((a, b) => b.score - a.score);
  return [...byDoc.values()];
}

/** Fold a response's fiscal years and doc types into the chip options.
 *
 *  WHY the options ACCUMULATE instead of being rebuilt from the latest response:
 *  filtering shrinks the result set, so rebuilding would delete the very chip you
 *  need to click to undo the filter (pick FY 2027, and every other year's chip
 *  disappears — a dead end). They reset when the query itself changes, since a new
 *  search is a new set of documents. */
function mergeFacets(prev: Facets, q: string, results: SearchResult[]): Facets {
  const base: Facets = prev.q === q ? prev : { q, years: [], docTypes: [] };
  const years = new Set(base.years);
  const docTypes = new Set(base.docTypes);
  for (const r of results) {
    if (r.fiscal_year !== null) years.add(r.fiscal_year);
    docTypes.add(r.doc_type);
  }
  return {
    q,
    years: [...years].sort((a, b) => b - a), // newest fiscal year first
    docTypes: [...docTypes].sort(),
  };
}

/** Add or remove one value in one filter dimension, returning a new filter object.
 *  An emptied dimension is DELETED rather than sent as `[]`, so the request body
 *  only ever carries filters the user actually set. */
function toggleFilter(
  prev: SearchFilters,
  key: FilterKey,
  value: string | number,
): SearchFilters {
  const next: SearchFilters = { ...prev };
  if (key === "fiscal_year") {
    const year = Number(value);
    const list = prev.fiscal_year ?? [];
    const updated = list.includes(year) ? list.filter((v) => v !== year) : [...list, year];
    if (updated.length) next.fiscal_year = updated;
    else delete next.fiscal_year;
  } else {
    const code = String(value);
    const list = prev[key] ?? [];
    const updated = list.includes(code) ? list.filter((v) => v !== code) : [...list, code];
    if (updated.length) next[key] = updated;
    else delete next[key];
  }
  return next;
}

export function Search() {
  const [params, setParams] = useSearchParams();
  // The URL is the source of truth for the query — that's what makes a results
  // page linkable and what lets Home's hero hand a search over by navigating.
  const query = (params.get("q") ?? "").trim();

  // The text box is separate local state so typing doesn't refetch on every
  // keystroke; submitting is what writes ?q= and therefore what runs a search.
  const [text, setText] = useState(query);
  const box = useRef<HTMLInputElement>(null);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [facets, setFacets] = useState<Facets>({ q: "", years: [], docTypes: [] });

  // Keep the box in step with the URL if ?q= changes underneath us (back button, or
  // a second search arriving from elsewhere in the app).
  useEffect(() => setText(query), [query]);

  useEffect(() => {
    if (!query) {
      setPhase({ kind: "idle" });
      return;
    }
    // Stale-response guard. If the query or the filters change while a request is
    // still in flight, React runs this effect's cleanup first, which flips
    // `ignore` — so when the OLD (slower) request finally answers, it returns here
    // and does nothing instead of overwriting the newer results.
    let ignore = false;
    setPhase({ kind: "loading" });
    api.search(query, filters, "budget").then(
      (res) => {
        if (ignore) return;
        setPhase({ kind: "ready", res });
        setFacets((prev) => mergeFacets(prev, query, res.results));
      },
      (err: unknown) => {
        if (ignore) return;
        // The api client already put the backend's own `detail` in the message;
        // show it verbatim rather than replacing it with a guess at the cause.
        setPhase({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      ignore = true;
    };
    // `filters` is a state object, so its identity only changes when a chip is
    // toggled — it is safe as a dependency and is what re-runs the search.
  }, [query, filters]);

  const groups = phase.kind === "ready" ? groupByDoc(phase.res.results) : [];

  return (
    <main className="page-search" data-testid="search">
      {/* The mockup's `.subhero` band. It sits inside <main> here (the mockup keeps
          it outside, but every ported rule is scoped under `.page-search`, which is
          on this element). Its aria-label="Page header" is dropped: it would add a
          landmark named "Page header" that says nothing a heading doesn't. */}
      <section className="subhero">
        <div className="wrap">
          <h1>Budget Document Search</h1>
          {/* DESIGN-SYSTEM.md §6: the lead is reserved at two lines and CLAMPED at
              two, so this copy is written to fit (~124 chars ≈ two 66ch lines)
              rather than left to ellipsis mid-sentence. */}
          <p className="lead">
            Full-text search across every Arizona budget document ingested so far —
            baselines, appropriations reports, and budget bills.
          </p>
          {/* §6 also requires the chip row on every sub-page. The mockup's first chip
              was a document COUNT ("419 documents") — dropped, because this page has
              no honest number to put there: the API returns per-search counts, not a
              corpus size. These two state the page's shape instead. */}
          <div className="chips">
            <span className="chip">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 2h9l5 5v15H6z" />
                <path d="M14 2v6h6" />
              </svg>{" "}
              {/* The corpus's four publishers, same labels as the filter chips.
                  AGAO is left abbreviated on purpose: it is the Arizona General
                  Accounting Office (data/system-prompt-context.md line 73) — NOT
                  the Auditor General, a different agency. */}
              JLBC · Governor's Office · AGAO · Legislature
            </span>
            <span className="chip">
              <SearchIcon /> Every match carries the page it came from
            </span>
          </div>
        </div>
      </section>

      <div className="wrap">
        <div className="search-wrap">
          <section className="card big-search-card">
            <form
              className="big-search"
              role="search"
              onSubmit={(e) => {
                e.preventDefault();
                const next = text.trim();
                // Same guard as Home's hero: a blank search would fire a request the
                // backend rejects ("query is empty") and show an error for something
                // the user hasn't typed yet.
                if (!next) return;
                // Writing ?q= is what triggers the fetch (the effect above watches it).
                setParams({ q: next });
              }}
            >
              <SearchIcon className="s-ic" />
              <input
                id="q"
                ref={box}
                type="search"
                name="q"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="e.g. how much does the Medicaid program get?"
                aria-label="Search Arizona budget documents"
                autoComplete="off"
              />
              {/* The mockup's custom clear-X: shown only when there's text, and it
                  clears the results too (it drops ?q=), which is what its own inline
                  script did — clear the value, reset the results, refocus the box. */}
              <button
                type="button"
                className={text ? "clr-x show" : "clr-x"}
                aria-label="Clear search"
                onClick={() => {
                  setText("");
                  setParams({});
                  box.current?.focus();
                }}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
              <button type="submit" className="s-btn">
                <SearchIcon />
                Search
              </button>
            </form>

            <FilterBar
              selected={filters}
              years={facets.q === query ? facets.years : []}
              docTypes={facets.q === query ? facets.docTypes : []}
              onToggle={(key, value) => setFilters((prev) => toggleFilter(prev, key, value))}
            />
          </section>

          {/* The mockup's status line under the card. Every phase says something
              true; none of them leaves the page blank. */}
          <div className="search-status">
            {phase.kind === "idle" && "Type a search above to query the budget corpus."}
            {phase.kind === "loading" && "Searching…"}
            {/* `.err` is the mockup's own error color on this line. The message is
                the backend's, passed through untouched. */}
            {phase.kind === "error" && <span className="err">{phase.message}</span>}
            {phase.kind === "ready" && (
              <>
                {phase.res.total} {phase.res.total === 1 ? "match" : "matches"} in{" "}
                {groups.length} {groups.length === 1 ? "document" : "documents"}
                {/* Dev honesty: say so when the rows are fixtures rather than the
                    real corpus. Task 12 swaps in LanceSearchProvider and this
                    badge stops rendering on its own. */}
                {phase.res.provider === "stub" && <span className="stub-badge">stub data</span>}
              </>
            )}
          </div>

          {phase.kind === "ready" && (
            <section className="card">
              <div className="card-head">
                <div className="head-row">
                  <span className="ic">
                    {/* Deviation: the mockup's own Results header reuses its HOUSE
                        icon here — plainly a copy-paste slip in a hand-built mockup
                        (it is the `.home-ic` path). Using the magnifier instead;
                        same glyph family, same 20px slot. */}
                    <SearchIcon />
                  </span>
                  <h2>Results</h2>
                  <span className="count">
                    {groups.length} {groups.length === 1 ? "document" : "documents"}
                  </span>
                </div>
              </div>
              {/* `.results`, not the mockup's `#results`: an id inside a component is
                  a page-wide uniqueness claim a component can't keep. Same rules,
                  ported onto the class. */}
              <div className="results">
                {groups.length === 0 ? (
                  // Two messages, because "nothing in the corpus matched" and "your
                  // filters excluded everything" are different facts and the second
                  // one is actionable. Saying the first when filters are on would
                  // blame the corpus for the user's own narrowing.
                  <p className="empty">
                    {Object.keys(filters).length > 0
                      ? "No matches for that search with the filters above. Try clearing a filter."
                      : "No matches in the corpus for that search."}
                  </p>
                ) : (
                  groups.map((group) => <ResultCard key={group.doc_id} group={group} />)
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
