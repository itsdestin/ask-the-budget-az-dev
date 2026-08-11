import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
// Namespace import, and every call goes through `api.corpusDocuments()`: the page's test
// intercepts the request with vi.spyOn(api, "corpusDocuments"), which can only see calls
// made through the module object.
import * as api from "../api";
import { publisherLabel } from "../publishers";
import { SearchIcon } from "../components/SearchIcon";
import { BookIcon, ChevronIcon, DocIcon, OpenIcon } from "../components/DocIcons";
import { ReportChooser } from "../components/ReportChooser";
import { PassageCard } from "../components/PassageCard";
import { SourcePanel } from "../pdf/SourcePanel";
import { familyOf, familyTitle, reportFormats } from "../reportFamilies";
import { groupPassages, toSearchFilters } from "../search/contentSearch";

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

/** Which half of the search the page is showing. */
type Mode = "titles" | "contents";

/** The content (retrieval) request's state. One value, so loading / error /
 *  ready can never be true at the same time. */
type ContentPhase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; results: api.SearchResult[] }
  | { kind: "error"; message: string };

/** How long the box must be quiet, with ZERO title matches, before content
 *  search fires on its own. Long enough that it never fires mid-word; short
 *  enough that it feels like the page answering rather than the user waiting. */
const ESCALATE_MS = 2000;

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
      families: orderFamilies([...fams.keys()]).map((f) => ({
        family: f,
        docs: [...fams.get(f)!].sort(byTitle),
      })),
    }));
}

/** The five curated families in FAMILY_ORDER, then anything else alphabetically.
 *
 *  WHY the trailing group exists: `familyOf` documents that an unknown doc_type
 *  "still groups, it just isn't prettified" — it returns the raw slug as its own
 *  family. This used to be `FAMILY_ORDER.filter(f => fams.has(f))`, which SILENTLY
 *  DROPPED every such family from the page while the status line still counted its
 *  documents, so the page could claim more documents than it rendered. Appending
 *  them keeps familyOf's contract true and makes the counts describe what is on
 *  screen. A new doc_type now appears under its raw slug — ugly, and the fix is to
 *  name it in FAMILY_OF_DOC_TYPE, not to hide the document. */
function orderFamilies(found: string[]): string[] {
  const known = FAMILY_ORDER.filter((f) => found.includes(f));
  const unknown = found.filter((f) => !FAMILY_ORDER.includes(f)).sort();
  return [...known, ...unknown];
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

/** The three-way "how does the whole report open" decision, shared by
 *  ReportRow (the browse view's own row) and FamilyCard's search branch
 *  (Task 9, 2026-08-10: a typed query had NO way to open the whole report —
 *  only the browse branch ever called the `onChoose` prop FamilyCard already
 *  received). BOTH curated formats -> open the chooser modal; exactly one —
 *  or, for a family with no curated formats, its lone document's own
 *  `doc_url` (the AFR's case) — link straight to it (a one-option chooser is
 *  pointless); NEITHER -> no control, never a dead href.
 *
 *  WHY a function and not one shared JSX block: the two call sites render
 *  structurally different markup — ReportRow wraps its ENTIRE row in the
 *  resulting button/link, while the search branch adds one small pill beside
 *  "N more matches" — so there is no single element tree to share. But the
 *  THREE-WAY RULE itself has to stay byte-identical, and two hand-copies of a
 *  three-way rule is exactly how one silently stops matching a case added
 *  only to the other. This is the one place that rule is written down; each
 *  call site supplies only its own JSX for whichever state comes back. */
type FullReportAction =
  | { kind: "choose"; onClick: () => void }
  | { kind: "link"; href: string }
  | { kind: "none" };

function resolveFullReportAction(
  family: string,
  year: number,
  docs: api.CorpusDocument[],
  onChoose: () => void,
): FullReportAction {
  const { singleFile, linkedToc } = reportFormats(family, year === 0 ? null : year);
  if (singleFile && linkedToc) return { kind: "choose", onClick: onChoose };
  const href = singleFile ?? linkedToc ?? docs[0]?.doc_url ?? null;
  return href ? { kind: "link", href } : { kind: "none" };
}

/** A whole-REPORT top-level row: "FY Y Family".
 *
 *  The row IS the report, so its action is the report — "Full report"
 *  REPLACES the generic "Open" pill, and the duplicate button is gone from the
 *  dashed block below (Destin, 2026-08-10).
 *
 *  THE RULE, unchanged from master: both formats -> ask which; exactly one ->
 *  go straight to it (a one-option chooser is pointless); neither -> no pill,
 *  and the row renders unlinked rather than as a dead href.
 *
 *  WHY the both-formats case is a <button> and not an <a>: the click has to
 *  open a dialog, and an interactive control nested inside a link is invalid
 *  markup. `.doc.rowbtn` carries UA resets only, so it looks identical to the
 *  anchors beside it. */
function ReportRow({
  year,
  family,
  docs,
  onChoose,
}: {
  year: number;
  family: string;
  docs: api.CorpusDocument[];
  onChoose: () => void;
}) {
  const title = familyTitle(family, year === 0 ? null : year);
  // A report family's documents share one publisher in this corpus, so the
  // chip reads the first document's — same posture as the mockup.
  const publisher = docs[0]?.publisher ?? "";
  const action = resolveFullReportAction(family, year, docs, onChoose);
  const body = (
    <>
      <PubChip publisher={publisher} />
      <div className="doc-main">
        <span className="doc-title">{title}</span>
      </div>
      {action.kind !== "none" && (
        <span className="doc-pill is-full">
          <BookIcon /> Full report
        </span>
      )}
    </>
  );
  if (action.kind === "choose") {
    return (
      <button type="button" className="doc rowbtn" onClick={action.onClick}>
        {body}
      </button>
    );
  }
  return action.kind === "link" ? (
    <a className="doc" href={action.href} target="_blank" rel="noopener noreferrer">
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
  onChoose,
}: {
  year: number;
  group: FamilyGroup;
  query: string;
  trayOpen: boolean;
  onToggleTray: () => void;
  onChoose: () => void;
}) {
  const searching = query !== "";
  const title = familyTitle(group.family, year === 0 ? null : year);

  if (!searching) {
    const docs = group.docs; // already title-sorted by groupCorpus
    // A single-document family (the AFR is only ever one doc) gets NO dashed
    // "N sections / Browse sections" box — the report row already links the
    // one document, so the box would only restate it.
    if (docs.length === 1) {
      return (
        <article className="grp">
          <ReportRow year={year} family={group.family} docs={docs} onChoose={onChoose} />
        </article>
      );
    }
    return (
      <article className="grp">
        <ReportRow year={year} family={group.family} docs={docs} onChoose={onChoose} />
        <div className="ctx">
          <div className="ctx-row">
            <span className="badge">
              {/* "sections", not "documents" (Destin, 2026-08-10). The page
                  counts REPORTS; a Baseline book's per-agency pages are parts
                  of one report, and calling them documents here contradicted
                  every count above. Same vocabulary on the tray toggle. */}
              <DocIcon /> {docs.length} sections in this report
            </span>
            <span className="spacer" />
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              {trayOpen ? "Hide sections" : "Browse sections"} <ChevronIcon />
            </button>
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
  // Task 9: the SAME three-way rule ReportRow follows, off `group.docs` (the
  // family's full, rail-filtered doc list — not just the matched subset) so
  // the AFR-style single-document fallback agrees with what the browse view
  // would show for this exact family/year, not with whichever doc happened
  // to match the query.
  const fullReport = resolveFullReportAction(group.family, year, group.docs, onChoose);
  return (
    <article className="grp">
      <DocRow doc={featured} />
      <div className="ctx">
        <div className="ctx-row">
          <span className="badge">
            <BookIcon /> Part of the {title}
          </span>
          <span className="spacer" />
          {/* Full report BEFORE "N more matches": the idle card's ctx-row
              (above) always ends in the tray-toggle button, and keeping "N
              more matches" last here too means that button stays in the
              same reading position in both card states, instead of moving
              depending on whether a full-report control also rendered. */}
          {fullReport.kind === "choose" && (
            <button type="button" className="grp-more" onClick={fullReport.onClick}>
              <BookIcon /> Full report
            </button>
          )}
          {fullReport.kind === "link" && (
            <a className="grp-more" href={fullReport.href} target="_blank" rel="noopener noreferrer">
              <BookIcon /> Full report
            </a>
          )}
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
  onChoose,
}: {
  year: number;
  families: FamilyGroup[];
  query: string;
  isOpen: boolean;
  onToggleYear: (year: number) => void;
  openTrays: ReadonlySet<string>;
  onToggleTray: (key: string) => void;
  onChoose: (year: number, family: string) => void;
}) {
  const yearLabel = year === 0 ? "Fiscal year unknown" : `Fiscal Year ${year}`;
  return (
    <section className={`yg${isOpen ? " yg-open" : " yg-closed"}`} data-year-card={year}>
      <button
        type="button"
        className="yg-head"
        aria-expanded={isOpen}
        aria-label={`${yearLabel}: ${families.length} report${families.length === 1 ? "" : "s"}`}
        onClick={() => onToggleYear(year)}
      >
        <div className="yg-ttl">
          <span className="yg-yr">{yearLabel}</span>
          {/* Reports only — the per-agency document total was dropped here
              (Destin, 2026-08-10). See the counting note in the page body. */}
          <span className="yg-meta">
            {families.length} report{families.length === 1 ? "" : "s"}
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
            onChoose={() => onChoose(year, f.family)}
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
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(() => (params.get("q") ?? "").trim());
  const [mode, setMode] = useState<Mode>(() =>
    params.get("in") === "contents" ? "contents" : "titles",
  );
  const [content, setContent] = useState<ContentPhase>({ kind: "idle" });
  // Bumped to re-run an identical content query. WHY it exists: the fetch
  // effect keys off (mode, query, filters); pressing Retry after a failure
  // changes none of them, so without this the button would appear to do
  // nothing — the exact dead end master's own `attempt` counter existed for.
  const [contentAttempt, setContentAttempt] = useState(0);

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [types, setTypes] = useState<ReadonlySet<string>>(new Set());
  const [years, setYears] = useState<ReadonlySet<number>>(new Set());
  // Years the user has manually toggled open/closed. Absent = the default:
  // newest in-scope year expanded, every prior year collapsed.
  const [yearToggle, setYearToggle] = useState<ReadonlyMap<number, boolean>>(new Map());
  // "year|family" keys with an open tray.
  const [openTrays, setOpenTrays] = useState<ReadonlySet<string>>(new Set());
  const box = useRef<HTMLInputElement>(null);
  // Which report's format chooser is open, or null. WHY it lives on the page
  // and not inside the card: `.report-modal` is `position:fixed`, and every
  // rule for it is scoped under `.page-docs` — mounted outside this <main> it
  // gets NO styling and paints as an unstyled block. (Hit exactly once, in
  // mockups/report-format-chooser.html.)
  const [chooser, setChooser] = useState<{ year: number; family: string } | null>(null);
  // The passage whose source is open, or null. Holds the display title
  // alongside the id because the row that was clicked already knows it —
  // app/routes/pdf.py's get_chunk deliberately does not return a second,
  // conflicting title.
  const [openPassage, setOpenPassage] = useState<{
    chunkId: string;
    docTitle: string;
    fiscalYear: number | null;
  } | null>(null);

  const openPassageById = (chunkId: string) => {
    const hit =
      content.kind === "ready" ? content.results.find((r) => r.chunk_id === chunkId) : undefined;
    setOpenPassage({
      chunkId,
      docTitle: hit?.doc_title ?? "",
      fiscalYear: hit?.fiscal_year ?? null,
    });
  };

  // --- URL <-> state, one direction at a time -------------------------------
  // `lastWritten` is what stops the two effects below from fighting: the write
  // effect records the string it put in the URL, and the read effect ignores
  // any URL it recognises as its own. Anything else is an OUTSIDE navigation
  // (Home's hero, a pasted link, Back) and is read into state.
  //
  // Every write is `replace: true`. Keystroke-level history entries are noise;
  // shareable links, correct restore on reload, and killing the identical-query
  // dead end are all satisfied without them (Destin, 2026-08-10).
  const lastWritten = useRef<string | null>(null);

  useEffect(() => {
    const next = new URLSearchParams();
    if (query) next.set("q", query);
    if (mode === "contents") next.set("in", "contents");
    const str = next.toString();
    if (str === lastWritten.current) return;
    lastWritten.current = str;
    setParams(next, { replace: true });
  }, [query, mode, setParams]);

  useEffect(() => {
    const str = params.toString();
    if (str === lastWritten.current) return;
    lastWritten.current = str;
    setQuery((params.get("q") ?? "").trim());
    setMode(params.get("in") === "contents" ? "contents" : "titles");
  }, [params]);

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

  // A new query, a new mode or a new filter means a new result set; leaving
  // the drawer open would keep a passage from the PREVIOUS search on screen
  // next to results that no longer contain it.
  useEffect(() => setOpenPassage(null), [q, mode, types, years]);

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
  // Built from the families actually PRESENT in the corpus, in the same order
  // the cards render (curated five, then unknown slugs). Hard-coding
  // FAMILY_ORDER here offered a filter for families that may not exist and —
  // worse — offered NO way to filter to a family rendered under a raw slug.
  const typeOptions = useMemo<MultiSelectOption[]>(() => {
    const present = orderFamilies([...new Set(docs.map((d) => familyOf(d.doc_type)))]);
    return present.map((f) => ({
      key: f,
      label: f,
      count: docs.filter((d) => familyOf(d.doc_type) === f).length,
    }));
  }, [docs]);
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

  // How many documents the TITLE filter matched. Zero is what arms escalation.
  const titleHits = useMemo(
    () => (searching ? docs.filter((d) => passesFilters(d, types, years) && queryHit(d, q)).length : 0),
    [docs, types, years, q, searching],
  );

  // Automatic escalation. A natural-language question essentially never
  // substring-matches a document title, while an agency name almost always
  // does — so "zero title hits" is an honest proxy for "this was a question
  // about CONTENT". Only fires from title mode, only with a query, only at
  // zero hits, and only after the box goes quiet.
  useEffect(() => {
    if (mode !== "titles" || !searching || titleHits > 0) return;
    // Nothing to escalate to until the listing has loaded — a corpus that has
    // not arrived yet has zero title hits for every query.
    if (phase.kind !== "ready") return;
    const timer = setTimeout(() => setMode("contents"), ESCALATE_MS);
    return () => clearTimeout(timer);
    // `q` is load-bearing here, not just an exhaustive-deps nit: titleHits
    // stays 0 across successive zero-hit keystrokes, so without `q` this
    // effect never re-ran after the FIRST such keystroke and the timer it
    // started kept ticking through every later one — escalation fired 2s
    // after the first zero-hit keystroke instead of 2s after the box went
    // quiet (Search.content.test.tsx: "typing again restarts the escalation
    // pause instead of firing on the stale timer").
  }, [mode, searching, titleHits, phase.kind, q]);

  // The content request itself. `ignore` is the stale-response guard: if the
  // query or the filters change while a request is in flight, React runs this
  // cleanup first, so the older (slower) answer returns here and does nothing
  // instead of painting over the newer one.
  useEffect(() => {
    if (mode !== "contents" || !searching) {
      setContent({ kind: "idle" });
      return;
    }
    let ignore = false;
    setContent({ kind: "loading" });
    api.search(q, toSearchFilters(types, years), "budget").then(
      (res) => {
        if (!ignore) setContent({ kind: "ready", results: res.results });
      },
      (err: unknown) => {
        // The api client already carries the backend's own `detail`; show it
        // verbatim rather than guessing at a cause.
        if (!ignore)
          setContent({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
      },
    );
    return () => {
      ignore = true;
    };
  }, [mode, q, types, years, searching, contentAttempt]);

  // Content results grouped one entry per document — the unit PassageCard
  // renders. Task 5 removed the equivalent memo from this file because it
  // was unused here at the time; recomputed now that content mode actually
  // renders. `content.results` only exists in the "ready" arm, so every
  // other ContentPhase kind renders zero documents.
  const passageDocs = useMemo(
    () => (content.kind === "ready" ? groupPassages(content.results) : []),
    [content],
  );

  // Default open year: newest in-scope. A manual toggle overrides it.
  const latestYear = visibleGroups[0]?.year ?? null;
  const isYearOpen = (year: number) =>
    yearToggle.has(year) ? yearToggle.get(year)! : year === latestYear;

  // --- counts for the status line -------------------------------------------
  //
  // THE PAGE COUNTS REPORTS, NOT SECTIONS (Destin, 2026-08-10). A Baseline book
  // is ONE report that happens to be ingested as ~100 per-agency documents; a
  // year card that announced "5 reports · 419 documents" was counting the
  // agency pages, which is not a number anyone asked for. Every count on this
  // page is now the number of top-level reports — one per report family per
  // fiscal year. The per-agency documents inside a report are still listed and
  // still counted, but only in the tray badge that describes that report's own
  // contents ("N sections in this report"), where the number means something.
  //
  // Derived from `visibleGroups`, which is what actually renders, rather than
  // recomputed off the raw doc list — a count computed independently of the
  // render can disagree with it, and this one did.
  const reportCount = visibleGroups.reduce(
    (n, g) => n + g.families.filter((f) => !searching || f.docs.some((d) => queryHit(d, q))).length,
    0,
  );
  const hasFilters = types.size > 0 || years.size > 0;
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
    setMode("titles");
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
            (mode === "contents" && searching
              ? content.kind === "ready"
                ? `${content.results.length} passage${content.results.length === 1 ? "" : "s"} in ${passageDocs.length} document${passageDocs.length === 1 ? "" : "s"}, matching “${q}”.`
                : ""
              : searching
                ? `${reportCount} report${reportCount === 1 ? "" : "s"} in ${yearScope}, matching “${q}”.`
                : `${reportCount} report${reportCount === 1 ? "" : "s"}, across ${yearScope}.`)}
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
                  onChange={(e) => {
                    // A new query is a new search, and titles are the cheap
                    // default — so editing the box always returns to title
                    // mode and re-arms escalation. Staying in content mode
                    // would fire a retrieval request on every keystroke.
                    setQuery(e.target.value);
                    setMode("titles");
                  }}
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
              <>
                <section className="yg">
                  <div className="yg-head-static">
                    <div className="yg-ttl">
                      {/* The header names the MODE. Without it there is no way
                          to tell which of the two searches produced the list.
                          Rendered UNCONDITIONALLY, including while a content
                          request is in flight — the loading block below ALSO
                          says "Searching document contents" at that moment,
                          so both are simultaneously present. That's fine: a
                          sighted reader sees two consistent statements of the
                          same fact, and this element (unlike the transient
                          loading block) exists in EVERY content-mode render,
                          so a test matching on it never races an in-flight
                          state change the way matching the loading block's
                          own (here-today-gone-on-ready) text would. */}
                      <span className="yg-yr">
                        Results{" "}
                        <span className="yg-mode">
                          (searching document {mode === "contents" ? "contents" : "titles"})
                        </span>
                      </span>
                      <span className="yg-meta">
                        {mode === "contents"
                          ? `${content.kind === "ready" ? content.results.length : 0} passage${
                              content.kind === "ready" && content.results.length === 1 ? "" : "s"
                            } · ${passageDocs.length} document${
                              passageDocs.length === 1 ? "" : "s"
                            } matching “${q}”`
                          : `${searchTiles.length} report${
                              searchTiles.length === 1 ? "" : "s"
                            } matching “${q}”`}
                      </span>
                    </div>
                  </div>

                  {mode === "contents" ? (
                    content.kind === "loading" ? (
                      <div className="docload" role="status">
                        <span className="spin" aria-hidden="true" />
                        <span>
                          Searching document contents
                          <span className="dots" aria-hidden="true" />
                          <span className="sub">
                            This may take a moment — reading inside every ingested PDF.
                          </span>
                        </span>
                      </div>
                    ) : content.kind === "error" ? (
                      <p className="empty">
                        <span className="err">{content.message}</span>{" "}
                        <button
                          type="button"
                          className="grp-more"
                          onClick={() => setContentAttempt((a) => a + 1)}
                        >
                          Retry
                        </button>
                      </p>
                    ) : passageDocs.length === 0 ? (
                      // Names what was searched — the text INSIDE the
                      // documents — so an empty answer never reads as "the
                      // corpus says nothing about this" when only titles were
                      // checked. And no filter advice unless a filter is set.
                      <p className="empty">
                        No passages inside the ingested documents mention “{q}”
                        {hasFilters ? " with those filters. Try clearing a filter." : "."}
                      </p>
                    ) : (
                      passageDocs.map((d) => (
                        <PassageCard
                          key={d.doc_id}
                          doc={d}
                          query={q}
                          trayOpen={openTrays.has(d.doc_id)}
                          onToggleTray={() => toggleTray(d.doc_id)}
                          onOpenPassage={openPassageById}
                        />
                      ))
                    )
                  ) : searchTiles.length === 0 ? (
                    <p className="empty">
                      {hasFilters
                        ? `No document titles match “${q}” with those filters — try clearing one.`
                        : `No document titles match “${q}”.`}
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
                        onChoose={() => setChooser({ year, family: family.family })}
                      />
                    ))
                  )}
                </section>

                {/* The toggle. ALWAYS shown once the box has text — including
                    on both empty states, so neither is ever a dead end. Hidden
                    ONLY while a request is in flight: there is nothing to
                    toggle to while the answer is pending, and offering it
                    invites a click that cancels work nobody asked to start. */}
                {!(mode === "contents" && content.kind === "loading") && (
                  <div className="allbar">
                    <button
                      type="button"
                      className={mode === "contents" ? "allbtn on" : "allbtn"}
                      aria-pressed={mode === "contents"}
                      onClick={() => setMode(mode === "contents" ? "titles" : "contents")}
                    >
                      <span className="all-off">
                        <SearchIcon /> Search document contents
                      </span>
                      <span className="all-on">↩ Back to title matches</span>
                    </button>
                  </div>
                )}
              </>
            ) : visibleGroups.length === 0 ? (
              <section className="yg">
                {/* Three different facts, and only one of them is the reader's
                    doing. An empty LISTING is not a filter problem — the page
                    used to say "try clearing one" with no filters set, blaming
                    the user for an empty or unreadable corpus.

                    The no-documents line deliberately names NO cause: the
                    route degrades a missing sidecar AND an unreadable chunk
                    table to the same empty list and cannot tell them apart
                    (see app/routes/corpus.py's `budget_doc_ids`), so any
                    "nothing has been ingested yet" here would be a guess. */}
                <p className="empty">
                  {docs.length === 0
                    ? "No budget documents are available."
                    : hasFilters
                      ? "No documents match those filters — try clearing one."
                      : "No budget documents are available."}
                </p>
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
                  onChoose={(y, family) => setChooser({ year: y, family })}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* Source drawer. It overlays the page rather than taking a column, so
          the results layout above is untouched. Like the chooser, it MUST
          render inside this <main>: `.pdf-drawer` is position:fixed and every
          rule for it is page-class scoped. */}
      {openPassage && (
        <SourcePanel
          // Keyed on the chunk so switching passages remounts, rather than
          // showing the previous page while the next one loads.
          key={openPassage.chunkId}
          chunkId={openPassage.chunkId}
          docTitle={openPassage.docTitle}
          fiscalYear={openPassage.fiscalYear}
          onClose={() => setOpenPassage(null)}
        />
      )}

      {chooser && (
        <ReportChooser
          title={familyTitle(chooser.family, chooser.year === 0 ? null : chooser.year)}
          formats={reportFormats(chooser.family, chooser.year === 0 ? null : chooser.year)}
          onClose={() => setChooser(null)}
        />
      )}
    </main>
  );
}
