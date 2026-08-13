import { useEffect, useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";
import { Toggle } from "./Toggle";
import { when } from "./format";

// The office's own shorthand for agency names (spec E1).
//
// Self-contained, like the guidance box: its own fetch, its own save, no part
// of the page's settings draft. An admin adding "DOR" must not have that
// write ride along with a half-finished spending-limit edit, and vice versa.
//
// EVERY mutation sends the whole list and renders whatever comes back. The
// server is the one that lowercases, de-duplicates, refuses toxic words and
// stamps who/when — so a locally appended row would show an admin a mapping
// that does not exist in the file the search actually reads.

export function AliasesPanel() {
  const [data, setData] = useState<api.AdminAliases | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [alias, setAlias] = useState("");
  const [agency, setAgency] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .adminAliases()
      .then((d) => !cancelled && setData(d))
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Write the whole overlay and adopt the server's answer as the new truth.
   *  On a refusal NOTHING local changes — the row the admin tried to add
   *  simply never appears, which is the honest picture of what was stored. */
  async function persist(body: {
    added: { alias: string; canonical_id: string }[];
    disabled: string[];
  }) {
    setError(null);
    setBusy(true);
    try {
      setData(await api.saveAdminAliases(body));
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <section
        className="card adm-panel"
        aria-labelledby="adm-aliases-h"
        data-testid="admin-aliases"
      >
        <h2 id="adm-aliases-h">Search language</h2>
        {error ? (
          <p className="adm-warn" role="alert">
            {error}
          </p>
        ) : (
          <p className="adm-empty">Loading…</p>
        )}
      </section>
    );
  }

  // The stored shape: the server keeps who/when itself, so a write only ever
  // carries the pairs.
  const pairs = data.added.map((row) => ({
    alias: row.alias,
    canonical_id: row.canonical_id,
  }));

  // Fix: SHORTHANDS, not rows. `shipped` carries one row per agency, so a
  // shorthand naming two agencies (`ua` names both University of Arizona
  // entries) was counted twice and the card claimed 12 where the office has
  // 11 words to type. The switch below is per-word too — turning `ua` off
  // turns it off for both rows — so the word is the honest unit here.
  const shorthandCount = new Set(data.shipped.map((s) => s.alias)).size;

  async function add() {
    const ok = await persist({
      added: [...pairs, { alias: alias.trim(), canonical_id: agency }],
      disabled: data!.disabled,
    });
    if (ok) {
      setAlias("");
      setAgency("");
    }
  }

  function remove(target: string) {
    void persist({
      added: pairs.filter((p) => p.alias !== target),
      disabled: data!.disabled,
    });
  }

  function setShippedEnabled(shipped: string, enabled: boolean) {
    const disabled = enabled
      ? data!.disabled.filter((d) => d !== shipped)
      : [...data!.disabled, shipped];
    void persist({ added: pairs, disabled });
  }

  return (
    <section
      className="card adm-panel"
      aria-labelledby="adm-aliases-h"
      data-testid="admin-aliases"
    >
      <h2 id="adm-aliases-h">Search language</h2>
      <p className="adm-sub">
        Short names your office uses for an agency, so typing one finds that
        agency's documents.
      </p>

      {/* Fix: hoisted out of "Your office's shorthand" — that card can be
          collapsed (renders no children while closed) while a save from the
          OTHER card fails, and a `role="alert"` inside unmounted content is
          an alert nobody sees. Panel-level catches refusals from both. */}
      {error ? (
        <p className="adm-warn" role="alert">
          {error}
        </p>
      ) : null}

      <CollapsibleCard
        title="Your office's shorthand"
        hint={
          data.added.length === 0
            ? "none added yet"
            : `${data.added.length} added`
        }
        testId="admin-aliases-card"
      >
        {/* Destin's rewrite of the spec's verbatim sentence (Task 10 fix
            pass 2): office English, and "short name" throughout instead of
            "alias" as a reader-facing noun. The limitation itself is
            unchanged and still real: documents already filed were labelled
            without this word, and no edit here goes back and re-labels
            them. */}
        <p className="adm-hint">
          Short names work in searches straight away. Documents already filed
          were labelled without them, so a new short name improves what you
          can type, not the labels on older documents.
        </p>

        {data.added.length === 0 ? (
          <p className="adm-empty" data-testid="admin-aliases-empty">
            Nothing added yet.
          </p>
        ) : (
          <div className="adm-table-wrap">
            <table className="adm-table" data-testid="admin-aliases-table">
              <thead>
                <tr>
                  <th>Short name</th>
                  <th>Agency</th>
                  <th>Added by</th>
                  <th>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.added.map((row) => (
                  <tr key={row.alias}>
                    <th scope="row">{row.alias}</th>
                    <td>{row.agency_name}</td>
                    <td>{row.added_by}</td>
                    <td>{when(row.added_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="adm-link"
                        disabled={busy}
                        onClick={() => remove(row.alias)}
                      >
                        Remove {row.alias}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="adm-inline">
          <label className="adm-field" htmlFor="adm-alias-new">
            <span>Shorthand</span>
            <input
              id="adm-alias-new"
              type="text"
              autoComplete="off"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
            />
          </label>
          <label className="adm-field" htmlFor="adm-alias-agency">
            <span>Agency</span>
            <select
              id="adm-alias-agency"
              value={agency}
              onChange={(e) => setAgency(e.target.value)}
            >
              <option value="">Choose an agency…</option>
              {data.agencies.map((a) => (
                <option key={a.canonical_id} value={a.canonical_id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="adm-btn"
            disabled={busy || alias.trim() === "" || agency === ""}
            onClick={add}
          >
            Add
          </button>
        </div>

        {/* Accepted, but worth saying out loud — the server allows these and
            tells us why it is uneasy. */}
        {data.warnings.length > 0 ? (
          <ul className="adm-rows" data-testid="admin-aliases-warnings">
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : null}
      </CollapsibleCard>

      <CollapsibleCard
        title="Shorthand that comes with the app"
        hint={
          data.disabled.length === 0
            ? `${shorthandCount} in use`
            : `${data.disabled.length} switched off`
        }
        testId="admin-shipped-card"
      >
        <p className="adm-hint">
          These come with the app. Switch one off if it keeps matching the wrong
          thing for your office.
        </p>
        <ul className="adm-rows">
          {data.shipped.map((s) => {
            const enabled = !data.disabled.includes(s.alias);
            return (
              // Fix: keyed by alias AND agency, because the server sends ONE
              // ROW PER AGENCY — `ua` names both University of Arizona
              // entries, so `key={s.alias}` was a duplicate React key (React
              // may then reconcile the wrong toggle) and a duplicate
              // data-testid (a getByTestId for it throws).
              <li
                key={`${s.alias}-${s.canonical_id}`}
                data-testid={`admin-shipped-${s.alias}-${s.canonical_id}`}
              >
                <span>
                  <strong>{s.alias}</strong> — {s.agency_name}
                </span>
                <Toggle
                  checked={enabled}
                  disabled={busy}
                  onChange={(next) => setShippedEnabled(s.alias, next)}
                  label={`Use ${s.alias} for ${s.agency_name}`}
                />
              </li>
            );
          })}
        </ul>
      </CollapsibleCard>
    </section>
  );
}
