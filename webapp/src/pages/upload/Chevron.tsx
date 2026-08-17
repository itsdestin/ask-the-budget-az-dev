/** The upload page's ONE disclosure caret.
 *
 *  🔴 IT LIVES IN ITS OWN MODULE BECAUSE THE PAGE HAD TWO OF THEM. The card
 *  headers drew this stroked chevron; the section rows inside a book card drew
 *  a CSS border-triangle (`.up-disclose-mark`) that pointed sideways and
 *  rotated 90°. Two shapes for one idea on one screen — which is the exact
 *  thing Plan C's browser pass fixed once already ("one caret shape
 *  throughout", recorded in STATUS.md) and which came back the moment a second
 *  component needed a caret and reached for a different one.
 *
 *  A shared module rather than a copied SVG: a copy is how the two drift apart
 *  again, silently, because nothing renders them side by side.
 *
 *  Rotated by CSS on the open state rather than swapped for a second glyph, so
 *  the two states are one shape in motion — the same treatment the Budget
 *  Documents year cards use. `aria-hidden`, because the control it sits in
 *  already announces its own expanded/collapsed state (a `<button
 *  aria-expanded>` or a `<summary>`), and a second announcement of the same
 *  fact is noise.
 */
export function Chevron() {
  return (
    <svg className="up-card-caret" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M4 6l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
