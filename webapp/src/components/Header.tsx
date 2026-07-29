import { NavLink } from "react-router-dom";

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
//    search page) is dropped: "Budget Search" is a first-class nav pill here, so
//    the button would be a second link to the same route.
const NAV_ITEMS = [
  { to: "/search", label: "Budget Search" },
  { to: "/fiscal-notes", label: "Fiscal Notes" },
  { to: "/settings", label: "Settings" },
];

export function Header() {
  return (
    <header className="site" data-testid="header">
      <div className="wrap head">
        <NavLink className="logo" to="/" aria-label="JLBC home">
          {/* Served from webapp/public/, copied from reference/assets/. */}
          <img src="/jlbc-logo.png" alt="JLBC — Joint Legislative Budget Committee" />
        </NavLink>
        <nav className="primary" aria-label="Primary">
          {/* Home is the mockup's icon-only house pill; aria-label carries the
              accessible name since there is no visible text. `end` keeps it from
              matching every route (NavLink treats "/" as a prefix otherwise). */}
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
        </nav>
      </div>
    </header>
  );
}
