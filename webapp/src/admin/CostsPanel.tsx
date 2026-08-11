import * as api from "../api";
import { CollapsibleCard } from "./Card";
import { cacheLooksBroken, count, unpricedNote, usd } from "./format";

// "What is this costing us" — the first question a new admin has, so the
// first thing on the page.
//
// What was deliberately REMOVED here (2026-07-31, Destin): the per-row
// "cached input" column and the "prompt caching: N% of input tokens served
// from cache" line. Both were true, and neither was usable by a
// non-technical admin — a percentage nobody can act on is noise, and noise
// on this page costs attention that the numbers below actually need.
//
// The fact underneath still matters: a broken cache prefix produces a bill
// roughly ten times larger with no other symptom. So it now surfaces the
// only way it usefully can — as a plain warning, only when it has actually
// gone wrong (see `cacheLooksBroken`).

const TABS = [
  { key: "by_user", label: "By person" },
  { key: "by_model", label: "By model" },
  { key: "by_tier", label: "By answer mode" },
] as const;

type Tab = (typeof TABS)[number]["key"];

// The raw tier key is a machine string — "standard", "deep_research",
// "title" — and the "By answer mode" tab renders it verbatim at row.key.
// An admin seeing "title" next to "standard" has no way to tell what it
// is, so this maps every known key to a human label. A key NOT in this map
// (a future tier, or a corrupt row) falls through to the raw string, so
// the admin still sees SOMETHING rather than a blank cell — the same
// fail-safe as `row.key || "(not recorded)"` below it.
const TIER_LABELS: Record<string, string> = {
  standard: "Standard",
  deep_research: "Deep Research",
  title: "Chat naming",
};

export function CostsPanel({
  usage,
  month,
  onMonthChange,
  tab,
  onTabChange,
  isCustomEndpoint,
}: {
  usage: api.AdminUsage;
  month: string;
  onMonthChange: (month: string) => void;
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  isCustomEndpoint: boolean;
}) {
  const rows = usage[tab];
  const footnote = unpricedNote(usage.rows_with_unknown_cost);

  return (
    <section className="card adm-panel" aria-labelledby="adm-costs-h" data-testid="admin-costs">
      <div className="adm-panel-head">
        <h2 id="adm-costs-h">Spending</h2>
        <label className="adm-month">
          <span className="adm-vh">Month</span>
          <input
            type="month"
            value={month}
            onChange={(e) => onMonthChange(e.target.value)}
            aria-label="Month"
          />
        </label>
      </div>

      <p className="adm-total" data-testid="admin-total">
        {usd(usage.total_usd)}
      </p>
      <p className="adm-sub">
        {count(usage.rows)} {usage.rows === 1 ? "request" : "requests"} this month
        {isCustomEndpoint ? ", worked out from the prices you entered" : ""}
      </p>

      {footnote ? (
        <p className="adm-hint" data-testid="admin-unpriced-note">
          {footnote}
        </p>
      ) : null}

      {cacheLooksBroken(usage.cached_tokens, usage.tokens_in) ? (
        <p className="adm-warn" data-testid="admin-cache-warning">
          Costs are running higher than they should. The app normally reuses
          most of each question's setup text instead of paying for it again,
          and that has stopped working. Worth reporting — nothing you can
          change here will fix it.
        </p>
      ) : null}

      {!usage.limits_active && usage.limits_inactive_reason ? (
        <p className="adm-warn" data-testid="admin-limits-inactive">
          {usage.limits_inactive_reason === "custom endpoint"
            ? "Nobody is capped right now: this AI service has no prices set, so the app can't tell when someone reaches a limit."
            : "Nobody is capped right now — no monthly limit is set below."}
        </p>
      ) : null}

      <CollapsibleCard
        title="Who spent what"
        hint={`${usage.by_user.length} ${usage.by_user.length === 1 ? "person" : "people"}`}
        testId="admin-breakdown"
      >
        <div className="adm-tabs" role="tablist" aria-label="Break spending down by">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={tab === t.key ? "adm-tab is-on" : "adm-tab"}
              onClick={() => onTabChange(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <p className="adm-empty">Nothing recorded this month.</p>
        ) : (
          <div className="adm-table-wrap">
          <table className="adm-table" data-testid="admin-usage-table">
            <thead>
              <tr>
                <th scope="col">
                  {tab === "by_user" ? "Person" : tab === "by_model" ? "Model" : "Answer mode"}
                </th>
                <th scope="col">Spent</th>
                <th scope="col">Requests</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key || "(unrecorded)"}>
                  <th scope="row">
                    {tab === "by_tier" ? (TIER_LABELS[row.key] ?? row.key ?? "(not recorded)") : (row.key || "(not recorded)")}
                  </th>
                  <td>{usd(row.cost_usd)}</td>
                  <td>{count(row.rows)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </CollapsibleCard>
    </section>
  );
}
