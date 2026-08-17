import type React from "react";
import { useEffect, useRef, useState } from "react";
import * as api from "../../api";
import { Section } from "./Section";

// The admin's side of the "Full report" button, as a row INSIDE the book card
// it belongs to (Upload → Baseline Book / Appropriations Report).
//
// WHY IT LIVES HERE AND NOT ON /admin. It shipped 2026-08-16 as its own panel
// on the admin page. When JLBC publishes FY2028 you do two things in one
// sitting: add its documents to search, and set its "Full report" link. Those
// were two pages for one event, so the second was the one you forgot. Destin,
// 2026-08-16: "I think 'full report links' should be an option under the
// baseline book/approps report upload cards, not its own top line menu item."
//
// 🔴 THE R7 DEVIATION IS RESOLVED BY THE MOVE, not carried over. The admin
// panel deliberately stayed on screen when healthy — one collapsed line —
// because approving a WRONG link is what makes it healthy, so the spec's
// "render nothing when nothing is waiting" rule made the only correction
// editor vanish on the very click that created the mistake. That reasoning is
// satisfied differently now: the book card is permanently on /upload, so the
// row (and the "Already answered" list inside it) is reachable every day
// whether or not anything is waiting. There is no quiet-shape/alert-shape
// split any more; there is one row.
//
// 🔴 ADMINS ONLY, AND NOT AT ALL FOR ANYONE ELSE. /upload is open to the whole
// office; these controls are not. Destin's call, 2026-08-16, over showing them
// read-only: a non-admin's card must look exactly as it did, with no row. The
// caller decides — see `BookFamilyPanel`'s `isAdmin` prop.
//
// The copy is TIGHTER than the admin panel's, and every cut was approved from
// a rendered mockup (`.superpowers/sdd/mockup.html`). The panel spent ~100
// words on one decision, 26 of them before you reached it. Gone: the leading
// explanation (the row's own name and its right-hand status say it), the
// per-format hint sentences, and the full web address (the filename carries
// the identity; `open ↗` carries the address).
//
// KEPT AT FULL STRENGTH, deliberately:
//  * the file size — half of what catches an admin approving the wrong file. A
//    0.2 MB "book" or a 47 MB "contents page" is visibly wrong.
//  * 🔴 the wrong-year warning — the ONE defect a 200 OK cannot detect: a
//    live, downloadable, WRONG report behind a button labelled "Full report".
//    The server flags it and never refuses it (exactly one genuinely year-less
//    address exists — `budget/apprpttoc.pdf` really is the FY2023 report), so
//    this warning is the entire mitigation. It must not get quieter.
//  * "the host never answered" vs "the host said 404" — two states, two
//    different next steps (check the network, or correct the address).
//  * a null size renders NOTHING, never "0 MB".
//  * the server's own sentence, verbatim, on a refusal; a 500 visible.
//  * the "Already answered" list, which is the only in-app repair for a link
//    approved wrongly.

/** 🔴 THE VOCABULARY TRAP. `family` on this page is the SLUG the registry and
 *  `ingest/book_discovery` use ("approps" / "baseline"). The whole-report
 *  table is keyed on the DISPLAY LABEL ("Appropriations Report" / "Baseline"),
 *  which is what `GET /api/admin/book-formats` puts in each edition's `family`
 *  field. Filtering the wrong one matches NOTHING and the row reports a clean
 *  sweep for a family that has editions waiting — a confident wrong answer
 *  with no error anywhere.
 *
 *  This map mirrors `app/routes/books_missing.py::FAMILY_LABELS`, and
 *  `ReportLinkRow.test.tsx` reads that file at test time so the two cannot
 *  drift (the same anti-drift idiom `tool-display.test.ts` uses against
 *  `harness/tools.py`). */
const FAMILY_LABELS: Record<string, string> = {
  approps: "Appropriations Report",
  baseline: "Baseline",
};

type Format = "single_file" | "linked_toc";

const FORMATS: Format[] = ["single_file", "linked_toc"];

/** The two things JLBC publishes for one edition, in office English.
 *
 *  These deliberately no longer echo the analyst-facing chooser
 *  (`webapp/src/components/ReportChooser.tsx` says "Single File PDF" and
 *  "Linked Table of Contents"). Destin renamed them from the approved mockup:
 *  the admin is deciding between a book and its index, and "Single File PDF"
 *  describes a file format rather than a document. If the chooser is ever
 *  re-worded, these are the words to match it to — not the other way round. */
const FORMAT_LABELS: Record<Format, string> = {
  single_file: "Whole book",
  linked_toc: "Contents page",
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
 *  reopen an approved edition, clear the Whole book box, press Approve, and a
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
 *  (a 0.2 MB "book" or a 47 MB "contents page" is visibly wrong). */
function sizeLabel(bytes: number | null): string | null {
  return bytes === null ? null : `${(bytes / 1e6).toFixed(1)} MB`;
}

/** `https://www.azjlbc.gov/27ar/apprpttoc.pdf` → `27ar/apprpttoc.pdf`.
 *
 *  The address bar's worth of scheme-and-host is identical on all 72 of these
 *  and identifies nothing; the directory and filename are what tell an admin
 *  which edition and which format they are looking at. The FULL address is
 *  never hidden — it is the `open ↗` link's href and the line's `title` — so
 *  this shortens what is READ, not what is available. A string that is not a
 *  URL at all comes back untouched rather than disappearing. */
function shortAddress(url: string): string {
  try {
    return new URL(url).pathname.replace(/^\/+/, "") || url;
  } catch {
    return url;
  }
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** One address line — name, filename, size, an opener — plus whatever is
 *  wrong with it. Rendered identically whether the app suggested the address
 *  or the admin pasted it, so a hand-typed link is never judged by a weaker
 *  standard than an offered one. */
function AddressFacts({
  label,
  url,
  status,
  bytes,
  namesItsYear,
  year,
  idPrefix,
  reason = null,
  controls = null,
}: {
  /** Empty for the line describing a just-checked replacement: the format is
   *  already named by the address box directly above it, and repeating it
   *  would read as a second format. */
  label: string;
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
  controls?: React.ReactNode;
}) {
  const size = sizeLabel(bytes);
  return (
    <>
      <div className="up-rl-fmt" data-testid={`${idPrefix}-address`}>
        <span className="up-rl-k">{label}</span>
        <span className="up-rl-f" title={url} data-testid={`${idPrefix}-url`}>
          {shortAddress(url)}
        </span>
        {size ? (
          <span className="up-rl-sz" data-testid={`${idPrefix}-size`}>
            {size}
          </span>
        ) : null}
        <a className="up-rl-open" href={url} target="_blank" rel="noopener noreferrer">
          open <span aria-hidden="true">↗</span>
        </a>
        {controls}
      </div>

      {/* A host that never answered and a host that answered "no" are
          DIFFERENT states and must read differently. One sends the admin to
          check the network, the other to correct the address; collapsing them
          has somebody editing a perfectly good address while the WiFi is
          off. */}
      {status === null ? (
        <p className="up-rl-warn" data-testid={`${idPrefix}-unreachable`}>
          {reason ??
            "azjlbc.gov didn't answer at all, so this address could not be checked. The address itself may be fine."}
        </p>
      ) : status >= 400 ? (
        <p className="up-rl-warn" data-testid={`${idPrefix}-dead`}>
          {reason ?? `This address didn't respond (${status}). Nothing would download.`}
        </p>
      ) : null}

      {/* Spec R6. A wrong-year address is the one defect a 200 OK cannot
          detect — a live, downloadable, WRONG report sitting behind a button
          labelled "Full report". The server deliberately flags and never
          refuses it, because `budget/apprpttoc.pdf` genuinely IS the FY2023
          report, so this warning is the whole mitigation. */}
      {!namesItsYear ? (
        <p className="up-rl-warn" data-testid={`${idPrefix}-year`}>
          That address doesn’t mention FY {year}. Open it before approving.
        </p>
      ) : null}
    </>
  );
}

/** One format's line, and the three ways the admin can answer it.
 *
 *  Defined at MODULE level, not inside the row. A component declared inside
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
  const label = FORMAT_LABELS[format];

  /** "change" (the mockup's word for what was "Use a different link"), plus
   *  the two other answers, rendered wherever they are not already the state
   *  the row is in. */
  const change = (
    <button
      type="button"
      className="linkish up-rl-mini"
      onClick={() => onChoose({ kind: "typed", url: candidate?.url ?? "" })}
    >
      change
    </button>
  );
  const none = (
    <button
      type="button"
      className="linkish up-rl-mini"
      onClick={() => onChoose({ kind: "none" })}
    >
      None published
    </button>
  );
  const useFound = (
    <button
      type="button"
      className="linkish up-rl-mini"
      onClick={() => onChoose({ kind: "candidate" })}
    >
      Use the address the app found
    </button>
  );

  return (
    <div className="up-rl-row" data-testid={`report-links-format-${format}`}>
      {choice.kind === "candidate" && candidate ? (
        <AddressFacts
          label={label}
          url={candidate.url}
          status={candidate.status}
          bytes={candidate.bytes}
          namesItsYear={candidate.names_its_year}
          year={year}
          idPrefix={`report-links-${format}`}
          // 🔴 "None published" stays on the line even when the app HAS a
          // suggestion, which the mockup does not show. It is a real answer,
          // not a refusal (spec R1) — Appropriations Reports FY2005–FY2010
          // genuinely have no single file — and the app suggesting an address
          // is not evidence one exists: `plan_edition` answers a catalogued
          // edition with no network call at all, and that catalog is built to
          // tolerate a 404. Behind "change" it would be a two-click path to
          // the correct answer for six editions.
          controls={
            <>
              {change}
              {none}
            </>
          }
        />
      ) : null}

      {choice.kind === "candidate" && !candidate ? (
        <div className="up-rl-fmt">
          <span className="up-rl-k">{label}</span>
          <span
            className="up-rl-f is-empty"
            data-testid={`report-links-${format}-nothing-found`}
          >
            The app has no address for this one.
          </span>
          {change}
          {none}
        </div>
      ) : null}

      {choice.kind === "none" ? (
        <div className="up-rl-fmt">
          <span className="up-rl-k">{label}</span>
          <span className="up-rl-f is-empty" data-testid={`report-links-${format}-none`}>
            Recorded as never published — readers see only the other one.
          </span>
          {change}
          {candidate ? useFound : null}
        </div>
      ) : null}

      {choice.kind === "typed" ? (
        <>
          <div className="up-rl-fmt">
            <span className="up-rl-k">{label}</span>
            <label className="up-field up-rl-input" htmlFor={inputId}>
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
              className="fchip"
              disabled={checked?.busy === true || choice.url.trim() === ""}
              onClick={() => onCheck(choice.url.trim())}
            >
              Check
            </button>
            {none}
            {candidate ? useFound : null}
          </div>
          {checked?.error ? (
            <p className="up-rl-warn" role="alert">
              {checked.error}
            </p>
          ) : null}
          {checked?.result ? (
            <AddressFacts
              label=""
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
  onNotNow,
  testId,
}: {
  urls: EditionUrls;
  /** The FORMAT LABELS of any address box the admin emptied without answering
   *  it. Non-empty blocks the save outright — see `isBlankTyped`. */
  blank: string[];
  busy: boolean;
  error: string | undefined;
  onApprove: () => void;
  /** Collapses the whole "Full report link" row. Offered on a WAITING edition
   *  only: it is the mockup's answer to "I am not ready to decide this", and
   *  beside a correction it would compete with that editor's own
   *  "Leave FY 2026 as it is". */
  onNotNow?: () => void;
  testId: string;
}) {
  const nothingToSave = urls.single_file === null && urls.linked_toc === null;
  return (
    <>
      {/* The reason is on screen, not implied by a greyed-out button: a
          silently dead button reads as the page being broken. */}
      {blank.length > 0 ? (
        <p className="up-rl-warn" data-testid="report-links-blank">
          The address for the {blank.join(" and the ")} is empty. Type an
          address, or press "None published" — recording that JLBC never
          published it is a real answer, and an empty box is not.
        </p>
      ) : nothingToSave ? (
        <p className="up-rl-warn" data-testid="report-links-blocked">
          At least one of the two formats needs a link. If JLBC published
          neither, this edition has nothing to open and there is nothing to
          save.
        </p>
      ) : null}
      {/* Both a refusal (400, carrying the store's own sentence verbatim) and a
          real failure (500) land here. An admin told nothing has no way to
          learn the approval did not stick. */}
      {error ? (
        <p className="up-rl-warn" role="alert" data-testid="report-links-save-error">
          {error}
        </p>
      ) : null}
      <div className="up-rl-acts">
        {onNotNow ? (
          <button type="button" className="linkish up-rl-mini" onClick={onNotNow}>
            not now
          </button>
        ) : null}
        <button
          type="button"
          className="allbtn"
          data-testid={testId}
          disabled={blank.length > 0 || nothingToSave || busy}
          onClick={onApprove}
        >
          Approve
        </button>
      </div>
    </>
  );
}

/** The editions already answered, each reopenable onto the same editor and the
 *  same PUT.
 *
 *  This list is the ONLY in-app repair for a link approved wrongly — the
 *  alternative is hand-editing `report-formats.json` on the share, which is
 *  the chore this whole feature exists to abolish. It has to stay reachable on
 *  an ordinary day, and now is: the book card is always on /upload. */
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
    <ul className="up-rl-approved">
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
            <div className="up-rl-approved-head">
              <span>FY {a.fiscal_year}</span>
              <button
                type="button"
                className="linkish up-rl-mini"
                onClick={() => onToggleEdit(key)}
              >
                {open
                  ? `Leave FY ${a.fiscal_year} as it is`
                  : `Change the links for FY ${a.fiscal_year}`}
              </button>
            </div>
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

export function ReportLinkRow({ family }: { family: string }) {
  // The SLUG in, the LABEL out. See FAMILY_LABELS' note — getting this wrong
  // silently matches nothing.
  const familyLabel = FAMILY_LABELS[family] ?? family;

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
  const detailsRef = useRef<HTMLDetailsElement>(null);

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

  function setChoice(family_: string, year: number, format: Format, choice: Choice) {
    const key = formatKey(family_, year, format);
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

  async function check(family_: string, year: number, format: Format, url: string) {
    const key = formatKey(family_, year, format);
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

  async function approve(family_: string, year: number, urls: EditionUrls) {
    const singleFile = urls.single_file;
    const linkedToc = urls.linked_toc;
    const key = editionKey(family_, year);
    setBusyEdition(key);
    setSaveErrors((e) => {
      const next = { ...e };
      delete next[key];
      return next;
    });
    try {
      const saved = await api.saveBookFormat(family_, year, singleFile, linkedToc);
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
          [key]: `Saved FY ${year} ${family_}, but the address for the ${wrong.join(
            " and the ",
          )} doesn’t mention FY ${year}. Open it and make sure it is the right year.`,
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
                {
                  family: family_,
                  fiscal_year: year,
                  single_file: singleFile,
                  linked_toc: linkedToc,
                },
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

  // 🔴 THIS FAMILY'S SLICE ONLY. One round-trip answers for both families and
  // each card shows its own — a Baseline Book card offering an Appropriations
  // Report edition is exactly the noise T10 removed, arriving by a new route.
  const pending = (state?.pending ?? []).filter((p) => p.family === familyLabel);
  const approved = (state?.approved ?? []).filter((a) => a.family === familyLabel);
  const myWarnings = Object.entries(savedWarnings).filter(([k]) =>
    k.startsWith(`${familyLabel}:`),
  );

  // A malformed row on the share belongs to NO family — the thing that failed
  // to parse is its family name — so it cannot be filed under one. Shown on
  // both book cards rather than dropped: a saved link the app is ignoring is a
  // real problem, and seeing it twice is cheaper than never seeing it.
  const problems = state?.problems ?? [];

  const needs =
    pending.length > 0 || problems.length > 0 || myWarnings.length > 0 || error !== null;

  /** The right-hand text on the collapsed row — what the card can be scanned
   *  for without opening anything. Derived, never a constant: the committed
   *  table's 39 is not the number an admin who has added to the overlay has. */
  let outstanding: string | undefined;
  if (error) outstanding = "couldn’t check";
  else if (pending.length === 1) outstanding = `FY ${pending[0].fiscal_year} needs one`;
  else if (pending.length > 1) outstanding = `${pending.length} editions need one`;
  else if (problems.length > 0 || myWarnings.length > 0) outstanding = "needs a look";
  else if (approved.length > 0)
    outstanding = `${approved.length} ${
      approved.length === 1 ? "edition" : "editions"
    } set`;
  // Loading, or genuinely nothing to say: no right-hand text at all. Silence
  // claims nothing, where "0 editions set" would claim the app looked and
  // found none.

  return (
    <Section
      name="Full report link"
      outstanding={outstanding}
      needs={needs}
      testId="report-links"
      detailsRef={detailsRef}
    >
      {!state && !error ? (
        <p className="up-note" data-testid="report-links-loading">
          Checking azjlbc.gov for the whole-report addresses…
        </p>
      ) : null}

      {error ? (
        <p className="up-note" role="alert" data-testid="report-links-error">
          <span className="err">{error}</span>
        </p>
      ) : null}

      {/* An outage must never be reported as "nothing needs a link". The list
          below is still complete — which editions are unanswered is knowable
          with no network at all — so the rows stay and only the suggested
          addresses are missing.

          The fallback is not dead code being defensive for its own sake: with
          a null reason this would be a row that says something is wrong and
          declines to say what. The route always sets a reason today; the point
          is that it cannot render an unexplained warning if that stops being
          true. */}
      {state && !state.online ? (
        <p className="up-rl-warn" data-testid="report-links-offline">
          {state.reason ??
            "Couldn’t reach azjlbc.gov, so no addresses could be looked up. Any edition below still needs a link."}
        </p>
      ) : null}

      {problems.length > 0 ? (
        <ul className="up-rl-notes" data-testid="report-links-problems">
          {problems.map((p) => (
            <li className="up-rl-warn" key={p} data-testid="report-links-problem">
              {p}
            </li>
          ))}
        </ul>
      ) : null}

      {myWarnings.length > 0 ? (
        <ul className="up-rl-notes" data-testid="report-links-saved-warnings">
          {myWarnings.map(([k, w]) => (
            <li className="up-rl-warn" key={k} data-testid="report-links-saved-warn">
              {w}
            </li>
          ))}
        </ul>
      ) : null}

      {pending.map((edition) => {
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
          <div key={key} className="up-rl-pending" data-testid="report-links-pending-card">
            {/* Only when there is more than one waiting: with a single
                edition the row above already says which year it is, and
                repeating it is a heading for a list of one. */}
            {pending.length > 1 ? (
              <p className="up-rl-pending-head">FY {edition.fiscal_year}</p>
            ) : null}
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
              onNotNow={() => {
                if (detailsRef.current) detailsRef.current.open = false;
              }}
              testId="report-links-approve"
            />
          </div>
        );
      })}

      {state && approved.length > 0 ? (
        <Section
          name="Already answered"
          outstanding={`${approved.length} ${
            approved.length === 1 ? "edition" : "editions"
          }`}
          testId="report-links-approved"
        >
          <ApprovedList
            approved={approved}
            decisions={decisions}
            checks={checks}
            openEdits={openEdits}
            busyEdition={busyEdition}
            saveErrors={saveErrors}
            onToggleEdit={(key) =>
              setOpenEdits((o) =>
                o.includes(key) ? o.filter((k) => k !== key) : [...o, key],
              )
            }
            onChoose={setChoice}
            onCheck={(f, year, format, url) => void check(f, year, format, url)}
            onApprove={(f, year, urls) => void approve(f, year, urls)}
          />
        </Section>
      ) : null}

      {state ? (
        <p className="up-note up-rl-again">
          <button
            type="button"
            className="linkish"
            disabled={refreshing}
            onClick={() => void lookAgain()}
          >
            {refreshing ? "Looking…" : "Look again"}
          </button>
        </p>
      ) : null}
    </Section>
  );
}
