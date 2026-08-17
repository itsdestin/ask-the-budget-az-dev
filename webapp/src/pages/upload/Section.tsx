import type React from "react";

/** One collapsed section of a document-type card: a name, what is outstanding
 *  inside it, and a caret.
 *
 *  `<details>/<summary>` rather than a hand-rolled disclosure because the page
 *  already owns that idiom (`.up-disclose`) and it is keyboard- and
 *  screen-reader-correct without any code here.
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
 *  one of them quietly acquires a different caret. */
export function Section({
  name,
  outstanding,
  needs = false,
  testId,
  detailsRef,
  children,
}: {
  name: string;
  outstanding?: string;
  needs?: boolean;
  testId: string;
  /** Lets a control INSIDE the section close it — the "not now" button beside
   *  Approve. Without it that button would have to be a second piece of state
   *  mirroring the `<details>`'s own `open`, which is how the caret and the
   *  body end up disagreeing. */
  detailsRef?: React.Ref<HTMLDetailsElement>;
  children: React.ReactNode;
}) {
  return (
    <details
      ref={detailsRef}
      className={`up-disclose up-book-sec${needs ? " is-need" : ""}`}
      data-testid={testId}
    >
      <summary>
        <span className="up-book-sec-name">{name}</span>
        {outstanding && <span className="up-book-sec-out">{outstanding}</span>}
        <span className="up-disclose-mark" aria-hidden="true" />
      </summary>
      <div className="up-book-sec-body">{children}</div>
    </details>
  );
}
