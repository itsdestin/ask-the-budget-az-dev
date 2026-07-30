import type { SearchFilters } from "../api";

// FilterBar — the mockup's `.filters` strip at the bottom of the big search card
// (webapp/reference/subpage-search_jlbc.html), with its `.flabel` / `.fchip` /
// `.fchip.on` classes so its CSS applies unmodified (spec S12).
//
// It holds no state: chips render from `selected` and report clicks back up, so
// Search.tsx stays the single owner of the filter object it sends to the API.

// The three filter dimensions this bar drives. They are the names of the backend's
// filter fields (app/routes/search.py's SearchFilters), NOT display strings — they
// are sent over the wire as-is. `agency` is the fourth backend filter and is
// deliberately absent: there is no agency-name vocabulary to build chips from yet
// (agency codes like "ahcccs" arrive per-result), so it stays unexposed rather
// than shipping a chip row of raw codes.
export type FilterKey = "publisher" | "fiscal_year" | "doc_type";

// The corpus's four publishers, from data/ingest-plan.yaml (`publisher:` values:
// jlbc, governor, agao, legislature). Fixed list — unlike years and doc types,
// these do not depend on what the current search happened to return, so all four
// stay clickable even when the result set contains none of them.
const PUBLISHERS: { value: string; label: string }[] = [
  { value: "jlbc", label: "JLBC" },
  { value: "governor", label: "Governor" },
  { value: "agao", label: "AGAO" },
  { value: "legislature", label: "Legislature" },
];

/** The chip label for a publisher code, so result badges and filter chips can
 *  never disagree about what "agao" is called. An unknown code falls through to
 *  itself rather than being hidden or guessed at. */
export function publisherLabel(value: string): string {
  return PUBLISHERS.find((p) => p.value === value)?.label ?? value;
}

interface FilterBarProps {
  selected: SearchFilters;
  /** Fiscal years offered as chips (accumulated from results by Search.tsx). */
  years: number[];
  /** Doc types offered as chips (accumulated from results by Search.tsx). */
  docTypes: string[];
  onToggle: (key: FilterKey, value: string | number) => void;
}

export function FilterBar({ selected, years, docTypes, onToggle }: FilterBarProps) {
  // INVARIANT: anything you can turn on, you can always turn off.
  //
  // The year and type options come from whatever the last response contained, but
  // a filter STAYS SET when the query changes. So a filter that now matches
  // nothing (search "roads" with type=afr, get 0 rows) would offer no chips at
  // all — the filter would still be applied and sent, with no visible way to
  // clear it, and the page would just claim "no matches". Unioning the SELECTED
  // values into the offered ones guarantees a set filter is always on screen and
  // always clickable. (Publisher needs no such fix: it is a fixed list.)
  const yearOpts = [...new Set([...years, ...(selected.fiscal_year ?? [])])].sort(
    (a, b) => b - a, // newest fiscal year first, matching Search.tsx's ordering
  );
  const typeOpts = [...new Set([...docTypes, ...(selected.doc_type ?? [])])].sort();

  function chip(key: FilterKey, value: string | number, label: string) {
    const on = ((selected[key] ?? []) as (string | number)[]).includes(value);
    return (
      <button
        key={`${key}:${value}`}
        type="button"
        // `.on` is the mockup's own selected-chip class (azure fill, white text).
        className={on ? "fchip on" : "fchip"}
        // The chip is a toggle, so its state has to be announced; the visible
        // label stays its accessible name.
        aria-pressed={on}
        onClick={() => onToggle(key, value)}
      >
        {label}
      </button>
    );
  }

  // ONE `.filters` row for all three groups, not one row per group. The mockup's
  // `.filters` rule is a single bordered strip (`border-top` + `margin-top:16px`),
  // so stacking three of them would draw three divider lines the mockup never
  // has. Grouping inside it uses the mockup's own idiom: it wraps its type chips
  // in `<span style="display:contents">` so they still lay out as items of the
  // one flex row. Same trick here, one span per dimension, each introduced by the
  // mockup's `.flabel`.
  return (
    <div className="filters">
      <span style={{ display: "contents" }}>
        <span className="flabel">Publisher</span>
        {PUBLISHERS.map((p) => chip("publisher", p.value, p.label))}
      </span>

      {/* Years and types only appear once a response has shown they exist — no
          invented option lists. The mockup hardcoded 43 <option> years because its
          index was a static file; this corpus's coverage is whatever has been
          ingested, so the chips come from the data. */}
      {yearOpts.length > 0 && (
        <span style={{ display: "contents" }}>
          <span className="flabel">Fiscal year</span>
          {/* "FY 2027" is the mockup's own year wording (its `select.fyear`
              options read `FY 2027`, `FY 2026`, …). */}
          {yearOpts.map((y) => chip("fiscal_year", y, `FY ${y}`))}
        </span>
      )}

      {typeOpts.length > 0 && (
        <span style={{ display: "contents" }}>
          <span className="flabel">Type</span>
          {/* Labels are the raw contract values ("baseline-per-agency", from
              data/ingest-plan.yaml's `doc_type:` keys — the same strings the
              search fixtures return). There is no display-name vocabulary for
              doc_type anywhere in the repo, so prettifying them here would be
              inventing document-category names. Swap in a label map when the
              corpus vocabulary is finalized.

              NOTE: the enum comment in db/migrations/0001_initial_schema.sql is
              NOT a usable source for that map — it is already stale (it says
              `baseline-agency`, the data says `baseline-per-agency`). Don't
              build labels from it without reconciling the two first. */}
          {typeOpts.map((t) => chip("doc_type", t, t))}
        </span>
      )}
    </div>
  );
}
