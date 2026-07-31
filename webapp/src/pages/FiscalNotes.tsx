import { memo, useEffect, useMemo, useRef, useState } from "react";
// Namespace import, and every call goes through `api.fiscalNotes()`: the page's test
// intercepts the request with vi.spyOn(api, "fiscalNotes"), which can only see calls
// made through the module object.
import * as api from "../api";
import type { Bill, Session } from "../api";
import { AiModePanel, AiModeToggle } from "../chat/AiModePanel";
import { useAiStatus } from "../chat/use-ai-status";
import { useChat } from "../chat/use-chat";
import { SearchIcon } from "../components/SearchIcon";

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
// The real layout, top to bottom: `.subhero` band → `.wrap.fnwrap` → `.fnlayout` grid of
// a sticky 248px `.fnside` filter rail (`.fside-search` box with `.clr-x`, the
// `.chswitch`/`.chseg` segmented chamber control, and a `.yscroll` list of `.frow` session
// rows with `.frow-n` counts) beside `.fnmain`, which stacks one `.yg` card per session
// (`.yg-head`: `.yg-yr` session name + `.yg-meta` count + the `.sortctl` menu; body: ONE
// merged `.fnlist` of `.fbill` rows — no chamber columns) and ends with the `.allbar`
// "Search all legislative sessions" pill.
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

/** Matches the source page's strike/rename convention:
 *  `<strike>old title</strike> (NOW: new title)` — and its sibling form,
 *  `<strike>old title</strike> S/E: new title` (S/E = a strike-everything amendment).
 *  Both fall out of "whatever text follows `</strike>`", so one pattern covers them. */
const STRUCK_TITLE = /^([\s\S]*?)<strike>([\s\S]*?)<\/strike>([\s\S]*)$/i;

/** Remove any markup and collapse the whitespace it leaves behind.
 *
 *  WHY this exists at all: ~241 of the 2,126 titles in the snapshot arrive as RAW HTML from
 *  the scraped source. Verified against app/data/fiscal-notes-snapshot.json —
 *  `<strike>`/`</strike>` are the ONLY tags that appear (241 of each, nothing else), and no
 *  HTML entities appear either (the single `&` in the corpus is the literal one in "G&F"),
 *  so nothing here needs entity decoding. The mockup, being a static file, just lets the
 *  browser parse those tags; this reaches the same result safely. */
function stripTags(text: string): string {
  return text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/** The words of a title a reader can actually SEE — what the filter searches and what the
 *  A-Z sort compares, so that typing "strike" cannot match 241 unrelated bills. This is
 *  also what the mockup's island reads (`.fbill-desc`'s textContent, tags already parsed
 *  away by the browser). */
function titleText(title: string): string {
  return title.includes("<") ? stripTags(title) : title;
}

/** Render a bill title, honestly and safely.
 *
 *  WHY not `{title}` directly: React escapes strings, so the 241 HTML-bearing titles would
 *  show users literal "<strike>…</strike>" tags.
 *  WHY not dangerouslySetInnerHTML: this text came from a scrape. Injecting it as HTML would
 *  hand whatever the source page contains — now, or after a Plan 3 refresh — straight to the
 *  DOM; one `<script>` in one title is enough.
 *  So: recognize the ONE documented pattern and build real elements from it, and strip tags
 *  from anything else. Unknown or unclosed markup degrades to plain text, never to injected
 *  HTML. */
function BillTitle({ title }: { title: string }) {
  // Fast path — ~89% of titles are plain text with no markup to reason about.
  if (!title.includes("<")) return <>{title}</>;
  const parts = STRUCK_TITLE.exec(title);
  if (!parts) return <>{stripTags(title)}</>;
  const [, lead, struck, rest] = parts;
  const before = stripTags(lead);
  const after = stripTags(rest);
  return (
    <>
      {before ? `${before} ` : ""}
      {/* <s>, not <strike>, which is obsolete in HTML5. It is the semantic element for "no
          longer accurate", which is exactly what a retitled bill's old title is. */}
      <s>{stripTags(struck)}</s>
      {after ? ` ${after}` : ""}
    </>
  );
}

// ---------------------------------------------------------------------------
// Filtering + sorting — behavior parity with the island (build.py:153-201)
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

/** The mockup's `.yg-meta` wording, one noun per chamber segment. */
const META_NOUN: Record<Chamber, { cls: string; noun: string }> = {
  all: { cls: "ym-all", noun: "Fiscal Notes" },
  house: { cls: "ym-h", noun: "House Notes" },
  senate: { cls: "ym-s", noun: "Senate Notes" },
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

/** One `.yg` session card: header (name + count + sort menu) and the merged bill list. */
function SessionCard({
  card,
  chamber,
  sort,
  onSort,
}: {
  card: Card;
  chamber: Chamber;
  sort: SortKey;
  onSort: (key: SortKey) => void;
}) {
  const meta = META_NOUN[chamber];
  const current = SORT_OPTIONS.find((o) => o.key === sort);
  return (
    <section className={`yg y${card.session.year}`}>
      <div className="yg-head">
        <div className="yg-ttl">
          <span className="yg-yr">{card.session.name}</span>
          {/* Accurate by construction: non-matching rows are removed, so the count of what
              is rendered IS the count of what the card shows. The mockup emits all three
              nouns and lets CSS pick; only the applicable one is rendered here. */}
          <span className="yg-meta">
            <span className={meta.cls}>
              {card.bills.length} {meta.noun}
            </span>
          </span>
        </div>
        {/* `.sortctl` opens on :hover / :focus-within — pure CSS, as in the mockup. Its
            tabIndex={0} is the mockup's own and is load-bearing: the options live in a
            `visibility:hidden` menu and so are unreachable by Tab until something inside
            `.sortctl` has focus. */}
        <div className="sortctl" tabIndex={0}>
          <span className="sortbtn">
            Sort: <span className="sortcur">{current?.current}</span>{" "}
            <svg className="sb-chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="m1 1 4 4 4-4" />
            </svg>
          </span>
          <div className="sortmenu">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                className={opt.key === sort ? `sortopt o-${opt.key} on` : `sortopt o-${opt.key}`}
                aria-pressed={opt.key === sort}
                onClick={() => onSort(opt.key)}
              >
                {opt.menu}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="fnlist">
        {card.bills.map((bill) => (
          // bill_number is NOT unique inside a session: an original note and its revision
          // share the number and differ only by URL (93 such rows in the snapshot, up to 3
          // per number — the mockup dedupes on the same (number, url) pair). The URL is what
          // makes the key unique.
          <BillRow key={`${bill.bill_number}|${bill.fiscal_note_url}`} bill={bill} />
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function FiscalNotes() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  // Retry counter — the same device the Search page uses: re-running an identical request
  // needs something in the dependency list that actually changes.
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [chamber, setChamber] = useState<Chamber>("all");
  const [sort, setSort] = useState<SortKey>("na");
  // The session the sidebar has selected. null = "whatever the newest session is", so the
  // default survives the payload arriving without needing an effect to backfill it.
  const [pickedYear, setPickedYear] = useState<number | null>(null);
  // The `.allbtn` scope toggle (the mockup's #fnAll checkbox).
  const [searchAll, setSearchAll] = useState(false);
  const box = useRef<HTMLInputElement>(null);

  // AI Mode (Plan 4 Task 12). The pill lives in the page-head band only; the
  // filter rail below is Plan 3's and is not touched. Turning it on swaps the
  // directory for a conversation over the fiscal-note corpus — one answer
  // surface at a time, same posture as the search page — and turning it off
  // re-renders the directory from state that the toggle never touched.
  const [aiOn, setAiOn] = useState(false);
  const aiStatus = useAiStatus();
  // Cheap while idle: no conversation is opened until the first send.
  const chat = useChat("fiscal_notes");

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
  // The API guarantees newest-session-first, so [0] is the default selection.
  const selectedYear = pickedYear ?? sessions[0]?.year ?? null;
  const selected = sessions.find((s) => s.year === selectedYear);
  const q = query.trim();
  // The island only honors the scope toggle while something is typed (build.py:174
  // force-unchecks it on an empty box), so an empty query always means "selected session".
  const wide = q !== "" && searchAll;

  const cards = useMemo<Card[]>(() => {
    const scope = wide ? sessions : sessions.filter((s) => s.year === selectedYear);
    return scope
      .map((session) => ({
        session,
        bills: sortBills(
          session.bills.filter((b) => inChamber(b, chamber) && matchesQuery(b, q)),
          sort,
        ),
      }))
      // With a query, a session with no matches disappears (the island hides the group).
      // With no query the selected session's card stays even if the chamber filter empties
      // it — the mockup keeps the card and only hides its rows.
      .filter((card) => q === "" || card.bills.length > 0);
  }, [sessions, selectedYear, chamber, q, sort, wide]);

  // Per-session counts for `.frow-n`. Scoped to the chamber segment (a persistent lens on
  // the whole page) but NOT to the typed query: this is the session's note inventory, a
  // different quantity from "matches", and the status line below states matches explicitly.
  // The mockup shows the raw total here and ignores the chamber; narrowing it keeps the
  // number from contradicting the card the row selects.
  const sessionCounts = useMemo(
    () =>
      new Map(sessions.map((s) => [s.year, s.bills.filter((b) => inChamber(b, chamber)).length])),
    [sessions, chamber],
  );

  const matched = cards.reduce((n, c) => n + c.bills.length, 0);
  const inScope = selected ? (sessionCounts.get(selected.year) ?? 0) : 0;
  /** Plural noun for the chamber lens, used when no number precedes it. */
  const nouns =
    chamber === "all" ? "fiscal notes" : chamber === "house" ? "House notes" : "Senate notes";
  /** "1 fiscal note" / "7 fiscal notes" — agreement matters in a spoken live region. */
  const counted = (n: number) => `${n} ${nouns.slice(0, -1)}${n === 1 ? "" : "s"}`;

  /** The live-region filter line. Every branch describes exactly the set on screen: what is
   *  counted is what the cards below render, and the scope it names is the scope in force. */
  function status(): string {
    if (phase.kind === "loading") return "Loading fiscal notes…";
    if (!sessions.length) return "No fiscal notes published yet.";
    const where = selected?.name ?? "the selected session";
    if (!q) return `${counted(inScope)} in ${where}.`;
    if (wide)
      return matched === 0
        ? `No ${nouns} matching "${q}" in any of the ${sessions.length} sessions.`
        : `${counted(matched)} matching "${q}" across ${cards.length} of ${sessions.length} sessions.`;
    return matched === 0
      ? `No ${nouns} matching "${q}" in ${where} — try searching all sessions.`
      : `${matched} of ${counted(inScope)} matching "${q}" in ${where}.`;
  }

  /** Clearing the box also drops the scope toggle, exactly as the island does. */
  function clearQuery() {
    setQuery("");
    setSearchAll(false);
    box.current?.focus();
  }

  return (
    <main className="page-fiscal-notes" data-testid="fiscal-notes">
      <section className="subhero">
        <div className="wrap">
          <h1>Fiscal Notes</h1>
          {/* Verbatim from the generated page. */}
          <p className="lead">
            Independent fiscal-impact analyses of pending legislation — each bill's effect on
            state revenues, spending, and the General Fund.
          </p>
          {/* ONE chip, which is what the generated page ships: build.py:266 deliberately
              strips the "57th Legislature…" chip from base.html's hero. (DESIGN-SYSTEM.md §6
              asks for 2-3 chips on every sub-page, so the generated artifact and the doc
              disagree here; the artifact is the S12 source of truth, so one chip it is.) */}
          <div className="chips">
            <span className="chip">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 2h9l5 5v15H6z" />
                <path d="M14 2v6h6" />
              </svg>{" "}
              House &amp; Senate bills
            </span>
            {/* Page-head region only — Plan 3 owns the rail below. */}
            <AiModeToggle on={aiOn} onChange={setAiOn} status={aiStatus} />
          </div>
        </div>
      </section>

      {aiOn && (
        <div className="wrap fnwrap">
          <AiModePanel chat={chat} status={aiStatus} corpus="fiscal_notes" />
        </div>
      )}

      {!aiOn && (
      <div className="wrap fnwrap">
        {/* The status line lives ABOVE the grid, spanning both columns: inside `.fnmain`
            it pushed the first session card down, leaving the rail's top edge floating
            higher than the card it sits beside (Destin flagged the misalignment). Up
            here both grid columns start level, directly under the note.
            role="status" makes it a live region, so the load, the result count and any
            error are announced as they replace each other instead of only being drawn
            (same posture as the search page's status line). */}
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
              {/* The mockup wraps the input in the `<label class="fside-search">` itself, so
                  clicking the pill focuses the box; the visible-label duty is carried by the
                  placeholder plus the aria-label. */}
              <label className="fside-search">
                <SearchIcon />
                <input
                  ref={box}
                  type="text"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    // Emptying the box reverts to the selected session (build.py:174).
                    if (!e.target.value.trim()) setSearchAll(false);
                  }}
                  placeholder="Bill # or keyword…"
                  aria-label="Filter fiscal notes by bill number or keyword"
                  autoComplete="off"
                />
                {/* `.clr-x` is a real button in the mockup too; `.show` is its own visibility
                    class, driven there by the island and here by state. */}
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
              {/* aria-labelledby, not aria-label: pointing the group at the visible `.flbl`
                  names it once instead of announcing "Chamber" twice. */}
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
              {/* `.yscroll` caps the list at 330px and scrolls — the mockup's own answer to
                  28 sessions in a 248px rail. Selecting a row swaps which card `.fnmain`
                  shows; the generated page scrolls the page nowhere, so neither does this. */}
              <div className="yscroll" role="group" aria-labelledby="fn-session-label">
                {sessions.map((session) => (
                  <button
                    key={session.year}
                    type="button"
                    className={session.year === selectedYear ? "frow on" : "frow"}
                    aria-pressed={session.year === selectedYear}
                    // The visible label is the YEAR plus a count, as in the mockup; the full
                    // session name and the noun go in the accessible name. The year and the
                    // count both appear in it, so a speech-input user saying what they see
                    // still hits the row (WCAG 2.5.3).
                    aria-label={`${session.name} — ${counted(sessionCounts.get(session.year) ?? 0)}`}
                    onClick={() => {
                      setPickedYear(session.year);
                      // Picking a session drops the widened scope (build.py:199).
                      setSearchAll(false);
                    }}
                  >
                    <span>{session.year}</span>
                    <span className="frow-n">{sessionCounts.get(session.year) ?? 0}</span>
                  </button>
                ))}
              </div>
            </div>

            <SemanticRailSearch />
          </aside>

          <div className="fnmain">
            {phase.kind === "error" ? (
              // Reuses the page's one standalone action pill rather than inventing a button.
              <div className="allbar">
                <button type="button" className="allbtn" onClick={() => setAttempt((a) => a + 1)}>
                  Retry
                </button>
              </div>
            ) : (
              <>
                {cards.map((card) => (
                  <SessionCard
                    key={card.session.year}
                    card={card}
                    chamber={chamber}
                    sort={sort}
                    onSort={setSort}
                  />
                ))}
                {phase.kind === "ready" && sessions.length > 0 && (
                  <div className="allbar">
                    <button
                      type="button"
                      className={wide ? "allbtn on" : "allbtn"}
                      aria-pressed={wide}
                      // Inert with an empty box — see deviation 5 in the header comment.
                      disabled={q === ""}
                      onClick={() => setSearchAll((v) => !v)}
                    >
                      <span className="all-off">
                        <SearchIcon /> Search all legislative sessions
                      </span>
                      <span className="all-on">↩ Search only the selected session</span>
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Rail: semantic search over the fiscal-note corpus (Plan 3)
// ---------------------------------------------------------------------------

/** Meaning-based search across the ingested notes, beside the exact-match
 *  filter box above it.
 *
 *  Two of them, because they answer different questions. The filter box finds a
 *  bill you can already name. This one is the coordinator's actual triage
 *  question — "have we written a note like this before?" — where the bill number
 *  is exactly what you don't have.
 *
 *  It stays disabled until the corpus reports passages. Ingesting the notes is a
 *  separate, long-running act (upload or refresh), so on a fresh install this
 *  really can be empty, and a live-looking box that can only ever return nothing
 *  is worse than one that says why.
 *
 *  Submit-driven, not keystroke-driven: the reranker runs locally on CPU at
 *  roughly three seconds a query, so search-as-you-type would queue a backlog of
 *  stale queries behind every word. */
function SemanticRailSearch() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [q, setQ] = useState("");
  const [phase, setPhase] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "done"; results: api.SearchResult[] }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  useEffect(() => {
    let live = true;
    api
      .fiscalNotesStatus()
      .then((s) => live && setReady(s.chunks > 0))
      // A failed probe means the corpus can't be searched anyway; treat it as
      // not-ready rather than showing an error for a control nobody asked for.
      .catch(() => live && setReady(false));
    return () => {
      live = false;
    };
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const query = q.trim();
    if (!query) return;
    setPhase({ kind: "loading" });
    try {
      const body = await api.search(query, {}, "fiscal_notes");
      setPhase({ kind: "done", results: body.results });
    } catch (err) {
      setPhase({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <div className="fgrp" data-testid="fn-semantic">
      <div className="flbl">{ready ? "Search note text" : "Coming soon"}</div>
      <form onSubmit={run}>
        {/* The mockup wraps the input in the label itself so clicking the pill
            focuses the box; `.is-disabled` is this page's existing dimming. */}
        <label className={`fside-search${ready ? "" : " is-disabled"}`}>
          <SearchIcon />
          <input
            type="text"
            value={q}
            disabled={!ready}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Semantic search across all notes"
            aria-label="Semantic search across all notes"
            aria-describedby="fn-semantic-hint"
          />
        </label>
      </form>
      {!ready && (
        <p className="fnnote" id="fn-semantic-hint">
          Unlocks when the fiscal-note corpus is ingested.
        </p>
      )}
      {ready && phase.kind === "idle" && (
        <p className="fnnote" id="fn-semantic-hint">
          Describe the topic and press Enter — e.g. “community college
          expenditure limits”.
        </p>
      )}
      {phase.kind === "loading" && (
        <p className="fnnote" role="status">
          Searching…
        </p>
      )}
      {phase.kind === "error" && (
        <p className="fnnote" role="status">
          <span className="err">{phase.message}</span>
        </p>
      )}
      {phase.kind === "done" && (
        <div className="fnsem" role="status">
          {phase.results.length === 0 ? (
            <p className="fnnote">No matching passages.</p>
          ) : (
            <ul className="fnsem-list">
              {phase.results.slice(0, 8).map((r) => (
                <li key={r.chunk_id} data-testid="fn-semantic-hit">
                  {/* data-chunk-id is Plan 4's hook for opening the passage in
                      the viewer; it is inert here. */}
                  <a
                    className="fnsem-hit"
                    data-chunk-id={r.chunk_id}
                    href={r.doc_url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span className="fnsem-title">{r.doc_title}</span>
                    <span className="fnsem-snip">{r.snippet}</span>
                    {r.page !== null && (
                      <span className="fnsem-page">p. {r.page}</span>
                    )}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
