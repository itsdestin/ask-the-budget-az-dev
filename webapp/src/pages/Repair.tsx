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
// The honest limitation, stated and not softened: a relocation cannot take
// effect mid-session. LanceDB handles and the search provider are resolved at
// startup, so the screen says "restart to finish" — because an app that
// claimed to be fixed and then served errors from stale handles would be
// worse than one that asked for a restart.

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
                  <strong>Saved.</strong> Close this window and open JLBC
                  Search again from the Start Menu to finish.
                </p>
                <p className="rep-fix">
                  The app has to start up again to use the new folder — it
                  can't switch over while it is running.
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
                  placeholder="\\\\server\\share\\jlbc-insight-data"
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

          <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={onRetry}>
            Check again
          </button>
        </section>
      </div>
    </main>
  );
}
