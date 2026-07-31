import * as api from "../api";
import { cachePercent, count, honestTotal, usd } from "./format";

// The first panel a new admin sees, because "what is this costing us" is the
// first question they have.
//
// Two numbers here are load-bearing beyond their face value:
//
//  1. The total is rendered "at least $X (N calls of unknown cost)" whenever
//     any row has no price (S15 custom endpoints). A bare sum would quietly
//     understate spend.
//  2. The prompt-cache percentage (S22). The same system prompt is resent on
//     every step of every turn, and cache reads cost roughly a tenth of fresh
//     input. A broken cache prefix is INVISIBLE — same answers, same tokens,
//     same logs — except as a bill ~10x larger. This percentage is the only
//     early warning anyone gets.

const TABS: { key: keyof Pick<api.AdminUsage, "by_user" | "by_model" | "by_tier">; label: string }[] = [
  { key: "by_user", label: "By person" },
  { key: "by_model", label: "By model" },
  { key: "by_tier", label: "By mode" },
];

export function CostsPanel({
  usage,
  month,
  onMonthChange,
  tab,
  onTabChange,
}: {
  usage: api.AdminUsage;
  month: string;
  onMonthChange: (month: string) => void;
  tab: "by_user" | "by_model" | "by_tier";
  onTabChange: (tab: "by_user" | "by_model" | "by_tier") => void;
}) {
  const cache = cachePercent(usage.cached_tokens, usage.tokens_in);
  const rows = usage[tab];

  return (
    <section className="card adm-panel" aria-labelledby="adm-costs-h" data-testid="admin-costs">
      <h2 id="adm-costs-h">Costs</h2>

      <div className="adm-month">
        <label htmlFor="adm-month">Month</label>
        <input
          id="adm-month"
          type="month"
          value={month}
          onChange={(e) => onMonthChange(e.target.value)}
        />
      </div>

      <p className="adm-total" data-testid="admin-total">
        {honestTotal(usage.total_usd, usage.rows_with_unknown_cost)}
      </p>
      <p className="adm-sub">
        {count(usage.rows)} {usage.rows === 1 ? "call" : "calls"} this month
        {!usage.limits_active && usage.limits_inactive_reason ? (
          <>
            {" · "}
            <span data-testid="admin-limits-inactive">
              spend limits are not being enforced ({usage.limits_inactive_reason})
            </span>
          </>
        ) : null}
      </p>

      {cache === null ? null : (
        <p className="adm-cache" data-testid="admin-cache">
          Prompt caching: {cache}% of input tokens served from cache.{" "}
          <span className="adm-hint">
            If this drops near zero and stays there, caching has broken and the
            bill will rise roughly tenfold with no other symptom.
          </span>
        </p>
      )}

      <div className="adm-tabs" role="tablist" aria-label="Break costs down by">
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
        <p className="adm-empty">No AI Mode usage recorded this month.</p>
      ) : (
        <table className="adm-table" data-testid="admin-usage-table">
          <thead>
            <tr>
              <th scope="col">{tab === "by_user" ? "Person" : tab === "by_model" ? "Model" : "Mode"}</th>
              <th scope="col">Cost</th>
              <th scope="col">Calls</th>
              <th scope="col">Cached input</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const rowCache = cachePercent(row.cached_tokens, row.tokens_in);
              return (
                <tr key={row.key || "(unrecorded)"}>
                  <th scope="row">{row.key || "(not recorded)"}</th>
                  <td>{honestTotal(row.cost_usd, row.rows_with_unknown_cost)}</td>
                  <td>{count(row.rows)}</td>
                  <td>{rowCache === null ? "—" : `${rowCache}%`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <p className="adm-note">
        Costs come from OpenRouter's own per-call figures, recorded as each call
        finishes. The hard monthly cap on your OpenRouter dashboard is the only
        limit that stops spending outright — the limits below decide who this app
        lets keep asking. Total across all people: {usd(usage.total_usd)}.
      </p>
    </section>
  );
}
