import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { Admin } from "./Admin";

// The specs that pin real requirements rather than markup. In order of how
// badly the thing they protect fails when it breaks:
//
//  1. The key field. Empty with a last-four hint; an untouched save sends the
//     "__unchanged__" sentinel. A blanked key looks like "AI Mode randomly
//     stopped working" a week later, with nothing pointing at the cause.
//  2. The S15 custom-endpoint caveats, rendered IN the panel at the moment the
//     admin chooses it, not in a handbook they will read afterwards.
//  3. Tier copy asserted against the string the API returned, never a copy
//     typed into this file — otherwise a spec edit drifts silently.
//  4. A retired model renders greyed and unselectable rather than vanishing.
//  5. Restore needs a typed word and names the snapshot's date.

const KEY_HINT = "…cdef";

function settings(over: Partial<api.AdminSettings> = {}): api.AdminSettings {
  return {
    provider: {
      provider: "openrouter",
      base_url: "https://openrouter.ai/api/v1",
      api_key_set: true,
      api_key_hint: KEY_HINT,
    },
    tiers: { standard: { model: "qwen/qwen3.7-plus" }, deep_research: { model: "" } },
    admin_username: "Destin",
    default_monthly_limit_usd: 25,
    user_limits: { analyst1: 5 },
    exempt_users: ["director"],
    ...over,
  };
}

function usage(over: Partial<api.AdminUsage> = {}): api.AdminUsage {
  return {
    month: "2026-07",
    total_usd: 1.23,
    rows: 20,
    rows_with_unknown_cost: 0,
    cached_tokens: 8000,
    tokens_in: 10000,
    by_user: [
      { key: "Destin", cost_usd: 1.0, tokens_in: 8000, tokens_out: 400,
        cached_tokens: 7000, rows: 15, rows_with_unknown_cost: 0 },
      { key: "analyst1", cost_usd: 0.23, tokens_in: 2000, tokens_out: 100,
        cached_tokens: 1000, rows: 5, rows_with_unknown_cost: 0 },
    ],
    by_model: [],
    by_tier: [],
    limits_active: true,
    limits_inactive_reason: null,
    ...over,
  };
}

function corpus(over: Partial<api.AdminCorpus> = {}): api.AdminCorpus {
  return {
    data_dir: "/share/jlbc-insight-data",
    budget_chunks: 7808,
    fiscal_note_chunks: 8438,
    documents: 1770,
    lancedb_bytes: 5_400_000_000,
    dead_version_bytes: 4_100_000_000,
    last_ingest_at: "2026-07-31T11:30:00-07:00",
    queue: { queued: 2, running: 1, failed: 0 },
    ...over,
  };
}

function models(over: Partial<api.ModelCatalog> = {}): api.ModelCatalog {
  return {
    source: "live",
    fetched_at: "2026-07-31T12:00:00-07:00",
    recommended: [
      { id: "qwen/qwen3.7-plus", name: "Qwen3.7 Plus", context_length: 1000000,
        prompt_usd_per_m: 0.32, completion_usd_per_m: 1.28, supports_tools: true,
        available: true, tier_hint: "standard", blurb: "The current default." },
      { id: "deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", context_length: 1048576,
        prompt_usd_per_m: 0.14, completion_usd_per_m: 0.28, supports_tools: true,
        available: true, tier_hint: "standard", blurb: "The cheapest option." },
      { id: "moonshotai/kimi-k3", name: "Kimi K3", context_length: 1048576,
        prompt_usd_per_m: null, completion_usd_per_m: null, supports_tools: true,
        available: false, tier_hint: "deep_research", blurb: "The current default." },
      { id: "z-ai/glm-5.2", name: "GLM 5.2", context_length: 1048576,
        prompt_usd_per_m: 1.12, completion_usd_per_m: 3.52, supports_tools: true,
        available: true, tier_hint: "deep_research", blurb: "Frontier-class, cheaper." },
    ],
    catalog: [],
    note: null,
    ...over,
  };
}

// The server's own S16 copy. Every assertion about tier text reads from THIS
// object rather than repeating the sentence, so an edit to the spec's wording
// can't leave a stale copy passing in here.
const AI_STATUS: api.AiStatus = {
  available: true,
  tiers: {
    standard: {
      label: "Standard",
      default: true,
      description: "for quick lookups — e.g. 'how much did we spend on X last year?'",
      examples: [],
      available: true,
      reason: null,
    },
    deep_research: {
      label: "Deep Research",
      default: false,
      description: "for open-ended, historical, broad-scope research",
      examples: [],
      available: true,
      reason: null,
    },
  },
  user_usage: { month_usd: 1.0, limit_usd: 25, warned: false },
};

function mockAll(over: {
  settings?: api.AdminSettings;
  usage?: api.AdminUsage;
  corpus?: api.AdminCorpus;
  models?: api.ModelCatalog;
  snapshots?: api.Snapshot[];
  notices?: api.Notice[];
  me?: Partial<api.Me>;
} = {}) {
  vi.spyOn(api, "me").mockResolvedValue({
    user: "Destin", is_admin: true, admin_username: "Destin",
    admin_claimable: false, admin_reset_pending: false, ...over.me,
  });
  vi.spyOn(api, "adminSettings").mockResolvedValue(over.settings ?? settings());
  vi.spyOn(api, "adminUsage").mockResolvedValue(over.usage ?? usage());
  vi.spyOn(api, "adminCorpus").mockResolvedValue(over.corpus ?? corpus());
  vi.spyOn(api, "adminModels").mockResolvedValue(over.models ?? models());
  vi.spyOn(api, "adminBackups").mockResolvedValue({ snapshots: over.snapshots ?? [] });
  vi.spyOn(api, "adminNotices").mockResolvedValue({ notices: over.notices ?? [] });
  vi.spyOn(api, "aiStatus").mockResolvedValue(AI_STATUS);
}

afterEach(() => vi.restoreAllMocks());

async function renderAdmin() {
  render(<Admin />);
  await screen.findByTestId("admin-costs");
}

// --- the API key ------------------------------------------------------------

describe("the API key", () => {
  it("renders no key field, only a last-four hint", async () => {
    mockAll();
    await renderAdmin();

    expect(screen.getByTestId("admin-key-hint")).toHaveTextContent(KEY_HINT);
    // Nothing on the page may contain the key itself — the server never sent
    // one, and a field prefilled with it is one screenshot from a leak.
    expect(screen.queryByDisplayValue(/sk-or/)).toBeNull();
    expect(screen.queryByLabelText(/^API key/i)).toBeNull();
  });

  it("sends the __unchanged__ sentinel when the key was never touched", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].api_key).toBe("__unchanged__");
  });

  it("sends a real key once the admin types one", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /replace the key/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), {
      target: { value: "sk-or-v1-new" },
    });
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].api_key).toBe("sk-or-v1-new");
  });

  it("goes back to the sentinel if the admin cancels the edit", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /replace the key/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), { target: { value: "oops" } });
    fireEvent.click(screen.getByRole("button", { name: /keep the saved key/i }));
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].api_key).toBe("__unchanged__");
  });
});

// --- S15 custom endpoint ----------------------------------------------------

describe("the custom endpoint", () => {
  it("states every caveat in the panel, at the moment it is chosen", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByRole("radio", { name: /custom endpoint/i }));

    const caveats = screen.getByTestId("admin-custom-caveats");
    expect(caveats).toHaveTextContent(/spend limits stop being enforced/i);
    expect(caveats).toHaveTextContent(/no model list, no recommendations and no live pricing/i);
    expect(caveats).toHaveTextContent(/must support tool calling/i);
    expect(caveats).toHaveTextContent(/self-support territory/i);
  });

  it("returns to OpenRouter in one click", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByRole("radio", { name: /custom endpoint/i }));
    fireEvent.click(screen.getByRole("button", { name: /go back to openrouter/i }));

    expect(screen.queryByTestId("admin-custom-caveats")).toBeNull();
    expect(screen.getByRole("radio", { name: /openrouter/i })).toBeChecked();
  });

  it("replaces the model picker with a free-text field", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByRole("radio", { name: /custom endpoint/i }));

    const tier = screen.getByTestId("admin-tier-standard");
    expect(within(tier).queryByRole("combobox")).toBeNull();
    expect(within(tier).getByRole("textbox")).toBeInTheDocument();
  });
});

// --- tier copy --------------------------------------------------------------

describe("tier explainers", () => {
  it("renders the server's own sentence, not a copy typed here", async () => {
    mockAll();
    await renderAdmin();

    // Asserted against the object the API returned. If the spec's wording
    // changes server-side, this test follows it automatically.
    expect(screen.getByTestId("admin-tier-standard")).toHaveTextContent(
      AI_STATUS.tiers.standard.description,
    );
    expect(screen.getByTestId("admin-tier-deep_research")).toHaveTextContent(
      AI_STATUS.tiers.deep_research.description,
    );
  });
});

// --- retired models ---------------------------------------------------------

describe("a model the catalog no longer offers", () => {
  it("renders greyed with the reason, and cannot be selected", async () => {
    mockAll();
    await renderAdmin();

    const tier = screen.getByTestId("admin-tier-deep_research");
    const option = within(tier).getByRole("option", {
      name: /kimi k3 — no longer offered by openrouter/i,
    }) as HTMLOptionElement;
    // Kept, not dropped: an admin whose tier names a retired model has to be
    // able to SEE that is what happened.
    expect(option.disabled).toBe(true);
  });

  it("shows a configured model that vanished from the catalog entirely", async () => {
    mockAll({
      settings: settings({
        tiers: { standard: { model: "vendor/gone" }, deep_research: { model: "" } },
      }),
    });
    await renderAdmin();

    expect(screen.getByTestId("admin-tier-standard")).toHaveTextContent(
      /vendor\/gone — no longer offered by OpenRouter/i,
    );
  });
});

// --- costs ------------------------------------------------------------------

describe("the costs panel", () => {
  it("never reports a total that lies by omission", async () => {
    mockAll({ usage: usage({ total_usd: 1.23, rows_with_unknown_cost: 3 }) });
    await renderAdmin();

    expect(screen.getByTestId("admin-total")).toHaveTextContent(
      "at least $1.23 (3 calls of unknown cost)",
    );
  });

  it("shows a plain total when every call has a price", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.getByTestId("admin-total")).toHaveTextContent("$1.23");
    expect(screen.getByTestId("admin-total")).not.toHaveTextContent("at least");
  });

  it("reports the prompt-cache share", async () => {
    mockAll();
    await renderAdmin();
    // 8000 of 10000 input tokens. The one number that reveals a silently
    // broken cache prefix.
    expect(screen.getByTestId("admin-cache")).toHaveTextContent("80%");
  });

  it("says so when limits are not being enforced", async () => {
    mockAll({
      usage: usage({ limits_active: false, limits_inactive_reason: "custom endpoint" }),
    });
    await renderAdmin();
    expect(screen.getByTestId("admin-limits-inactive")).toHaveTextContent(
      /custom endpoint/i,
    );
  });
});

// --- restore ----------------------------------------------------------------

describe("restore", () => {
  const snapshot: api.Snapshot = {
    name: "lancedb-20260731T120000Z.zip",
    created_at: "2026-07-31T12:00:00+00:00",
    bytes: 1_500_000,
  };

  it("requires the word to be typed and names the snapshot's date", async () => {
    mockAll({ snapshots: [snapshot] });
    const restore = vi.spyOn(api, "restoreBackup");
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));

    const confirm = screen.getByTestId("admin-restore-confirm");
    expect(confirm).toHaveTextContent(/Jul 31, 2026/);
    const button = screen.getByRole("button", { name: /restore this snapshot/i });
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restor" },
    });
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restore" },
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(restore).toHaveBeenCalledWith(snapshot.name));
  });

  it("tells the admin plainly that a restart is required", async () => {
    mockAll({ snapshots: [snapshot] });
    vi.spyOn(api, "restoreBackup").mockResolvedValue({
      restored: snapshot.name,
      restart_required: true,
    });
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));
    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restore" },
    });
    fireEvent.click(screen.getByRole("button", { name: /restore this snapshot/i }));

    // Ground truth 10: the handles are resolved at startup, so a page that
    // said "done" without this would claim to be fixed and then serve errors.
    const done = await screen.findByTestId("admin-restore-done");
    expect(done).toHaveTextContent(/reopen JLBC Insight/i);
  });

  it("surfaces the server's refusal when an ingest is running", async () => {
    mockAll({ snapshots: [snapshot] });
    vi.spyOn(api, "restoreBackup").mockRejectedValue(
      new Error("restore: An ingest is running — wait for it to finish, then try again."),
    );
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));
    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restore" },
    });
    fireEvent.click(screen.getByRole("button", { name: /restore this snapshot/i }));

    expect(await screen.findByTestId("admin-restore-error")).toHaveTextContent(
      /An ingest is running/,
    );
  });
});

// --- corpus + notices + gating ---------------------------------------------

describe("the rest of the page", () => {
  it("flags reclaimable space when it dominates the folder", async () => {
    mockAll();
    await renderAdmin();
    // 4.1 GB of a 5.4 GB folder.
    expect(screen.getByTestId("admin-dead-versions")).toHaveTextContent(/3.8 GB/);
  });

  it("stays quiet about reclaimable space when it is noise", async () => {
    mockAll({ corpus: corpus({ lancedb_bytes: 5_000_000, dead_version_bytes: 15_000 }) });
    await renderAdmin();
    expect(screen.queryByTestId("admin-dead-versions")).toBeNull();
  });

  it("says nothing has gone wrong when the notices feed is empty", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.getByTestId("admin-notices")).toHaveTextContent(
      /nothing has gone wrong/i,
    );
  });

  it("lists notices newest first", async () => {
    mockAll({
      notices: [
        { at: "2026-07-30T09:00:00-07:00", kind: "ingest_failed", message: "older" },
        { at: "2026-07-31T09:00:00-07:00", kind: "model_fallback", message: "newer" },
      ],
    });
    await renderAdmin();
    const items = screen.getAllByTestId("admin-notice");
    expect(items[0]).toHaveTextContent("newer");
    expect(items[1]).toHaveTextContent("older");
  });

  it("tells a non-admin who to ask instead of showing an empty page", async () => {
    mockAll({ me: { is_admin: false, admin_username: "Destin" } });
    render(<Admin />);
    expect(await screen.findByText(/limited to Destin/i)).toBeInTheDocument();
    expect(screen.queryByTestId("admin-costs")).toBeNull();
  });

  it("says the admin gate is soft, in the app itself", async () => {
    mockAll();
    await renderAdmin();
    // Spec S11 / plan risk 2: if anyone later mistakes this for security and
    // puts something sensitive behind it, that is a real vulnerability
    // introduced by misreading. The page says what it is.
    expect(screen.getByTestId("admin-transfer")).toHaveTextContent(
      /soft gate, not a lock/i,
    );
  });

  it("names the break-glass reset file", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.getByTestId("admin-transfer")).toHaveTextContent("RESET-ADMIN.txt");
  });

  it("shows the server's sentence when a save is rejected", async () => {
    mockAll();
    vi.spyOn(api, "saveAdminSettings").mockRejectedValue(
      new Error("save settings: A monthly limit can't be negative."),
    );
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-save"));

    expect(await screen.findByTestId("admin-save-error")).toHaveTextContent(
      /can't be negative/,
    );
  });
});
