import { useState } from "react";

// A sub-card inside a panel: bordered, rounded, with a header row that can
// carry a switch or a show/hide control.
//
// This REPLACED the nested <details> treatment (2026-07-31, Destin). That
// rendered as a thin vertical rule with a small triangle beside a bold line —
// a "fingernail" — which reads as an outline tree rather than as settings you
// can act on, and it got worse the moment one nested inside another. Cards
// nest by containment instead, which needs no rule and no caret.

export function Card({
  title,
  hint,
  action,
  children,
  testId,
  tone,
}: {
  title: string;
  /** One short line beside the title. On a collapsible card this is what
   *  lets someone know what is inside without opening it. */
  hint?: string;
  /** A switch, a button — whatever belongs at the right of the header. */
  action?: React.ReactNode;
  children?: React.ReactNode;
  testId?: string;
  tone?: "muted";
}) {
  return (
    <section
      className={tone === "muted" ? "adm-card is-muted" : "adm-card"}
      data-testid={testId}
    >
      <div className="adm-card-head">
        <div className="adm-card-title">
          <h3>{title}</h3>
          {hint ? <span className="adm-card-hint">{hint}</span> : null}
        </div>
        {action ? <div className="adm-card-action">{action}</div> : null}
      </div>
      {children ? <div className="adm-card-body">{children}</div> : null}
    </section>
  );
}

/** A card whose body is hidden until asked for. The header is a button, so
 *  the whole row is one keyboard target — no caret, no tree. */
export function CollapsibleCard({
  title,
  quotedTitle = false,
  hint,
  children,
  defaultOpen = false,
  testId,
}: {
  title: string;
  /** True when `title` is somebody else's words quoted verbatim rather than
   *  copy this app wrote. Marks ONLY the title element `data-quoted`, which
   *  is what the plain-English guards strip before checking vocabulary.
   *
   *  WHY the card cannot mark itself as a whole (review, 2026-08-12): the
   *  See System Guidance window used to wrap every card in one
   *  `data-quoted` div, which exempted the app's own chrome too — the
   *  "written by your office" hint and this card's own Show/Hide label —
   *  so any developer word added to the card later would sail past the
   *  guard. The exemption has to be as narrow as the quotation is. */
  quotedTitle?: boolean;
  hint?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section
      className={open ? "adm-card is-open" : "adm-card"}
      data-testid={testId}
      data-open={open ? "true" : "false"}
    >
      <button
        type="button"
        className="adm-card-head adm-card-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <div className="adm-card-title">
          <h3 data-quoted={quotedTitle ? "true" : undefined}>{title}</h3>
          {hint ? <span className="adm-card-hint">{hint}</span> : null}
        </div>
        <span className="adm-card-more">{open ? "Hide" : "Show"}</span>
      </button>
      {open ? <div className="adm-card-body">{children}</div> : null}
    </section>
  );
}
