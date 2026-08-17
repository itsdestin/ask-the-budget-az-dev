import { useState } from "react";
import * as api from "../../api";
import { ReportLinkRow } from "./ReportLinkRow";
import { Section } from "./Section";

// The JLBC-book flow for ONE family, rendered inside that family's own
// document-type card on the upload page (spec T10).
//
// TWO reworks are folded in here, in order:
//
// 1. T10 inverted what the panel offers. It used to list every edition the
//    catalog knows about with no indication of which were already here.
//    Measured 2026-08-13: 62 editions offered, **0** usefully addable -- 38
//    ingestable and all 38 already in the corpus, 24 not ingestable and
//    offered anyway. "Add all" reported skipped_existing: 139 and appeared
//    to do nothing. It now answers one question: what has JLBC published
//    that we don't have?
//
// 2. The separate "Add a JLBC book" section is GONE (2026-08-15, at the
//    product owner's direction: "no separate JLBC Books section"). A
//    Baseline Book and an Appropriations Report are two of the six document
//    types on this page, so each one's card expands into its own family's
//    gap -- rather than a card that says "go and use the tool below" and a
//    tool below that re-states both families together. That redirect
//    button, and the scroll it performed, are deleted.
//
// 3. STATE -> ACTIONS -> EXPLANATION (2026-08-16, at the product owner's
//    direction: the cards have "too much text and feel poorly visually
//    styled without an easy/intuitive visual hierarchy").
//
//    Measured on the Baseline Book card before this change: **102 words**
//    were visible on opening it, and THE ANSWER WAS THE FOURTH THING YOU
//    READ. The reading order was (1) where it is published, (2) four lines
//    explaining why the tool fetches per-agency pages instead of the
//    single-file PDF, (3) "Every published Baseline Book is already here."
//    — the thing you opened the card to find out, 54 words in — then (4)
//    the actions, then (5) three more lines about public record and
//    overnight processing. Every line was the same size and colour, so
//    nothing told the eye where to land.
//
//    The card now OPENS with the answer, in one line, naming the year the
//    reader wants ("Every edition through FY 2027 is here."). Under it sits
//    the only action that can be outstanding — an edition to add. Everything
//    that explains rather than answers moved behind two disclosure rows that
//    each carry, on the right, what is outstanding inside them — so the card
//    can be scanned without opening anything. Nothing was deleted; the
//    three explanatory paragraphs live inside "About this book".
//
// Discovery itself is untouched by any of them. `ingest/book_discovery.py`
// is catalog-first with a HEAD-verified probe ladder that on 2026-07-31
// found the FY2027 Appropriations Report the harvest had recorded as
// unpublished, walking 139 documents with 0 unreachable. This is
// presentation.
//
// NO Invariant 8 checkbox here, and that is deliberate: everything this
// panel can reach is a JLBC-published report, which is public record by
// definition. Asking again would train people to click past the checkbox
// that does matter — the one on the file-upload form next door.
//
// Preview and Add are separate steps for the same reason they always were:
// a book is an overnight commitment on office hardware, so the honest
// sequence is see exactly what it contains (and what is unreachable) first,
// then decide.

/** "3 hours ago" — how stale the azjlbc.gov check is. The panel serves a
 *  cached answer rather than probing on every open (JLBC publishes a couple
 *  of books a year), so it must say how old the answer is instead of
 *  implying it is live. */
function agoLabel(iso: string | null): string {
  if (!iso) return "not yet";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return "just now";
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// `Section` — the disclosure row this card's body is built from — moved to
// `./Section.tsx` when ReportLinkRow started rendering one too. Two copies of
// a disclosure row is how one of them quietly acquires a different caret.

export function BookFamilyPanel({
  family,
  label,
  detail,
  wherePublished,
  check,
  checking,
  checkError,
  isAdmin,
  onRecheck,
  onQueued,
}: {
  /** The book family in `ingest/book_discovery`'s vocabulary — "approps" or
   *  "baseline". Comes off the wire (registry `redirect.family`), never
   *  derived from the doc_type key client-side. */
  family: string;
  /** The document type's own label, e.g. "Appropriations Report". Passed in
   *  rather than mapped from `family` here so an edition is named with the
   *  SAME words as the card it sits inside, from one source. */
  label: string;
  /** The registry's explanation of why this type is fetched rather than
   *  uploaded. Rendered verbatim. */
  detail: string;
  /** The registry's "where it comes from" sentence, which used to sit on
   *  the collapsed row and now lives inside, like every other type's. */
  wherePublished: string;
  /** The shared "what has JLBC published that we don't have?" answer, owned
   *  by the PAGE. It covers both families in one round-trip and the
   *  collapsed rows above show a count off it, so a panel-local copy would
   *  be a second fetch and a second version of the same number. */
  check: api.BookCheck | null;
  checking: boolean;
  checkError: string;
  /** Whether the "Full report link" row renders AT ALL.
   *
   *  /upload is open to the whole office and that row's controls are not:
   *  approving an address changes what every analyst's "Full report" button
   *  downloads. Destin's call, 2026-08-16, over showing it read-only — a
   *  non-admin's card must look exactly as it did, with no row and no fetch.
   *  Presentation, not protection: the routes behind it are admin-gated
   *  server-side, the same soft gate (spec S11) the Admin nav pill uses. */
  isAdmin: boolean;
  onRecheck: () => void;
  onQueued: () => void;
}) {
  const [busyKey, setBusyKey] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // The by-hand path. Spec T10 keeps it: "a specific year can still be
  // requested", reaching the probe ladder for a year the automatic check
  // missed -- an edition under a URL pattern nobody has seen yet, say. The
  // family picker it used to carry is gone: this panel IS one family.
  const [manualOpen, setManualOpen] = useState(false);
  const [manualYear, setManualYear] = useState("");

  const [plan, setPlan] = useState<{ key: string; plan: api.BookPlan } | null>(null);

  function editionName(fiscalYear: number): string {
    return `FY ${fiscalYear} ${label}`;
  }

  async function add(fiscalYear: number) {
    const key = String(fiscalYear);
    setBusyKey(key);
    setError("");
    setMessage("");
    try {
      const r = await api.ingestBook(family, fiscalYear);
      setMessage(
        `Queued ${r.queued} documents from the ${editionName(fiscalYear)}` +
          (r.skipped_existing ? `; ${r.skipped_existing} were already here` : "") +
          (r.unreachable.length ? `; ${r.unreachable.length} could not be reached` : "") +
          ".",
      );
      onQueued();
      onRecheck();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey("");
    }
  }

  // Preview = the old panel's "Discover": a dry run that lists what WOULD be
  // queued and downloads nothing. Kept deliberately when this panel was
  // inverted -- T10's mockup shows only an Add button, but discovery is what
  // found the FY2027 Appropriations Report on 2026-07-31 (139 documents, 0
  // unreachable) and it is the only way to see an edition's `notes` (the
  // rolling-folder warning) or its unreachable URLs before committing to an
  // overnight run. It also supplies the document count that a PROBED edition
  // deliberately does not carry, so opening the card stays cheap.
  async function preview(fiscalYear: number) {
    const key = String(fiscalYear);
    setBusyKey(key);
    setError("");
    try {
      setPlan({ key, plan: await api.discoverBook(family, fiscalYear) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey("");
    }
  }

  // One family's slice of a check that covers both. The endpoint answers for
  // the whole corpus in one round-trip (and one 12-hour cache), so the two
  // cards share the fetch and each shows only its own rows.
  const missing = (check?.missing ?? []).filter((m) => m.family === family);
  const unavailable = (check?.unavailable ?? []).filter((u) => u.family === family);
  const present = (check?.present ?? []).filter((p) => p.family === family);

  // The one-line answer the card opens with. It names the year rather than
  // the document type — "Every edition through FY 2027 is here." tells you
  // the thing you came to find out, where "Every published Baseline Book is
  // already here." repeats the card's own title back at you and leaves you
  // to work out which years that covers. The year is DERIVED from the
  // check's own `present` list, never written down here: a hardcoded year
  // becomes a lie the January JLBC publishes the next edition.
  const newestPresent = present.length
    ? Math.max(...present.map((p) => p.fiscal_year))
    : null;
  let state = "";
  if (check && check.online) {
    if (missing.length === 1) state = `FY ${missing[0].fiscal_year} is missing.`;
    else if (missing.length > 1) state = `${missing.length} editions are missing.`;
    else if (newestPresent !== null)
      state = `Every edition through FY ${newestPresent} is here.`;
    // No `present` rows means the check cannot name a year — say the true
    // thing without one rather than inventing a year to fill the sentence.
    else state = "Every published edition is here.";
  }

  return (
    <div className="up-book" data-testid="book-panel" data-family={family}>
      {(error || checkError) && (
        <p className="up-note">
          <span className="err">{error || checkError}</span>
        </p>
      )}

      {checking && !check && (
        <p className="up-note">Checking azjlbc.gov for editions you don’t have…</p>
      )}

      {/* An unreachable azjlbc.gov must SAY so. Reporting an empty gap would
          read as "everything is already here" -- a confident wrong answer
          produced by a network failure, on a card whose whole job is telling
          you what is missing. */}
      {check && !check.online && check.reason && (
        <p className="up-note">
          <span className="err">{check.reason}</span>
        </p>
      )}

      {/* THE ANSWER, FIRST. Everything above it is a failure state that
          replaces it; everything below it is either the action it implies
          or an explanation you asked for. */}
      {state && (
        <p className="up-book-state" data-testid="book-state">
          {state}
        </p>
      )}

      {check && (
        <p className="up-note up-book-checked">
          Checked azjlbc.gov {agoLabel(check.checked_at)} ·{" "}
          <button
            type="button"
            className="linkish"
            disabled={checking}
            onClick={onRecheck}
          >
            {checking ? "Checking…" : "Check again"}
          </button>
        </p>
      )}

      {/* An edition to add stays TOP-LEVEL, never behind a disclosure: it is
          the one thing this card exists to let you do, and it is outstanding
          work. Task 2's "Full report link" row goes below here. */}
      {check && missing.length > 0 && (
        <ul className="up-book-missing" data-testid="missing-editions">
          {missing.map((m) => {
            const key = String(m.fiscal_year);
            return (
              <li key={key} className="up-book-item" data-testid="missing-edition">
                <div className="up-book-row">
                  <div className="up-book-lead">
                    <span className="up-book-name">{editionName(m.fiscal_year)}</span>
                    <span className="up-book-detail">
                      {m.document_count === null
                        ? "not in your corpus"
                        : `${m.document_count} documents · not in your corpus`}
                    </span>
                  </div>
                  <div className="up-book-acts">
                    <button
                      type="button"
                      className="fchip"
                      disabled={busyKey !== ""}
                      onClick={() => void preview(m.fiscal_year)}
                    >
                      Preview
                    </button>
                    <button
                      type="button"
                      className="allbtn"
                      disabled={busyKey !== ""}
                      onClick={() => void add(m.fiscal_year)}
                    >
                      {busyKey === key ? "Adding…" : "Add"}
                    </button>
                  </div>
                </div>
                {plan?.key === key && (
                  <div className="up-book-plan" data-testid="book-plan" role="status">
                    <p>
                      {`Found ${plan.plan.count} documents for ${editionName(m.fiscal_year)}`}
                      {plan.plan.unreachable.length
                        ? ` (${plan.plan.unreachable.length} unreachable — listed below)`
                        : ""}
                      .
                    </p>
                    {plan.plan.notes.map((note) => (
                      <p className="up-note" key={note}>
                        {note}
                      </p>
                    ))}
                    {plan.plan.unreachable.length > 0 && (
                      <ul className="up-book-bad">
                        {plan.plan.unreachable.map((url) => (
                          <li key={url}>{url}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <p className="up-status" role="status">
        {message}
      </p>

      {/* THE "FULL REPORT LINK" ROW (2026-08-16). It used to be its own panel
          on /admin. Publishing an edition is ONE event — add its documents to
          search, set its whole-report link — and it was two pages, so the
          second half was the half you forgot. Admins only; see `isAdmin`. */}
      {isAdmin && <ReportLinkRow family={family} />}

      {/* Everything from here down EXPLAINS rather than answers, so it is
          behind a row that says what is inside it. */}

      <Section
        name="Add an older edition"
        // What is outstanding inside: editions JLBC never published in a form
        // this app can ingest. Stated on the row rather than only inside,
        // because "5 can't be added" is the whole of what most people need
        // from this section and it used to be the summary text of a
        // disclosure you had to notice before you could learn it.
        outstanding={unavailable.length ? `${unavailable.length} can’t be added` : undefined}
        testId="book-older"
      >
        <div className="up-book-manual">
          <button type="button" className="linkish" onClick={() => setManualOpen((v) => !v)}>
            Add a specific year
          </button>
          {manualOpen && (
            <div className="up-book-row" data-testid="manual-edition">
              <label className="up-field">
                Fiscal year
                <input
                  type="text"
                  aria-label="Fiscal year"
                  inputMode="numeric"
                  value={manualYear}
                  onChange={(e) => setManualYear(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="allbtn"
                disabled={!/^\d{4}$/.test(manualYear) || busyKey !== ""}
                onClick={() => void add(Number(manualYear))}
              >
                Add
              </button>
            </div>
          )}
        </div>

        {/* NO Add button on any of these, because there is nothing to add.
            Spec T10 is explicit that they are not selectable. */}
        {unavailable.length > 0 && (
          <ul className="up-book-unavailable">
            {unavailable.map((u) => (
              <li key={u.fiscal_year} className="up-book-dim" data-testid="unavailable-edition">
                <span className="up-book-name">{editionName(u.fiscal_year)}</span>
                <span className="up-book-detail">{u.era_note}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section name="About this book" outstanding="how it’s stored, timing" testId="book-about">
        {wherePublished && <p className="up-where">{wherePublished}</p>}
        <p className="up-book-why">{detail}</p>
        {/* Unsoftened on purpose: an analyst who expects a book in five
            minutes concludes the app is broken. The third sentence this used
            to carry ("Historical backfills are best run one book at a time")
            is folded into the second — it was a second sentence saying the
            same thing the overnight cost already implies. */}
        <p className="up-expect">
          Public record, so no confirmation is needed. A full book takes overnight
          on office computers, so add one at a time.
        </p>
      </Section>
    </div>
  );
}
