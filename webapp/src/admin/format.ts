// Number and date formatting shared across the admin panels.
//
// These live together because two panels rendering the same dollar total in
// two formats is the fastest way to make an admin distrust both of them.

export function usd(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** The honest office total (spec S19 / Ground truth 6).
 *
 *  A call on a custom endpoint has no dollar cost — OpenRouter's exact-cost
 *  accounting isn't available there — so its tokens are known and its price is
 *  not. Rendering the sum alone would understate spend with no sign it
 *  happened, which is precisely the number an admin budgets against. So an
 *  unknown-cost row turns the figure into "at least $X".
 */
export function honestTotal(total: number, unknownRows: number): string {
  if (unknownRows <= 0) return usd(total);
  const calls = unknownRows === 1 ? "1 call" : `${unknownRows} calls`;
  return `at least ${usd(total)} (${calls} of unknown cost)`;
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "unknown";
  if (value < 1024) return `${value} bytes`;
  const units = ["KB", "MB", "GB", "TB"];
  let n = value / 1024;
  let unit = 0;
  while (n >= 1024 && unit < units.length - 1) {
    n /= 1024;
    unit += 1;
  }
  return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[unit]}`;
}

/** Dollars per million tokens, as every model vendor quotes prices.
 *  `null` means the live catalog had no usable price — shown as "price
 *  unknown" rather than a confident $0.00. */
export function perMillion(value: number | null): string {
  if (value === null) return "price unknown";
  return `$${value < 1 ? value.toFixed(3) : value.toFixed(2)}/M`;
}

export function count(value: number): string {
  return value.toLocaleString("en-US");
}

/** A date a non-technical reader can act on, from an ISO timestamp.
 *  Returns the raw string if it doesn't parse — better a machine timestamp
 *  than "Invalid Date". */
export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "prompt caching: N% of input tokens served from cache".
 *
 *  THE number that reveals a silently broken cache prefix (S22). A broken
 *  cache produces identical answers, identical tokens and identical logs —
 *  and a bill roughly 10x larger. Nothing else in the system can tell.
 */
export function cachePercent(cached: number, tokensIn: number): number | null {
  if (tokensIn <= 0) return null;
  return Math.round((cached / tokensIn) * 100);
}
