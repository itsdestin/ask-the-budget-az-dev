import type { AdminSettings } from "../api";

// What has the admin actually changed, in their words.
//
// This exists because a bare "Save changes" button is unanswerable: it sits
// between two cards, belongs to neither of them visually, and gives no way to
// tell whether it is lit because you changed a model or because you fat-
// fingered a spending limit three screens up. Naming the changes turns the
// save into a decision rather than a leap.
//
// The labels are the words on the controls, not the field names. "Standard's
// model" — not `tiers.standard.model`.

export function describeChanges(
  saved: AdminSettings | null,
  draft: AdminSettings,
  /** null when the key field was never touched; a string once it was. */
  apiKey: string | null,
  /** non-null once an admin transfer has been confirmed in the UI. */
  transferTo: string | null,
  /** Server-side label per answer mode, so this doesn't re-type S16's copy. */
  tierLabels: Record<string, string> = {},
): string[] {
  if (!saved) return [];
  const changes: string[] = [];
  const label = (tier: string) => tierLabels[tier] ?? tier;

  if (draft.ai_enabled !== saved.ai_enabled) {
    changes.push(draft.ai_enabled ? "AI Mode switched on" : "AI Mode switched off");
  }
  if (apiKey !== null) {
    changes.push(apiKey === "" ? "the key removed" : "a new key");
  }

  for (const [tier, cfg] of Object.entries(draft.tiers)) {
    const before = saved.tiers[tier];
    if (!before) {
      changes.push(`${label(tier)} added`);
      continue;
    }
    if (cfg.enabled !== before.enabled) {
      changes.push(`${label(tier)} switched ${cfg.enabled ? "on" : "off"}`);
    }
    // A model change is only worth reporting while the mode is on — turning
    // a mode off doesn't need "and its model changed" underneath it.
    if (cfg.model !== before.model && cfg.enabled) {
      changes.push(`${label(tier)}'s model`);
    }
  }

  if (draft.provider.provider !== saved.provider.provider) {
    changes.push("which AI service is used");
  } else if (draft.provider.base_url !== saved.provider.base_url) {
    changes.push("the service address");
  }
  if (
    draft.provider.prompt_usd_per_m !== saved.provider.prompt_usd_per_m ||
    draft.provider.completion_usd_per_m !== saved.provider.completion_usd_per_m
  ) {
    changes.push("what the service charges");
  }

  if (draft.default_monthly_limit_usd !== saved.default_monthly_limit_usd) {
    changes.push("the monthly limit");
  }
  if (JSON.stringify(draft.user_limits) !== JSON.stringify(saved.user_limits)) {
    changes.push("who has their own limit");
  }
  if (JSON.stringify(draft.exempt_users) !== JSON.stringify(saved.exempt_users)) {
    changes.push("who has no limit");
  }
  if (transferTo !== null) {
    changes.push(`admin handed to ${transferTo}`);
  }
  return changes;
}

/** "a and b" / "a, b and c" — a list a person reads, not a bulleted dump. */
export function joinChanges(changes: string[]): string {
  if (changes.length <= 1) return changes[0] ?? "";
  return `${changes.slice(0, -1).join(", ")} and ${changes[changes.length - 1]}`;
}
