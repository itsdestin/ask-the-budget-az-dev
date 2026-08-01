import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import { Repair } from "./pages/Repair";

// Wraps the router (Plan 5 Task 12, spec S18).
//
// A WRAPPER, NOT A ROUTE. That is the whole design decision: a broken share
// must not depend on client-side routing working, and "/repair" would be a
// URL nobody navigates to — the analyst is sitting on "/" watching an app
// that will not start.
//
// While the check is in flight the gate renders its children, not a spinner.
// The healthy case is overwhelmingly the common one, and a spinner in front
// of every launch would trade a real, everyday cost (a flash of blank on a
// working app) for a cosmetic gain in the rare broken case. The failure
// screen replaces the app the moment the check comes back.

export function HealthGate({ children }: { children: React.ReactNode }) {
  const [report, setReport] = useState<api.HealthReport | null>(null);

  const check = useCallback(() => {
    api
      .healthDetail()
      .then(setReport)
      .catch(() => {
        // The health endpoint itself is unreachable — the server is not
        // answering at all. Nothing useful can be said about WHY from in
        // here, so say only what is certainly true and offer the retry.
        setReport({
          ok: false,
          rungs: [
            {
              name: "server",
              ok: false,
              detail: "The app isn't responding on this computer.",
              fix: "Close this window and open JLBC Insight again from the Start Menu.",
            },
          ],
          data_dir: null,
          can_repair: false,
        });
      });
  }, []);

  useEffect(check, [check]);

  if (report && !report.ok) {
    return <Repair report={report} onRetry={check} />;
  }
  return <>{children}</>;
}
