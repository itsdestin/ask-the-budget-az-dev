import { useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";
import { samePerson } from "./same-person";

// The things an admin touches once, or never — collapsed by default.
//
// Admin transfer and file locations used to be two full-width panels at the
// bottom of the page. Neither is something anyone does on a normal visit, and
// both carried the longest explanatory text on the screen, so they took up
// most of the page while earning the least of it.
//
// What did NOT get shortened: the sentence saying this gate is soft. If
// anyone later mistakes it for security and puts something genuinely
// sensitive behind it, that is a real vulnerability introduced by misreading
// — so the app says what it is, in the app, where someone deciding will see
// it.

export function AdvancedPanel({
  settings,
  me,
  dataDir,
  onTransfer,
  people,
  peopleError,
}: {
  settings: api.AdminSettings;
  me: api.Me;
  dataDir: string;
  onTransfer: (username: string) => void;
  people: api.AdminUsers | null;
  peopleError: string | null;
}) {
  const [next, setNext] = useState("");
  const [armed, setArmed] = useState(false);

  // A PICKER, not a typed box (spec U10/U11, Destin 2026-08-25). A typed
  // username here was the single most dangerous typo in the product — one
  // wrong letter locked both people out, recoverable only by hand-creating
  // RESET-ADMIN.txt on the share. The picker offers people who have opened
  // the app, minus hidden people and me. There is deliberately NO typed
  // escape hatch in normal use: a successor opens the app once (thirty
  // seconds) and appears here. The typed box returns ONLY when the people
  // list itself cannot be read (spec U12) — an empty picker there would be
  // a dead end.
  const candidates = (people?.people ?? []).filter(
    (p) => !p.hidden && !samePerson(p.username, me.user),
  );
  const chosen = candidates.find((p) => p.username === next);
  const chosenLabel = chosen?.display_name ? chosen.display_name : next;

  return (
    <section className="card adm-panel" aria-labelledby="adm-adv-h" data-testid="admin-advanced">
      <h2 id="adm-adv-h">Access and files</h2>

      <CollapsibleCard
        title="Who can open this page"
        hint={settings.admin_username || "nobody — unclaimed"}
        testId="admin-transfer"
      >
        <p className="adm-sub">
          Windows knows you as <strong>{me.user}</strong>.
        </p>

        <p className="adm-note">
          This is a soft gate, not a lock. It goes by your Windows username,
          and anyone who can write to the shared folder can change it. It keeps
          the page from being advertised office-wide and keeps one person's
          spending from being casually browsable — nothing dangerous sits
          behind it. The key is protected by the hard spending cap on your
          OpenRouter account, not by this.
        </p>

        {peopleError !== null || people?.unreachable ? (
          <>
            <p className="adm-warn">
              The list of people couldn't be read from the shared folder, so
              you'll have to type the username. Their Settings page displays
              it. One wrong letter locks you both out.
            </p>
            <label className="adm-field">
              <span className="adm-label">Hand admin to someone else</span>
              <input
                type="text"
                value={next}
                placeholder="their Windows username"
                onChange={(e) => { setNext(e.target.value); setArmed(false); }}
              />
            </label>
          </>
        ) : people === null ? (
          // Still loading. `Admin.tsx` fetches the people list
          // fire-and-forget (not inside the awaited Promise.all), so this
          // is the FIRST render on every page load, not an edge case — and
          // the old code had no branch for it, so it fell into "no
          // candidates" and claimed "Nobody else has opened the app yet"
          // before it had asked (review finding, 2026-08-25).
          <label className="adm-field">
            <span className="adm-label">Hand admin to someone else</span>
            <select disabled aria-label="Hand admin to someone else">
              <option>Checking who has opened the app…</option>
            </select>
          </label>
        ) : (
          <label className="adm-field">
            <span className="adm-label">Hand admin to someone else</span>
            {candidates.length === 0 ? (
              <select disabled aria-label="Hand admin to someone else">
                <option>Nobody else has opened the app yet</option>
              </select>
            ) : (
              <select
                aria-label="Hand admin to someone else"
                value={next}
                onChange={(e) => { setNext(e.target.value); setArmed(false); }}
              >
                <option value="">Choose a person…</option>
                {candidates.map((p) => (
                  <option key={p.key} value={p.username}>
                    {p.display_name ? `${p.display_name} (${p.username})` : p.username}
                  </option>
                ))}
              </select>
            )}
            {candidates.length === 0 ? (
              <span className="adm-hint">Ask your successor to open the app once and they will appear here.</span>
            ) : null}
          </label>
        )}

        {armed ? (
          <div className="adm-caveats" data-testid="admin-transfer-confirm">
            <p>
              Handing admin to <strong>{chosenLabel}</strong> removes your own
              access to this page. Only they can give it back.
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
            <button type="button" className="adm-btn adm-btn-quiet" onClick={() => setArmed(false)}>
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
          If nobody can get in — a mistyped username, someone left, IT changed
          the username format — create an empty file called{" "}
          <code>RESET-ADMIN.txt</code> in the shared folder and reopen the app.
          The handbook has the step-by-step version.
        </p>
      </CollapsibleCard>

      <CollapsibleCard title="Where the files are" hint={dataDir} testId="admin-locations">
        <dl className="adm-stats">
          <div>
            <dt>Shared folder</dt>
            <dd>
              <code>{dataDir}</code>
            </dd>
          </div>
          <div>
            <dt>Settings</dt>
            <dd>
              <code>{dataDir}/settings.json</code>
            </dd>
          </div>
          <div>
            <dt>Spending records</dt>
            <dd>
              <code>{dataDir}/usage/</code>
            </dd>
          </div>
          <div>
            <dt>Backups</dt>
            <dd>
              <code>{dataDir}/backups/</code>
            </dd>
          </div>
        </dl>
        <p className="adm-hint">
          <a href="https://openrouter.ai/settings/credits" target="_blank" rel="noreferrer">
            Your OpenRouter account
          </a>{" "}
          — credits, and the hard monthly cap that actually stops spending.
        </p>
      </CollapsibleCard>
    </section>
  );
}
