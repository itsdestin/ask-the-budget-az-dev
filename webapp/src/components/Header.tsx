import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import * as api from "../api";

// Ported from the mockup's `header.site` block (webapp/reference/index.html):
// sticky white bar, 3px navy-900 bottom border, logo left, centered inline pill
// nav. Class names are the mockup's so its CSS applies unmodified (spec S12).
//
// Deviations from the mockup markup, all deliberate:
//  - <NavLink to> instead of <a href="subpage-*.html"> so nav is client-side routing
//    and the current surface gets the azure "active" pill automatically.
//  - The mockup's eight JLBC menu items (several with dropdowns) collapse to this
//    app's four real surfaces. Nothing is linked that doesn't exist.
//  - The mockup's round magnifier button (`.search-icon-btn`, a shortcut to its
//    search page) is dropped: "Budget Documents" is a first-class nav pill here, so
//    the button would be a second link to the same route.
const NAV_ITEMS = [
  // Renamed from "Budget Search" (Destin, 2026-07-31): AI Mode is no longer a
  // toggle on this page, so the pill names what the page IS — the document
  // browser — rather than one of two things it used to do.
  { to: "/search", label: "Budget Documents" },
  { to: "/fiscal-notes", label: "Fiscal Notes" },
  { to: "/upload", label: "Upload" },
  { to: "/settings", label: "Settings" },
];

export function Header() {
  // The Admin pill renders only for the admin (Plan 5 Task 8). This is
  // presentation, not protection — the gate that matters is server-side, and
  // it is soft by design (spec S11). Hiding the pill keeps the page from
  // being advertised office-wide; it does not keep anyone out, and nothing
  // behind it would be harmful if it did not.
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    let cancelled = false;
    // A failure here means no pill, which is the right default: better a
    // missing link than a link that 403s.
    api.me().then((m) => !cancelled && setIsAdmin(m.is_admin)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="site" data-testid="header">
      <div className="wrap head">
        {/* Link, not NavLink: the logo is branding, so it wants no active styling —
            NavLink would also mark it aria-current="page" at "/" alongside the Home
            pill, and any future `.logo.active` rule would apply to it by surprise. */}
        <Link className="logo" to="/" aria-label="JLBC home">
          {/* Served from webapp/public/. The mark reads "JLBC SEARCH" over the
              Capitol dome and Winged Victory, so the alt text says the app's
              name and then expands the acronym — a screen-reader user gets what
              a sighted user gets, not just the initials.

              The file ships with a real alpha channel. The source art came with
              an opaque white background, which is invisible in this white header
              but would render as a white rectangle anywhere else (the navy home
              band, a print stylesheet). It was cut out with a luminance ramp
              rather than a hard threshold so the anti-aliased letter edges don't
              carry a white fringe. */}
          <img
            src="/jlbc-logo.png"
            alt="JLBC Search — Joint Legislative Budget Committee"
          />
        </Link>
        <nav className="primary" aria-label="Primary">
          {/* Home is the mockup's icon-only house pill; aria-label carries the
              accessible name since there is no visible text. `end` is belt-and-braces:
              react-router 7.18 already never prefix-matches "/" (its prefix branch
              requires the next char to be "/"), so `end` is a no-op here today — it's
              kept explicit so a future router version can't quietly light this pill on
              every route. */}
          <div className="nav-item">
            <NavLink to="/" end aria-label="Home" title="Home">
              <svg
                className="home-ic"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M3 11.5 12 4l9 7.5" />
                <path d="M5 10v9h14v-9" />
              </svg>
            </NavLink>
          </div>
          {NAV_ITEMS.map((item) => (
            <div className="nav-item" key={item.to}>
              <NavLink to={item.to}>{item.label}</NavLink>
            </div>
          ))}
          {isAdmin ? (
            <div className="nav-item" data-testid="nav-admin">
              <NavLink to="/admin">Admin</NavLink>
            </div>
          ) : null}
          {/* AI Mode (Destin, 2026-07-31). Icon-only in the house pill's exact
              shape — aria-label + title carry the accessible name — because it is
              a MODE, not another corpus, and giving it a word in the same row as
              "Budget Documents"/"Fiscal Notes" would read as a fourth place to
              browse. `.nav-ai` is what pulls it to the right of the centered pill
              group (see app.css); the separation IS the statement that it stands
              apart from the corpora. */}
          <div className="nav-item nav-ai">
            <NavLink to="/ai" aria-label="AI Mode" title="AI Mode">
              <AiSparkIcon />
            </NavLink>
          </div>
        </nav>
      </div>
    </header>
  );
}

/** The AI sparkle, built to the house glyph's recipe so the two read as one set:
 *  same 24×24 box, same `fill="none" stroke="currentColor" strokeWidth=2`, same
 *  round caps/joins, no fills and no gradients.
 *
 *  Shape: one four-point star with concave sides (the conventional AI sparkle),
 *  set low-left, plus a small plus-mark spark up-right. The plus rather than a
 *  second miniature star is deliberate — at the 18px the nav renders this at, a
 *  5-unit star with a 2-unit stroke fills in solid and reads as a blob, while
 *  two crossed strokes stay crisp. (It is also the idiom Lucide's own `sparkles`
 *  uses for its small sparks, so it looks conventional rather than invented.)
 *
 *  Its own class, not `.home-ic`: the star's mass sits inside its box where the
 *  house's fills it, so the two may need different sizes later. */
function AiSparkIcon() {
  return (
    <svg
      className="ai-ic"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 3.5Q11.2 10.3 17.5 11.5Q11.2 12.7 10 19.5Q8.8 12.7 2.5 11.5Q8.8 10.3 10 3.5Z" />
      <path d="M19 3v4" />
      <path d="M21 5h-4" />
    </svg>
  );
}
