import { useEffect, useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";

// Book editions the corpus holds that nothing opens as a whole report yet.
//
// The "Full report" button on Budget Documents only appears for an edition
// whose two addresses have been verified. That table used to be 39 rows of
// TypeScript in the bundle, so adding a fiscal year meant editing code and
// rebuilding — a step the non-developer who inherits this app cannot perform,
// for a list that gains two rows a year forever. This card is the replacement:
// the app finds the candidate addresses and checks them, the admin approves.
//
// TWO SHAPES, and the quiet one is a DELIBERATE DEVIATION from spec R7.
//
//  * Something waiting (a pending edition, a problem, an offline probe, or a
//    year warning from a save just made) → the full alert panel below.
//  * Everything answered → ONE collapsed line, "Full report links — N editions
//    answered", opening onto the same correction editor.
//
// Spec R7 says this panel renders nothing at all when healthy, "however many
// editions are in `approved`", on the reasoning that a box on screen every day
// teaches an admin to scroll past it — the rule NoticesPanel, NeedsAttention
// and PoorlyRead all follow. Destin overrode it for THIS panel on 2026-08-16,
// and the reason is that the recovery path has to be reachable: approving an
// edition with the wrong URL pasted in (a Baseline address on an
// Appropriations Report row, which contains the right two digits so the year
// rule sees nothing wrong) makes the panel healthy, so the silent rule made
// the panel vanish on the very click that created the mistake. From then on
// "Full report" downloaded the wrong report — a false provenance claim — and
// the only repair was hand-editing report-formats.json on the share, the exact
// chore this feature exists to abolish. One quiet line every day is the price
// of a permanent undo. Do NOT "fix" this back to matching its siblings.
//
// Two silences remain, because there is genuinely nothing to say and nothing
// to correct: while the first fetch is in flight (an empty panel and a loading
// panel look identical, so a loading box would flash on every admin page open)
// and when nothing has been approved yet.

type Format = "single_file" | "linked_toc";

const FORMATS: Format[] = ["single_file", "linked_toc"];

/** The names the ANALYST sees in the Full report chooser
 *  (webapp/src/components/ReportChooser.tsx). The admin is approving those two
 *  buttons, so the card calls them what the reader will see rather than
 *  inventing a second vocabulary for the same two things. */
const FORMAT_LABELS: Record<Format, string> = {
  single_file: "Single File PDF",
  linked_toc: "Linked Table of Contents",
};

const FORMAT_HINTS: Record<Format, string> = {
  single_file: "The complete report as one document.",
  linked_toc: "An index page where each agency and section opens its own PDF.",
};

/** What the admin has decided about ONE format, before pressing Approve.
 *
 *  A single value rather than separate `dismissed` / `replacement` flags: with
 *  two flags, "replaced AND marked never-published" is representable and
 *  nothing says which of them wins. Here it cannot be expressed at all. */
type Choice =
  | { kind: "candidate" } // use the address the app found
  | { kind: "none" } // JLBC published no such format
  | { kind: "typed"; url: string }; // the admin pasted one

/** key: `${family}:${fiscal_year}|${format}` */
type Decisions = Record<string, Choice>;

type CheckState = {
  busy: boolean;
  result: api.UrlCheckResult | null;
  error: string | null;
};

function editionKey(family: string, year: number): string {
  return `${family}:${year}`;
}

function formatKey(family: string, year: number, format: Format): string {
  return `${editionKey(family, year)}|${format}`;
}

/** An id an <input> can carry: HTML ids may not contain whitespace, and every
 *  family name here has a space in it ("Appropriations Report"). */
function domId(family: string, year: number, format: Format): string {
  return `rl-${format}-${year}-${family.replace(/[^a-z0-9]+/gi, "-")}`.toLowerCase();
}

function urlFor(choice: Choice, candidate: api.BookFormatCandidate | null): string | null {
  if (choice.kind === "none") return null;
  if (choice.kind === "typed") return choice.url.trim() || null;
  return candidate?.url ?? null;
}

/** An address box the admin emptied and did not answer.
 *
 *  🔴 This exists because `urlFor` maps an empty typed box to `null`, and
 *  `null` on the wire is the POSITIVE claim "JLBC published no such format"
 *  (spec R1) — not "no answer yet". Reproduced end to end before this guard:
 *  reopen an approved edition, clear the Single File box, press Approve, and a
 *  good link is deleted AND replaced by a claim about JLBC, on one keystroke,
 *  with nothing on screen. `{kind:"typed", url:""}` and `{kind:"none"}` are
 *  different intentions and must not collapse into each other — which is the
 *  whole reason `Choice` is one value rather than two flags. */
function isBlankTyped(choice: Choice): boolean {
  return choice.kind === "typed" && choice.url.trim() === "";
}

/** What Approve would send for one edition. Built ONCE per card and read by
 *  BOTH the disabled-check and the save.
 *
 *  It used to be computed twice — once for the button's props, once inside its
 *  own onApprove — and mutating one copy left every test green, so the button's
 *  idea of what it would send could drift from what it actually sent with
 *  nothing to catch it. */
type EditionUrls = { single_file: string | null; linked_toc: string | null };

type Candidates = {
  single_file: api.BookFormatCandidate | null;
  linked_toc: api.BookFormatCandidate | null;
};

function urlsFor(choices: Choice[], candidates: Candidates): EditionUrls {
  return {
    single_file: urlFor(choices[0], candidates.single_file),
    linked_toc: urlFor(choices[1], candidates.linked_toc),
  };
}

/** Where an ALREADY-ANSWERED edition's editor starts: the stored address, or
 *  "never published" when the stored value is null. Those two are different
 *  answers (spec R1) and the editor has to reopen on the one that was given. */
function storedChoice(url: string | null): Choice {
  return url === null ? { kind: "none" } : { kind: "typed", url };
}

/** Nothing rather than "0 MB" when the server omitted Content-Length: an
 *  invented zero next to a 600-page book reads as a broken link, and this size
 *  is half of what catches an admin approving without opening either address
 *  (a 0.2 MB "book" or a 47 MB "table of contents" is visibly wrong). */
function sizeLabel(bytes: number | null): string | null {
  return bytes === null ? null : `${(bytes / 1e6).toFixed(1)} MB`;
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The three facts a checked address carries, rendered identically whether the
 *  app suggested it or the admin pasted it. */
function AddressFacts({
  url,
  status,
  bytes,
  namesItsYear,
  year,
  idPrefix,
  reason = null,
}: {
  url: string;
  status: number | null;
  bytes: number | null;
  namesItsYear: boolean;
  year: number;
  idPrefix: string;
  /** The check route's own sentence about why an address did not work, when it
   *  wrote one. Preferred over the two below it wherever it exists: the route
   *  already words this failure for this reader, and two wordings for one fact
   *  is the duplication `write_edition`'s docstring forbids for the 400. The
   *  fallbacks stay because a CANDIDATE carries no reason — the listing route
   *  reports the three measurements and no prose. */
  reason?: string | null;
}) {
  const size = sizeLabel(bytes);
  return (
    <>
      <p className="adm-hint" data-testid={`${idPrefix}-address`}>
        <a href={url} target="_blank" rel="noopener noreferrer">
          Open to check ↗
        </a>{" "}
        <span data-testid={`${idPrefix}-url`}>{url}</span>
        {size ? (
          <>
            {" — "}
            <span data-testid={`${idPrefix}-size`}>{size}</span>
          </>
        ) : null}
      </p>

      {/* A host that never answered and a host that answered "no" are
          DIFFERENT states and must read differently. One sends the admin to
          check the network, the other to correct the address; collapsing them
          has somebody editing a perfectly good address while the WiFi is
          off. */}
      {status === null ? (
        <p className="adm-warn" data-testid={`${idPrefix}-unreachable`}>
          {reason ??
            "azjlbc.gov didn't answer at all, so this address could not be checked. The address itself may be fine."}
        </p>
      ) : status >= 400 ? (
        <p className="adm-warn" data-testid={`${idPrefix}-dead`}>
          {reason ?? `This address didn't respond (${status}). Nothing would download.`}
        </p>
      ) : null}

      {/* Spec R6. A wrong-year address is the one defect a 200 OK cannot
          detect — a live, downloadable, WRONG report sitting behind a button
          labelled "Full report". The server deliberately flags and never
          refuses it, because `budget/apprpttoc.pdf` genuinely IS the FY2023
          report, so this warning is the whole mitigation. */}
      {!namesItsYear ? (
        <p className="adm-warn" data-testid={`${idPrefix}-year`}>
          This address doesn't mention FY {year} — open it before approving.
        </p>
      ) : null}
    </>
  );
}

/** One format's row: what the app found (or did not), and the three ways the
 *  admin can answer it.
 *
 *  Defined at MODULE level, not inside the panel. A component declared inside
 *  another component is a new type on every render, so React unmounts and
 *  remounts it — which would throw focus out of the address field after every
 *  single keystroke. `fireEvent.change` sets a whole value at once and cannot
 *  see that, so nothing below would have caught it. */
function FormatRow({
  family,
  year,
  format,
  candidate,
  choice,
  checked,
  onChoose,
  onCheck,
}: {
  family: string;
  year: number;
  format: Format;
  candidate: api.BookFormatCandidate | null;
  choice: Choice;
  checked: CheckState | undefined;
  onChoose: (choice: Choice) => void;
  onCheck: (url: string) => void;
}) {
  const inputId = domId(family, year, format);

  return (
    <div className="adm-card is-muted" data-testid={`report-links-format-${format}`}>
      <div className="adm-card-body">
        <p className="adm-card-title">
          <strong>{FORMAT_LABELS[format]}</strong> — {FORMAT_HINTS[format]}
        </p>

        {choice.kind === "candidate" && candidate ? (
          <AddressFacts
            url={candidate.url}
            status={candidate.status}
            bytes={candidate.bytes}
            namesItsYear={candidate.names_its_year}
            year={year}
            idPrefix={`report-links-${format}`}
          />
        ) : null}

        {choice.kind === "candidate" && !candidate ? (
          <p className="adm-empty" data-testid={`report-links-${format}-nothing-found`}>
            The app has no address for this one. Paste one below, or record that
            JLBC never published it.
          </p>
        ) : null}

        {choice.kind === "none" ? (
          <p className="adm-hint" data-testid={`report-links-${format}-none`}>
            Recorded as never published. The reader will see only the other
            format.
          </p>
        ) : null}

        {choice.kind === "typed" ? (
          <>
            <div className="adm-inline">
              <label className="adm-field" htmlFor={inputId}>
                <span>Web address</span>
                <input
                  id={inputId}
                  type="text"
                  autoComplete="off"
                  value={choice.url}
                  onChange={(e) => onChoose({ kind: "typed", url: e.target.value })}
                />
              </label>
              <button
                type="button"
                className="adm-btn"
                disabled={checked?.busy === true || choice.url.trim() === ""}
                onClick={() => onCheck(choice.url.trim())}
              >
                Check
              </button>
            </div>
            {checked?.error ? (
              <p className="adm-warn" role="alert">
                {checked.error}
              </p>
            ) : null}
            {checked?.result ? (
              <AddressFacts
                url={choice.url.trim()}
                status={checked.result.status}
                bytes={checked.result.bytes}
                namesItsYear={checked.result.names_its_year}
                year={year}
                idPrefix={`report-links-${format}-checked`}
                reason={checked.result.reason}
              />
            ) : null}
          </>
        ) : null}

        <div className="adm-inline">
          {choice.kind !== "typed" ? (
            <button
              type="button"
              className="adm-link"
              onClick={() => onChoose({ kind: "typed", url: candidate?.url ?? "" })}
            >
              Use a different link
            </button>
          ) : null}
          {choice.kind !== "none" ? (
            <button
              type="button"
              className="adm-link"
              onClick={() => onChoose({ kind: "none" })}
            >
              None published
            </button>
          ) : null}
          {choice.kind !== "candidate" && candidate ? (
            <button
              type="button"
              className="adm-link"
              onClick={() => onChoose({ kind: "candidate" })}
            >
              Use the address the app found
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** The Approve row, shared by a waiting edition and a correction to an
 *  already-answered one — the same PUT either way, because an overlay entry
 *  replaces its key wholesale (spec R1), so there is no separate "edit" verb
 *  to keep in step with this one. */
function ApproveRow({
  urls,
  blank,
  busy,
  error,
  onApprove,
  testId,
}: {
  urls: EditionUrls;
  /** The FORMAT LABELS of any address box the admin emptied without answering
   *  it. Non-empty blocks the save outright — see `isBlankTyped`. */
  blank: string[];
  busy: boolean;
  error: string | undefined;
  onApprove: () => void;
  testId: string;
}) {
  const nothingToSave = urls.single_file === null && urls.linked_toc === null;
  return (
    <>
      {/* The reason is on screen, not implied by a greyed-out button: a
          silently dead button reads as the page being broken. */}
      {blank.length > 0 ? (
        <p className="adm-warn" data-testid="report-links-blank">
          The address for the {blank.join(" and the ")} is empty. Type an
          address, or press "None published" — recording that JLBC never
          published it is a real answer, and an empty box is not.
        </p>
      ) : nothingToSave ? (
        <p className="adm-warn" data-testid="report-links-blocked">
          At least one of the two formats needs a link. If JLBC published
          neither, this edition has nothing to open and there is nothing to
          save.
        </p>
      ) : null}
      {/* Both a refusal (400, carrying the store's own sentence verbatim) and a
          real failure (500) land here. An admin told nothing has no way to
          learn the approval did not stick. */}
      {error ? (
        <p className="adm-warn" role="alert" data-testid="report-links-save-error">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className="adm-btn"
        data-testid={testId}
        disabled={blank.length > 0 || nothingToSave || busy}
        onClick={onApprove}
      >
        Approve
      </button>
    </>
  );
}

/** The editions already answered, each reopenable onto the same editor and the
 *  same PUT.
 *
 *  Module level, and shared by BOTH shapes of this panel — the alert one and
 *  the quiet collapsed one. Two copies of this list would be two correction
 *  paths, and the quiet one is the copy nobody looks at, so it is the copy that
 *  would rot. */
function ApprovedList({
  approved,
  decisions,
  checks,
  openEdits,
  busyEdition,
  saveErrors,
  onToggleEdit,
  onChoose,
  onCheck,
  onApprove,
}: {
  approved: api.ApprovedEdition[];
  decisions: Decisions;
  checks: Record<string, CheckState>;
  openEdits: string[];
  busyEdition: string | null;
  saveErrors: Record<string, string>;
  onToggleEdit: (key: string) => void;
  onChoose: (family: string, year: number, format: Format, choice: Choice) => void;
  onCheck: (family: string, year: number, format: Format, url: string) => void;
  onApprove: (family: string, year: number, urls: EditionUrls) => void;
}) {
  return (
    <ul className="adm-rows">
      {approved.map((a) => {
        const key = editionKey(a.family, a.fiscal_year);
        const open = openEdits.includes(key);
        const choices = FORMATS.map(
          (f) => decisions[formatKey(a.family, a.fiscal_year, f)] ?? storedChoice(a[f]),
        );
        // No candidates on this side: an already-answered edition is not
        // probed, so the editor opens on what is STORED.
        const urls = urlsFor(choices, { single_file: null, linked_toc: null });
        // This side is where an emptied box costs the most: every format
        // reopens as a typed box holding a STORED address, so clearing one
        // deletes a link that is already working.
        const blank = FORMATS.filter((_, i) => isBlankTyped(choices[i])).map(
          (f) => FORMAT_LABELS[f],
        );
        return (
          <li key={key} data-testid="report-links-approved-row">
            <span>
              FY {a.fiscal_year} {a.family}
            </span>
            <button type="button" className="adm-link" onClick={() => onToggleEdit(key)}>
              {open
                ? `Leave FY ${a.fiscal_year} as it is`
                : `Change the links for FY ${a.fiscal_year}`}
            </button>
            {open ? (
              <div data-testid="report-links-edit">
                {FORMATS.map((format, i) => (
                  <FormatRow
                    key={format}
                    family={a.family}
                    year={a.fiscal_year}
                    format={format}
                    // No candidate here on purpose: this edition was answered,
                    // so it is not probed and there is no suggestion to offer.
                    // The editor opens on what is STORED, which is the thing
                    // being corrected.
                    candidate={null}
                    choice={choices[i]}
                    checked={checks[formatKey(a.family, a.fiscal_year, format)]}
                    onChoose={(c) => onChoose(a.family, a.fiscal_year, format, c)}
                    onCheck={(url) => onCheck(a.family, a.fiscal_year, format, url)}
                  />
                ))}
                <ApproveRow
                  urls={urls}
                  blank={blank}
                  busy={busyEdition === key}
                  error={saveErrors[key]}
                  onApprove={() => onApprove(a.family, a.fiscal_year, urls)}
                  testId="report-links-approve-correction"
                />
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function ReportLinksPanel() {
  const [state, setState] = useState<api.BookFormats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Decisions>({});
  const [checks, setChecks] = useState<Record<string, CheckState>>({});
  const [openEdits, setOpenEdits] = useState<string[]>([]);
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});
  /** Keyed by EDITION, not appended to a list. A list keyed on its own sentence
   *  meant correcting the same edition twice produced two rows saying the same
   *  thing under a duplicate React key, and a correction that FIXED the year
   *  left the old complaint on screen forever — a stale warning about an
   *  address that is no longer stored. One entry per edition, replaced or
   *  deleted by that edition's next save. */
  const [savedWarnings, setSavedWarnings] = useState<Record<string, string>>({});
  const [busyEdition, setBusyEdition] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.bookFormats().then(
      (d) => !cancelled && setState(d),
      (e) => !cancelled && setError(message(e)),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  /** Ask again, ignoring the 12-hour probe cache. Without this an edition
   *  published an hour after the last look is invisible until tomorrow, with
   *  nothing on screen saying why. */
  async function lookAgain() {
    setRefreshing(true);
    try {
      setState(await api.bookFormats(true));
      setError(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setRefreshing(false);
    }
  }

  function setChoice(family: string, year: number, format: Format, choice: Choice) {
    const key = formatKey(family, year, format);
    setDecisions((d) => ({ ...d, [key]: choice }));
    // 🔴 A verdict belongs to the address it was gathered about. Reproduced:
    // check a good FY2028 address, then edit the box to the rolling `/budget/`
    // one WITHOUT pressing Check again — the card showed the NEW address beside
    // the OLD 47.0 MB size and no year warning, and Approve sent the new one.
    // That is exactly the wrong-year approval this card exists to prevent,
    // committed while the screen displays evidence about a different file. An
    // edited address now has no verdict at all until it is checked again.
    setChecks((c) => {
      if (!(key in c)) return c; // typing is per-keystroke; don't churn state
      const next = { ...c };
      delete next[key];
      return next;
    });
  }

  async function check(family: string, year: number, format: Format, url: string) {
    const key = formatKey(family, year, format);
    setChecks((c) => ({ ...c, [key]: { busy: true, result: null, error: null } }));
    try {
      const result = await api.checkBookFormatUrl(url, year);
      setChecks((c) => ({ ...c, [key]: { busy: false, result, error: null } }));
    } catch (e) {
      setChecks((c) => ({
        ...c,
        [key]: { busy: false, result: null, error: message(e) },
      }));
    }
  }

  async function approve(family: string, year: number, urls: EditionUrls) {
    const singleFile = urls.single_file;
    const linkedToc = urls.linked_toc;
    const key = editionKey(family, year);
    setBusyEdition(key);
    setSaveErrors((e) => {
      const next = { ...e };
      delete next[key];
      return next;
    });
    try {
      const saved = await api.saveBookFormat(family, year, singleFile, linkedToc);
      // 🔴 The server's own year check on what it just stored. Nothing forces
      // an admin to press Check first, so without this the R6 mitigation rests
      // entirely on a step they can skip — and a wrong-year report behind a
      // "Full report" button is a false provenance claim, not a typo.
      const wrong = FORMATS.filter((f) => saved.names_its_year[f] === false).map(
        (f) => FORMAT_LABELS[f],
      );
      setSavedWarnings((w) => {
        // A clean save DELETES this edition's warning. Without that, correcting
        // a wrong-year address leaves the complaint about the old one on screen
        // and the admin has no way to tell they fixed it.
        if (wrong.length === 0) {
          if (!(key in w)) return w;
          const next = { ...w };
          delete next[key];
          return next;
        }
        return {
          ...w,
          [key]: `Saved FY ${year} ${family}, but the address for the ${wrong.join(
            " and the ",
          )} doesn't mention FY ${year}. Open it and make sure it is the right year.`,
        };
      });
      // The edition moves out of "waiting" locally rather than by re-fetching:
      // the save succeeded, so its answer is known, and a re-fetch would
      // re-probe every OTHER pending edition to learn one thing we already
      // have. It moves into `approved` so a mistake noticed one second later
      // is still correctable without a page reload.
      setState((s) =>
        s === null
          ? s
          : {
              ...s,
              pending: s.pending.filter(
                (p) => editionKey(p.family, p.fiscal_year) !== key,
              ),
              approved: [
                { family, fiscal_year: year, single_file: singleFile, linked_toc: linkedToc },
                ...s.approved.filter((a) => editionKey(a.family, a.fiscal_year) !== key),
              ],
            },
      );
      setOpenEdits((o) => o.filter((k) => k !== key));
    } catch (e) {
      setSaveErrors((prev) => ({ ...prev, [key]: message(e) }));
    } finally {
      setBusyEdition(null);
    }
  }

  /** Everything the panel could tell the admin to DO is already done. */
  const nothingWaiting =
    state !== null &&
    error === null &&
    state.online &&
    state.pending.length === 0 &&
    state.problems.length === 0 &&
    Object.keys(savedWarnings).length === 0;

  const approvedList =
    state === null ? null : (
      <ApprovedList
        approved={state.approved}
        decisions={decisions}
        checks={checks}
        openEdits={openEdits}
        busyEdition={busyEdition}
        saveErrors={saveErrors}
        onToggleEdit={(key) =>
          setOpenEdits((o) => (o.includes(key) ? o.filter((k) => k !== key) : [...o, key]))
        }
        onChoose={setChoice}
        onCheck={(family, year, format, url) => void check(family, year, format, url)}
        onApprove={(family, year, urls) => void approve(family, year, urls)}
      />
    );

  // Nothing at all while the first fetch is in flight — see the header note on
  // why there is no loading box.
  if (!state && !error) return null;

  // A load failure renders as a bare sentence rather than a titled section.
  // Deliberate: Admin.tsx's own specs read the order of the page's <h2>s to
  // decide what comes first, and a heading that appears only when a fetch
  // fails would reshuffle the page in exactly the circumstances nobody is
  // watching.
  if (!state) {
    return (
      <p className="adm-warn" role="alert" data-testid="admin-report-links-error">
        {error}
      </p>
    );
  }

  // 🔴 THE VISIBILITY RULE, and it deviates from spec R7 on purpose — the full
  // reasoning is in this file's header note. Healthy is ONE collapsed line, not
  // silence, because a wrong link approved a moment ago makes the panel healthy
  // and its correction editor is the only repair short of hand-editing JSON on
  // the share. It carries no <h2> and no `adm-panel-alert`, so it neither
  // reshuffles the page's heading order nor reads as an alarm.
  if (nothingWaiting) {
    // Genuinely nothing to correct: no edition has been answered yet, so the
    // list this line exists to open would be empty.
    if (state.approved.length === 0) return null;
    return (
      <CollapsibleCard
        title="Full report links"
        hint={`${state.approved.length} ${
          state.approved.length === 1 ? "edition" : "editions"
        } answered`}
        testId="admin-report-links-answered"
      >
        <p className="adm-hint">
          Every book edition in search opens as a whole report. Open one to
          change which addresses its "Full report" button uses.
        </p>
        {approvedList}
      </CollapsibleCard>
    );
  }

  return (
    <section
      className="card adm-panel adm-panel-alert"
      aria-labelledby="adm-report-links-h"
      data-testid="admin-report-links"
    >
      <div className="adm-panel-head">
        <h2 id="adm-report-links-h">Books with no "Full report" link</h2>
        <button
          type="button"
          className="adm-link"
          disabled={refreshing}
          onClick={() => void lookAgain()}
        >
          Look again
        </button>
      </div>

      <p className="adm-sub">
        These editions are in search, but nothing opens the whole report. Check
        each address and approve it, and the "Full report" button appears on
        Budget Documents.
      </p>

      {error ? (
        <p className="adm-warn" role="alert" data-testid="admin-report-links-error">
          {error}
        </p>
      ) : null}

      {/* An outage must never be reported as "nothing needs a link". The list
          below is still complete — which editions are unanswered is knowable
          with no network at all — so the rows stay and only the suggested
          addresses are missing. */}
      {/* The fallback is not dead code being defensive for its own sake: this
          panel is on screen BECAUSE `online` is false, and with a null reason
          it would otherwise be a heading, a subtitle and nothing — a section
          that says something is wrong and declines to say what. The route
          always sets a reason today, so the fallback should never be read;
          the point is that it cannot render an unexplained alert if that ever
          stops being true. */}
      {!state.online ? (
        <p className="adm-warn" data-testid="report-links-offline">
          {state.reason ??
            "Couldn't reach azjlbc.gov, so no addresses could be looked up. The editions below still need a link."}
        </p>
      ) : null}

      {state.problems.length > 0 ? (
        <ul className="adm-rows" data-testid="report-links-problems">
          {state.problems.map((p) => (
            <li key={p} data-testid="report-links-problem">
              {p}
            </li>
          ))}
        </ul>
      ) : null}

      {Object.keys(savedWarnings).length > 0 ? (
        <ul className="adm-rows" data-testid="report-links-saved-warnings">
          {Object.entries(savedWarnings).map(([k, w]) => (
            <li key={k} className="adm-warn" data-testid="report-links-saved-warn">
              {w}
            </li>
          ))}
        </ul>
      ) : null}

      {state.pending.map((edition) => {
        const key = editionKey(edition.family, edition.fiscal_year);
        const choices = FORMATS.map(
          (f) =>
            decisions[formatKey(edition.family, edition.fiscal_year, f)] ??
            ({ kind: "candidate" } as Choice),
        );
        const urls = urlsFor(choices, edition.candidates);
        const blank = FORMATS.filter((_, i) => isBlankTyped(choices[i])).map(
          (f) => FORMAT_LABELS[f],
        );
        return (
          <div key={key} className="adm-card" data-testid="report-links-pending-card">
            <div className="adm-card-head">
              <div className="adm-card-title">
                <h3>
                  FY {edition.fiscal_year} {edition.family} — no "Full report"
                  link yet
                </h3>
              </div>
            </div>
            <div className="adm-card-body">
              {FORMATS.map((format, i) => (
                <FormatRow
                  key={format}
                  family={edition.family}
                  year={edition.fiscal_year}
                  format={format}
                  candidate={edition.candidates[format]}
                  choice={choices[i]}
                  checked={checks[formatKey(edition.family, edition.fiscal_year, format)]}
                  onChoose={(c) => setChoice(edition.family, edition.fiscal_year, format, c)}
                  onCheck={(url) => void check(edition.family, edition.fiscal_year, format, url)}
                />
              ))}
              <ApproveRow
                urls={urls}
                blank={blank}
                busy={busyEdition === key}
                error={saveErrors[key]}
                onApprove={() => void approve(edition.family, edition.fiscal_year, urls)}
                testId="report-links-approve"
              />
            </div>
          </div>
        );
      })}

      {/* Behind a disclosure. The quiet shape of this panel opens onto the
          SAME list — see the header note — because without a reachable
          correction editor an approved MISTAKE is unfixable from the app and
          the admin is back to hand-editing JSON on the share, the exact step
          this feature exists to remove. */}
      {state.approved.length > 0 ? (
        <CollapsibleCard
          title="Already answered"
          hint={`${state.approved.length} ${
            state.approved.length === 1 ? "edition" : "editions"
          }`}
          testId="report-links-approved"
        >
          {approvedList}
        </CollapsibleCard>
      ) : null}
    </section>
  );
}
