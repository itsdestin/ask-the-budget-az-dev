import type React from "react";
import { Chevron } from "./Chevron";

/** One collapsed section of a document-type card: a name, what is outstanding
 *  inside it, and a caret.
 *
 *  `<details>/<summary>` rather than a hand-rolled disclosure because the page
 *  already owns that idiom (`.up-disclose`) and it is keyboard- and
 *  screen-reader-correct without any code here. (The card HEAD above it is a
 *  `<button aria-expanded>` instead, and deliberately so: "only one card open
 *  at a time" is a decision about the SET, which the parent has to drive, and a
 *  `<details>` cannot be driven from outside. Two idioms, two different jobs.)
 *
 *  `outstanding` is what lets the card be SCANNED without opening anything —
 *  the count of editions that can't be added, or the edition still needing a
 *  "Full report" link, sits on the row, where it used to be the summary text
 *  of a disclosure you had to notice first.
 *
 *  `needs` colours that right-hand text amber. It is the ONLY colour in the
 *  card's body, so it is spent on one thing: there is outstanding work in
 *  here. A row that is merely informative ("5 can't be added", "23 editions
 *  set") must not use it, or the colour stops meaning anything.
 *
 *  Lives in its own module rather than inside BookFamilyPanel because
 *  ReportLinkRow renders one too, and two copies of a disclosure row is how
 *  one of them quietly acquires a different caret.
 *
 *  🔴 WHICH IS EXACTLY WHAT HAD HAPPENED. This row drew a CSS border-triangle
 *  (`.up-disclose-mark`) while the card header above it drew a stroked SVG
 *  chevron — two caret shapes on one card, against the "one caret shape
 *  throughout" decision STATUS.md records from Plan C's browser pass. Both now
 *  render `<Chevron/>` from one module, so a copy cannot drift again.
 */
export function Section({
  name,
  outstanding,
  needs = false,
  testId,
  children,
}: {
  name: string;
  outstanding?: string;
  needs?: boolean;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <details
      className={`up-disclose up-book-sec${needs ? " is-need" : ""}`}
      data-testid={testId}
    >
      <summary>
        <span className="up-book-sec-name">{name}</span>
        {outstanding && <span className="up-book-sec-out">{outstanding}</span>}
        <Chevron />
      </summary>
      <div className="up-book-sec-body">{children}</div>
    </details>
  );
}
