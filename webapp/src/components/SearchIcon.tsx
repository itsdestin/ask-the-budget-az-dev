// The mockup's magnifier glyph, in exactly one place.
//
// Source: the `<svg>` inside `.search-expand .s-ic` / `.big-search .s-ic` /
// `.search-icon-btn` in webapp/reference/subpage-search_jlbc.html — the same two
// paths (circle r=7 + the m21 21 handle) appear in every mockup file, so this is
// the mockup's glyph copied verbatim, not a redrawn one.
//
// WHY a component and not four copies: it is used in four spots across two pages
// (Home's hero pill + Budget Library card icon, Search's search pill + its Search
// button), and four hand-copied path pairs is four chances for them to drift apart.
//
// WHY only the ICON was extracted, not a whole SearchField: the two pages' search
// pills are NOT the same markup. Home's is the mockup's `.search-field` (icon +
// input + text button, sized 19px/15.5px); the search page's is the mockup's
// `.big-search` (icon + input + a clear-X + an icon-and-text button, sized
// 20px/16px, different padding and focus ring). They are two different mockup
// components that happen to share a glyph — merging them would mean inventing a
// third design, which spec S12 forbids. Sizing/color stay in the page-scoped CSS:
// this component only draws the shape, and takes the class that styles it.
export function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
