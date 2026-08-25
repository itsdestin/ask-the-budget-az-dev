import { useState } from "react";
import * as api from "../api";

// The full-page failure screen (Plan 5 Task 12, spec S18).
//
// This renders INSTEAD of the app, and it is the only screen in the product
// whose reader is someone whose app will not start. Two rules follow from
// that, and both are asserted in HealthGate.test.tsx:
//
//   * No stack trace, no JSON, no error codes. The server has already turned
//     every failure into one plain sentence plus one action.
//   * The repair box appears ONLY when relocating the folder can actually
//     help (`can_repair`). Offering it for a corrupt corpus would send
//     someone through a fix that cannot work.
//
// A relocation takes effect at once: the server re-probes the folder when
// it is saved (2026-08-25). The "Check again" button re-runs the ladder.

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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.setDataDir(path);
      setSaved(true);
    } catch (err) {
      // The server's own sentence — it distinguishes "can't find that
      // folder" from "that folder has no corpus in it", and the difference
      // decides what the reader does next.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-repair" data-testid="repair">
      <div className="wrap">
        <section className="card rep-card">
          <h1>JLBC Search can't start</h1>

          {report.rungs.map((rung) => (
            <RungRow rung={rung} key={rung.name} />
          ))}

          {report.can_repair ? (
            saved ? (
              <div className="rep-done" role="status" data-testid="repair-done">
                <p>
                  <strong>Saved.</strong> Click <strong>Check again</strong> below to
                  confirm the app can open that folder.
                </p>
              </div>
            ) : (
              <form className="rep-form" onSubmit={submit} data-testid="repair-form">
                <label htmlFor="rep-path">
                  If the shared folder has moved, type its new location:
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
                <p className="rep-fix">
                  Open the folder in File Explorer, click the address bar, and
                  copy what it says.
                </p>
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
