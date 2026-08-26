import { useState } from "react";
import type * as api from "../api";
import { samePerson } from "./same-person";

// The People panel (spec 2026-08-25-central-user-roster-design.md, U13).
//
// APPROVED FROM A RENDERED MOCKUP — docs/superpowers/specs/assets/
// 2026-08-25-user-roster-mockup/people-panel.html. Two earlier shapes were
// rejected on sight: a seven-column table with a Status column, numbered
// badges and a "show hidden" tick box ("too complicated, visual hierarchy
// messy"), and a box announcing a limit stored for a username nobody has
// logged in as ("wasteful and confusing"). What stands: one row per person,
// the limit as a dropdown on the row, ONE pill per row, hidden people as a
// single line beneath. Every action is a pill — never a bare underlined
// link control (Destin's standing rule, pinned repo-wide by
// styles/no-bare-links.test.ts).
//
// PURE. Admin.tsx fetches `people` and owns the settings draft; this edits
// the draft through the two callbacks and the page's save bar writes it.
// A limit change here is therefore listed in the save bar ("who has their
// own limit") exactly like the rows it replaced in ProviderPanel.

export type SortCol = "person" | "last_seen" | "spent" | "limit";
type Dir = "asc" | "desc";

const DEFAULT_SORT: { col: SortCol; dir: Dir } = { col: "spent", dir: "desc" };

function nameOf(p: api.PersonRow): string {
  return p.display_name || "";
}

/** Highest amount, then office default, then no limit (spec U13). */
function limitRank(p: api.PersonRow): number {
  if (p.limit.kind === "exempt") return -Infinity;
  if (p.limit.kind === "default") return -1;
  return p.limit.amount ?? -1;
}

export function sortPeople(rows: api.PersonRow[], col: SortCol, dir: Dir): api.PersonRow[] {
  const sign = dir === "asc" ? 1 : -1;
  const named = rows.filter((p) => nameOf(p));
  const unnamed = rows.filter((p) => !nameOf(p));
  const cmp = (a: api.PersonRow, b: api.PersonRow): number => {
    switch (col) {
      case "person":
        return sign * nameOf(a).localeCompare(nameOf(b));
      case "last_seen":
        return sign * a.last_seen.localeCompare(b.last_seen);
      case "spent":
        return sign * (a.spent_usd - b.spent_usd);
      case "limit":
        return sign * (limitRank(a) - limitRank(b));
    }
  };
  if (col === "person") {
    // A person with no recorded name sorts LAST in BOTH directions:
    // reversing a sort must not promote the least informative rows.
    return [...named].sort(cmp).concat(unnamed.sort((a, b) => a.username.localeCompare(b.username)));
  }
  return [...rows].sort(cmp);
}

function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

function when(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const LIMIT_OPTIONS: Array<{ value: api.PersonLimit["kind"]; label: (d: number | null) => string }> = [
  { value: "default", label: (d) => (d === null ? "Office default (no limit)" : `Office default ($${d})`) },
  { value: "custom", label: () => "A specific amount" },
  { value: "exempt", label: () => "No limit" },
];

/** What the dropdown + amount box for `p` should show RIGHT NOW.
 *
 * Reads the DRAFT, not the server row (`p.limit`). Before this fix the
 * controls were bound to `p.limit`, which never changes as the admin
 * types — React re-applies that value on every render, so the dropdown
 * snapped back to the server's kind and a typed amount was overwritten
 * mid-keystroke (reproduced live, 2026-08-25 final review). The two
 * settings fields are mutually exclusive (spec U8: exempt wins over a
 * custom amount), and a stored key can be spelled two ways (U0), so the
 * lookup order mirrors `Settings.limit_for` on the server: exempt (folded)
 * beats a custom amount; an EXACT key match on `user_limits` beats a
 * folded one, so the row shown before a save agrees with what a save then
 * reads back. */
function draftLimitFor(
  username: string,
  draft: api.AdminSettings,
): { kind: api.PersonLimit["kind"]; amount: number | null } {
  if (draft.exempt_users.some((u) => samePerson(u, username))) {
    return { kind: "exempt", amount: null };
  }
  if (Object.prototype.hasOwnProperty.call(draft.user_limits, username)) {
    return { kind: "custom", amount: draft.user_limits[username] };
  }
  for (const [key, amount] of Object.entries(draft.user_limits)) {
    if (samePerson(key, username)) {
      return { kind: "custom", amount };
    }
  }
  return { kind: "default", amount: null };
}

export function PeoplePanel({
  people,
  loadError,
  draft,
  onLimitChange,
  onHiddenChange,
}: {
  people: api.AdminUsers | null;
  loadError: string | null;
  draft: api.AdminSettings;
  onLimitChange: (username: string, kind: api.PersonLimit["kind"], amount: number | null) => void;
  onHiddenChange: (hidden_users: string[]) => void;
}) {
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [showHidden, setShowHidden] = useState(false);

  function clickHeading(col: SortCol) {
    setSort((s) => (s.col === col ? { col, dir: s.dir === "asc" ? "desc" : "asc" } : { col, dir: col === "person" ? "asc" : "desc" }));
  }

  // `hidden` comes from the DRAFT, not the server row, so a hide shows at
  // once and the save bar lists it; the server's flag is what the draft
  // started from. Compared under U0's fold (`samePerson`, not `.includes`)
  // — the roster can re-spell a person's username between visits
  // (`DMOSS` → `dmoss`), and an exact-match `.includes` would let someone
  // hidden under one spelling reappear under the next (2026-08-26 final
  // review).
  const isHidden = (p: api.PersonRow) => draft.hidden_users.some((u) => samePerson(u, p.username));

  function hide(p: api.PersonRow) {
    if (isHidden(p)) return; // already present under the fold — no duplicate entry
    onHiddenChange([...draft.hidden_users, p.username]);
  }
  function unhide(p: api.PersonRow) {
    // Every spelling, not just the one that matched the visible row — a
    // legacy hidden_users list can hold both `dmoss` and `DMOSS`.
    onHiddenChange(draft.hidden_users.filter((u) => !samePerson(u, p.username)));
  }

  const rows = people ? sortPeople(people.people, sort.col, sort.dir) : [];
  const visible = rows.filter((p) => !isHidden(p) || showHidden);
  const hidden = rows.filter(isHidden);

  const heading = (col: SortCol, label: string) => (
    <th
      scope="col"
      className="adm-people-sortable"
      aria-sort={sort.col === col ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
    >
      {/* A column-sort heading is not an action — Destin's "every action is
          a pill" rule (see the CSS block below) governs Hide/Unhide/Show,
          not this. The mockup renders it as plain heading text with an
          arrow, so it carries no `adm-btn`. */}
      <button type="button" className="adm-people-sort" onClick={() => clickHeading(col)}>
        {label}
        {sort.col === col ? <span className="adm-people-arrow">{sort.dir === "asc" ? "▲" : "▼"}</span> : null}
      </button>
    </th>
  );

  return (
    <section className="card adm-panel" aria-labelledby="adm-people-h" data-testid="admin-people">
      <h2 id="adm-people-h">People</h2>
      <p className="adm-sub">
        Everyone who has opened the app, and what they have spent on AI Mode this
        month. Names come from Windows; anyone can change their own on their
        Settings page.
      </p>

      {loadError ? (
        <p className="adm-warn" role="alert">{loadError}</p>
      ) : people === null ? (
        <p className="adm-empty">Loading…</p>
      ) : people.unreachable ? (
        <p className="adm-warn" role="alert" data-testid="admin-people-unreachable">
          The list of people couldn't be read from the shared folder. Check the
          shared drive is connected, then reload.
        </p>
      ) : people.people.length === 0 ? (
        <p className="adm-empty">Nobody has opened the app yet.</p>
      ) : (
        <>
          <div className="adm-table-wrap">
            <table className="adm-table adm-people">
              <thead>
                <tr>
                  {heading("person", "Person")}
                  {heading("last_seen", "Last seen")}
                  {heading("spent", "Spent this month")}
                  {heading("limit", "Monthly limit")}
                  <th scope="col"><span className="adm-vh">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((p) => {
                  const name = nameOf(p);
                  const label = name || p.username;
                  const hiddenRow = isHidden(p);
                  // The DRAFT's view of this row's limit — see draftLimitFor's
                  // comment for why this replaced `p.limit` (Fix 1, final review).
                  const draftLimit = draftLimitFor(p.username, draft);
                  return (
                    <tr key={p.key} className={hiddenRow ? "is-hidden" : undefined}>
                      <th scope="row">
                        {name ? name : <span className="adm-people-noname">No name yet</span>}
                        <span className="adm-people-who">{p.username}</span>
                      </th>
                      <td>{when(p.last_seen)}</td>
                      <td>{usd(p.spent_usd)}</td>
                      <td>
                        <span className="adm-people-limit">
                          <select
                            aria-label={`Monthly limit for ${label}`}
                            value={draftLimit.kind}
                            disabled={hiddenRow}
                            onChange={(e) => {
                              const kind = e.target.value as api.PersonLimit["kind"];
                              onLimitChange(p.username, kind, kind === "custom" ? (draftLimit.amount ?? draft.default_monthly_limit_usd ?? 0) : null);
                            }}
                          >
                            {LIMIT_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label(draft.default_monthly_limit_usd)}</option>
                            ))}
                          </select>
                          {draftLimit.kind === "custom" ? (
                            <input
                              type="number"
                              min={0}
                              aria-label={`Monthly amount for ${label}`}
                              value={draftLimit.amount ?? ""}
                              disabled={hiddenRow}
                              onChange={(e) => onLimitChange(p.username, "custom", e.target.value === "" ? 0 : Number(e.target.value))}
                            />
                          ) : null}
                        </span>
                        {p.limit.collision.length > 1 ? (
                          <p className="adm-people-warn">
                            Two spellings of this limit are saved ({p.limit.collision.join(" and ")}).
                            The exact match is the one in force — remove the other.
                          </p>
                        ) : null}
                      </td>
                      <td className="adm-people-act">
                        {hiddenRow ? (
                          <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => unhide(p)}>
                            Unhide <span className="adm-vh">{label}</span>
                          </button>
                        ) : (
                          <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => hide(p)}>
                            Hide <span className="adm-vh">{label}</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {people.unreadable > 0 ? (
            <p className="adm-hint">
              {people.unreadable === 1 ? "1 person's record" : `${people.unreadable} people's records`} couldn't be read.
            </p>
          ) : null}

          {hidden.length > 0 && !showHidden ? (
            <div className="adm-people-hidden">
              <span>
                {hidden.length === 1
                  ? `1 person hidden (${nameOf(hidden[0]) || hidden[0].username}, last seen ${when(hidden[0].last_seen)})`
                  : `${hidden.length} people hidden`}
              </span>
              <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => setShowHidden(true)}>Show</button>
            </div>
          ) : null}
          <p className="adm-hint">
            Hiding someone takes them out of the lists on this page. Their past
            spending still counts; nothing is deleted.
          </p>
        </>
      )}
    </section>
  );
}
