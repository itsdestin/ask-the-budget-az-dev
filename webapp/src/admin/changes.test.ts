import { describe, expect, it } from "vitest";
import { describeChanges } from "./changes";
import type { AdminSettings } from "../api";

const base: AdminSettings = {
  provider: { provider: "openrouter", base_url: "https://openrouter.ai/api/v1", api_key_set: true, api_key_hint: "…abcd", prompt_usd_per_m: null, completion_usd_per_m: null },
  tiers: { standard: { model: "vendor/m", enabled: true } },
  admin_username: "Destin",
  ai_enabled: true,
  default_monthly_limit_usd: 40,
  user_limits: {},
  exempt_users: [],
  hidden_users: [],
};

describe("hidden people", () => {
  it("names a hide as a change the admin can read", () => {
    const draft = { ...base, hidden_users: ["pchen"] };
    expect(describeChanges(base, draft, null, null)).toEqual(["who is hidden"]);
  });
});
