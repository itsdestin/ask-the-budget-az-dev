import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
// The mockup's magnifier glyph, shared with the search page (Task 9) so the two
// pages can't drift apart. Sizing still comes from each page's own CSS.
import { SearchIcon } from "../components/SearchIcon";

// Home — ported from the approved JLBC mockup's home page (webapp/reference/index.html),
// trimmed to this app's three surfaces (spec S12: port, don't redesign).
//
// What carries over, with the mockup's own class names so its CSS applies unmodified:
//   .snapshot / .snap-h1 / .snap-tag  — the capitol-photo hero, navy-banded top and
//     bottom, title centered with a one-line tagline under it.
//   .metric-overlap / .m-cards / .m-card (+ .cardhead / .ic / .t / .d / .arr) — the
//     three white gateway cards that float up and overlap the hero's lower band.
//   .search-field (+ .s-ic) — the mockup's big azure-buttoned pill search box.
//
// What is dropped, and why:
//   - Everything the mockup's <main> held: "Budget & Revenue Updates", "Committee
//     Meetings", the Quick Links sidebar and the promo panel. All of it is JLBC.gov
//     content this app does not have. Because they are gone, the mockup's
//     `main .wrap` two-column grid (1fr 340px) is NOT ported at all — there is no
//     sidebar for the second column to hold. See app.css for the note.
//   - The `.gov-pill` glass pill ("Fiscal Policy Analysis … ★ azleg.gov"): it exists to
//     link the official state site, which this internal tool has no business claiming.
//     Its slot under the title is filled by `.snap-tag`, a tagline rule the mockup's own
//     stylesheet defines (and this A2c variant happens to leave unused) — so the
//     subtitle below is still mockup CSS, not new CSS.
//   - The CSS-only `(i)` image-credit popover (`.credit-*`), a checkbox-hack modal.
//     Recording the credit here so it is not lost with the markup: the hero background
//     is from the Arizona Memory Project
//     (https://azmemory.azlibrary.gov/assets/display/1581392-max), modified with Gemini.
//   - The mockup's search box lived in the CENTER gateway card (a GET form to its
//     search page). Here the search box is the hero's centerpiece per the plan, and the
//     freed center slot is a third peer card (AI Mode). Same `.search-field` markup and
//     CSS, moved; see the deviation notes in app.css for the two rules that had to
//     change as a result (the 1fr/1.5fr/1fr column ratio and `align-items`).
export function Home() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  return (
    // The mockup keeps the hero OUTSIDE <main> (its <main> was just the two-column
    // body). Here the hero IS the page's content, and — more importantly — every
    // ported home rule is scoped under `.page-home`, which sits on this element, so
    // anything that needs those rules must live inside it.
    <main className="page-home" data-testid="home">
      {/* No aria-label here: labelling the <section> would promote the hero to a named
          region landmark ("Search…"), duplicating the landmark the search form inside it
          already contributes via role="search". */}
      <section className="snapshot">
        <div className="wrap">
          <h1 className="snap-h1">Ask the Budget AZ</h1>
          <p className="snap-tag">Search Arizona budget documents and fiscal notes</p>
          {/* The mockup's form did a plain GET to its search page; this one hands the
              query to the router so /search owns the fetch. */}
          <form
            className="hero-search"
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              // Don't route a blank (or whitespace-only) search: /search queries on mount
              // from ?q=, so an empty q would land the user on a results page that fires a
              // pointless request and has nothing to show.
              const query = q.trim();
              if (!query) return;
              navigate("/search?q=" + encodeURIComponent(query));
            }}
          >
            <div className="search-field">
              <SearchIcon className="s-ic" />
              <input
                type="search"
                name="q"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search budgets, reports, fiscal notes…"
                aria-label="Search Arizona budget documents"
              />
              <button type="submit">Search</button>
            </div>
          </form>
        </div>
      </section>

      <div className="wrap metric-overlap">
        <div className="m-cards">
          {/* Card accents keep the mockup's pairings: azure (a-gold) on the magnifier
              card, cobalt (a-red) on the fiscal-note card, cerulean (a-teal) — the accent
              its third card used — on AI Mode. Per DESIGN-SYSTEM.md §2 all three are
              decorative rhythm, not encoded meaning, so a-teal on the inert card carries
              no "disabled" signal; the dimming and the copy do that. */}
          {/* aria-label so the link's accessible name is the card TITLE. Without it the
              name is the card's whole ~180 characters of text, which reads terribly in a
              screen reader's link list. */}
          <Link className="m-card a-gold" to="/search" aria-label="Budget Library">
            <div className="cardhead">
              <span className="ic">
                <SearchIcon />
              </span>
              {/* <h2>, not <div>: gives the page a heading outline under the hero's h1.
                  Visually identical — the base reset zeroes heading margins and `.t`
                  supplies the size/weight the mockup's div had. */}
              <h2 className="t">Budget Library</h2>
            </div>
            <p className="d">
              Every ingested JLBC report, baseline book, appropriations report, and
              executive budget — searched full text, with every hit linked to the exact
              PDF page behind it.
            </p>
            <span className="arr">Search documents →</span>
          </Link>

          {/* AI Mode has no route yet (Plan 4 wires it), so it is a <div>, not a <Link>:
              an anchor that only *looks* disabled is still focusable and still
              navigates on Enter. `title` carries the explanation on hover — the mockup
              has no tooltip pattern of its own to borrow.
              `aria-disabled` is a semantic marker only: assistive tech ignores it on a
              roleless <div>, and it is not doing hidden a11y work here. The visible
              "Needs an API key." line is what actually tells a user why the card is
              dead — if this ever becomes a real control, the attribute starts mattering. */}
          <div
            className="m-card a-teal is-disabled"
            aria-disabled="true"
            title="AI answers require an API key — coming with AI Mode"
          >
            <div className="cardhead">
              <span className="ic">
                {/* The mockup has no AI/sparkle glyph; rather than invent one, this is
                    its Arizona star path — `.azstar`, which appears exactly once in the
                    mockup, as the divider inside the hero's `.gov-pill` — and which reads
                    as the conventional "AI sparkle". */}
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 2l2.9 6.3 6.9.7-5.1 4.6 1.4 6.8L12 17.8 5.9 20.4l1.4-6.8L2.2 9l6.9-.7L12 2z" />
                </svg>
              </span>
              <h2 className="t">AI Mode</h2>
            </div>
            <p className="d">
              Ask a question in plain language and get a written answer, with every claim
              carrying a citation to the page it came from. Needs an API key.
            </p>
            <span className="arr">Coming soon</span>
          </div>

          <Link className="m-card a-red" to="/fiscal-notes" aria-label="Fiscal Notes">
            <div className="cardhead">
              <span className="ic">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <path d="M6 2h9l5 5v15H6z" />
                  <path d="M14 2v6h6" />
                  <path d="M10 13h4M12 11v6" />
                </svg>
              </span>
              {/* Titled for the surface it opens. The mockup called this card "Bill
                  Analysis"; this app's nav pill and route are both "Fiscal Notes", and
                  two names for one destination would be worse than a copy change. */}
              <h2 className="t">Fiscal Notes</h2>
            </div>
            <p className="d">
              JLBC's bill analyses by session year — the revenue and expenditure impacts
              of proposed legislation.
            </p>
            <span className="arr">Browse by year →</span>
          </Link>
        </div>
      </div>
    </main>
  );
}
