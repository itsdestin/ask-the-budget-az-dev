import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
// Namespace import, and every call goes through `api.fiscalNotes()`: the page's test
// intercepts the request with vi.spyOn(api, "fiscalNotes"), which can only see calls
// made through the module object.
import * as api from "../api";
import type { Bill, Session } from "../api";
import { SearchIcon } from "../components/SearchIcon";

// Fiscal Notes — ported from the approved mockup's fiscal-notes directory page
// (webapp/reference/fiscal-notes-build/base.html), keeping its class names so its CSS
// applies unmodified (spec S12: port, don't redesign). Top to bottom, the mockup's own
// structure: `.subhero` title band → `main .wrap` two-column grid → in the main column
// ONE `.card` holding the `.card-head` + `.intro`, the newest session's two-column
// `.bills` grid (`.bcol` House | Senate of `.bill` rows), and then the `.acc` accordion
// whose `.tray` carries every earlier session as a `.yr-mini` block with its own
// `.bills` grid → and an `aside.side` sidebar of `.card`/`.quick` link lists.
//
// This page deliberately does NOT reuse the Budget Search page's FilterBar/ResultCard.
// The mockup styles this directory with a different idiom (`.era-chip` chips, `.bcol`
// columns, `.bill-no`/`.bill-pill` rows) and generalizing the two into one component
// would mean inventing a third design — which S12 forbids. The duplication is the port.
//
// TRACEABILITY EXCEPTIONS (mockup content this page does not carry, and why):
//   - The mockup contains NO JavaScript at all: its accordion is a `:checked` checkbox
//     and its archive filter is a radio group with hardcoded era ranges. The checkbox
//     accordion is ported AS a real checkbox (below), so DESIGN-SYSTEM.md §8's "almost
//     no JavaScript" still holds for that interaction. The text filter, the chamber
//     switcher and the session jump-list are new behavior the plan requires; they are
//     built out of this page's own chip / qlink components.
//   - `.era-radio` + the `#fn-e1|e2|e3:checked ~ .era-list` era filter: DROPPED. Its
//     three buckets are hardcoded to the mockup's 2008-2025 range while the real payload
//     spans 1999-2026, so porting it literally would mis-label the data and re-deriving
//     the buckets would be inventing a filter the mockup never had. The sidebar's
//     session jump-list covers the same "get me to an older session" need.
//     `.era-bar`/`.era-lbl`/`.era-chip` ARE carried — they style the chamber switcher.
//   - The `.promo` "Ballot initiatives" box and two of the three `.quick` "Related
//     Pages" links (Annual Budgets, Tax Handbook, Monthly Fiscal Highlights): they point
//     at JLBC pages this app does not have. The one surviving link goes to the Budget
//     Search page, which is real.
//   - The mockup's `.doc`/`.doc-*` row (and the `.acc-body .tray .doc` overrides): that
//     is its OTHER card's row style; every row on this page is a `.bill`.
//   - The mockup's first `.subhero` chip hardcodes the current session's name, which the
//     card header below already states. It is replaced by a session-count and year-range
//     chip derived from the payload so it stays true as the snapshot grows —
//     DESIGN-SYSTEM.md §6 explicitly sanctions a range chip ("FY 2026-1984").
//   - Shared chrome (`header.site`, `footer.site`, the dead `.search-expand`) lives in
//     components/Header.tsx or is dropped app-wide; not this page's business.

/** Which chamber column(s) the directory is showing. */
type Chamber = "all" | "H" | "S";

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
 *  WHY this exists at all: ~241 of the 2,126 titles in the snapshot arrive as RAW HTML
 *  from the scraped source. Verified against app/data/fiscal-notes-snapshot.json —
 *  `<strike>`/`</strike>` are the ONLY tags that appear (241 of each, nothing else), and
 *  no HTML entities appear either (the single `&` in the corpus is the literal one in
 *  "G&F"), so nothing here needs entity decoding. */
function stripTags(text: string): string {
  return text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/** The words of a title a reader can actually SEE — what the text filter searches, so
 *  that typing "strike" cannot match 241 unrelated bills while a struck old title stays
 *  findable. */
function titleText(title: string): string {
  return title.includes("<") ? stripTags(title) : title;
}

/** Render a bill title, honestly and safely.
 *
 *  WHY not `{title}` directly: React escapes strings, so the 241 HTML-bearing titles
 *  would show users literal "<strike>…</strike>" tags.
 *  WHY not dangerouslySetInnerHTML: this text came from a scrape. Injecting it as HTML
 *  would hand whatever the source page contains — now, or after a Plan 3 refresh —
 *  straight to the DOM; one `<script>` in one title is enough.
 *  So: recognize the ONE documented pattern and build real elements from it, and strip
 *  tags from anything else. Unknown markup degrades to plain text, never to injected
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
      {/* <s>, not <strike>, which is obsolete in HTML5. It is the semantic element for
          "no longer accurate", which is exactly what a retitled bill's old title is. */}
      <s>{stripTags(struck)}</s>
      {after ? ` ${after}` : ""}
    </>
  );
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

/** Collapse a bill number for prefix comparison.
 *
 *  WHY: the snapshot spaces its numbers ("HB 2011") and people type them unspaced
 *  ("hb2011"). Collapsing whitespace on BOTH sides makes either spelling work, so the
 *  filter box is usable for its most obvious purpose. */
function billKey(value: string): string {
  return value.toLowerCase().replace(/\s+/g, "");
}

/** Does this bill survive the text filter?
 *
 *  Two ways in, matching the mockup's framing of this page as a bill directory: a PREFIX
 *  match on the bill number ("hb20" → every HB 20xx), or an ALL-terms keyword match on
 *  the visible title text ("ahcccs rates"). Terms are AND-ed because a second word is a
 *  narrowing, not a widening. */
function matchesText(bill: Bill, needle: string, terms: string[]): boolean {
  if (!needle) return true;
  if (billKey(bill.bill_number).startsWith(billKey(needle))) return true;
  const haystack = titleText(bill.title).toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

/** Sort one chamber column into a readable directory: by bill-number prefix (HB before
 *  HCR before HJR), then numerically.
 *
 *  WHY sort at all: the API's contract only promises newest-session-first (see
 *  app/routes/fiscal_notes.py) — within a session it returns whatever the source emitted,
 *  which today puts SCR 1001 ahead of SB 1009. The mockup's columns are ascending, so ONE
 *  posture — always sort here — keeps that true for any source order, including Plan 3's
 *  live scraper. */
function sortColumn(bills: Bill[]): Bill[] {
  const prefix = (n: string) => n.replace(/[\s\d]+/g, "");
  const number = (n: string) => Number(n.replace(/\D+/g, "")) || 0;
  return [...bills].sort(
    (a, b) =>
      prefix(a.bill_number).localeCompare(prefix(b.bill_number)) ||
      number(a.bill_number) - number(b.bill_number),
  );
}

/** A session with its bills already filtered and split into the two `.bcol` columns.
 *  Sessions whose every bill was filtered out are dropped, so a session that reaches the
 *  DOM always has at least one row. */
interface VisibleSession {
  session: Session;
  matched: number;
  columns: { chamber: "H" | "S"; label: string; bills: Bill[] }[];
}

const COLUMNS = [
  { chamber: "H" as const, label: "House Bills" },
  { chamber: "S" as const, label: "Senate Bills" },
];

function visibleSessions(sessions: Session[], chamber: Chamber, needle: string): VisibleSession[] {
  const terms = needle.split(/\s+/).filter(Boolean);
  const out: VisibleSession[] = [];
  for (const session of sessions) {
    const columns = COLUMNS
      // An unselected chamber's column is removed entirely rather than rendered empty: a
      // "Senate Bills" heading over nothing would read as "this session had none".
      .filter((col) => chamber === "all" || chamber === col.chamber)
      .map((col) => ({
        ...col,
        bills: sortColumn(
          session.bills.filter((b) => b.chamber === col.chamber && matchesText(b, needle, terms)),
        ),
      }))
      .filter((col) => col.bills.length > 0);
    const matched = columns.reduce((n, col) => n + col.bills.length, 0);
    if (matched > 0) out.push({ session, matched, columns });
  }
  return out;
}

/** DOM id of a session block — the target of the sidebar jump-list. */
function sessionAnchor(year: number): string {
  return `fn-session-${year}`;
}

// ---------------------------------------------------------------------------
// Icons — the mockup repeats these inline SVGs on every row; they are hoisted into
// functions so 2,126 bill rows cannot drift apart glyph by glyph. Every path below is
// copied verbatim from base.html.
// ---------------------------------------------------------------------------

/** base.html's document glyph. `lines` adds the two body rules that its `.card-head`
 *  copy carries and that the smaller `.dotic` / `.chip` copies omit. */
function DocIcon({ lines = false }: { lines?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d={lines ? "M14 2v6h6M9 13h6M9 17h6" : "M14 2v6h6"} />
    </svg>
  );
}

/** base.html's house glyph. NOTE: the mockup uses this same glyph in BOTH `.bcol-head`
 *  rows — plainly a copy-paste slip in a hand-built mockup, since the Senate column is
 *  not a house. It is ported as-is anyway: the mockup's icon set has no second chamber
 *  glyph to substitute, and drawing one would be adding a design element S12 says not to
 *  invent. Swap the Senate one the day the mockup gains a glyph for it. */
function ChamberIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10v9h14v-9" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

/** One `.bill` row. Both of the mockup's links point at the same real PDF on azleg.gov
 *  with its `target="_blank" rel="noopener"` — kept, plus `noreferrer` (`noopener` alone
 *  still hands the referrer to the target). */
function BillRow({ bill }: { bill: Bill }) {
  return (
    <div className="bill">
      <div className="bill-main">
        <a
          className="bill-no"
          href={bill.fiscal_note_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {bill.bill_number}
        </a>
        <span className="bill-desc">
          <BillTitle title={bill.title} />
        </span>
      </div>
      <a
        className="bill-pill"
        href={bill.fiscal_note_url}
        target="_blank"
        rel="noopener noreferrer"
        // The pill repeats the row's own link, so its visible text ("Fiscal Note · PDF")
        // is identical on all 2,126 rows. The label adds the bill it belongs to, which is
        // what a link list read out of context needs. The visible text is kept as the
        // label's PREFIX so a speech-input user saying what they can see still hits it
        // (WCAG 2.5.3, label in name).
        aria-label={`Fiscal Note · PDF — ${bill.bill_number}`}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" />
        </svg>{" "}
        Fiscal Note · PDF
      </a>
    </div>
  );
}

/** The mockup's two-column House | Senate grid. */
function BillGrid({ columns }: { columns: VisibleSession["columns"] }) {
  return (
    // `one-col` when a chamber filter left a single column: without it the lone column
    // would sit in one 1fr half of a two-column grid with dead space beside it. The
    // declaration is the mockup's own narrow-screen value for `.bills` (its
    // max-width:760px block), not a new one.
    <div className={columns.length === 1 ? "bills one-col" : "bills"}>
      {columns.map((col) => (
        <div className="bcol" key={col.chamber}>
          <div className="bcol-head">
            <ChamberIcon /> {col.label}
          </div>
          {col.bills.map((bill) => (
            // bill_number is NOT unique inside a session: an original note and its
            // revision share the number and differ only by URL (93 such rows in the
            // snapshot, up to 3 per number). The URL is what makes the key unique.
            <BillRow key={`${bill.bill_number}|${bill.fiscal_note_url}`} bill={bill} />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function FiscalNotes() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  // Retry counter — the same device the Search page uses: re-running an identical
  // request needs something in the dependency list that actually changes.
  const [attempt, setAttempt] = useState(0);
  const [chamber, setChamber] = useState<Chamber>("all");
  const [filter, setFilter] = useState("");
  // Whether the user opened the "Earlier Sessions" accordion themselves.
  const [openedByUser, setOpenedByUser] = useState(false);
  // Set by the sidebar jump-list, consumed by the effect below — AFTER the click has
  // opened the accordion. Scrolling inside the click handler would target an element
  // that is still collapsed (height 0) at that moment.
  const [jumpTo, setJumpTo] = useState<string | null>(null);

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
  const needle = filter.trim().toLowerCase();

  // Memoized because filtering walks all 2,126 bills and sorts every column; without it
  // that would re-run on unrelated state changes (accordion toggle, jump target).
  const visible = useMemo(
    () => visibleSessions(sessions, chamber, needle),
    [sessions, chamber, needle],
  );

  // The newest session is the payload's first (the API guarantees newest-first) and gets
  // the card header; everything older lives in the accordion, exactly as in the mockup.
  // This tracks the SESSION, not the filter: if the newest session has no matches it
  // simply renders no grid, so the page never re-labels a different session as current.
  const newestYear = sessions[0]?.year;
  const current = visible.find((v) => v.session.year === newestYear);
  const earlier = visible.filter((v) => v.session.year !== newestYear);
  const earlierTotal = Math.max(sessions.length - 1, 0);

  const filtering = needle.length > 0 || chamber !== "all";
  // A live filter pins the accordion open: most of the matches are inside it, and leaving
  // them behind a closed lid would make the filter look broken.
  const accordionOpen = filtering || openedByUser;

  useEffect(() => {
    if (!jumpTo) return;
    document.getElementById(jumpTo)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setJumpTo(null);
  }, [jumpTo]);

  const years = sessions.map((s) => s.year);
  const shown = visible.reduce((n, v) => n + v.matched, 0);
  const total = sessions.reduce((n, s) => n + s.bills.length, 0);

  return (
    <main className="page-fiscal-notes" data-testid="fiscal-notes">
      {/* The mockup's `.subhero` band. It sits inside <main> here (the mockup keeps it
          outside, but every ported rule is scoped under `.page-fiscal-notes`, which is on
          this element). Its aria-label="Page header" is dropped: it would add a landmark
          named "Page header" that says nothing a heading doesn't. */}
      <section className="subhero">
        <div className="wrap">
          <h1>Fiscal Notes</h1>
          {/* DESIGN-SYSTEM.md §6: the lead is reserved at two lines and CLAMPED at two, so
              this copy is written to fit rather than left to ellipsis mid-sentence. The
              wording is the mockup's own, trimmed to fit. */}
          <p className="lead">
            JLBC Staff's fiscal-impact analyses of pending legislation — each bill's effect on
            state revenues, spending, and the General Fund.
          </p>
          <div className="chips">
            <span className="chip">
              {/* base.html's calendar glyph, verbatim. */}
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="3" />
                <path d="M16 2v4M8 2v4M3 10h18" />
              </svg>{" "}
              {/* Derived from the payload rather than hardcoded — see the traceability
                  note at the top. The band's height is fixed either way (§6), so this
                  text can land a beat after first paint without shifting anything. */}
              {sessions.length
                ? `${sessions.length} sessions · ${Math.min(...years)}–${Math.max(...years)}`
                : "Every session JLBC has published"}
            </span>
            <span className="chip">
              <DocIcon /> House &amp; Senate bills
            </span>
          </div>
        </div>
      </section>

      <div className="wrap">
        <div className="col-main">
          {phase.kind === "error" ? (
            // `.acc-note` is this page's own small note line; `.err` is the app's error
            // color. The message is the backend's, passed through untouched.
            <p className="acc-note">
              <span className="err">{phase.message}</span>{" "}
              {/* Styled as an `.era-chip` — this page's only small inline button — rather
                  than as a new button design. */}
              <button type="button" className="era-chip" onClick={() => setAttempt((a) => a + 1)}>
                Retry
              </button>
            </p>
          ) : (
            <section className="card">
              <div className="card-head">
                <div className="head-row">
                  <span className="ic">
                    <DocIcon lines />
                  </span>
                  {/* While loading there is no session to name and inventing one would be
                      a lie, so the heading says what the card IS until the name arrives. */}
                  <h2>{sessions[0]?.name ?? "Current session"}</h2>
                  <span className="count">
                    {phase.kind === "loading"
                      ? "Loading…"
                      : filtering
                        ? `${shown} of ${total} bills`
                        : "By chamber"}
                  </span>
                </div>
                {/* The mockup's intro copy, verbatim apart from "select any bill" →
                    "select any bill number", because here BOTH the number and the pill
                    link to the same PDF. */}
                <p className="intro">
                  Fiscal notes are prepared by JLBC Staff as bills advance through the
                  Legislature. Bills are grouped by chamber below — <b>select any bill number</b>{" "}
                  to open its fiscal note PDF.
                </p>
              </div>

              {phase.kind === "loading" && (
                // role="status" makes this a live region, so the load — and then its
                // result — are announced rather than only drawn.
                <p className="acc-note" role="status">
                  Loading fiscal notes…
                </p>
              )}

              {current ? (
                <BillGrid columns={current.columns} />
              ) : (
                phase.kind === "ready" && (
                  <p className="acc-note">
                    {filtering
                      ? "No bills in the current session match this filter — check the earlier sessions below."
                      : "No bills published for the current session yet."}
                  </p>
                )
              )}

              {phase.kind === "ready" && earlierTotal > 0 && (
                <div className="acc">
                  {/* Ported as a REAL checkbox so the mockup's `:checked ~` CSS still
                      drives the open/close animation (DESIGN-SYSTEM.md §8: almost no
                      JavaScript). React only supplies `checked`, because a live filter can
                      also open it. The id is kept from the mockup — there is exactly one
                      accordion on this page, and label/input need an id to pair up. */}
                  <input
                    className="acc-toggle"
                    type="checkbox"
                    id="fn-earlier"
                    checked={accordionOpen}
                    onChange={(e) => setOpenedByUser(e.target.checked)}
                  />
                  <label className="acc-head" htmlFor="fn-earlier">
                    <span className="acc-yr">
                      {/* Range read off the data. Collapses to one year when there is only
                          one earlier session, instead of reading "2025 to 2025". */}
                      Earlier Sessions —{" "}
                      {earlierTotal === 1 ? years[1] : `${Math.min(...years)} to ${years[1]}`}
                    </span>
                    <span className="acc-tab">
                      <span className="acc-meta">
                        {filtering
                          ? `${earlier.length} of ${earlierTotal} sessions match`
                          : `${earlierTotal} ${earlierTotal === 1 ? "session" : "sessions"}`}
                      </span>
                      <svg className="acc-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                        <path d="m6 9 6 6 6-6" />
                      </svg>
                    </span>
                  </label>
                  <div className="acc-body">
                    <div>
                      {/* PERF NOTE: every earlier session's rows are in the DOM at all
                          times — up to ~2,000 `.bill` rows — which is exactly what the
                          mockup does (its 18 sessions are all rendered statically inside
                          this collapsed tray). Kept on purpose: virtualizing would add
                          machinery the design never had, and the filtering above is
                          memoized so typing re-walks the data without re-sorting on
                          unrelated renders. If it ever measures slow, the honest fix is to
                          mount this tray's contents only while the accordion is open. */}
                      <div className="tray">
                        {earlier.length === 0 ? (
                          <p className="acc-note">No earlier session matches this filter.</p>
                        ) : (
                          earlier.map((v) => (
                            <div
                              className="yr-mini"
                              key={v.session.year}
                              id={sessionAnchor(v.session.year)}
                            >
                              <div className="yr-mini-h">{v.session.name}</div>
                              <BillGrid columns={v.columns} />
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="side">
          <section className="card">
            <div className="quick">
              <div className="qh">Filter notes</div>
              {/* base.html has NO text input anywhere, so this is the mockup's OTHER small
                  search pill lifted wholesale: `.search-field` from reference/index.html
                  (the home hero's icon + input pill, already ported once as
                  `.page-home .search-field`). Reusing a real mockup component beats
                  inventing a fourth input design. */}
              <div className="search-field">
                <SearchIcon className="s-ic" />
                <input
                  type="search"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter by bill number or keyword"
                  aria-label="Filter fiscal notes by bill number or keyword"
                  autoComplete="off"
                />
              </div>

              {/* Chamber switcher. `.era-bar`/`.era-lbl`/`.era-chip` are this page's own
                  filter-chip idiom (the mockup uses them for its archive era filter).
                  DEVIATION: the mockup's chips are `<label>`s over a radio group styled by
                  `#id:checked ~ .era-bar label[for=…]`; selection here comes from React
                  state, so they are real `<button>`s carrying an `.on` class with those
                  same declarations. aria-pressed is what tells a screen reader which one
                  is active — the CSS fill alone is a visual-only cue. */}
              <div className="era-bar" role="group" aria-label="Chamber">
                <span className="era-lbl">Chamber</span>
                {[
                  // "All" gets an explicit accessible name: on its own, out loud, the word
                  // says nothing about what it selects.
                  { value: "all" as const, label: "All", name: "All chambers" },
                  { value: "H" as const, label: "House" },
                  { value: "S" as const, label: "Senate" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={chamber === opt.value ? "era-chip on" : "era-chip"}
                    aria-pressed={chamber === opt.value}
                    aria-label={opt.name}
                    onClick={() => setChamber(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* NEW — the mockup has no counterpart. Plan 3 wires this to POST /api/search
                  with corpus "fiscal_notes"; until the fiscal-note corpus is ingested there
                  is nothing to search, so the input carries a real `disabled` attribute
                  rather than looking live and doing nothing. Styling reuses the same
                  `.search-field` pill plus the `is-disabled` dimming Home already ported,
                  and the hint is this page's `.acc-note`. */}
              <div className="qh">Coming soon</div>
              <div className="search-field is-disabled">
                <SearchIcon className="s-ic" />
                <input
                  type="search"
                  disabled
                  placeholder="Semantic search across all notes"
                  aria-describedby="fn-semantic-hint"
                />
              </div>
              <p className="acc-note" id="fn-semantic-hint">
                Unlocks when the fiscal-note corpus is ingested.
              </p>
            </div>
          </section>

          {phase.kind === "ready" && (
            <section className="card">
              <div className="quick">
                <div className="qh">Jump to a session</div>
                {/* The mockup's `.quick a.qlink` rows, one per session. They stay real
                    anchors (so the CSS matches and the target is copyable) but the default
                    jump is prevented: the target may still be inside a collapsed accordion
                    at click time, which the browser would scroll to at height zero.
                    Opening it and scrolling afterwards is the `jumpTo` effect above.
                    The visible label is the YEAR, not the full session name — 28 rows of
                    "57th Legislature, 2nd Reg. Session (2026)" would not fit a 320px
                    column — and the full name is the link's accessible name instead.
                    The mockup's `.arr` slot holds the bill count rather than an arrow:
                    same right-aligned muted slot, and a count is the useful thing here.
                    The list is long (28 rows today) and that is fine — the sidebar does not
                    stick (§8 rule 4) and the bill columns beside it are far taller. */}
                {visible.length === 0 && <p className="acc-note">No session matches this filter.</p>}
                {visible.map((v) => (
                  <a
                    className="qlink"
                    key={v.session.year}
                    href={`#${sessionAnchor(v.session.year)}`}
                    aria-label={`${v.session.name} — ${v.matched} ${v.matched === 1 ? "bill" : "bills"}`}
                    onClick={(e) => {
                      e.preventDefault();
                      if (v.session.year !== newestYear) setOpenedByUser(true);
                      setJumpTo(sessionAnchor(v.session.year));
                    }}
                  >
                    <span className="dotic c-gold">
                      <DocIcon />
                    </span>
                    {v.session.year}
                    <span className="arr">{v.matched}</span>
                  </a>
                ))}
              </div>
            </section>
          )}

          <section className="card">
            <div className="quick">
              <div className="qh">Related Pages</div>
              {/* A router Link, not the mockup's `<a href="subpage-…">`: a plain anchor
                  would reload the whole SPA. It renders an <a>, so `.quick a.qlink` still
                  matches and the markup is the mockup's. */}
              <Link className="qlink" to="/search">
                <span className="dotic c-gold">
                  <SearchIcon />
                </span>
                Budget Document Search
                <span className="arr">→</span>
              </Link>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
