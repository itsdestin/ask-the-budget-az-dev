import { useCallback, useEffect, useState } from "react";
import * as api from "../../api";

// "Add a JLBC book" (spec T10), inverted.
//
// The panel used to list every edition the catalog knows about with no
// indication of which were already here. Measured 2026-08-13: 62 editions
// offered, **0** of them usefully addable -- 38 ingestable and all 38 already
// in the corpus, 24 not ingestable and offered anyway. "Add all" reported
// skipped_existing: 139 and appeared to do nothing.
//
// It now answers ONE question: what has JLBC published that we don't have?
//
// Discovery itself is untouched. `ingest/book_discovery.py` is catalog-first
// with a HEAD-verified probe ladder that on 2026-07-31 found the FY2027
// Appropriations Report the harvest had recorded as unpublished, walking 139
// documents with 0 unreachable. This is presentation.

const FAMILY_LABELS: Record<string, string> = {
  approps: "Appropriations Report",
  baseline: "Baseline",
};

function editionName(family: string, fiscalYear: number): string {
  return `FY ${fiscalYear} ${FAMILY_LABELS[family] ?? family}`;
}

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

export function BookPanel({ onQueued }: { onQueued: () => void }) {
  const [check, setCheck] = useState<api.BookCheck | null>(null);
  const [checking, setChecking] = useState(true);
  const [busyKey, setBusyKey] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // The by-hand path. Spec T10 keeps it: "a specific year can still be
  // requested", reaching the probe ladder for a year the automatic check
  // missed -- an edition under a URL pattern nobody has seen yet, say.
  const [manualOpen, setManualOpen] = useState(false);
  const [manualFamily, setManualFamily] = useState("approps");
  const [manualYear, setManualYear] = useState("");

  const load = useCallback(async (refresh: boolean) => {
    setChecking(true);
    setError("");
    try {
      setCheck(await api.booksMissing(refresh));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  async function add(family: string, fiscalYear: number) {
    const key = `${family}-${fiscalYear}`;
    setBusyKey(key);
    setError("");
    setMessage("");
    try {
      const r = await api.ingestBook(family, fiscalYear);
      setMessage(
        `Queued ${r.queued} documents from the ${editionName(family, fiscalYear)}` +
          (r.skipped_existing ? `; ${r.skipped_existing} were already here` : "") +
          (r.unreachable.length ? `; ${r.unreachable.length} could not be reached` : "") +
          ".",
      );
      onQueued();
      await load(true);
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
  // deliberately does not carry, so opening the panel stays cheap.
  const [plan, setPlan] = useState<{ key: string; plan: api.BookPlan } | null>(null);

  async function preview(family: string, fiscalYear: number) {
    const key = `${family}-${fiscalYear}`;
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

  const missing = check?.missing ?? [];
  const unavailable = check?.unavailable ?? [];

  return (
    <section className="card up-book" aria-labelledby="up-book-h" data-testid="add-book">
      <h2 id="up-book-h">Add a JLBC book</h2>

      {error && (
        <p className="up-note">
          <span className="err">{error}</span>
        </p>
      )}

      {checking && !check && (
        <p className="up-note">Checking azjlbc.gov for editions you don’t have…</p>
      )}

      {/* An unreachable azjlbc.gov must SAY so. Reporting an empty gap would
          read as "everything is already here" -- a confident wrong answer
          produced by a network failure, on a page whose whole job is telling
          you what is missing. */}
      {check && !check.online && check.reason && (
        <p className="up-note">
          <span className="err">{check.reason}</span>
        </p>
      )}

      {check && missing.length > 0 && (
        <ul className="up-book-missing" data-testid="missing-editions">
          {missing.map((m) => {
            const key = `${m.family}-${m.fiscal_year}`;
            return (
              <li key={key} className="up-book-row" data-testid="missing-edition">
                <span className="up-book-name">{editionName(m.family, m.fiscal_year)}</span>
                <span className="up-book-detail">
                  {m.document_count === null
                    ? "not in your corpus"
                    : `${m.document_count} documents — not in your corpus`}
                </span>
                <button
                  type="button"
                  className="fchip"
                  disabled={busyKey !== ""}
                  onClick={() => void preview(m.family, m.fiscal_year)}
                >
                  Preview
                </button>
                <button
                  type="button"
                  className="allbtn"
                  disabled={busyKey !== ""}
                  onClick={() => void add(m.family, m.fiscal_year)}
                >
                  {busyKey === key ? "Adding…" : "Add"}
                </button>
                {plan?.key === key && (
                  <div className="up-book-plan" data-testid="book-plan" role="status">
                    <p>
                      {`Found ${plan.plan.count} documents for ${editionName(m.family, m.fiscal_year)}`}
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

      {check && check.online && missing.length === 0 && (
        <p className="up-note">Everything else JLBC publishes is already here.</p>
      )}

      {check && (
        <p className="up-note up-book-checked">
          Checked azjlbc.gov {agoLabel(check.checked_at)}.{" "}
          <button
            type="button"
            className="linkish"
            disabled={checking}
            onClick={() => void load(true)}
          >
            {checking ? "Checking…" : "Check again"}
          </button>
        </p>
      )}

      <p className="up-status" role="status">
        {message}
      </p>

      {/* Editions JLBC never published in a form this app can ingest. Stated
          rather than hidden -- "FY 1984 was never published as per-agency
          PDFs" is a fact worth having -- but NO Add button, because there is
          nothing to add. Spec T10 is explicit that these are not selectable. */}
      {unavailable.length > 0 && (
        <details className="up-book-unavailable">
          <summary>{unavailable.length} older editions can’t be added</summary>
          <ul>
            {unavailable.map((u) => (
              <li
                key={`${u.family}-${u.fiscal_year}`}
                className="up-book-dim"
                data-testid="unavailable-edition"
              >
                <span className="up-book-name">{editionName(u.family, u.fiscal_year)}</span>
                <span className="up-book-detail">{u.era_note}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="up-note">
        <button type="button" className="linkish" onClick={() => setManualOpen((v) => !v)}>
          Need an older edition? Choose a specific year
        </button>
      </p>

      {manualOpen && (
        <div className="up-book-row" data-testid="manual-edition">
          <label>
            Book
            <select
              aria-label="Book"
              value={manualFamily}
              onChange={(e) => setManualFamily(e.target.value)}
            >
              <option value="approps">Appropriations Report</option>
              <option value="baseline">Baseline</option>
            </select>
          </label>
          <label>
            Fiscal year
            <input
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
            onClick={() => void add(manualFamily, Number(manualYear))}
          >
            Add
          </button>
        </div>
      )}

      {/* Unsoftened on purpose, and carried over verbatim from the panel this
          replaces: an analyst who expects a book in five minutes concludes the
          app is broken. */}
      <p className="up-expect">
        JLBC-published reports are public record, so no confirmation is needed. A
        full book takes overnight on office computers. Historical backfills are
        best run one book at a time.
      </p>
    </section>
  );
}
