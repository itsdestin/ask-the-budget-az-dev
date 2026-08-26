import { useState } from "react";
import * as api from "../api";

// The full-page failure screen (Plan 5 Task 12, spec S18; the wording and
// the folder picker were rewritten to spec §2.5, 2026-08-25 — Destin judged
// the earlier screen "too complicated for no reason").
//
// This renders INSTEAD of the app, and it is the only screen in the product
// whose reader is someone whose app will not start. Two rules follow from
// that, and both are asserted in HealthGate.test.tsx:
//
//   * No stack trace, no JSON, no error codes. The server has already turned
//     every failure into one plain sentence.
//   * The repair box appears ONLY when relocating the folder can actually
//     help (`can_repair`). Offering it for a corrupt corpus would send
//     someone through a fix that cannot work.
//
// A browser cannot learn a folder's real address (a page can't read the
// filesystem) — the server runs on the same PC and can, via Windows' own
// Browse-for-Folder dialog (`can_pick`; absent on Linux/macOS). The dialog's
// choice is NOT saved directly: it is fed through the same save() the typed
// box uses, so nothing here can bypass the server-side validation that
// already lives in /api/config/data-dir.
//
// A relocation takes effect at once: the server re-probes the folder when
// it is saved. The "Check again" button re-runs the ladder.

function RungRow({ rung }: { rung: api.HealthRung }) {
  if (rung.ok === true) return null;
  if (rung.ok === null) return null; // short-circuited; saying so twice helps nobody
  return (
    <div className="rep-rung" data-testid="repair-rung">
      <p className="rep-detail">{rung.detail}</p>
      {rung.fix ? <p className="rep-fix">{rung.fix}</p> : null}
    </div>
  );
}

export function Repair({
  report,
  onRetry,
}: {
  report: api.HealthReport;
  onRetry: () => void;
}) {
  const [path, setPath] = useState(report.data_dir ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pickerBusy, setPickerBusy] = useState(false);

  async function save(value: string) {
    setError(null);
    setBusy(true);
    try {
      await api.setDataDir(value);
      setSaved(true);
    } catch (err) {
      // The server's own sentence — it distinguishes "can't find that
      // folder" from "that folder has no data in it", and the difference
      // decides what the reader does next.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await save(path);
  }

  async function pick() {
    // A SEPARATE busy flag from `busy`: the picker button must say "Waiting
    // for the folder window…" only while ITS dialog is open, not whenever
    // the typed-address form happens to be saving.
    setError(null);
    setPickerBusy(true);
    try {
      const { path: chosen } = await api.pickFolder();
      if (chosen) {
        setPath(chosen);
        await save(chosen);
      }
      // chosen is null on Cancel — leave the form exactly as it was.
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPickerBusy(false);
    }
  }

  return (
    <main className="page-repair" data-testid="repair">
      <div className="wrap">
        <section className="card rep-card">
          <h1>JLBC Search needs the budget folder</h1>

          {report.rungs.map((rung) => (
            <RungRow rung={rung} key={rung.name} />
          ))}

          {report.can_repair ? (
            saved ? (
              <div className="rep-done" role="status" data-testid="repair-done">
                <p>
                  Saved. Click <strong>Check again</strong>.
                </p>
              </div>
            ) : (
              <form className="rep-form" onSubmit={submit} data-testid="repair-form">
                {report.can_pick ? (
                  <button
                    type="button"
                    className="adm-btn"
                    onClick={pick}
                    disabled={pickerBusy}
                  >
                    {pickerBusy ? "Waiting for the folder window…" : "Choose folder…"}
                  </button>
                ) : null}
                <label htmlFor="rep-path">
                  {report.can_pick ? "or type its location:" : "Type its location:"}
                </label>
                <input
                  id="rep-path"
                  type="text"
                  value={path}
                  autoComplete="off"
                  spellCheck={false}
                  // WHY: JSX attribute strings are not escape-processed; a plain
                  // placeholder="..." rendered four leading backslashes (seen in
                  // the 2026-08-25 checkpoint screenshot). This JS expression is
                  // escape-processed, so it renders the intended two.
                  placeholder={"\\\\server\\share\\jlbc-search-data"}
                  onChange={(e) => setPath(e.target.value)}
                />
                {error ? (
                  <p className="rep-error" role="alert" data-testid="repair-error">
                    {error}
                  </p>
                ) : null}
                <button type="submit" className="adm-btn" disabled={busy || !path.trim()}>
                  Use this folder
                </button>
              </form>
            )
          ) : null}

          <button type="button" className="adm-link" onClick={onRetry}>
            Check again
          </button>
        </section>
      </div>
    </main>
  );
}
