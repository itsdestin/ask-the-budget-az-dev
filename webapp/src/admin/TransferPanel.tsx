import { useState } from "react";
import * as api from "../api";

// Admin transfer, and the place the app says out loud what the admin gate is.
//
// The transfer is one-way from the giver's point of view: the app matches the
// username EXACTLY, so a typo hands admin to a person who does not exist and
// takes it away from the one who does. That is a real, mundane lockout — which
// is why this panel names the prevention (ask them what Windows calls them)
// and the escape hatch (the RESET-ADMIN.txt file) in the same breath.

export function TransferPanel({
  settings,
  me,
  onTransfer,
}: {
  settings: api.AdminSettings;
  me: api.Me;
  onTransfer: (username: string) => void;
}) {
  const [next, setNext] = useState("");
  const [armed, setArmed] = useState(false);

  return (
    <section className="card adm-panel" aria-labelledby="adm-transfer-h" data-testid="admin-transfer">
      <h2 id="adm-transfer-h">Who can open this page</h2>
      <p>
        Right now: <strong>{settings.admin_username || "nobody — it is unclaimed"}</strong>.
        Windows knows you as <strong>{me.user}</strong>.
      </p>

      <p className="adm-note">
        This is a soft gate, not a lock. It is keyed on the Windows username and
        anyone who can write to the shared folder can change it. It exists so
        this page isn't advertised office-wide and so one person's spending
        isn't casually browsable — nothing dangerous sits behind it. The
        OpenRouter key is protected by the hard spending cap on your OpenRouter
        dashboard, not by this gate.
      </p>

      <label className="adm-field">
        <span>Hand admin to someone else</span>
        <input
          type="text"
          value={next}
          placeholder="their Windows username"
          onChange={(e) => {
            setNext(e.target.value);
            setArmed(false);
          }}
        />
        <span className="adm-hint">
          Ask them what Windows shows for their username rather than guessing
          from their name — the Settings page displays it. It is matched
          exactly, so one wrong letter locks both of you out.
        </span>
      </label>

      {armed ? (
        <div className="adm-caveats" data-testid="admin-transfer-confirm">
          <p>
            Handing admin to <strong>{next}</strong> removes your own access to
            this page. Only they can give it back.
          </p>
          <button
            type="button"
            className="adm-btn adm-btn-danger"
            onClick={() => {
              onTransfer(next.trim());
              setArmed(false);
            }}
          >
            Yes, hand over admin
          </button>
          <button type="button" className="adm-link" onClick={() => setArmed(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="adm-btn adm-btn-quiet"
          disabled={!next.trim()}
          onClick={() => setArmed(true)}
        >
          Hand over admin…
        </button>
      )}

      <p className="adm-hint">
        If nobody can get into this page — a mistyped username, someone left,
        IT changed the username format — create an empty file called{" "}
        <code>RESET-ADMIN.txt</code> in the shared data folder and reopen the
        app. The handbook has the step-by-step version.
      </p>
    </section>
  );
}
