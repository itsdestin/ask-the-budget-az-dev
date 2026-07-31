import { useEffect, useRef, useState } from "react";
import type { SearchFilters } from "../api";
import { FILTER_BUCKETS } from "../reportFamilies";

// FilterBar — the dropdown rail (Destin's pick from the 2026-07-30 design
// round, artifact "Filter strip alternatives", option E2b + parenthetical
// counts): three trigger pills — Publisher, Type, Fiscal year — each opening
// a themed menu. The panel/row/hover/active recipes are the app's own
// dropdown idiom (the fiscal-notes sort menu, itself verbatim mockup CSS);
// see app.css's "filter dropdown rail" block.
//
// Selection display, per Destin: NO chips, NO count badges — the trigger
// text carries a plain parenthetical count ("Type (2)") and the trigger
// tints gold while anything inside is selected.
//
// Behavior: click opens; multi-select rows (checkbox marks) toggle and the
// menu STAYS OPEN for multi-picking; the year menu is single-select (radio
// marks, "All years" clears) and closes on pick; outside click or Escape
// closes. It holds no filter state: everything renders from `selected` and
// reports changes up, so Search.tsx stays the single owner of the filter
// object it sends to the API.

export type FilterKey = "publisher" | "fiscal_year" | "doc_type";

// The corpus's four publishers, from data/ingest-plan.yaml (`publisher:`
// values). Fixed list — not dependent on what a search returned.
const PUBLISHERS: { value: string; label: string }[] = [
  { value: "jlbc", label: "JLBC" },
  { value: "governor", label: "Governor" },
  { value: "agao", label: "AGAO" },
  { value: "legislature", label: "Legislature" },
];

/** The label for a publisher code, so result surfaces and filter menus can
 *  never disagree about what "agao" is called. An unknown code falls through
 *  to itself rather than being hidden or guessed at. */
export function publisherLabel(value: string): string {
  return PUBLISHERS.find((p) => p.value === value)?.label ?? value;
}

interface FilterBarProps {
  selected: SearchFilters;
  /** Fiscal years offered in the year menu (accumulated from results by Search.tsx). */
  years: number[];
  onToggle: (key: FilterKey, value: string | number) => void;
  /** Toggle a curated bucket's whole slug list in the doc_type filter. */
  onToggleBucket: (slugs: string[]) => void;
  /** Set the (single) fiscal-year filter; null clears it. */
  onYearChange: (year: number | null) => void;
}

/** The trigger's text: "Publisher" or "Publisher (2)" — a plain parenthetical,
 *  deliberately not a badge (Destin rejected the count-pill look). */
function triggerText(label: string, count: number): string {
  return count > 0 ? `${label} (${count})` : label;
}

function CheckMark({ round = false }: { round?: boolean }) {
  return (
    <span className={round ? "ck rd" : "ck"} aria-hidden="true">
      <svg viewBox="0 0 12 10" fill="none" stroke="currentColor" strokeWidth="2.4">
        <path d="m1 5 3.5 3.5L11 1" />
      </svg>
    </span>
  );
}

export function FilterBar({ selected, years, onToggle, onToggleBucket, onYearChange }: FilterBarProps) {
  // Which menu is open ("publisher" | "type" | "year" | null). One at a time.
  const [open, setOpen] = useState<string | null>(null);
  const rail = useRef<HTMLDivElement>(null);

  // Outside click / Escape close the open menu — a multi-select menu must NOT
  // close on option clicks (that's the whole point), so closing is explicit.
  useEffect(() => {
    if (open === null) return;
    const onDocClick = (e: MouseEvent) => {
      if (rail.current && !rail.current.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // The dead-end rule, unchanged: a year chosen under an earlier query stays
  // an option even when the current results don't contain it.
  const selectedYear = selected.fiscal_year?.[0] ?? null;
  const yearOpts = [...new Set([...years, ...(selectedYear !== null ? [selectedYear] : [])])].sort(
    (a, b) => b - a,
  );

  const selectedPubs = selected.publisher ?? [];
  const selectedTypes = selected.doc_type ?? [];
  // A bucket is "on" when every one of its slugs is in the filter; the Type
  // count counts BUCKETS (what the user picked), not slugs (how the API
  // spells them).
  const bucketOn = (slugs: string[]) => slugs.every((s) => selectedTypes.includes(s));
  const bucketCount = FILTER_BUCKETS.filter((b) => bucketOn(b.slugs)).length;

  const toggleMenu = (key: string) => setOpen((v) => (v === key ? null : key));

  function trigger(key: string, label: string, count: number) {
    return (
      <button
        type="button"
        className={count > 0 ? "fbtn has" : "fbtn"}
        aria-expanded={open === key}
        onClick={() => toggleMenu(key)}
      >
        {triggerText(label, count)}
        <svg className="chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="m1 1 4 4 4-4" />
        </svg>
      </button>
    );
  }

  return (
    <div className="filters" ref={rail}>
      <div className="fctl">
        {trigger("publisher", "Publisher", selectedPubs.length)}
        {open === "publisher" && (
          <div className="fmenu">
            {PUBLISHERS.map((p) => {
              const on = selectedPubs.includes(p.value);
              return (
                <button
                  key={p.value}
                  type="button"
                  className={on ? "fopt on" : "fopt"}
                  aria-pressed={on}
                  onClick={() => onToggle("publisher", p.value)}
                >
                  <CheckMark />
                  {p.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="fctl">
        {trigger("type", "Type", bucketCount)}
        {open === "type" && (
          <div className="fmenu">
            {FILTER_BUCKETS.map((bucket) => {
              const on = bucketOn(bucket.slugs);
              return (
                <button
                  key={bucket.label}
                  type="button"
                  className={on ? "fopt on" : "fopt"}
                  aria-pressed={on}
                  onClick={() => onToggleBucket(bucket.slugs)}
                >
                  <CheckMark />
                  {bucket.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="fctl">
        {trigger("year", "Fiscal year", selectedYear !== null ? 1 : 0)}
        {open === "year" && (
          <div className="fmenu">
            <button
              type="button"
              className={selectedYear === null ? "fopt on" : "fopt"}
              onClick={() => {
                onYearChange(null);
                setOpen(null); // single-select: picking closes
              }}
            >
              <CheckMark round />
              All years
            </button>
            {yearOpts.map((y) => (
              <button
                key={y}
                type="button"
                className={selectedYear === y ? "fopt on" : "fopt"}
                onClick={() => {
                  onYearChange(y);
                  setOpen(null);
                }}
              >
                <CheckMark round />
                FY {y}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
