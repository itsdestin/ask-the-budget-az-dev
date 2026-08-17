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
// It renders NOTHING when nothing is waiting — the same rule as NoticesPanel
// and NeedsAttention directly above it, and the same reason: a box on screen
// every day teaches an admin to scroll past it. On a healthy install every
// edition is already answered, so silence is the normal state. Note that the
// already-answered list is NOT a reason to stay on screen; it is a reference
// for fixing a wrong approval, reachable only once something else has put the
// card there.
//
// There is deliberately no loading box either: an empty panel and a loading
// panel look identical, so a loading box would flash on every admin page open
// for a feature that says nothing almost always.

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
}: {
  url: string;
  status: number | null;
  bytes: number | null;
  namesItsYear: boolean;
  year: number;
  idPrefix: string;
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
          azjlbc.gov didn't answer at all, so this address could not be checked.
          The address itself may be fine.
        </p>
      ) : status >= 400 ? (
        <p className="adm-warn" data-testid={`${idPrefix}-dead`}>
          This address didn't respond ({status}). Nothing would download.
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
  busy,
  error,
  onApprove,
  testId,
}: {
  urls: EditionUrls;
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
      {nothingToSave ? (
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
        disabled={nothingToSave || busy}
        onClick={onApprove}
      >
        Approve
      </button>
    </>
  );
}

export function ReportLinksPanel() {
  const [state, setState] = useState<api.BookFormats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Decisions>({});
  const [checks, setChecks] = useState<Record<string, CheckState>>({});
  const [openEdits, setOpenEdits] = useState<string[]>([]);
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});
  const [savedWarnings, setSavedWarnings] = useState<string[]>([]);
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
    setDecisions((d) => ({ ...d, [formatKey(family, year, format)]: choice }));
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
      if (wrong.length > 0) {
        setSavedWarnings((w) => [
          ...w,
          `Saved FY ${year} ${family}, but the address for the ${wrong.join(
            " and the ",
          )} doesn't mention FY ${year}. Open it and make sure it is the right year.`,
        ]);
      }
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

  // Render NOTHING until there is something to say. `approved` is deliberately
  // absent from this test: on a healthy corpus every edition is in it, and a
  // reference list is not a reason to occupy the page.
  if (!state && !error) return null;
  if (
    state &&
    !error &&
    state.online &&
    state.pending.length === 0 &&
    state.problems.length === 0 &&
    savedWarnings.length === 0
  ) {
    return null;
  }

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
      {!state.online && state.reason ? (
        <p className="adm-warn" data-testid="report-links-offline">
          {state.reason}
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

      {savedWarnings.length > 0 ? (
        <ul className="adm-rows" data-testid="report-links-saved-warnings">
          {savedWarnings.map((w) => (
            <li key={w} className="adm-warn" data-testid="report-links-saved-warn">
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
                busy={busyEdition === key}
                error={saveErrors[key]}
                onApprove={() => void approve(edition.family, edition.fiscal_year, urls)}
                testId="report-links-approve"
              />
            </div>
          </div>
        );
      })}

      {/* Behind a disclosure, and only ever on screen once something else has
          put this panel there. Without it an approved MISTAKE is unfixable
          from the app and the admin is back to hand-editing JSON on the share
          — the exact step this feature exists to remove. */}
      {state.approved.length > 0 ? (
        <CollapsibleCard
          title="Already answered"
          hint={`${state.approved.length} ${
            state.approved.length === 1 ? "edition" : "editions"
          }`}
          testId="report-links-approved"
        >
          <ul className="adm-rows">
            {state.approved.map((a) => {
              const key = editionKey(a.family, a.fiscal_year);
              const open = openEdits.includes(key);
              const choices = FORMATS.map(
                (f) =>
                  decisions[formatKey(a.family, a.fiscal_year, f)] ?? storedChoice(a[f]),
              );
              // No candidates on this side: an already-answered edition is not
              // probed, so the editor opens on what is STORED.
              const urls = urlsFor(choices, { single_file: null, linked_toc: null });
              return (
                <li key={key} data-testid="report-links-approved-row">
                  <span>
                    FY {a.fiscal_year} {a.family}
                  </span>
                  <button
                    type="button"
                    className="adm-link"
                    onClick={() =>
                      setOpenEdits((o) =>
                        o.includes(key) ? o.filter((k) => k !== key) : [...o, key],
                      )
                    }
                  >
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
                          // No candidate here on purpose: this edition was
                          // answered, so it is not probed and there is no
                          // suggestion to offer. The editor opens on what is
                          // STORED, which is the thing being corrected.
                          candidate={null}
                          choice={choices[i]}
                          checked={checks[formatKey(a.family, a.fiscal_year, format)]}
                          onChoose={(c) => setChoice(a.family, a.fiscal_year, format, c)}
                          onCheck={(url) => void check(a.family, a.fiscal_year, format, url)}
                        />
                      ))}
                      <ApproveRow
                        urls={urls}
                        busy={busyEdition === key}
                        error={saveErrors[key]}
                        onApprove={() => void approve(a.family, a.fiscal_year, urls)}
                        testId="report-links-approve-correction"
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </CollapsibleCard>
      ) : null}
    </section>
  );
}
