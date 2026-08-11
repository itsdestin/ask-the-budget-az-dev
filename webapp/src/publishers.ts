// Publisher display vocabulary.
//
// Extracted verbatim from `components/FilterBar.tsx` (2026-08-10) when that
// component was deleted: the browse page replaced the old filter chip strip
// with its own rail, leaving FilterBar unreferenced, but `publisherLabel` was
// still the single source of truth for how a stored publisher code is spelled
// on screen. A display vocabulary is not a component, so it lives here rather
// than inside one.

// The corpus's publisher CODES, from data/ingest-plan.yaml (`publisher:`
// values). The stored codes are unchanged — changing them would be a re-tag of
// every ingested document and the ingest plan. What changed (Destin, 2026-08-03)
// is only the LABEL each code displays as: the Governor's Office of Strategic
// Planning & Budgeting publishes the Executive Budget ("governor" → OSPB), the
// General Accounting Office publishes the AFR ("agao" → GAO), and the separate
// "legislature" code is folded into JLBC — the budget bills it tagged are JLBC
// products in this corpus. Displayed as three chips: JLBC · OSPB · GAO.
const PUBLISHERS: { value: string; label: string }[] = [
  { value: "jlbc", label: "JLBC" },
  { value: "governor", label: "OSPB" },
  { value: "agao", label: "GAO" },
  { value: "legislature", label: "JLBC" },
];

/** The DISPLAY label for a stored publisher code, so result surfaces and
 *  filter menus can never disagree about what "agao" is called.
 *
 *  Two codes map to JLBC ("jlbc" and the folded "legislature") — this is a
 *  display fold, not a data change: the stored code is untouched, only what
 *  the reader sees. An unknown code falls through to itself rather than being
 *  hidden or guessed at (an honest raw code beats an invented label). */
export function publisherLabel(value: string): string {
  return PUBLISHERS.find((p) => p.value === value)?.label ?? value;
}
