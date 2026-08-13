import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { Admin } from "./Admin";

// The specs that pin real requirements rather than markup. In order of how
// badly the thing they protect fails when it breaks:
//
//  1. The key field. Empty with a last-four hint; an untouched save sends the
//     "__unchanged__" sentinel. A blanked key looks like "AI Mode randomly
//     stopped working" a week later, with nothing pointing at the cause.
//  2. A custom AI service cannot be saved without prices — that is what
//     eliminated the "unknown cost" state, and with it the silent
//     disabling of every spending limit.
//  3. Tier copy asserted against the string the API returned, never a copy
//     typed into this file — otherwise a spec edit drifts silently.
//  4. A retired model renders unselectable rather than vanishing.
//  5. Restore needs a typed word and names the backup's date.
//  6. Jargon stays out: no token counts, no cache percentages, no
//     "endpoint" in anything a non-technical admin reads.

const KEY_HINT = "…cdef";

function settings(over: Partial<api.AdminSettings> = {}): api.AdminSettings {
  return {
    provider: {
      provider: "openrouter",
      base_url: "https://openrouter.ai/api/v1",
      api_key_set: true,
      api_key_hint: KEY_HINT,
      prompt_usd_per_m: null,
      completion_usd_per_m: null,
    },
    tiers: {
      standard: { model: "qwen/qwen3.7-plus", enabled: true },
      deep_research: { model: "", enabled: false },
    },
    admin_username: "Destin",
    ai_enabled: true,
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
    cached_tokens: 800_000,
    tokens_in: 1_000_000,
    by_user: [
      { key: "Destin", cost_usd: 1.0, tokens_in: 800_000, tokens_out: 400,
        cached_tokens: 700_000, rows: 15, rows_with_unknown_cost: 0 },
      { key: "analyst1", cost_usd: 0.23, tokens_in: 200_000, tokens_out: 100,
        cached_tokens: 100_000, rows: 5, rows_with_unknown_cost: 0 },
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
    ingest_enabled_here: false,
    queue_stalled: false,
    queue_stalled_message: null,
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
        available: true, tier_hint: "standard", blurb: "The current default.",
        max_output_tokens: 131072, is_open_weights: false,
        usd_per_question: 0.0127 ,
        intelligence_index: 39, intelligence_percent: 58, agentic_index: 20.8 },
      { id: "deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash", context_length: 1048576,
        prompt_usd_per_m: 0.14, completion_usd_per_m: 0.28, supports_tools: true,
        available: true, tier_hint: "standard", blurb: "The cheapest option.",
        max_output_tokens: 393216, is_open_weights: true,
        usd_per_question: 0.0049 ,
        intelligence_index: null, intelligence_percent: null, agentic_index: null },
      { id: "moonshotai/kimi-k3", name: "Kimi K3", context_length: 1048576,
        prompt_usd_per_m: null, completion_usd_per_m: null, supports_tools: true,
        available: false, tier_hint: "deep_research", blurb: "The current default.",
        max_output_tokens: null, is_open_weights: true,
        usd_per_question: null ,
        intelligence_index: null, intelligence_percent: null, agentic_index: null },
      { id: "z-ai/glm-5.2", name: "GLM 5.2", context_length: 1048576,
        prompt_usd_per_m: 1.12, completion_usd_per_m: 3.52, supports_tools: true,
        available: true, tier_hint: "deep_research", blurb: "Frontier-class, cheaper.",
        max_output_tokens: 128000, is_open_weights: true,
        usd_per_question: 0.184 ,
        intelligence_index: 51.1, intelligence_percent: 77, agentic_index: 43.1 },
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
  aliases?: api.AdminAliases;
  guidance?: api.AdminGuidance;
  issues?: api.IssuesResponse;
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
  // The three E6 panels fetch for themselves rather than riding the page's
  // settings draft, so the page's own mock set has to cover them too —
  // otherwise every spec in this file makes three real network calls and the
  // page renders three load errors that no assertion here is about. Their
  // behaviour is pinned in their own spec files.
  vi.spyOn(api, "adminAliases").mockResolvedValue(
    over.aliases ?? { added: [], disabled: [], shipped: [], agencies: [], warnings: [] },
  );
  vi.spyOn(api, "adminGuidance").mockResolvedValue(
    over.guidance ?? { text: "", max_bytes: 8192, edited_by: "", edited_at: "" },
  );
  vi.spyOn(api, "issues").mockResolvedValue(
    over.issues ?? { reports: [], unresolved: 0, is_admin: true },
  );
}

afterEach(() => vi.restoreAllMocks());

async function renderAdmin() {
  render(<Admin />);
  await screen.findByTestId("admin-costs");
}

/** Open a collapsible card by its title. Clicking the header is what a
 *  person does, and unlike <details> the body genuinely is not in the DOM
 *  until then — so these specs also prove the content is reachable. */
function open(title: RegExp) {
  const card = screen
    .getAllByRole("heading", { level: 3 })
    .find((h) => title.test(h.textContent ?? ""));
  if (!card) throw new Error(`no card titled ${title}`);
  fireEvent.click(card.closest("button")!);
}

// --- the API key ------------------------------------------------------------

describe("the API key", () => {
  it("renders no key field, only a last-four hint", async () => {
    mockAll();
    await renderAdmin();

    expect(screen.getByTestId("admin-key-card")).toHaveTextContent(KEY_HINT);
    // Nothing on the page may contain the key itself — the server never sent
    // one, and a field prefilled with it is one screenshot from a leak.
    expect(screen.queryByDisplayValue(/sk-or/)).toBeNull();
    expect(screen.queryByLabelText(/^API key/i)).toBeNull();
  });

  it("sends the __unchanged__ sentinel when the key was never touched", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    // The real scenario: an admin edits something ELSE and saves. That is
    // the save that used to blank the key.
    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].api_key).toBe("__unchanged__");
  });

  it("sends a real key once the admin types one", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /^replace$/i }));
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

    fireEvent.click(screen.getByRole("button", { name: /^replace$/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), { target: { value: "oops" } });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    // Another edit, so there is something to save at all — cancelling the
    // key must not leave it pending on its own.
    fireEvent.click(screen.getByTestId("admin-tier-toggle-standard"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].api_key).toBe("__unchanged__");
  });
});

// --- a custom AI service ----------------------------------------------------

describe("a custom AI service", () => {
  it("states what changes, at the moment it is chosen", async () => {
    mockAll();
    await renderAdmin();
    open(/which ai service/i);

    fireEvent.click(screen.getByRole("radio", { name: /something else/i }));

    const caveats = screen.getByTestId("admin-custom-caveats");
    expect(caveats).toHaveTextContent(/tell the app what your service charges/i);
    expect(caveats).toHaveTextContent(/no model list and no live prices/i);
    expect(caveats).toHaveTextContent(/must support tool calling/i);
  });

  it("asks for both prices, which is what makes costs knowable", async () => {
    mockAll();
    await renderAdmin();
    open(/which ai service/i);

    fireEvent.click(screen.getByRole("radio", { name: /something else/i }));

    // THE change that removed "unknown cost". Without these two figures the
    // app can't price a request, which used to mean spending was invisible
    // and every limit silently stopped being enforced.
    const prices = screen.getByTestId("admin-custom-prices");
    expect(within(prices).getByLabelText(/input tokens/i)).toBeInTheDocument();
    expect(within(prices).getByLabelText(/output tokens/i)).toBeInTheDocument();
  });

  it("sends the prices it was given", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();
    open(/which ai service/i);
    fireEvent.click(screen.getByRole("radio", { name: /something else/i }));

    fireEvent.change(screen.getByLabelText(/input tokens/i), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/output tokens/i), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].provider).toMatchObject({
      provider: "custom",
      prompt_usd_per_m: 2,
      completion_usd_per_m: 10,
    });
  });

  it("returns to OpenRouter in one click", async () => {
    mockAll();
    await renderAdmin();
    open(/which ai service/i);
    fireEvent.click(screen.getByRole("radio", { name: /something else/i }));

    fireEvent.click(screen.getByRole("button", { name: /go back to openrouter/i }));

    expect(screen.queryByTestId("admin-custom-caveats")).toBeNull();
    expect(screen.getByRole("radio", { name: /openrouter/i })).toBeChecked();
  });

  it("replaces the model picker with a free-text field", async () => {
    mockAll();
    await renderAdmin();
    open(/which ai service/i);

    fireEvent.click(screen.getByRole("radio", { name: /something else/i }));

    const tier = screen.getByTestId("admin-tier-standard");
    expect(within(tier).queryByRole("combobox")).toBeNull();
    expect(within(tier).getByRole("textbox")).toBeInTheDocument();
  });

  it("says the totals are worked out from those prices", async () => {
    mockAll({
      settings: settings({
        provider: {
          provider: "custom", base_url: "https://example.test/v1",
          api_key_set: true, api_key_hint: KEY_HINT,
          prompt_usd_per_m: 2, completion_usd_per_m: 10,
        },
      }),
    });
    await renderAdmin();
    // Honest: an estimate from admin-entered rates is not the provider's own
    // exact figure, and the page says which it is looking at.
    expect(screen.getByTestId("admin-costs")).toHaveTextContent(
      /worked out from the prices you entered/i,
    );
  });
});

// --- tier copy --------------------------------------------------------------

describe("answer mode explainers", () => {
  it("renders the server's own sentence, not a copy typed here", async () => {
    mockAll();
    await renderAdmin();

    expect(screen.getByTestId("admin-tier-standard")).toHaveTextContent(
      AI_STATUS.tiers.standard.description,
    );
    expect(screen.getByTestId("admin-tier-deep_research")).toHaveTextContent(
      AI_STATUS.tiers.deep_research.description,
    );
  });
});

// --- retired models ---------------------------------------------------------

describe("a model that is no longer offered", () => {
  it("renders unselectable rather than vanishing", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-tier-toggle-deep_research"));
    const tier = screen.getByTestId("admin-tier-deep_research");
    fireEvent.click(within(tier).getByRole("button", { name: /model for deep research/i }));

    const row = screen.getByRole("option", { name: /kimi k3/i });
    // Kept, not dropped: an admin whose mode names a retired model has to be
    // able to SEE that is what happened.
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row).toHaveTextContent(/no longer available/i);
  });

  it("shows a configured model that vanished from the list entirely", async () => {
    mockAll({
      settings: settings({
        tiers: {
          standard: { model: "vendor/gone", enabled: true },
          deep_research: { model: "", enabled: false },
        },
      }),
    });
    await renderAdmin();

    const tier = screen.getByTestId("admin-tier-standard");
    // Visible on the closed control — an admin must not have to open a menu
    // to discover their configured model is gone.
    expect(tier).toHaveTextContent("vendor/gone");
    expect(tier).toHaveTextContent(/no longer available/i);
  });
});

// --- costs ------------------------------------------------------------------

describe("the spending panel", () => {
  it("shows a plain total", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.getByTestId("admin-total")).toHaveTextContent("$1.23");
    // No more "at least $X (N calls of unknown cost)" welded into the
    // headline — no new request can be unpriced.
    expect(screen.getByTestId("admin-total")).not.toHaveTextContent("at least");
  });

  it("footnotes older unpriced requests instead of mangling the total", async () => {
    mockAll({ usage: usage({ total_usd: 1.23, rows_with_unknown_cost: 3 }) });
    await renderAdmin();

    expect(screen.getByTestId("admin-total")).toHaveTextContent("$1.23");
    // Still said, because a total that silently omits rows understates what
    // was spent — but said underneath, in words.
    expect(screen.getByTestId("admin-unpriced-note")).toHaveTextContent(
      /3 older requests aren't counted here/i,
    );
  });

  it("shows no footnote when there is nothing to footnote", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.queryByTestId("admin-unpriced-note")).toBeNull();
  });

  it("says nothing about caching when caching is working", async () => {
    mockAll();
    await renderAdmin();
    // A percentage a non-technical admin cannot act on is noise, and noise
    // costs attention the real numbers need.
    expect(screen.queryByTestId("admin-cache-warning")).toBeNull();
    expect(screen.getByTestId("admin-costs")).not.toHaveTextContent(/cach/i);
  });

  it("warns in plain words when caching has actually broken", async () => {
    mockAll({ usage: usage({ cached_tokens: 10_000, tokens_in: 1_000_000 }) });
    await renderAdmin();

    const warning = screen.getByTestId("admin-cache-warning");
    expect(warning).toHaveTextContent(/costs are running higher/i);
    // No jargon in the warning either — the admin can't fix it, they can
    // only report it.
    expect(warning).not.toHaveTextContent(/token|prefix|prompt cach/i);
  });

  it("does not cry wolf on a quiet month", async () => {
    mockAll({ usage: usage({ cached_tokens: 0, tokens_in: 5_000, rows: 2 }) });
    await renderAdmin();
    expect(screen.queryByTestId("admin-cache-warning")).toBeNull();
  });

  it("breaks spending down without a token column", async () => {
    mockAll();
    await renderAdmin();
    open(/who spent what/i);

    const table = screen.getByTestId("admin-usage-table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Person", "Spent", "Requests"]);
  });

  it("says plainly when nobody is capped", async () => {
    mockAll({
      usage: usage({ limits_active: false, limits_inactive_reason: "custom endpoint" }),
    });
    await renderAdmin();
    expect(screen.getByTestId("admin-limits-inactive")).toHaveTextContent(
      /nobody is capped right now/i,
    );
  });
});

// --- restore ----------------------------------------------------------------

describe("which computer processes uploads", () => {
  // The per-machine switch defaults to OFF because one bundle is installed
  // on all ~20 office PCs. That default re-creates the failure the
  // one-bundle decision was made to avoid — uploads queue on the share and
  // nothing drains them — so the warning below is the other half of the fix,
  // not decoration.

  it("warns when uploads are waiting and nothing will process them", async () => {
    mockAll({
      corpus: corpus({
        queue: { queued: 3, running: 0, failed: 0 },
        ingest_enabled_here: false,
        queue_stalled: true,
        queue_stalled_message:
          "Uploads are waiting and no computer is set to process them. Open " +
          "JLBC Insight on the computer that should do this work, go to " +
          'Admin → Corpus, and turn on "Process uploads on this computer".',
      }),
    });
    await renderAdmin();

    const warning = screen.getByTestId("admin-queue-stalled");
    expect(warning).toHaveTextContent(/no computer is set to process them/i);
    // An alert, not a paragraph: this is the one thing on the page that
    // means work is silently going nowhere.
    expect(warning).toHaveAttribute("role", "alert");
  });

  it("stays quiet when the queue is empty", async () => {
    // Nineteen of the twenty office PCs sit exactly like this all day. A
    // warning they all see is a warning nobody reads.
    mockAll({ corpus: corpus({ ingest_enabled_here: false, queue_stalled: false }) });
    await renderAdmin();

    expect(screen.queryByTestId("admin-queue-stalled")).toBeNull();
  });

  it("turns this computer on and says a restart is needed", async () => {
    mockAll({ corpus: corpus({ ingest_enabled_here: false }) });
    const set = vi.spyOn(api, "adminSetMachineIngest").mockResolvedValue({
      ingest_enabled_here: true,
      message: "This computer will process uploads after JLBC Insight is restarted here.",
    });
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ingest-toggle"));

    await waitFor(() => expect(set).toHaveBeenCalledWith(true));
    await waitFor(() =>
      expect(screen.getByTestId("admin-ingest-message")).toHaveTextContent(
        /restarted/i,
      ),
    );
  });

  it("shows the switch as on where it is on", async () => {
    mockAll({ corpus: corpus({ ingest_enabled_here: true }) });
    await renderAdmin();

    expect(screen.getByTestId("admin-ingest-toggle")).toBeChecked();
  });

  it("surfaces a failure instead of looking like it worked", async () => {
    mockAll({ corpus: corpus({ ingest_enabled_here: false }) });
    vi.spyOn(api, "adminSetMachineIngest").mockRejectedValue(
      new Error("Couldn't write the setting for this computer."),
    );
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ingest-toggle"));

    await waitFor(() =>
      expect(screen.getByTestId("admin-ingest-message")).toHaveTextContent(
        /couldn't write/i,
      ),
    );
  });
});

describe("restore", () => {
  const snapshot: api.Snapshot = {
    name: "lancedb-20260731T120000Z.zip",
    created_at: "2026-07-31T12:00:00+00:00",
    bytes: 1_500_000,
  };

  it("requires the word to be typed and names the backup's date", async () => {
    mockAll({ snapshots: [snapshot] });
    const restore = vi.spyOn(api, "restoreBackup");
    await renderAdmin();
    open(/^backups$/i);

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));

    const confirm = screen.getByTestId("admin-restore-confirm");
    expect(confirm).toHaveTextContent(/Jul 31, 2026/);
    const button = screen.getByRole("button", { name: /restore this backup/i });
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
    open(/^backups$/i);

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));
    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restore" },
    });
    fireEvent.click(screen.getByRole("button", { name: /restore this backup/i }));

    // Ground truth 10: the handles are resolved at startup, so a page that
    // said "done" without this would claim to be fixed and then serve errors.
    const done = await screen.findByTestId("admin-restore-done");
    expect(done).toHaveTextContent(/open JLBC Insight again/i);
  });

  it("surfaces the server's refusal when an ingest is running", async () => {
    mockAll({ snapshots: [snapshot] });
    vi.spyOn(api, "restoreBackup").mockRejectedValue(
      new Error("restore: An ingest is running — wait for it to finish, then try again."),
    );
    await renderAdmin();
    open(/^backups$/i);

    fireEvent.click(screen.getByRole("button", { name: /restore…/i }));
    fireEvent.change(screen.getByLabelText(/type restore to confirm/i), {
      target: { value: "restore" },
    });
    fireEvent.click(screen.getByRole("button", { name: /restore this backup/i }));

    expect(await screen.findByTestId("admin-restore-error")).toHaveTextContent(
      /An ingest is running/,
    );
  });
});

// --- grouping and jargon ----------------------------------------------------

describe("the page's shape", () => {
  it("keeps rarely-used controls behind a labelled summary", async () => {
    mockAll();
    await renderAdmin();

    // Each of these says what is inside, so an admin can find it by reading
    // rather than by opening everything.
    for (const id of ["admin-breakdown", "admin-limits", "admin-service", "admin-backups",
                      "admin-transfer", "admin-locations"]) {
      expect(screen.getByTestId(id)).toHaveAttribute("data-open", "false");
    }
  });

  it("summarises spending limits without being opened", async () => {
    mockAll();
    await renderAdmin();
    expect(screen.getByTestId("admin-limits")).toHaveTextContent(
      /\$25 a month each, 1 with their own/,
    );
  });

  it("opens the AI service section when it is not the standard one", async () => {
    mockAll({
      settings: settings({
        provider: {
          provider: "custom", base_url: "https://example.test/v1",
          api_key_set: true, api_key_hint: KEY_HINT,
          prompt_usd_per_m: 2, completion_usd_per_m: 10,
        },
      }),
    });
    await renderAdmin();
    // A non-default setup is worth seeing without hunting for it.
    expect(screen.getByTestId("admin-service")).toHaveAttribute("data-open", "true");
  });

  it("shows no 'needs a look' section when nothing is wrong", async () => {
    mockAll();
    await renderAdmin();
    // A panel that is present every day gets scrolled past, which is the
    // habit that makes it useless on the day it matters.
    expect(screen.queryByTestId("admin-notices")).toBeNull();
  });

  it("puts problems first when there are any", async () => {
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
    const main = screen.getByTestId("admin");
    // The page is function groups now (spec E6), so the first heading is the
    // group label and the notices panel is the first thing inside it. Both
    // are asserted: "problems first" is a claim about the whole page, and it
    // would still be satisfiable by a group whose first panel was something
    // else.
    const headings = within(main).getAllByRole("heading", { level: 2 });
    expect(headings[0]).toHaveTextContent(/needs attention/i);
    expect(headings[1]).toHaveTextContent(/needs a look/i);
  });

  it("labels multi-panel groups, in the order an admin needs them, and drops the label from single-panel groups", async () => {
    mockAll();
    const { container } = render(<Admin />);
    await screen.findByTestId("admin-costs");

    // Read off the rendered page by the group label's own class, not by
    // matching text: two panels carry a heading identical to the group they
    // sit in ("AI Mode", "Spending"), so a text filter would count those too.
    //
    // Task 10 fix pass 2 (Destin's call): "Spending" and "Access & files"
    // each hold exactly one panel, and that panel already carries the same
    // heading — so those two groups render with NO `.adm-group-title` at
    // all now. This assertion is exact-array, not "contains": it fails if
    // the order changes, if a surviving label goes missing, or if either
    // single-panel group's label comes back.
    const groups = [...container.querySelectorAll(".adm-group-title")].map(
      (h) => h.textContent,
    );
    expect(groups).toEqual(["Needs attention", "AI Mode", "Search & documents"]);
  });

  it("keeps developer vocabulary off the page", async () => {
    mockAll();
    await renderAdmin();

    const text = screen.getByTestId("admin").textContent ?? "";
    // Words a fiscal analyst has no reason to know. "tokens" survives in
    // exactly one place — the custom-service price form, where it is what
    // the vendor's own pricing page says — and that section is closed here.
    for (const jargon of ["endpoint", "corpus", "chunk", "prompt caching", "catalog", "tier"]) {
      expect(text.toLowerCase()).not.toContain(jargon);
    }
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
    open(/who can open this page/i);
    // Plan risk 2: if anyone later mistakes this for security and puts
    // something sensitive behind it, that is a real vulnerability introduced
    // by misreading. The page says what it is.
    expect(screen.getByTestId("admin-transfer")).toHaveTextContent(
      /soft gate, not a lock/i,
    );
  });

  it("names the break-glass reset file", async () => {
    mockAll();
    await renderAdmin();
    open(/who can open this page/i);
    expect(screen.getByTestId("admin-transfer")).toHaveTextContent("RESET-ADMIN.txt");
  });

  it("shows the server's sentence when a save is rejected", async () => {
    mockAll();
    vi.spyOn(api, "saveAdminSettings").mockRejectedValue(
      new Error("save settings: A monthly limit can't be negative."),
    );
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByTestId("admin-save"));

    expect(await screen.findByTestId("admin-save-error")).toHaveTextContent(
      /can't be negative/,
    );
  });
});

// --- the AI Mode toggle chain -----------------------------------------------
// AI Mode [off] → nothing · [on] → Key · key added → per-mode switches →
// each switch → its model picker. Everything below a switch is genuinely
// ABSENT until relevant, not present-but-greyed: a disabled picker above an
// empty key field invites an admin to try the picker and conclude the page
// is broken.

describe("the AI Mode toggle chain", () => {
  const noKey = () =>
    settings({
      ai_enabled: false,
      provider: {
        provider: "openrouter", base_url: "https://openrouter.ai/api/v1",
        api_key_set: false, api_key_hint: "",
        prompt_usd_per_m: null, completion_usd_per_m: null,
      },
      tiers: {
        standard: { model: "", enabled: false },
        deep_research: { model: "", enabled: false },
      },
    });

  it("shows nothing but the switch while AI Mode is off", async () => {
    mockAll({ settings: noKey() });
    await renderAdmin();

    expect(screen.getByTestId("admin-ai-toggle")).not.toBeChecked();
    expect(screen.queryByTestId("admin-key-card")).toBeNull();
    expect(screen.queryByTestId("admin-tier-standard")).toBeNull();
    expect(screen.queryByTestId("admin-limits")).toBeNull();
    expect(screen.queryByTestId("admin-service")).toBeNull();
  });

  it("switching it on surfaces the key flow, and only that", async () => {
    mockAll({ settings: noKey() });
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));

    expect(screen.getByTestId("admin-key-card")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a key/i })).toBeInTheDocument();
    // No answer modes yet — there is nothing to run them with.
    expect(screen.queryByTestId("admin-tier-standard")).toBeNull();
    expect(screen.getByTestId("admin-needs-key")).toHaveTextContent(
      /add a key to choose which models/i,
    );
  });

  it("adding a key surfaces a switch per answer mode", async () => {
    mockAll({ settings: noKey() });
    await renderAdmin();
    fireEvent.click(screen.getByTestId("admin-ai-toggle"));

    fireEvent.click(screen.getByRole("button", { name: /add a key/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), {
      target: { value: "sk-or-v1-typed" },
    });

    expect(screen.getByTestId("admin-tier-standard")).toBeInTheDocument();
    expect(screen.getByTestId("admin-tier-deep_research")).toBeInTheDocument();
    expect(screen.getByTestId("admin-tier-toggle-standard")).not.toBeChecked();
    // Still no model picker — each mode is switched on individually.
    expect(
      within(screen.getByTestId("admin-tier-standard")).queryByRole("combobox"),
    ).toBeNull();
  });

  it("switching an answer mode on unlocks its model picker", async () => {
    mockAll({ settings: noKey() });
    await renderAdmin();
    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /add a key/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), {
      target: { value: "sk-or-v1-typed" },
    });

    fireEvent.click(screen.getByTestId("admin-tier-toggle-standard"));

    expect(screen.getByTestId("admin-picker-standard")).toBeInTheDocument();
    // Only the mode that was switched on.
    expect(screen.queryByTestId("admin-picker-deep_research")).toBeNull();
  });

  it("switching a mode off keeps the model it was using", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-tier-toggle-standard"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    // Turning a mode back on must not be a fresh decision — the whole
    // reason `enabled` is a setting rather than "blank the model".
    expect(save.mock.calls[0][0].tiers?.standard).toEqual({
      model: "qwen/qwen3.7-plus",
      enabled: false,
    });
  });

  it("sends the master switch as a real setting", async () => {
    mockAll();
    const save = vi.spyOn(api, "saveAdminSettings").mockResolvedValue(settings());
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    // Not "delete the key" — an admin pausing AI Mode for a week must not
    // have to re-enter it afterwards.
    expect(save.mock.calls[0][0].ai_enabled).toBe(false);
    expect(save.mock.calls[0][0].api_key).toBe("__unchanged__");
  });

  it("uses switches and cards, with no outline-tree markup left", async () => {
    mockAll();
    const { container } = render(<Admin />);
    await screen.findByTestId("admin-costs");

    // The "fingernail" — a nested <details> rendering as a thin rule and a
    // caret — is gone entirely; grouping is cards and pills now.
    expect(container.querySelectorAll("details")).toHaveLength(0);
    expect(container.querySelectorAll(".adm-card").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".adm-toggle").length).toBeGreaterThan(0);
  });
});

// --- the save bar -----------------------------------------------------------
// It replaced a "Save changes" button parked in the gap between the AI Mode
// card and the Documents card. Both of Destin's complaints get a spec: it was
// unclear which menu it belonged to, and it never said what needed saving.

describe("the save bar", () => {
  it("does not exist when there is nothing to save", async () => {
    mockAll();
    await renderAdmin();
    // The old button was always present, always identical, attached to no
    // card — which is what made "which menu is this for?" a fair question.
    expect(screen.queryByTestId("admin-savebar")).toBeNull();
    expect(screen.queryByTestId("admin-save")).toBeNull();
  });

  it("appears as soon as something changes, and names it", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-tier-toggle-standard"));

    const bar = screen.getByTestId("admin-savebar");
    expect(bar).toHaveTextContent("1 unsaved change");
    expect(screen.getByTestId("admin-savebar-list")).toHaveTextContent(
      "Standard switched off",
    );
  });

  it("uses the answer mode's own label, not the field name", async () => {
    mockAll();
    await renderAdmin();
    open(/which ai service/i);

    fireEvent.click(screen.getByTestId("admin-tier-toggle-deep_research"));

    // "Deep Research", from /api/ai/status — never `tiers.deep_research`.
    expect(screen.getByTestId("admin-savebar-list")).toHaveTextContent(
      "Deep Research switched on",
    );
  });

  it("lists several changes in a sentence a person reads", async () => {
    mockAll();
    await renderAdmin();

    // Order matters here for a real reason: switching AI Mode off hides
    // everything beneath it, so the mode and limit edits happen first.
    fireEvent.click(screen.getByTestId("admin-tier-toggle-standard"));
    open(/spending limits/i);
    fireEvent.change(screen.getByLabelText(/each person, per month/i), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByTestId("admin-ai-toggle"));

    expect(screen.getByTestId("admin-savebar")).toHaveTextContent("3 unsaved changes");
    expect(screen.getByTestId("admin-savebar-list")).toHaveTextContent(
      "AI Mode switched off, Standard switched off and the monthly limit",
    );
  });

  it("says a new key is pending without showing it", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByRole("button", { name: /^replace$/i }));
    fireEvent.change(screen.getByLabelText(/API key/i), {
      target: { value: "sk-or-v1-secret" },
    });

    const bar = screen.getByTestId("admin-savebar");
    expect(bar).toHaveTextContent("a new key");
    // The bar is on screen while an admin might be sharing it.
    expect(bar.textContent).not.toContain("sk-or-v1-secret");
  });

  it("discards every pending edit at once", async () => {
    mockAll();
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));

    // Back to what is on disk, and the bar goes with it.
    expect(screen.queryByTestId("admin-savebar")).toBeNull();
    expect(screen.getByTestId("admin-ai-toggle")).toBeChecked();
  });

  it("goes away once the save lands", async () => {
    mockAll();
    vi.spyOn(api, "saveAdminSettings").mockResolvedValue(
      settings({ ai_enabled: false }),
    );
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await screen.findByTestId("admin-saved");
    expect(screen.queryByTestId("admin-savebar")).toBeNull();
  });

  it("keeps the changes listed when the server refuses", async () => {
    mockAll();
    vi.spyOn(api, "saveAdminSettings").mockRejectedValue(
      new Error("save settings: A monthly limit can't be negative."),
    );
    await renderAdmin();

    fireEvent.click(screen.getByTestId("admin-ai-toggle"));
    fireEvent.click(screen.getByTestId("admin-save"));

    await screen.findByTestId("admin-save-error");
    // The edits are still pending, so the list must still be there to say
    // so — clearing it would look like the save had worked.
    expect(screen.getByTestId("admin-savebar-list")).toHaveTextContent(
      "AI Mode switched off",
    );
  });
});
