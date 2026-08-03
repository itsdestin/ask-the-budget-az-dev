import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
// Namespace import, and every call goes through `api.corpusDocuments()`: the page's test
// intercepts the request with vi.spyOn(api, "corpusDocuments"), which can only see calls
// made through the module object.
import * as api from "../api";
import { publisherLabel } from "../components/FilterBar";
import { SearchIcon } from "../components/SearchIcon";
import { familyOf, familyTitle, reportFormats } from "../reportFamilies";

// Budget Documents — a browse-first directory, rebuilt 2026-08-03 from the
// approved interactive mockup `mockups/budget-documents-browse.html` (port,
// don't redesign — spec S12). It replaces the old retrieval-backed "type a
// search to see anything" results page with the Fiscal Notes layout: a sticky
// `.docside` filter rail (search pill + two named multi-select dropdowns)
// beside a `.docmain` results column of one `.yg` year card per fiscal year,
// each holding one `.grp` card per report family.
//
// THE PAGE AUTO-LOADS WITH CONTENT: an empty search box shows the corpus
// grouped by fiscal year — there is no "type to begin" dead end. The data is
// ONE listing (`GET /api/corpus/documents`), filtered/grouped/searched
// entirely client-side, so there is no server round-trip per keystroke.
//
// Differences from the old page (all Destin-approved in the mockup; see its
// header comment):
//   - Rail filters are Document Type and Fiscal Year only (multi-select, "Any
//     type" / "Any year" defaults, trigger shows the pick or "N selected",
//     tints gold while active). NO Publisher filter — publisher is a chip on
//     each row (the folded JLBC · OSPB · GAO vocabulary, see publisherLabel).
//   - Two card states per family: IDLE (empty box) a bare report card whose
//     top-level row IS the report; SEARCHING the matched agency page promoted
//     to the top with "Part of the FY Y Baseline" framing and the rest behind
//     "N more matches".
//   - Searching collapses the year cards into ONE unified "Results" card
//     (newest year first); clearing returns to the year browse.
//   - Latest FY expanded, prior years collapsed by default; toggle state
//     persists across filter/search round-trips.
//   - Single-document families (AFR, Exec Budget) get no dashed tray.
//   - Removed: the per-card Sort menu (fixed title A→Z), the `.doc-ic` icon
//     tile (the publisher chip leads the row), the "N documents" sub-line, and
//     the per-type divider headers.
//
// PORT DEVIATIONS from the mockup's throwaway JS (same rendering, same values):
//   1. React state, not DOM-innerHTML re-renders. The mockup re-renders
//      `#cards` wholesale on every click (renderCards), which destroys focus.
//      Here every year's body is MOUNTED ONCE and shown/hidden via the
//      `hidden` attribute, so a collapsed year's open trays and — critically —
//      the keyboard focus on a year-toggle button survive a toggle. (The
//      mockup re-creates the button on each render; a real port must not.)
//   2. `?q=` is still honored (Home's hero navigates to /search?q=…): an
//      arriving ?q= seeds the rail box and lands in the unified-search state,
//      and the box stays one-way synced FROM the URL so back/forward works.
//      The old page's retrieval-backed keyword search is GONE — this page
//      searches document titles/publisher, not chunk text (the listing has no
//      chunk text). Content search lives in AI Mode now.

// ---------------------------------------------------------------------------
// Types + data shaping
// ---------------------------------------------------------------------------

/** What the page is currently showing. One state, so "loading" / "error" /
 *  "ready" can never be true at the same time. */
type Phase =
  | { kind: "loading" }
  | { kind: "ready"; docs: api.CorpusDocument[] }
  | { kind: "error"; message: string };

/** The five report families, in display order within a year card — the same
 *  order the mockup lists them and `reportFamilies.ts` names them. */
const FAMILY_ORDER = [
  "Baseline",
  "Appropriations Report",
  "Annual Financial Report",
  "Executive Budget",
  "Budget Bill",
];

/** One report family within one fiscal year, with its documents. */
interface FamilyGroup {
  family: string;
  docs: api.CorpusDocument[];
}

/** The fixed document order inside a family: title A→Z (the mockup's one
 *  order — its per-card "Sort A→Z" menu was removed, so there is nothing
 *  else). Case-insensitive so "AHCCCS" and "Arizona…" interleave the way a
 *  reader expects. */
const byTitle = (a: api.CorpusDocument, b: api.CorpusDocument) =>
  a.title.toLowerCase().localeCompare(b.title.toLowerCase());

/** Group a set of documents into the page's year → family structure. Years are
 *  returned newest-first; families in FAMILY_ORDER; docs title-sorted. */
function groupCorpus(docs: api.CorpusDocument[]): { year: number; families: FamilyGroup[] }[] {
  const byYear = new Map<number, Map<string, api.CorpusDocument[]>>();
  for (const d of docs) {
    // A document with no fiscal_year can't be placed in a year card. The
    // browse page's whole structure is year-grouped, so an unknown year is
    // bucketed as 0 ("Fiscal year unknown") rather than dropped silently —
    // it still renders, honestly labeled, at the bottom.
    const year = d.fiscal_year ?? 0;
    const family = familyOf(d.doc_type);
    if (!byYear.has(year)) byYear.set(year, new Map());
    const fams = byYear.get(year)!;
    if (!fams.has(family)) fams.set(family, []);
    fams.get(family)!.push(d);
  }
  return [...byYear.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, fams]) => ({
      year,
      families: FAMILY_ORDER.filter((f) => fams.has(f)).map((f) => ({
        family: f,
        docs: [...fams.get(f)!].sort(byTitle),
      })),
    }));
}

/** Does this document match the typed query? Ported from the mockup's
 *  queryHit: a case-insensitive substring of the title OR of the publisher's
 *  DISPLAY label (so "osb" finds OSPB docs). NOT multi-term AND — the mockup
 *  matches a single substring, and splitting would redesign the filter. */
function queryHit(d: api.CorpusDocument, q: string): boolean {
  if (!q) return false;
  const needle = q.toLowerCase();
  return (
    d.title.toLowerCase().includes(needle) ||
    publisherLabel(d.publisher).toLowerCase().includes(needle)
  );
}

/** Passes the two rail filters (Document Type family, Fiscal Year). An empty
 *  set means "any". */
function passesFilters(
  d: api.CorpusDocument,
  types: ReadonlySet<string>,
  years: ReadonlySet<number>,
): boolean {
  if (types.size && !types.has(familyOf(d.doc_type))) return false;
  if (years.size && !years.has(d.fiscal_year ?? 0)) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Glyphs — the mockup's inline SVGs, paths verbatim.
// ---------------------------------------------------------------------------

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}
function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 4h13a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z" />
      <path d="M4 18a2 2 0 0 1 2-2h13" />
    </svg>
  );
}
function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
function OpenIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Document + report rows
// ---------------------------------------------------------------------------

/** The copper publisher chip that leads every row — the mockup's one new
 *  element. Budget docs have no bill number, so the publisher is the
 *  identifying chip. ONE color for every publisher (it labels the source, it
 *  doesn't color-code it); the folded JLBC · OSPB · GAO vocabulary. */
function PubChip({ publisher }: { publisher: string }) {
  return <span className="doc-pub">{publisherLabel(publisher)}</span>;
}

/** A single-document row (an agency page). The whole row links to the source
 *  PDF; with no verified `doc_url` it renders unlinked rather than as a dead
 *  href (honesty invariant). */
function DocRow({ doc }: { doc: api.CorpusDocument }) {
  const body = (
    <>
      <PubChip publisher={doc.publisher} />
      <div className="doc-main">
        <span className="doc-title">{doc.title}</span>
      </div>
      {doc.doc_url && (
        <span className="doc-pill">
          <OpenIcon /> Open
        </span>
      )}
    </>
  );
  return doc.doc_url ? (
    <a className="doc" href={doc.doc_url} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  ) : (
    <div className="doc doc-unlinked">{body}</div>
  );
}

/** A whole-REPORT top-level row (idle state): "FY Y Family". Clicking opens
 *  the single-file PDF when a hand-verified URL exists, else the family's
 *  first document (which itself may be unlinked). */
function ReportRow({ year, family, docs }: { year: number; family: string; docs: api.CorpusDocument[] }) {
  const title = familyTitle(family, year === 0 ? null : year);
  // A report family's documents share one publisher in this corpus, so the
  // chip reads the first document's — same posture as the mockup.
  const publisher = docs[0]?.publisher ?? "";
  const { singleFile } = reportFormats(family, year === 0 ? null : year);
  const href = singleFile ?? docs[0]?.doc_url ?? null;
  const body = (
    <>
      <PubChip publisher={publisher} />
      <div className="doc-main">
        <span className="doc-title">{title}</span>
      </div>
      {href && (
        <span className="doc-pill">
          <OpenIcon /> Open
        </span>
      )}
    </>
  );
  return href ? (
    <a className="doc" href={href} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  ) : (
    <div className="doc doc-unlinked">{body}</div>
  );
}

// ---------------------------------------------------------------------------
// Family cards — the two states
// ---------------------------------------------------------------------------

/** ONE family card, two states (the mockup's familyCard):
 *
 *  IDLE (search box empty): a bare report card — the top-level IS the report,
 *  with a dashed box listing/collapsing the documents inside it. No "Part of"
 *  framing. A single-document family gets NO dashed tray.
 *
 *  SEARCHING: the most-relevant matching agency page is promoted to the top,
 *  the dashed box switches to "Part of the FY Y Family", and the other matches
 *  sit behind "N more matches". */
function FamilyCard({
  year,
  group,
  query,
  trayOpen,
  onToggleTray,
}: {
  year: number;
  group: FamilyGroup;
  query: string;
  trayOpen: boolean;
  onToggleTray: () => void;
}) {
  const searching = query !== "";
  const { singleFile } = reportFormats(group.family, year === 0 ? null : year);
  const title = familyTitle(group.family, year === 0 ? null : year);

  if (!searching) {
    const docs = group.docs; // already title-sorted by groupCorpus
    // A single-document family (the AFR is only ever one doc) gets NO dashed
    // "N documents / Browse documents" box — the report row already links the
    // one document, so the box would only restate it.
    if (docs.length === 1) {
      return (
        <article className="grp">
          <ReportRow year={year} family={group.family} docs={docs} />
        </article>
      );
    }
    return (
      <article className="grp">
        <ReportRow year={year} family={group.family} docs={docs} />
        <div className="ctx">
          <div className="ctx-row">
            <span className="badge">
              <DocIcon /> {docs.length} documents in this report
            </span>
            <span className="spacer" />
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              {trayOpen ? "Hide documents" : "Browse documents"} <ChevronIcon />
            </button>
            {singleFile && (
              <a className="grp-full" href={singleFile} target="_blank" rel="noopener noreferrer">
                <BookIcon /> Full report
              </a>
            )}
          </div>
          {trayOpen && (
            <div className="tray open">
              {docs.map((d) => (
                <DocRow key={d.doc_id} doc={d} />
              ))}
            </div>
          )}
        </div>
      </article>
    );
  }

  // Search state: promote the best (title-sorted-first) match; the rest
  // collapse behind "N more".
  const matches = group.docs.filter((d) => queryHit(d, query));
  if (!matches.length) return null;
  const [featured, ...siblings] = matches;
  return (
    <article className="grp">
      <DocRow doc={featured} />
      <div className="ctx">
        <div className="ctx-row">
          <span className="badge">
            <BookIcon /> Part of the {title}
          </span>
          <span className="spacer" />
          {siblings.length > 0 && (
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              {siblings.length === 1 ? "1 more match" : `${siblings.length} more matches`}{" "}
              <ChevronIcon />
            </button>
          )}
          {singleFile && (
            <a className="grp-full" href={singleFile} target="_blank" rel="noopener noreferrer">
              <BookIcon /> Full report
            </a>
          )}
        </div>
        {trayOpen && siblings.length > 0 && (
          <div className="tray open">
            {siblings.map((d) => (
              <DocRow key={d.doc_id} doc={d} />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// The collapsible year card
// ---------------------------------------------------------------------------

/** One fiscal-year card. The head is a full-width toggle button; the newest
 *  in-scope year starts open, prior years collapsed. The body is MOUNTED ONCE
 *  and toggled via `hidden` (see port deviation 1): open trays inside it, and
 *  the keyboard focus on the head button, survive a collapse/expand. */
const YearCard = memo(function YearCard({
  year,
  families,
  query,
  isOpen,
  onToggleYear,
  openTrays,
  onToggleTray,
}: {
  year: number;
  families: FamilyGroup[];
  query: string;
  isOpen: boolean;
  onToggleYear: (year: number) => void;
  openTrays: ReadonlySet<string>;
  onToggleTray: (key: string) => void;
}) {
  const total = families.reduce((n, f) => n + f.docs.length, 0);
  const yearLabel = year === 0 ? "Fiscal year unknown" : `Fiscal Year ${year}`;
  return (
    <section className={`yg${isOpen ? " yg-open" : " yg-closed"}`} data-year-card={year}>
      <button
        type="button"
        className="yg-head"
        aria-expanded={isOpen}
        aria-label={`${yearLabel}: ${families.length} report${families.length === 1 ? "" : "s"}, ${total} document${total === 1 ? "" : "s"}`}
        onClick={() => onToggleYear(year)}
      >
        <div className="yg-ttl">
          <span className="yg-yr">{yearLabel}</span>
          <span className="yg-meta">
            {families.length} report{families.length === 1 ? "" : "s"} · {total} document
            {total === 1 ? "" : "s"}
          </span>
        </div>
        <span className={`yg-chev${isOpen ? " open" : ""}`}>
          <ChevronIcon />
        </span>
      </button>
      {/* `hidden`, not conditional mount: keeps tray state and head focus. */}
      <div className="yg-body" hidden={!isOpen}>
        {families.map((f) => (
          <FamilyCard
            key={f.family}
            year={year}
            group={f}
            query={query}
            trayOpen={openTrays.has(`${year}|${f.family}`)}
            onToggleTray={() => onToggleTray(`${year}|${f.family}`)}
          />
        ))}
      </div>
    </section>
  );
});

// ---------------------------------------------------------------------------
// The rail's named multi-select dropdown (the search FilterBar recipe)
// ---------------------------------------------------------------------------

interface MultiSelectOption {
  key: string;
  label: string;
  count: number;
}

/** One labelled multi-select dropdown — "Document Type" / "Fiscal Year". The
 *  trigger shows "Any …" when nothing is picked, the single pick's label, or
 *  "N selected"; it tints gold (`.has`) while active. The menu stays open for
 *  multi-picking; outside click / Escape closes it (the FilterBar idiom). */
function RailMultiSelect({
  label,
  anyLabel,
  options,
  selected,
  onToggle,
}: {
  label: string;
  anyLabel: string;
  options: MultiSelectOption[];
  selected: ReadonlySet<string>;
  onToggle: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const labelId = useRef(`ms-${label.replace(/\W+/g, "-").toLowerCase()}`).current;

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const triggerText =
    selected.size === 0
      ? anyLabel
      : selected.size === 1
        ? (options.find((o) => selected.has(o.key))?.label ?? anyLabel)
        : `${selected.size} selected`;

  return (
    <div className="fgrp">
      <div className="flbl" id={labelId}>
        {label}
      </div>
      <div className="fctl" ref={root}>
        <button
          type="button"
          className={selected.size > 0 ? "fbtn has" : "fbtn"}
          aria-expanded={open}
          aria-labelledby={labelId}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="fb-label">{triggerText}</span>
          <svg className="chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="m1 1 4 4 4-4" />
          </svg>
        </button>
        {open && (
          <div className="fmenu" role="group" aria-label={`${label} options`}>
            {options.map((o) => {
              const on = selected.has(o.key);
              return (
                <button
                  key={o.key}
                  type="button"
                  className={on ? "fopt on" : "fopt"}
                  aria-pressed={on}
                  onClick={() => onToggle(o.key)}
                >
                  <span className="ck" aria-hidden="true">
                    <svg viewBox="0 0 12 10" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <path d="m1 5 3.5 3.5L11 1" />
                    </svg>
                  </span>
                  {o.label}
                  <span className="fopt-n">{o.count}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Search() {
  const [params] = useSearchParams();
  // ?q= is the read-only hand-off (Home's hero navigates here with it). It
  // seeds the box; it does NOT live-sync while the user types (the box is the
  // ephemeral state).
  const urlQuery = (params.get("q") ?? "").trim();

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState(urlQuery);
  const [types, setTypes] = useState<ReadonlySet<string>>(new Set());
  const [years, setYears] = useState<ReadonlySet<number>>(new Set());
  // Years the user has manually toggled open/closed. Absent = the default:
  // newest in-scope year expanded, every prior year collapsed.
  const [yearToggle, setYearToggle] = useState<ReadonlyMap<number, boolean>>(new Map());
  // "year|family" keys with an open tray.
  const [openTrays, setOpenTrays] = useState<ReadonlySet<string>>(new Set());
  const box = useRef<HTMLInputElement>(null);

  // One-way sync FROM the URL: a ?q= arriving while the page is mounted (Home
  // hero, back/forward) replaces the box. Typing does NOT write the URL.
  useEffect(() => setQuery(urlQuery), [urlQuery]);

  useEffect(() => {
    let ignore = false;
    setPhase({ kind: "loading" });
    api.corpusDocuments().then(
      (data) => {
        if (!ignore) setPhase({ kind: "ready", docs: data.documents });
      },
      (err: unknown) => {
        if (!ignore)
          setPhase({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
      },
    );
    return () => {
      ignore = true;
    };
  }, [attempt]);

  const docs = phase.kind === "ready" ? phase.docs : [];
  const q = query.trim();
  const searching = q !== "";

  // The whole corpus grouped into year → family, BEFORE the rail filters (the
  // filter option counts are computed off this so a picked filter doesn't
  // erase its own siblings' counts).
  const grouped = useMemo(() => groupCorpus(docs), [docs]);

  const allYears = useMemo(() => grouped.map((g) => g.year), [grouped]);

  // In-scope years: the picked ones, else every year. Newest-first already.
  const scopedYears = useMemo(
    () => (years.size ? allYears.filter((y) => years.has(y)) : allYears),
    [allYears, years],
  );

  // Filter option counts (docs per family / per year), from the FULL corpus.
  const typeOptions = useMemo<MultiSelectOption[]>(
    () =>
      FAMILY_ORDER.map((f) => ({
        key: f,
        label: f,
        count: docs.filter((d) => familyOf(d.doc_type) === f).length,
      })),
    [docs],
  );
  const yearOptions = useMemo<MultiSelectOption[]>(
    () =>
      allYears.map((y) => ({
        key: String(y),
        label: y === 0 ? "Unknown" : `FY ${y}`,
        count: docs.filter((d) => (d.fiscal_year ?? 0) === y).length,
      })),
    [allYears, docs],
  );

  // The filtered, in-scope year cards.
  const visibleGroups = useMemo(() => {
    return scopedYears
      .map((year) => {
        const g = grouped.find((x) => x.year === year);
        if (!g) return null;
        const families = g.families
          .map((f) => ({ ...f, docs: f.docs.filter((d) => passesFilters(d, types, years)) }))
          .filter((f) => f.docs.length > 0);
        return families.length ? { year, families } : null;
      })
      .filter((g): g is { year: number; families: FamilyGroup[] } => g !== null);
  }, [scopedYears, grouped, types, years]);

  // Default open year: newest in-scope. A manual toggle overrides it.
  const latestYear = visibleGroups[0]?.year ?? null;
  const isYearOpen = (year: number) =>
    yearToggle.has(year) ? yearToggle.get(year)! : year === latestYear;

  // --- counts for the status line -------------------------------------------
  const matched = docs.filter((d) => passesFilters(d, types, years) && (!searching || queryHit(d, q)));
  const matchedFamilies = new Set(matched.map((d) => `${d.fiscal_year ?? 0}|${familyOf(d.doc_type)}`)).size;
  const yearScope = years.size
    ? years.size === 1
      ? `FY ${[...years][0]}`
      : `${years.size} fiscal years`
    : "all fiscal years";

  function toggleIn(setter: React.Dispatch<React.SetStateAction<ReadonlySet<string>>>, key: string) {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }
  const toggleYearFilter = (key: string) => {
    const y = Number(key);
    setYears((prev) => {
      const next = new Set(prev);
      if (next.has(y)) next.delete(y);
      else next.add(y);
      return next;
    });
  };
  const toggleYearCard = (year: number) =>
    setYearToggle((prev) => new Map(prev).set(year, !isYearOpen(year)));
  const toggleTray = (key: string) =>
    setOpenTrays((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const clearQuery = () => {
    setQuery("");
    box.current?.focus();
  };

  // --- the unified search view ----------------------------------------------
  // Collapse the year cards into ONE "Results" card holding every matching
  // family card across in-scope years, newest year first.
  const searchTiles = searching
    ? visibleGroups.flatMap((g) =>
        g.families
          .filter((f) => f.docs.some((d) => queryHit(d, q)))
          .map((f) => ({ year: g.year, family: f })),
      )
    : [];
  const searchTotal = searching
    ? docs.filter((d) => passesFilters(d, types, years) && queryHit(d, q)).length
    : 0;

  return (
    <main className="page-docs" data-testid="search">
      <section className="subhero">
        <div className="wrap">
          <h1>Budget Documents</h1>
          <p className="lead">
            Every Arizona budget document ingested so far — baselines, appropriations reports,
            annual financial reports, executive budgets, and budget bills.
          </p>
          <div className="chips">
            <span className="chip">
              <DocIcon /> JLBC · OSPB · GAO
            </span>
            <span className="chip">
              <SearchIcon /> Every document opens its source PDF
            </span>
          </div>
        </div>
      </section>

      <div className="wrap docwrap">
        <p className="fnnote docstatus" role="status">
          {phase.kind === "loading" && "Loading…"}
          {phase.kind === "error" && <span className="err">{phase.message}</span>}
          {phase.kind === "ready" &&
            (searching
              ? `${matched.length} document${matched.length === 1 ? "" : "s"} across ${matchedFamilies} report${matchedFamilies === 1 ? "" : "s"}, in ${yearScope}, matching “${q}”.`
              : `${matchedFamilies} report${matchedFamilies === 1 ? "" : "s"} · ${matched.length} document${matched.length === 1 ? "" : "s"}, across ${yearScope}.`)}
        </p>

        <div className="doclayout">
          <aside className="docside">
            <div className="fgrp">
              <label className="fside-search">
                <SearchIcon />
                <input
                  ref={box}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Agency or keyword…"
                  aria-label="Filter documents by agency or keyword"
                  autoComplete="off"
                />
                <button
                  type="button"
                  className={query ? "clr-x show" : "clr-x"}
                  aria-label="Clear search"
                  onClick={clearQuery}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
                    <path d="M6 6l12 12M18 6 6 18" />
                  </svg>
                </button>
              </label>
            </div>

            <RailMultiSelect
              label="Document Type"
              anyLabel="Any type"
              options={typeOptions}
              selected={types}
              onToggle={(k) => toggleIn(setTypes, k)}
            />
            <RailMultiSelect
              label="Fiscal Year"
              anyLabel="Any year"
              options={yearOptions}
              selected={new Set([...years].map(String))}
              onToggle={toggleYearFilter}
            />
          </aside>

          <div className="docmain">
            {phase.kind === "error" ? (
              <div className="allbar">
                <button type="button" className="allbtn" onClick={() => setAttempt((a) => a + 1)}>
                  Retry
                </button>
              </div>
            ) : searching ? (
              <section className="yg">
                <div className="yg-head-static">
                  <div className="yg-ttl">
                    <span className="yg-yr">Results</span>
                    <span className="yg-meta">
                      {searchTiles.length} report{searchTiles.length === 1 ? "" : "s"} · {searchTotal}{" "}
                      document{searchTotal === 1 ? "" : "s"} matching “{q}”
                    </span>
                  </div>
                </div>
                {searchTiles.length === 0 ? (
                  <p className="empty">
                    No documents match “{q}” with those filters — try clearing one.
                  </p>
                ) : (
                  searchTiles.map(({ year, family }) => (
                    <FamilyCard
                      key={`${year}|${family.family}`}
                      year={year}
                      group={family}
                      query={q}
                      trayOpen={openTrays.has(`${year}|${family.family}`)}
                      onToggleTray={() => toggleTray(`${year}|${family.family}`)}
                    />
                  ))
                )}
              </section>
            ) : visibleGroups.length === 0 ? (
              <section className="yg">
                <p className="empty">No documents match those filters — try clearing one.</p>
              </section>
            ) : (
              visibleGroups.map((g) => (
                <YearCard
                  key={g.year}
                  year={g.year}
                  families={g.families}
                  query={q}
                  isOpen={isYearOpen(g.year)}
                  onToggleYear={toggleYearCard}
                  openTrays={openTrays}
                  onToggleTray={toggleTray}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
