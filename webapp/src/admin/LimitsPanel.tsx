import * as api from "../api";

// Spend limits (S19). This panel edits CONFIG only — it never re-implements
// the resolution. `check_limit()` on the server already owns every rule here
// (exempt list beats per-user override beats org default; 0 means "block
// outright"; blank means "no limit"; the warning fires at 80%), and a second
// copy of that logic in the UI would eventually disagree with the one that
// actually decides whether an analyst can ask a question.

export function LimitsPanel({
  settings,
  limitsActive,
  limitsInactiveReason,
  onDefaultChange,
  onUserLimitsChange,
  onExemptChange,
}: {
  settings: api.AdminSettings;
  limitsActive: boolean;
  limitsInactiveReason: string | null;
  onDefaultChange: (value: number | null) => void;
  onUserLimitsChange: (limits: Record<string, number>) => void;
  onExemptChange: (users: string[]) => void;
}) {
  const entries = Object.entries(settings.user_limits);

  function setRow(oldName: string, name: string, amount: number) {
    const next: Record<string, number> = {};
    for (const [k, v] of entries) {
      if (k === oldName) {
        if (name.trim()) next[name] = amount;
      } else {
        next[k] = v;
      }
    }
    onUserLimitsChange(next);
  }

  return (
    <section className="card adm-panel" aria-labelledby="adm-limits-h" data-testid="admin-limits">
      <h2 id="adm-limits-h">Spend limits</h2>
      <p className="adm-sub">
        These decide who this app lets keep asking once they have spent a set
        amount in a month. <strong>Search is never affected</strong> — a person
        at their limit can still search, browse fiscal notes and upload.
      </p>

      {!limitsActive && limitsInactiveReason ? (
        <p className="adm-warn" data-testid="admin-limits-warning">
          {limitsInactiveReason === "custom endpoint"
            ? "Limits are not being enforced: on a custom endpoint this app never learns what a call cost, so there is no figure to compare against a limit."
            : "No limit is set, so nobody is capped by this app. The hard monthly cap on your OpenRouter dashboard is what actually stops spending."}
        </p>
      ) : null}

      <label className="adm-field">
        <span>Monthly limit for everyone</span>
        <input
          type="number"
          min={0}
          step="1"
          value={settings.default_monthly_limit_usd ?? ""}
          placeholder="no limit"
          onChange={(e) =>
            onDefaultChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
        <span className="adm-hint">
          Leave blank for no limit. Enter 0 to block everyone from AI Mode.
        </span>
      </label>

      <h3>People with a different limit</h3>
      {entries.length === 0 ? (
        <p className="adm-empty">Nobody has their own limit.</p>
      ) : (
        <ul className="adm-rows">
          {entries.map(([name, amount]) => (
            <li key={name} data-testid="admin-user-limit">
              <input
                aria-label={`Windows username for the ${name} limit`}
                type="text"
                value={name}
                onChange={(e) => setRow(name, e.target.value, amount)}
              />
              <input
                aria-label={`Monthly limit for ${name}`}
                type="number"
                min={0}
                value={amount}
                onChange={(e) => setRow(name, name, Number(e.target.value))}
              />
              <button
                type="button"
                className="adm-link"
                onClick={() => {
                  const next = { ...settings.user_limits };
                  delete next[name];
                  onUserLimitsChange(next);
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="adm-btn adm-btn-quiet"
        onClick={() => onUserLimitsChange({ ...settings.user_limits, "": 0 })}
        disabled={Object.prototype.hasOwnProperty.call(settings.user_limits, "")}
      >
        Add a person
      </button>
      <p className="adm-hint">
        Type the username Windows shows for them — the Settings page displays
        each person their own. It is matched exactly, so <code>dmoss</code> and{" "}
        <code>DMOSS</code> are two different people to this app.
      </p>

      <h3>People with no limit at all</h3>
      <p className="adm-hint">
        An exemption beats everything else, including a limit typed above.
      </p>
      <input
        aria-label="Exempt usernames, separated by commas"
        type="text"
        value={settings.exempt_users.join(", ")}
        placeholder="e.g. the director"
        onChange={(e) =>
          onExemptChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    </section>
  );
}
