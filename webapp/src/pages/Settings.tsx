import { useEffect, useState } from "react";
import * as api from "../api";
import { unpricedNote, usd } from "../admin/format";

// The Settings page every analyst sees (Plan 5 Task 9). Not an admin surface —
// it answers the three questions a person has about themselves: what have I
// spent, why can't I use AI Mode right now, and where does my work live.
//
// Everything it shows about limits and availability is the SERVER'S sentence,
// never a re-typed one. The ledger owns "you've reached your monthly limit"
// and `ai_available()` owns "no API key configured" / "no model configured —
// ask the admin". Two subtly different versions of those, one in the composer
// and one here, is worse than one blunt version everywhere.

export function Settings() {
  const [me, setMe] = useState<api.Me | null>(null);
  const [usage, setUsage] = useState<api.MyUsage | null>(null);
  const [status, setStatus] = useState<api.AiStatus | null>(null);
  const [corpusDir, setCorpusDir] = useState<string | null>(null);
  const [claimed, setClaimed] = useState<string | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((m) => {
        if (cancelled) return;
        setMe(m);
        // Only an admin may read the corpus endpoint; an analyst simply
        // doesn't get the folder path, which is fine — the sentence below
        // works without it.
        if (m.is_admin) {
          api
            .adminCorpus()
            .then((c) => !cancelled && setCorpusDir(c.data_dir))
            .catch(() => {});
        }
      })
      .catch(() => {});
    api.myUsage().then((u) => !cancelled && setUsage(u)).catch(() => {});
    api.aiStatus().then((s) => !cancelled && setStatus(s)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function claim() {
    setClaimError(null);
    try {
      const result = await api.claimAdmin();
      setClaimed(result.admin_username);
      setMe(await api.me());
    } catch (err) {
      setClaimError(err instanceof Error ? err.message : String(err));
    }
  }

  const pct =
    usage && usage.limit_usd && usage.limit_usd > 0 && usage.month_usd !== null
      ? Math.min(100, Math.round((usage.month_usd / usage.limit_usd) * 100))
      : null;

  return (
    <main className="page-settings" data-testid="settings">
      <div className="wrap">
        <h1>Settings</h1>

        {me?.admin_claimable && !claimed ? (
          <section className="card adm-panel" data-testid="settings-claim">
            <h2>No admin is set up yet</h2>
            <p>
              Nobody has claimed the Admin page, so anyone can. Whoever claims it
              can add the API key, choose models and set spending limits.
            </p>
            {me.admin_reset_pending ? (
              <p className="adm-warn" data-testid="settings-reset-pending">
                An admin reset file is present in the data folder — claiming
                admin now will use it up.
              </p>
            ) : null}
            <button type="button" className="adm-btn" onClick={claim}>
              Claim admin as {me.user}
            </button>
            {claimError ? (
              <p className="adm-warn" role="alert">
                {claimError}
              </p>
            ) : null}
          </section>
        ) : null}

        {claimed ? (
          <p className="adm-ok" role="status" data-testid="settings-claimed">
            You are now the admin ({claimed}). The Admin page is in the menu above.
          </p>
        ) : null}

        <section className="card adm-panel" data-testid="settings-you">
          <h2>You</h2>
          <p>
            Windows knows you as <strong>{me?.user ?? "…"}</strong>. That is the
            name the admin needs if you ask for your own spending limit — it is
            matched exactly, capital letters included.
          </p>
          {me?.admin_username ? (
            <p className="adm-hint">
              Your admin is <strong>{me.admin_username}</strong>.
            </p>
          ) : null}
        </section>

        <section className="card adm-panel" data-testid="settings-usage">
          <h2>Your AI Mode usage this month</h2>
          {!usage ? (
            <p className="adm-empty">Loading…</p>
          ) : (
            <>
              <p className="adm-total" data-testid="settings-total">
                {usd(usage.month_usd ?? 0)}
                {usage.limit_usd !== null ? ` of ${usd(usage.limit_usd)}` : ""}
              </p>
              {unpricedNote(usage.rows_with_unknown_cost) ? (
                <p className="adm-hint" data-testid="settings-unpriced-note">
                  {unpricedNote(usage.rows_with_unknown_cost)}
                </p>
              ) : null}
              {pct !== null ? (
                <div
                  className="adm-meter"
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Share of your monthly limit used"
                  data-testid="settings-meter"
                >
                  <span style={{ width: `${pct}%` }} className={`is-${usage.status}`} />
                </div>
              ) : null}
              {/* The ledger's exact wording, never a re-typed copy. */}
              {usage.message ? (
                <p
                  className={usage.status === "blocked" ? "adm-warn" : "adm-note"}
                  data-testid="settings-limit-message"
                  role={usage.status === "blocked" ? "alert" : undefined}
                >
                  {usage.message}
                </p>
              ) : null}
              {usage.limit_usd === null ? (
                <p className="adm-hint" data-testid="settings-no-limit">
                  {usage.reason === "exempt"
                    ? "You have no spending limit."
                    : usage.reason === "custom endpoint"
                      ? "No limit is being enforced — your admin hasn't told the app what this office's AI service charges."
                      : "No spending limit is set for you."}
                </p>
              ) : null}
              <p className="adm-hint">
                Searching, browsing fiscal notes and uploading documents cost
                nothing and are never blocked by a limit.
              </p>
            </>
          )}
        </section>

        <section className="card adm-panel" data-testid="settings-ai">
          <h2>AI Mode</h2>
          {!status ? (
            <p className="adm-empty">Loading…</p>
          ) : status.available ? (
            <p data-testid="settings-ai-available">AI Mode is available.</p>
          ) : (
            /* The server's own reason string — "no API key configured" or
               "no model configured — ask the admin". */
            <p className="adm-warn" data-testid="settings-ai-reason">
              AI Mode is unavailable — {status.reason}.
            </p>
          )}
          {status
            ? Object.entries(status.tiers).map(([tier, info]) => (
                <p className="adm-hint" key={tier}>
                  <strong>{info.label}</strong> {info.description}
                  {info.available ? "" : ` (unavailable — ${info.reason})`}
                </p>
              ))
            : null}
        </section>

        <section className="card adm-panel" data-testid="settings-data">
          <h2>Where your work lives</h2>
          <p>
            Documents, the search index and this app's settings all live in one
            shared folder
            {corpusDir ? (
              <>
                {": "}
                <code>{corpusDir}</code>
              </>
            ) : (
              " on the office drive"
            )}
            . Nothing you search leaves the network. AI Mode is the exception:
            answering a question sends the passages it retrieved to an outside
            model provider.
          </p>
          <p className="adm-note" data-testid="settings-public-record">
            <strong>Public-record documents only.</strong> Upload baseline books,
            appropriations reports, fiscal notes, bills, executive and agency
            budget requests, and annual financial reports. Do not upload
            confidential material — anything in the shared folder can be
            retrieved by an AI Mode question and sent to the model provider,
            whose data-retention practices are not under our control.
          </p>
        </section>
      </div>
    </main>
  );
}
