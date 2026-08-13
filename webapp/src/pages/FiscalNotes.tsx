import { memo, useEffect, useMemo, useRef, useState } from "react";
// Namespace import, and every call goes through `api.fiscalNotes()`/`api.search()`: the
// page's tests intercept the requests with vi.spyOn(api, ...), which can only see calls
// made through the module object.
import * as api from "../api";
import type { Bill, Session } from "../api";
import { SearchIcon } from "../components/SearchIcon";
import { SourcePanel } from "../pdf/SourcePanel";
import { groupNotes, parseNoteTitle, resultsHeader, sessionLabel } from "../search/fiscalNotes";
import { FiscalNoteResult } from "./FiscalNoteResult";
// The title renderer lives in its own module so the result card can reuse it without a
// circular import (spec F16). Re-exported below: this page has always been where callers
// look for BillTitle.
import { BillTitle, stripTags, titleText } from "./billTitle";

export { BillTitle, stripTags, titleText };

// Fiscal Notes — ported from the GENERATED mockup page,
// `webapp/reference/subpage-fiscal-notes.html`, keeping its class names so its CSS
// applies unmodified (spec S12: port, don't redesign).
//
// SOURCE NOTE (this page was re-ported once): `fiscal-notes-build/base.html` is NOT the
// source of truth — its own line 2 says so ("DO NOT point this at the generated page").
// `fiscal-notes-build/build.py` replaces base.html's entire <main>, appends ~130 lines of
// layout CSS, and ships the page's JS island; the vendored `subpage-fiscal-notes.html` is
// that rendered output. base.html's <main> (a two-column House|Senate `.bills` grid inside
// one `.card`, with an `.acc` archive accordion) is a SUPERSEDED body and is not this page.
// Markup + CSS come from subpage-fiscal-notes.html; behavior comes from build.py:153-201.
//
// REBUILT 2026-08-13 (spec F1-F17, docs/superpowers/specs/2026-08-13-fiscal-notes-browse-
// and-retrieval-design.md). The port above is still the ancestry of this file's markup and
// its title/filter/sort helpers; the LAYOUT below is no longer the generated page's, because
// the page's job changed from "look at one session" to "browse the corpus by year, and
// search it".
//
// The real layout, top to bottom: `.subhero` band → `.wrap.fnwrap` → `.fnlayout` grid of a
// sticky 248px `.fnside` rail beside `.fnmain`.
//
// The rail is now FOUR controls, in this order (F1/F2/F5/F6):
//   1. ONE `.fside-search` box — a textarea, because a whole question gets typed into it.
//      It filters titles, and at zero title hits it escalates to real retrieval.
//   2. the `.chswitch`/`.chseg` segmented Chamber control (kept: three options read at a
//      glance, where a dropdown would hide which lens is active behind a click);
//   3. a `.fctl`/`.fbtn`/`.fmenu` Legislative Session MULTI-SELECT — Budget Documents' own
//      control, sharing its CSS, not a lookalike;
//   4. a `.fctl` Sort dropdown, which left the card headers where it forced one element to
//      be both a collapse toggle and a menu.
// Chamber and Sort both grey out in content mode, behind ONE shared sentence (F9).
//
// `.fnmain` holds one of two things:
//   - BROWSING / TITLE SEARCH: one collapsible `.yg` card per in-scope session, newest
//     expanded (newest THREE during a title search — F8's cap, which exists because typing
//     `a` matches 2,029 of 2,126 rows across all 28 sessions). Card bodies mount only when
//     open. Ends with the `.allbar` titles/contents toggle.
//   - CONTENT SEARCH: ONE ranked "Results" card of `FiscalNoteResult` buttons, each one
//     note showing its single best passage, opening the in-app source drawer.
//
// GONE, and deliberately: the `.yscroll` list of `.frow` session rows (replaced by the
// multi-select), the per-card `.sortctl` menu (moved to the rail), the rail's SECOND
// "Search note text" box (`SemanticRailSearch` — one box does both jobs now), and the
// `.allbar` "Search all legislative sessions" pill (with sessions as a filter, search always
// spans everything in scope). Their CSS is still in app.css and is now unused by this page;
// `.sortctl` remains referenced by SORT_OPTIONS' comment only, as provenance.
//
// DEVIATIONS from the generated page, and why:
//
//  1. CSS-only selection → React state. The mockup drives the session filter, chamber
//     switch, sort order and toggle-pill state from hidden radios (`.fnr`) plus ~120
//     generated `#fnY-1999:checked ~ …` selectors (DESIGN-SYSTEM.md §8 rule 8 calls this
//     out as deliberate). Two things make that impossible here: (a) those selectors
//     hardcode one rule per YEAR, and this page's years come from the API — a static
//     stylesheet cannot enumerate a payload; (b) the page's pinned test asserts a filtered
//     bill is `not.toBeInTheDocument()`, which `display:none` can never satisfy. So the
//     controls are `<button>`s carrying an `.on` class whose declarations are copied
//     unchanged from the corresponding `:checked ~` rule, and filtered rows are REMOVED
//     rather than hidden. Same rendering, same values.
//  2. The CSS display swaps (`.ym-all`/`.ym-h`/`.ym-s`, the four `.sortcur` labels,
//     `#fnC-house:checked ~ … .b-s{display:none}`) exist because a static page must emit
//     every variant and hide all but one. Here the applicable one is simply rendered, so
//     those `display` rules are deliberately NOT ported (porting `.ym-h{display:none}`
//     would hide the count we DO render). The classes stay as markers.
//  3. Sort runs in JS, not via `order:var(--na)`. The mockup precomputes four rank vars per
//     row because a static page cannot re-sort; the four orders and the default (bill number
//     ascending) are identical. `data-no`/`data-num`/`--na…--td` are island plumbing, not
//     design, and are dropped.
//  4. Title sort compares the VISIBLE title text, not the raw string the mockup sorts on.
//     The mockup's A-Z sort keys off the raw scraped HTML, so all 241 `<strike>`-prefixed
//     titles clump at the top under "<" — an artifact of the tags, not a design decision.
//     (Its own JS filter matches the RENDERED text, so the mockup is inconsistent here.)
//  5. The "Search all legislative sessions" pill is `disabled` while the box is empty. The
//     island force-unchecks it on an empty query (build.py:174), so in the mockup it is
//     ALREADY inert there while still looking clickable; a real `disabled` attribute makes
//     that honest rather than inventing behavior.
//  6. NEW, no counterpart: a `role="status"` filter line (a11y + accuracy — the mockup
//     reports no filter result anywhere) and the disabled Plan-3 semantic-search box.
//  7. `rel="noopener"` → `rel="noopener noreferrer"`: `noopener` alone still hands the
//     referrer to azleg.gov.
//  8. The hero's `aria-label="Page header"` is dropped — a landmark named "Page header"
//     says nothing a heading doesn't.
//  9. `.yg-meta` counts what the card is SHOWING; the artifact bakes in the pre-filter total.
//     The mockup has no choice — its count is static text and CSS cannot recount rows, so
//     after a filter its "112 Fiscal Notes" sits above however few rows survived. Since this
//     port removes filtered rows, the rendered number and the rendered rows are the same set
//     by construction. A deliberate honesty divergence, not a redesign: same element, same
//     wording, same three chamber nouns. The `.frow-n` rail counts deviate the other way on
//     purpose — they follow the chamber lens but NOT the query, because a session's inventory
//     is a different quantity from "matches" (which the status line states outright). Both
//     halves are pinned by tests.
//
// Shared chrome (`header.site`, `footer.site`) lives in components/Header.tsx or is dropped
// app-wide; not this page's business.

/** Chamber segment, named as the island names its radios (`fnC-all|house|senate`). */
type Chamber = "all" | "house" | "senate";
/** Sort key, named as the island names its radios (`fnS-na|nd|ta|td`). */
type SortKey = "na" | "nd" | "ta" | "td";

/** What the page is currently showing. One state, so "loading" and "error" and "ready"
 *  can never be true at the same time. Same shape as the Search page's Phase minus its
 *  stale-while-revalidate branch: this page fetches once, so there is never a previous
 *  payload worth keeping on screen. */
type Phase =
  | { kind: "loading" }
  | { kind: "ready"; sessions: Session[] }
  | { kind: "error"; message: string };

// ---------------------------------------------------------------------------
// Titles
// ---------------------------------------------------------------------------

/** The bill number with its space removed ("HB 2011" → "HB2011"), the island's `data-no`. */
function billId(bill: Bill): string {
  return bill.bill_number.replace(/\s+/g, "").toUpperCase();
}

/** The numeric part of the bill number ("HB 2011" → "2011"), the island's `data-num`. */
function billNum(bill: Bill): string {
  return bill.bill_number.match(/\d+/)?.[0] ?? "";
}

/** Does this bill match the typed query? Ported line-for-line from the island:
 *
 *   - A query containing ANY letter → prefix-match the whitespace-stripped bill number OR
 *     find the query as a SINGLE SUBSTRING of the title.
 *   - A DIGITS-ONLY query → prefix-match the numeric part of the bill number only, and
 *     nothing else. This is what makes the island's documented contract hold: "2015",
 *     "HB 2015" and "HB2015" all hit HB 2015 (build.py:157). Note the corollary — a
 *     digits-only query never searches titles.
 *
 *  The substring test is deliberately NOT split into AND-ed terms: "school funding" does not
 *  match "school facilities; funding" in the mockup, and inventing multi-term matching would
 *  be redesigning the filter. */
function matchesQuery(bill: Bill, q: string): boolean {
  if (!q) return true;
  if (/[a-z]/i.test(q)) {
    if (billId(bill).startsWith(q.toUpperCase().replace(/\s+/g, ""))) return true;
    return titleText(bill.title).toLowerCase().includes(q.toLowerCase());
  }
  const digits = q.replace(/[^0-9]/g, "");
  return digits !== "" && billNum(bill).startsWith(digits);
}

function inChamber(bill: Bill, chamber: Chamber): boolean {
  return chamber === "all" || (chamber === "house" ? bill.chamber === "H" : bill.chamber !== "H");
}

/** The four sort orders of the `.sortctl` menu (build.py:62-73).
 *
 *  "Bill number" compares the NUMBER first and the whole string second — the mockup's
 *  `numkey`, which is why SCR 1001 sorts ahead of SB 1009 in its own output. Descending is
 *  the exact reverse of ascending (the mockup derives `--nd` as `N-1-rank`), so reversing a
 *  stable sort reproduces it including how ties fall. */
function sortBills(bills: Bill[], sort: SortKey): Bill[] {
  const byNumber = (a: Bill, b: Bill) =>
    Number(billNum(a) || 0) - Number(billNum(b) || 0) ||
    a.bill_number.localeCompare(b.bill_number);
  const byTitle = (a: Bill, b: Bill) =>
    titleText(a.title).toLowerCase().localeCompare(titleText(b.title).toLowerCase());
  const out = [...bills].sort(sort === "na" || sort === "nd" ? byNumber : byTitle);
  if (sort === "nd" || sort === "td") out.reverse();
  return out;
}

const SORT_OPTIONS: { key: SortKey; menu: string; current: string }[] = [
  { key: "na", menu: "Bill number — low to high", current: "Bill Number (Low to High)" },
  { key: "nd", menu: "Bill number — high to low", current: "Bill Number (High to Low)" },
  { key: "ta", menu: "Bill title — A to Z", current: "Bill Title (A to Z)" },
  { key: "td", menu: "Bill title — Z to A", current: "Bill Title (Z to A)" },
];

/** The mockup's `.yg-meta` wording, one noun per chamber segment.
 *
 *  `one` exists because the browse rebuild made this count far more visible: the page used
 *  to show ONE session card, whose count was in the hundreds, and now shows a card per
 *  in-scope session — so a filtered search puts "1 Fiscal Notes" on screen repeatedly.
 *  Seen on the rendered page, not in a test; jsdom asserts text content and has no opinion
 *  about English. (The mockup has the same defect, being a static file with one count.) */
const META_NOUN: Record<Chamber, { cls: string; noun: string; one: string }> = {
  all: { cls: "ym-all", noun: "Fiscal Notes", one: "Fiscal Note" },
  house: { cls: "ym-h", noun: "House Notes", one: "House Note" },
  senate: { cls: "ym-s", noun: "Senate Notes", one: "Senate Note" },
};

/** One `.yg` card's worth of already-filtered, already-sorted bills. */
interface Card {
  session: Session;
  bills: Bill[];
}

// The magnifier in `.fside-search` and `.allbtn` is components/SearchIcon.tsx — the same
// circle-r7 + m21 21 path pair this page's mockup uses, already extracted for exactly this
// reason ("four hand-copied path pairs is four chances for them to drift apart"). It needs no
// className here: `.fside-search svg` and `.allbtn svg` size it.

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

/** One `.fbill` row — the whole row is the link to the PDF, as in the mockup.
 *
 *  memo()'d so a re-render that does not change a row's `bill` skips it: the sort label, the
 *  chamber segment, the status line and the scope pill all re-render the card list. `bill`
 *  objects come straight from the fetched payload, so their identity is stable and the memo
 *  actually holds.
 *
 *  HONEST MEASUREMENT (jsdom, real snapshot, A/B with memo removed): in THIS layout the
 *  difference is inside the noise — worst case, every session in scope, ~5 keystrokes:
 *  321/75/43/28/30ms with memo vs 271/73/52/52/40ms without; default scope 37/13/16/12/9 vs
 *  43/14/15/11/10. The reason is structural: the mockup shows ONE session at a time, so only
 *  ~37-135 rows are mounted unless the "all sessions" pill is on, and the widened case is
 *  dominated by mounting/unmounting rows as the match set changes — which memo cannot avoid.
 *  (A larger win, ~113ms → ~55ms, was measured on this page's earlier draft, which kept all
 *  2,126 rows mounted at all times. Do not quote that number for this layout.) memo is kept
 *  because it is free and correct, not because it is load-bearing here. */
const BillRow = memo(function BillRow({ bill }: { bill: Bill }) {
  return (
    <a
      className={bill.chamber === "H" ? "fbill b-h" : "fbill b-s"}
      href={bill.fiscal_note_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="fbill-no">{bill.bill_number}</span>
      <span className="fbill-desc">
        <BillTitle title={bill.title} />
      </span>
      {/* `.fbill-dl` renders a ↓ via `::before`; "PDF" is the mockup's own label. The row's
          accessible name is already "HB 2011 <title> PDF", so this needs no aria of its
          own. */}
      <span className="fbill-dl">PDF</span>
    </a>
  );
});

/** One `.yg` session card: a collapse-toggle header (name + count) and the merged bill list.
 *
 *  COLLAPSIBLE since 2026-08-13 (spec F1/F3). The page stopped being "look at one session"
 *  and became "browse the corpus by year", so every in-scope session gets a card — newest
 *  expanded, priors collapsed.
 *
 *  The sort menu LEFT this header (spec F5). It forced the header to be both a collapse
 *  toggle and a menu, which cannot both own the same click; sort is one rail control now.
 *
 *  The body is mounted CONDITIONALLY, and that is deliberate. Budget Documents mounts every
 *  year body once and hides it with the `hidden` attribute, specifically to preserve open
 *  trays and head-button focus across a collapse. A session card has no trays, and the head
 *  button survives either way, so there is no state that mounting would protect — while
 *  mounting all 28 bodies puts ~2,126 rows in the DOM at once.
 *
 *  Do NOT cite this file's "~113 ms → ~55 ms" memo() comment in support of that. It measured
 *  what memo() was worth on an earlier draft that happened to keep all 2,126 rows mounted;
 *  it is not a measurement of mounting-vs-not, and the comment says in terms not to quote it
 *  for the current layout. The argument here is structural. If mounting ever looks tempting,
 *  measure it. */
function SessionCard({
  card,
  chamber,
  open,
  onToggle,
}: {
  card: Card;
  chamber: Chamber;
  open: boolean;
  onToggle(year: number): void;
}) {
  const meta = META_NOUN[chamber];
  const label = sessionLabel(card.session);
  const count = `${card.bills.length} ${card.bills.length === 1 ? meta.one : meta.noun}`;
  return (
    <section className={open ? `yg yg-open y${card.session.year}` : `yg yg-closed y${card.session.year}`}>
      <button
        type="button"
        className="yg-head"
        aria-expanded={open}
        // The full label AND the count in the accessible name: a collapsed card's count is
        // the only thing telling a screen-reader user there is anything behind it.
        aria-label={`${label}: ${count}`}
        onClick={() => onToggle(card.session.year)}
      >
        <div className="yg-ttl">
          <span className="yg-yr">{label}</span>
          {/* Accurate by construction: non-matching rows are removed, so the count of what
              is rendered IS the count of what the card shows. The mockup emits all three
              nouns and lets CSS pick; only the applicable one is rendered here. */}
          <span className="yg-meta">
            <span className={meta.cls}>{count}</span>
          </span>
        </div>
        <svg
          className={open ? "yg-chev open" : "yg-chev"}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="fnlist">
          {card.bills.map((bill) => (
            // bill_number is NOT unique inside a session: an original note and its revision
            // share the number and differ only by URL (93 such rows in the snapshot, up to 3
            // per number — the mockup dedupes on the same (number, url) pair). The URL is what
            // makes the key unique.
            <BillRow key={`${bill.bill_number}|${bill.fiscal_note_url}`} bill={bill} />
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/** How many matching session cards auto-expand during a TITLE search (spec F8).
 *
 *  WHY a cap exists at all — measured against the real 2,126-row snapshot:
 *
 *      typed     matching rows   sessions that would expand
 *      water          11                  10
 *      fund           90                  25
 *      school        177                  28
 *      tax           513                  28
 *      a           2,029                  28
 *
 *  "Expand every matching card" reaches the exact all-rows-mounted state
 *  SessionCard's conditional mount exists to prevent, and it does so on ONE
 *  keystroke. Short prefixes are not an edge case — they are the state every
 *  longer query passes through, on every keystroke.
 *
 *  Three, because it holds the shape the reader asked for (the matches are
 *  visible, newest first) while capping the mounted rows at roughly one
 *  session-and-a-half in the worst case. Older matching cards render collapsed
 *  with their match count in the header, which is a true statement and one
 *  click from the rows.
 *
 *  Do NOT "fix" this with virtualised scrolling: that trades a one-line rule
 *  for a scroll-position and measurement problem on a page that has neither. */
const AUTO_OPEN = 3;

/** How long the box must go quiet before a zero-title-hit query escalates to a
 *  real content search. Budget Documents' number, deliberately identical. */
const ESCALATE_MS = 2000;

/** ONE sentence for BOTH stood-down controls (spec F9). Chamber and sort go
 *  inactive together, for the same reason, in the same words — two sentences
 *  would imply two different reasons. */
const INERT_HINT = "Ranked results are ordered by relevance — chamber and sort apply to browsing.";

type ContentPhase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; body: api.SearchResponse }
  | { kind: "error"; message: string };

export function FiscalNotes() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  // Retry counter — the same device the Search page uses: re-running an identical request
  // needs something in the dependency list that actually changes.
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [chamber, setChamber] = useState<Chamber>("all");
  const [sort, setSort] = useState<SortKey>("na");
  /** Sessions the rail has ticked. EMPTY means "any session" (spec F1) — the control is a
   *  FILTER now, not a selector, so "nothing ticked" is the widest scope rather than the
   *  narrowest. */
  const [pickedYears, setPickedYears] = useState<Set<number>>(new Set());
  /** Manual card toggles. Absent = whatever the current mode's default is, which differs
   *  between browse (newest ONE) and title search (newest THREE) — see `defaultOpen`. */
  const [openSessions, setOpenSessions] = useState<Map<number, boolean>>(new Map());
  const [openMenu, setOpenMenu] = useState<"sess" | "sort" | null>(null);
  const [mode, setMode] = useState<"titles" | "contents">("titles");
  /** The query for which the reader deliberately crossed BACK to titles.
   *
   *  A query string, not a boolean, and that is load-bearing: a reader who clicks back to
   *  titles is BY CONSTRUCTION the population that stays at zero title hits, so a boolean
   *  would let the page yank them forward again on the very next render. Keyed on the query,
   *  it self-invalidates the moment the query changes by any route. (Live defect on Budget
   *  Documents, 2026-08-10.) */
  const [suppressedQuery, setSuppressedQuery] = useState<string | null>(null);
  const [content, setContent] = useState<ContentPhase>({ kind: "idle" });
  /** The chunk whose passage is open in the source drawer. */
  const [openSource, setOpenSource] = useState<{ chunkId: string; title: string; year: number | null } | null>(null);
  const box = useRef<HTMLInputElement>(null);

  // NO AI Mode here (Destin, 2026-07-31). This page had a toggle that swapped
  // the directory for a conversation over the fiscal-note corpus; AI Mode is now
  // its own tab (`pages/Ai.tsx`), and its corpus picker is what preserves the
  // coordinator's "have we written a note like this before?" workflow. Do not
  // reintroduce a toggle — see STATUS.md's Plan 4 deviation note.

  useEffect(() => {
    // Stale-response guard: if this re-runs (retry) while a request is in flight, the
    // cleanup flips `ignore` so the older answer cannot overwrite the newer one.
    let ignore = false;
    setPhase({ kind: "loading" });
    api.fiscalNotes().then(
      (data) => {
        if (!ignore) setPhase({ kind: "ready", sessions: data.sessions });
      },
      (err: unknown) => {
        // The api client already put the backend's own `detail` in the message; show it
        // verbatim rather than replacing it with a guess at the cause.
        if (!ignore)
          setPhase({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      ignore = true;
    };
  }, [attempt]);

  const sessions = phase.kind === "ready" ? phase.sessions : [];
  const q = query.trim();

  /** The sessions in scope. Empty selection = all of them (spec F1). */
  const scoped = useMemo(
    () => (pickedYears.size === 0 ? sessions : sessions.filter((s) => pickedYears.has(s.year))),
    [sessions, pickedYears],
  );

  /** Session name lookup for the RESULT card (spec F4).
   *
   *  A search result carries `fiscal_year` — the bare number — and nothing else about the
   *  session; the name string lives only in the browse directory. The page has already
   *  fetched that directory, so this is a map over data in hand: no request, no endpoint.
   *  The 28 sessions cover 1999-2026 one-per-year, so the map is total. */
  const labelByYear = useMemo(
    () => new Map(sessions.map((s) => [s.year, sessionLabel(s)])),
    [sessions],
  );

  const cards = useMemo<Card[]>(
    () =>
      scoped
        .map((session) => ({
          session,
          bills: sortBills(
            session.bills.filter((b) => inChamber(b, chamber) && matchesQuery(b, q)),
            sort,
          ),
        }))
        // With a query, a session with no matches disappears entirely. With no query the
        // card stays even if the chamber filter empties it — the mockup keeps the card and
        // only hides its rows.
        .filter((card) => q === "" || card.bills.length > 0),
    [scoped, chamber, q, sort],
  );

  const titleHits = cards.reduce((n, c) => n + c.bills.length, 0);

  // --- escalation (spec F6) -------------------------------------------------
  // A natural-language question essentially never substring-matches a bill title (the filter
  // tests the query as ONE substring, deliberately un-AND-ed), while a bill number almost
  // always does — so "zero title hits" is an honest proxy for "this was a question about
  // CONTENT". Only fires from title mode, only with a query, only at zero hits, only after
  // the box goes quiet.
  useEffect(() => {
    if (mode !== "titles" || q === "" || titleHits > 0) return;
    if (suppressedQuery === q) return;
    // Nothing to escalate to until the directory has loaded — a payload that has not arrived
    // has zero title hits for every query.
    if (phase.kind !== "ready") return;
    const timer = setTimeout(() => setMode("contents"), ESCALATE_MS);
    return () => clearTimeout(timer);
    // `q` is load-bearing here, not an exhaustive-deps nit: titleHits stays 0 across
    // successive zero-hit keystrokes, so without `q` this effect never re-ran after the
    // FIRST such keystroke and the timer it started kept ticking through every later one —
    // escalation fired 2s after the first zero-hit keystroke instead of 2s after the box
    // went quiet.
  }, [mode, q, titleHits, phase.kind, suppressedQuery]);

  /** Is the escalation timer armed right now? Mirrors the guard above, term for term — if
   *  you change one, change both.
   *
   *  WHY this exists: without it the page sits on "No note titles match X" for the full 2s
   *  pause and THEN swaps to the spinner, which reads as a hiccup — the page appears to
   *  fail, then change its mind. The pause is a deliberate debounce, not a result, so it
   *  must not be presented as one. The moment escalation is armed the page has COMMITTED to
   *  searching contents, so it says so and keeps saying so straight through the request. */
  const escalating =
    mode === "titles" && q !== "" && titleHits === 0 && phase.kind === "ready" && suppressedQuery !== q;
  const showingContents = mode === "contents" || escalating;
  const contentsBusy = escalating || (mode === "contents" && content.kind === "loading");

  // The content request itself. `ignore` is the stale-response guard: if the query or the
  // filters change while a request is in flight, React runs this cleanup first, so the older
  // (slower) answer returns here and does nothing instead of painting over the newer one.
  useEffect(() => {
    if (mode !== "contents" || q === "") {
      setContent({ kind: "idle" });
      return;
    }
    let ignore = false;
    setContent({ kind: "loading" });
    // Session narrows the REQUEST — `fiscal_year` on a fiscal-note chunk IS the session
    // year, so the filter reaches content mode the same way it does for Budget Documents.
    // Chamber does NOT: there is no chamber column, so it could only remove ranked notes
    // after the fact with nothing to backfill them (spec F9).
    const filters = pickedYears.size ? { fiscal_year: [...pickedYears] } : {};
    api.search(q, filters, "fiscal_notes").then(
      (body) => {
        if (!ignore) setContent({ kind: "ready", body });
      },
      (err: unknown) => {
        if (!ignore)
          setContent({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      ignore = true;
    };
  }, [mode, q, pickedYears]);

  /** Ranked notes, cut at 15 (spec F10/F11). */
  const results = useMemo(
    () => (content.kind === "ready" ? groupNotes(content.body.results) : { notes: [], cut: false }),
    [content],
  );

  /** Which sessions the search inferred from the words typed, if any (spec F15). */
  const inferredYears = content.kind === "ready" ? (content.body.inferred_fiscal_years ?? []) : [];

  /** Is this a real search, or the fixture provider?
   *
   *  The app falls back to `StubSearchProvider` when no corpus has been ingested, and that
   *  provider ignores the query — every search returns the same handful of rows in the same
   *  order. Which is honest as a fixture and indistinguishable from a BROKEN SEARCH as a
   *  user experience: Destin, on the running page, read it as "stuck at the same 4 fiscal
   *  notes regardless of query", which is exactly what it looks like.
   *
   *  The response has always carried `provider`; nothing ever showed it. Say it plainly
   *  instead, and say what to do about it — the rail's old semantic box used to carry this
   *  signal ("Unlocks when the fiscal-note corpus is ingested") and deleting that box took
   *  the page's only mention of ingestion with it. */
  const isFixtureData = content.kind === "ready" && content.body.provider === "stub";

  // Per-session counts for the rail's dropdown. Scoped to the chamber segment (a persistent
  // lens on the whole page) but NOT to the typed query: this is the session's note
  // inventory, a different quantity from "matches", which the status line states outright.
  const sessionCounts = useMemo(
    () =>
      new Map(sessions.map((s) => [s.year, s.bills.filter((b) => inChamber(b, chamber)).length])),
    [sessions, chamber],
  );

  /** Plural noun for the chamber lens, used when no number precedes it. */
  const nouns =
    chamber === "all" ? "fiscal notes" : chamber === "house" ? "House notes" : "Senate notes";
  /** "1 fiscal note" / "7 fiscal notes" — agreement matters in a spoken live region. */
  const counted = (n: number) => `${n} ${nouns.slice(0, -1)}${n === 1 ? "" : "s"}`;

  /** Is this card open? Default differs BY MODE — newest one while browsing, newest three
   *  during a title search (spec F8) — which is exactly why the toggle handler below flips
   *  what is on screen instead of recomputing this. */
  function defaultOpen(index: number): boolean {
    return q === "" ? index === 0 : index < AUTO_OPEN;
  }

  const scopeWords =
    pickedYears.size === 0
      ? `all ${sessions.length} sessions`
      : pickedYears.size === 1
        ? `the ${[...pickedYears][0]} session`
        : `${pickedYears.size} sessions`;

  /** The live-region filter line. Every branch describes exactly the set on screen: what is
   *  counted is what the cards below render, and the scope it names is the scope in force. */
  function status(): string {
    if (phase.kind === "loading") return "Loading fiscal notes…";
    if (!sessions.length) return "No fiscal notes published yet.";
    if (showingContents) {
      if (contentsBusy) return `Searching note contents for “${q}”…`;
      if (content.kind === "error") return content.message;
      if (!results.notes.length) return `No passages matching “${q}” in ${scopeWords}.`;
      // Spec F10's copy, carrying the query and scope this line has always shown.
      return `${resultsHeader(results.notes.length, results.cut)} for “${q}” in ${scopeWords}, each showing its best-matching passage.`;
    }
    if (!q) return `${counted(titleHits)} across ${scopeWords}.`;
    // Every branch names the scope IN FORCE. The earlier draft of this line reported
    // "across 1 of 1 in-scope sessions" for a filtered search — arithmetic about the cards
    // rather than a statement of what was searched, which left a ticked session filter
    // invisible in the one place on the page whose job is to describe the current set.
    return titleHits === 0
      ? `No ${nouns} matching “${q}” in ${scopeWords}.`
      : `${counted(titleHits)} matching “${q}” in ${scopeWords}.`;
  }

  function clearQuery() {
    setQuery("");
    setSuppressedQuery(null);
    setMode("titles");
    setOpenSource(null);
    box.current?.focus();
  }

  /** Cross between the two modes by hand. */
  function toggleMode() {
    setOpenSource(null);
    if (showingContents) {
      // A deliberate return to titles. Arm the suppression FOR THIS QUERY so the escalation
      // guard does not immediately fire again.
      setSuppressedQuery(q);
      setMode("titles");
    } else {
      setSuppressedQuery(null);
      setMode("contents");
    }
  }

  const inert = showingContents;

  return (
    <main className="page-fiscal-notes" data-testid="fiscal-notes">
      <section className="subhero">
        <div className="wrap">
          <h1>Fiscal Notes</h1>
          <p className="lead">
            Independent fiscal-impact analyses of pending legislation — each bill's effect on
            state revenues, spending, and the General Fund.
          </p>
          <div className="chips">
            <span className="chip">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 2h9l5 5v15H6z" />
                <path d="M14 2v6h6" />
              </svg>{" "}
              House &amp; Senate bills
            </span>
            {/* Second chip, naming the new search behaviour (spec: "the subhero, beyond a
                second chip naming the new search behaviour"). */}
            <span className="chip">
              <SearchIcon /> Searches titles, then note text
            </span>
          </div>
        </div>
      </section>

      <div className="wrap fnwrap">
        <p className="fnnote fnstatus" role="status">
          {phase.kind === "error" ? (
            // The message is the backend's own `detail`, passed through untouched.
            <span className="err">{phase.message}</span>
          ) : (
            status()
          )}
        </p>
        <div className="fnlayout">
          <aside className="fnside">
            <div className="fgrp">
              <label className="fside-search">
                <SearchIcon />
                {/* A plain one-line input, IDENTICAL to Budget Documents' (Destin,
                    2026-08-13, reversing spec F6/Q1). A growing textarea was tried and
                    undone: the two sibling pages must present the same control, and making
                    this one taller than its twin re-created the divergence the rebuild
                    existed to remove. If the box is ever too small for a whole question,
                    that is one change to BOTH pages, not a local improvement to this one. */}
                <input
                  ref={box}
                  type="text"
                  value={query}
                  onChange={(e) => {
                    // A NEW QUERY IS A NEW SEARCH, and titles are the cheap default — so
                    // editing the box always returns to title mode and re-arms escalation.
                    // Budget Documents' rule, ported verbatim, and it is what makes
                    // backspacing behave: shortening a question until it matches a title
                    // (or emptying the box) lands you back in the title list instead of
                    // stranding you in a ranked view that no longer answers anything.
                    // Staying in content mode would also fire a retrieval request on every
                    // keystroke.
                    //
                    // No explicit suppression clear is needed: `suppressedQuery` holds the
                    // specific query it applies to, so typing a fresh query already makes
                    // the escalation effect's `suppressedQuery === q` comparison false on
                    // its own.
                    setQuery(e.target.value);
                    setMode("titles");
                    setOpenSource(null);
                  }}
                  placeholder="Bill # or a question…"
                  aria-label="Filter fiscal notes by bill number or keyword, or ask a question"
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

            <div className="fgrp">
              <div className="flbl" id="fn-chamber-label">
                Chamber
              </div>
              <div className="chswitch" role="group" aria-labelledby="fn-chamber-label">
                {(
                  [
                    { value: "all", label: "All" },
                    { value: "house", label: "House" },
                    { value: "senate", label: "Senate" },
                  ] as const
                ).map((seg) => (
                  <button
                    key={seg.value}
                    type="button"
                    className={chamber === seg.value ? "chseg on" : "chseg"}
                    aria-pressed={chamber === seg.value}
                    // Stands down in content mode (spec F9). There is no chamber column on
                    // the corpus, so a chamber lens could only remove ranked notes AFTER
                    // ranking, with no way to fetch more — a House-only search would come
                    // back short by an amount nobody can predict. Disabled, not hidden: the
                    // reader keeps seeing which lens is set and that it comes back.
                    disabled={inert}
                    onClick={() => setChamber(seg.value)}
                  >
                    {seg.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="fgrp">
              <div className="flbl" id="fn-session-label">
                Legislative Session
              </div>
              {/* A MULTI-SELECT, the twin of Budget Documents' Fiscal Year control (spec F1).
                  It replaced a 28-row scrolling radio list, and with it the page stopped
                  being "look at one session" and became "browse the corpus by year". */}
              <div className="fctl">
                <button
                  type="button"
                  className={pickedYears.size ? "fbtn has" : "fbtn"}
                  id="fn-sess-btn"
                  aria-expanded={openMenu === "sess"}
                  aria-labelledby="fn-session-label fn-sess-btn"
                  onClick={() => setOpenMenu((m) => (m === "sess" ? null : "sess"))}
                >
                  <span className="fb-label">
                    {pickedYears.size === 0
                      ? "Any session"
                      : pickedYears.size === 1
                        ? String([...pickedYears][0])
                        : `${pickedYears.size} selected`}
                  </span>
                  <svg className="chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                    <path d="m1 1 4 4 4-4" />
                  </svg>
                </button>
                {openMenu === "sess" && (
                  <div className="fmenu" role="group" aria-label="Legislative session options">
                    {sessions.map((s) => {
                      const on = pickedYears.has(s.year);
                      return (
                        <button
                          key={s.year}
                          type="button"
                          className={on ? "fopt on" : "fopt"}
                          aria-pressed={on}
                          aria-label={`${sessionLabel(s)} — ${counted(sessionCounts.get(s.year) ?? 0)}`}
                          onClick={() =>
                            setPickedYears((prev) => {
                              const next = new Set(prev);
                              if (next.has(s.year)) next.delete(s.year);
                              else next.add(s.year);
                              return next;
                            })
                          }
                        >
                          <span className="ck">
                            <svg viewBox="0 0 12 10" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                              <path d="m1 5 3.5 3.5L11 1" />
                            </svg>
                          </span>
                          {s.year}
                          <span className="fopt-n">{sessionCounts.get(s.year) ?? 0}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="fgrp">
              <div className="flbl" id="fn-sort-label">
                Sort bills
              </div>
              {/* Sort LEFT the card headers (spec F5), where it forced the header to be both
                  a collapse toggle and a menu. Sessions themselves stay newest-first; this
                  reorders bills INSIDE each card and never flattens them into one list. */}
              <div className="fctl">
                <button
                  type="button"
                  className="fbtn"
                  id="fn-sort-btn"
                  aria-expanded={openMenu === "sort"}
                  aria-labelledby="fn-sort-label fn-sort-btn"
                  // Inactive against a relevance ranking: silently reordering a ranked list
                  // would be a lie about what the ranking means (spec F5/F9).
                  disabled={inert}
                  onClick={() => setOpenMenu((m) => (m === "sort" ? null : "sort"))}
                >
                  <span className="fb-label">{SORT_OPTIONS.find((o) => o.key === sort)?.current}</span>
                  <svg className="chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                    <path d="m1 1 4 4 4-4" />
                  </svg>
                </button>
                {openMenu === "sort" && !inert && (
                  <div className="fmenu" role="group" aria-label="Sort options">
                    {SORT_OPTIONS.map((opt) => (
                      <button
                        key={opt.key}
                        type="button"
                        className={opt.key === sort ? `fopt on o-${opt.key}` : `fopt o-${opt.key}`}
                        aria-pressed={opt.key === sort}
                        onClick={() => {
                          setSort(opt.key);
                          setOpenMenu(null);
                        }}
                      >
                        <span className="ck" />
                        {opt.menu}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {inert && (
                <p className="fhint" id="fn-inert-hint">
                  {INERT_HINT}
                </p>
              )}
            </div>
          </aside>

          <div className="fnmain">
            {phase.kind === "error" ? (
              <div className="allbar">
                <button type="button" className="allbtn" onClick={() => setAttempt((a) => a + 1)}>
                  Retry
                </button>
              </div>
            ) : showingContents ? (
              <>
                <section className="yg">
                  <div className="yg-head-static">
                    <div className="yg-ttl">
                      <span className="yg-yr">
                        Results <span className="yg-mode">(searching note contents)</span>
                      </span>
                      {!contentsBusy && content.kind === "ready" && results.notes.length > 0 && (
                        <span className="yg-meta">
                          {resultsHeader(results.notes.length, results.cut)}
                        </span>
                      )}
                    </div>
                  </div>
                  {contentsBusy ? (
                    <div className="docload" role="status">
                      <span className="spin" aria-hidden="true" />
                      <span>
                        Searching note contents…
                        <span className="sub">Reading inside every ingested fiscal note.</span>
                      </span>
                    </div>
                  ) : content.kind === "error" ? (
                    // The backend's own `detail`, passed through untouched — never a guess.
                    <p className="empty">
                      <span className="err">{content.message}</span>
                    </p>
                  ) : results.notes.length === 0 ? (
                    <p className="empty">
                      No passages inside the ingested notes mention “{q}”
                      {pickedYears.size ? " in the sessions you picked. Try adding one." : "."}
                    </p>
                  ) : (
                    <div className="fnresults">
                      {isFixtureData && (
                        <p className="fnnote fn-fixture" role="note">
                          <strong>These are sample results, not a real search.</strong> No
                          fiscal notes have been ingested on this machine, so the same few
                          example notes come back for every question. Ingest the notes to
                          search their text.
                        </p>
                      )}
                      {/* F15: state what the search inferred from the words typed, with an
                          undo. A question naming a year is hard-filtered by session while
                          the rail still reads "Any session" — and unlike the doc-type guess,
                          the year guess is NEVER dropped when it narrows too far. */}
                      {inferredYears.length > 0 && pickedYears.size === 0 && (
                        <p className="fnnote fn-inferred">
                          <strong>
                            {/* A single inferred year rendered as "the 2027–2027 sessions",
                                which reads like a bug because it is one. The pipeline
                                widens the guess a year either side when it FILTERS, but it
                                echoes back only what it parsed — often one year. */}
                            {Math.min(...inferredYears) === Math.max(...inferredYears)
                              ? `Also limited to the ${inferredYears[0]} session`
                              : `Also limited to the ${Math.min(...inferredYears)}–${Math.max(...inferredYears)} sessions`}
                          </strong>
                          , because your question named a year.{" "}
                          <button
                            type="button"
                            className="linkbtn"
                            // Sends an explicit filter wide enough to SUPPRESS the inference
                            // (the pipeline only infers when the caller passed no
                            // fiscal_year of its own) — rather than stripping the year from
                            // the analyst's question, which would change what they asked.
                            onClick={() => setPickedYears(new Set(sessions.map((s) => s.year)))}
                          >
                            Search every session.
                          </button>
                        </p>
                      )}
                      {results.notes.map((noteDoc) => {
                        const best = noteDoc.passages[0];
                        return (
                          <FiscalNoteResult
                            key={noteDoc.doc_id}
                            note={noteDoc}
                            sessionLabel={
                              best.fiscal_year !== null
                                ? (labelByYear.get(best.fiscal_year) ?? String(best.fiscal_year))
                                : null
                            }
                            query={q}
                            open={openSource?.chunkId === best.chunk_id}
                            onToggle={(chunkId) =>
                              setOpenSource((cur) =>
                                cur?.chunkId === chunkId
                                  ? null
                                  : {
                                      chunkId,
                                      // stripTags, NOT the raw parsed title: the drawer
                                      // takes a plain STRING and renders it as text, so a
                                      // struck title arrived with its markup visible —
                                      // "<strike>appropriation; Ganado School Loop Road"
                                      // printed literally in the breadcrumb and again in
                                      // the "Source:" line. Exactly the defect F16 exists
                                      // to prevent, missed because the card renders through
                                      // BillTitle and only the DRAWER takes a bare string.
                                      // Found by opening a real note (2026-08-13).
                                      title: stripTags(parseNoteTitle(noteDoc.doc_title).title),
                                      year: best.fiscal_year,
                                    },
                              )
                            }
                          />
                        );
                      })}
                    </div>
                  )}
                </section>
                {!contentsBusy && <ModeToggle on onClick={toggleMode} />}
              </>
            ) : (
              <>
                {cards.map((card, i) => (
                  <SessionCard
                    key={card.session.year}
                    card={card}
                    chamber={chamber}
                    open={openSessions.get(card.session.year) ?? defaultOpen(i)}
                    onToggle={(year) =>
                      setOpenSessions((prev) => {
                        const next = new Map(prev);
                        // Flip what is ACTUALLY ON SCREEN, not a recomputed default: the
                        // default differs by mode (newest one while browsing, newest three
                        // during a title search), and re-deriving it here is how the two
                        // drift apart. The symptom would be a first click that appears to do
                        // nothing.
                        const shown = prev.get(year) ?? defaultOpen(cards.findIndex((c) => c.session.year === year));
                        next.set(year, !shown);
                        return next;
                      })
                    }
                  />
                ))}
                {q !== "" && cards.length === 0 && (
                  <section className="yg">
                    <p className="empty">No note titles or bill numbers match “{q}”.</p>
                  </section>
                )}
                {/* The mode toggle, in the slot the retired "Search all legislative sessions"
                    pill used to occupy (spec F7). Rendered whenever the box has text — NOT
                    only when title mode is empty: a single topical word like "water" matches
                    11 titles and so never auto-escalates, by design, which makes this the
                    only route to the note text exactly there. */}
                {q !== "" && <ModeToggle on={false} onClick={toggleMode} />}
              </>
            )}
          </div>
        </div>
      </div>

      {/* F14: "Open note" opens the SOURCE DRAWER, in-app, at the cited passage — not the
          PDF. The page pill it replaced was the drawer's trigger, and handing that click to
          a new tab would delete the only surface that shows the cited span in place, which
          is most of what makes a result checkable. The drawer carries its own "Open the
          source PDF" link out to azleg.gov. */}
      {openSource && (
        <SourcePanel
          chunkId={openSource.chunkId}
          // MUST be passed: this prop DEFAULTS TO "budget", and a miss would 404 every
          // drawer on this page against the wrong table — with an honest error message, but
          // a uniformly broken feature, and invisible in jsdom.
          corpus="fiscal_notes"
          docTitle={openSource.title}
          fiscalYear={openSource.year}
          onClose={() => setOpenSource(null)}
        />
      )}
    </main>
  );
}

/** The titles/contents toggle, in `.allbar` — the slot the retired "Search all legislative
 *  sessions" pill used to occupy (spec F7). Its whole job was widening scope past the one
 *  selected session; with sessions as a filter, search always spans everything in scope. */
function ModeToggle({ on, onClick }: { on: boolean; onClick(): void }) {
  return (
    <div className="allbar">
      {/* Only the APPLICABLE label is rendered, which is this file's stated rule for every
          other control (deviation 2): the mockup emits both and lets CSS hide one because a
          static page must, and here the state is known. It also stops the button from
          having an accessible name that says BOTH "Search note contents" and "Back to title
          matches" at once — which is what it did until 2026-08-13, making the control
          impossible to assert on and, more importantly, ambiguous to a screen reader. */}
      <button type="button" className={on ? "allbtn on" : "allbtn"} aria-pressed={on} onClick={onClick}>
        {on ? (
          <span className="all-on">↩ Back to title matches</span>
        ) : (
          <span className="all-off">
            <SearchIcon /> Search note contents
          </span>
        )}
      </button>
    </div>
  );
}
