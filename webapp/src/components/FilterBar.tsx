import type { SearchFilters } from "../api";
import { FILTER_BUCKETS } from "../reportFamilies";

// FilterBar — the mockup's `.filters` strip at the bottom of the big search card
// (webapp/reference/subpage-search_jlbc.html), with its `.flabel` / `.fchip` /
// `.fchip.on` / `select.fyear` classes so its CSS applies unmodified (spec S12).
//
// It holds no state: everything renders from `selected` and reports changes back
// up, so Search.tsx stays the single owner of the filter object it sends to the
// API.
//
// Three dimensions:
//   publisher   — fixed chip list (the corpus's four publishers)
//   doc_type    — CURATED bucket chips (reportFamilies.ts), the mockup's own
//                 approach: a fixed, always-visible set, each toggling its whole
//                 slug family. Replaces the earlier result-derived raw-slug
//                 chips at Destin's direction (2026-07-29).
//   fiscal_year — the mockup's `select.fyear` dropdown. Options come from the
//                 data (the mockup hardcoded 43 years because its index was a
//                 static file); the selected year is always kept as an option so
//                 a set filter can never lose its own control (same dead-end
//                 rule as before, different widget).
//
// `agency` is the fourth backend filter and stays unexposed: there is no
// agency-name vocabulary to build chips from yet.
//
// NO COUNTS on the chips: the mockup's chip counts ("Baseline Books (21)") are
// corpus-wide numbers from its local index. This API has no facets/aggregate
// endpoint, and deriving counts from the current result page would show
// per-search numbers where the mockup showed corpus totals — a quiet lie.
// Counts can return with a facets endpoint later.

export type FilterKey = "publisher" | "fiscal_year" | "doc_type";

// The corpus's four publishers, from data/ingest-plan.yaml (`publisher:` values:
// jlbc, governor, agao, legislature). Fixed list — these do not depend on what
// the current search happened to return, so all four stay clickable even when
// the result set contains none of them.
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
  /** Fiscal years offered in the dropdown (accumulated from results by Search.tsx). */
  years: number[];
  onToggle: (key: FilterKey, value: string | number) => void;
  /** Toggle a curated bucket's whole slug list in the doc_type filter. */
  onToggleBucket: (slugs: string[]) => void;
  /** Set the (single) fiscal-year filter; null clears it. */
  onYearChange: (year: number | null) => void;
}

export function FilterBar({ selected, years, onToggle, onToggleBucket, onYearChange }: FilterBarProps) {
  // A set filter must always keep its own control on screen (the dead-end rule):
  // the year options come from results, but a year chosen under an earlier query
  // may not appear in the next query's results — union the selection in.
  const selectedYear = selected.fiscal_year?.[0] ?? null;
  const yearOpts = [...new Set([...years, ...(selectedYear !== null ? [selectedYear] : [])])].sort(
    (a, b) => b - a, // newest fiscal year first, matching Search.tsx's ordering
  );

  // A bucket chip is "on" when every one of its slugs is in the filter. Partial
  // overlap can't happen through this UI (buckets are the only doc_type control
  // and their slug sets don't intersect), so this reads as plain on/off.
  const selectedTypes = selected.doc_type ?? [];
  const bucketOn = (slugs: string[]) => slugs.every((s) => selectedTypes.includes(s));

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
  // `.filters` rule is a single bordered strip, so stacking three would draw
  // divider lines the mockup never has. Grouping uses the mockup's own idiom:
  // `<span style="display:contents">` so everything lays out as items of the one
  // flex row.
  return (
    <div className="filters">
      <span style={{ display: "contents" }}>
        <span className="flabel">Publisher</span>
        {PUBLISHERS.map((p) => chip("publisher", p.value, p.label))}
      </span>

      <span style={{ display: "contents" }}>
        <span className="flabel">Type</span>
        {FILTER_BUCKETS.map((bucket) => (
          <button
            key={bucket.label}
            type="button"
            className={bucketOn(bucket.slugs) ? "fchip on" : "fchip"}
            aria-pressed={bucketOn(bucket.slugs)}
            onClick={() => onToggleBucket(bucket.slugs)}
          >
            {bucket.label}
          </button>
        ))}
      </span>

      <span style={{ display: "contents" }}>
        <span className="flabel">Fiscal year</span>
        {/* The mockup's `select.fyear`, "All years" first, "FY 2027" wording. */}
        <select
          className="fyear"
          aria-label="Filter by fiscal year"
          value={selectedYear ?? ""}
          onChange={(e) => onYearChange(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">All years</option>
          {yearOpts.map((y) => (
            <option key={y} value={y}>
              FY {y}
            </option>
          ))}
        </select>
      </span>
    </div>
  );
}
