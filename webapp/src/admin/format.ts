// Number and date formatting shared across the admin panels.
//
// These live together because two panels rendering the same dollar total in
// two formats is the fastest way to make an admin distrust both of them.

export function usd(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** The office total, plus a footnote only when one is actually needed.
 *
 *  Since 2026-07-31 a call CANNOT be recorded without a cost: OpenRouter
 *  reports its own, and a custom endpoint can't be saved without per-million
 *  prices to compute one from. So the second half of this pair is only ever
 *  reached by rows written before that change, and the normal reading is a
 *  plain dollar figure with no caveat attached.
 *
 *  It still has to be said when it happens — a total that silently omits
 *  rows understates the number an admin budgets against — but it is said in
 *  plain words underneath, not welded into the headline.
 */
export function unpricedNote(unknownRows: number): string | null {
  if (unknownRows <= 0) return null;
  const calls = unknownRows === 1 ? "1 older request isn't" : `${unknownRows} older requests aren't`;
  return `${calls} counted here — they were made before prices were set up.`;
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
 *  `null` means the live list had no usable price — shown as "price unknown"
 *  rather than a confident $0.00. */
export function perMillion(value: number | null): string {
  if (value === null) return "price unknown";
  return `$${value < 1 ? value.toFixed(2) : value.toFixed(2)}`;
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

/** Below this share of input served from cache, something is wrong.
 *
 *  Prompt caching is invisible when it works and invisible when it breaks —
 *  same answers, same logs, same token counts, and a bill roughly ten times
 *  larger. It is the one thing on this page a non-technical admin cannot
 *  possibly be expected to monitor, so it is NOT shown as a statistic. It
 *  surfaces only as a warning, only when it has actually gone wrong.
 *
 *  40% is well under the ~80% a healthy multi-step turn produces and well
 *  above the noise of a month with only one or two short questions in it.
 */
const CACHE_TROUBLE_BELOW = 0.4;
const CACHE_MIN_TOKENS = 200_000;

export function cacheLooksBroken(cached: number, tokensIn: number): boolean {
  // Not enough traffic to judge — a quiet month must not raise an alarm.
  if (tokensIn < CACHE_MIN_TOKENS) return false;
  return cached / tokensIn < CACHE_TROUBLE_BELOW;
}
