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
  hint,
  children,
  defaultOpen = false,
  testId,
}: {
  title: string;
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
          <h3>{title}</h3>
          {hint ? <span className="adm-card-hint">{hint}</span> : null}
        </div>
        <span className="adm-card-more">{open ? "Hide" : "Show"}</span>
      </button>
      {open ? <div className="adm-card-body">{children}</div> : null}
    </section>
  );
}
