import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { Settings } from "./Settings";

// Settings is every analyst's page, not an admin surface. The property worth
// protecting: every sentence about limits and availability is the SERVER'S,
// not a re-typed copy. If this page invented its own "you're over your limit"
// wording, the office would have two of them — and the one people quote back
// would be whichever they happened to read first.

const LEDGER_BLOCKED =
  "You've reached your monthly AI usage limit ($5.00) — ask Destin to raise it.";

function me(over: Partial<api.Me> = {}): api.Me {
  return {
    user: "analyst1",
    is_admin: false,
    admin_username: "Destin",
    admin_claimable: false,
    admin_reset_pending: false,
    ...over,
  };
}

function myUsage(over: Partial<api.MyUsage> = {}): api.MyUsage {
  return {
    month: "2026-07",
    month_usd: 2.5,
    limit_usd: 5,
    status: "allowed",
    message: null,
    reason: null,
    rows_with_unknown_cost: 0,
    ...over,
  };
}

function aiStatus(over: Partial<api.AiStatus> = {}): api.AiStatus {
  return {
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
    },
    user_usage: { month_usd: 2.5, limit_usd: 5, warned: false },
    ...over,
  };
}

function mockAll(over: {
  me?: Partial<api.Me>;
  usage?: api.MyUsage;
  status?: api.AiStatus;
} = {}) {
  vi.spyOn(api, "me").mockResolvedValue(me(over.me));
  vi.spyOn(api, "myUsage").mockResolvedValue(over.usage ?? myUsage());
  vi.spyOn(api, "aiStatus").mockResolvedValue(over.status ?? aiStatus());
  vi.spyOn(api, "adminCorpus").mockResolvedValue({
    data_dir: "/share/jlbc-insight-data",
    budget_chunks: 1, fiscal_note_chunks: 1, documents: 1,
    lancedb_bytes: 1, dead_version_bytes: null, last_ingest_at: null,
    queue: { queued: 0, running: 0, failed: 0 },
    ingest_enabled_here: false,
    queue_stalled: false,
    queue_stalled_message: null,
  });
}

afterEach(() => vi.restoreAllMocks());

describe("your own usage", () => {
  it("shows the month's spend against the limit, with a meter", async () => {
    mockAll();
    render(<Settings />);

    expect(await screen.findByTestId("settings-total")).toHaveTextContent("$2.50 of $5.00");
    expect(screen.getByTestId("settings-meter")).toHaveAttribute("aria-valuenow", "50");
  });

  it("renders the ledger's exact blocked sentence, not a re-typed one", async () => {
    mockAll({
      usage: myUsage({ status: "blocked", month_usd: 5, message: LEDGER_BLOCKED }),
    });
    render(<Settings />);

    const message = await screen.findByTestId("settings-limit-message");
    expect(message).toHaveTextContent(LEDGER_BLOCKED);
    // An analyst reading this needs to know they can still work.
    expect(screen.getByTestId("settings-usage")).toHaveTextContent(
      /Searching.*cost nothing and are never blocked/is,
    );
  });

  it("renders the ledger's warn sentence at the boundary", async () => {
    const warn = "You've used $4.50 of your $5.00 monthly AI usage limit (90%).";
    mockAll({ usage: myUsage({ status: "warn", month_usd: 4.5, message: warn }) });
    render(<Settings />);
    expect(await screen.findByTestId("settings-limit-message")).toHaveTextContent(warn);
  });

  it("footnotes older unpriced requests instead of mangling the total", async () => {
    mockAll({
      usage: myUsage({ month_usd: 1.0, limit_usd: null, rows_with_unknown_cost: 2 }),
    });
    render(<Settings />);
    // Since custom-service pricing became mandatory (2026-07-31) no new
    // request can be unpriced, so the headline is a plain figure. Older
    // rows still get said — a total that silently omits them understates
    // what was spent — but underneath, in words.
    expect(await screen.findByTestId("settings-total")).toHaveTextContent("$1.00");
    expect(screen.getByTestId("settings-unpriced-note")).toHaveTextContent(
      /2 older requests aren't counted here/i,
    );
  });

  it("explains an exemption rather than showing an empty limit", async () => {
    mockAll({ usage: myUsage({ limit_usd: null, reason: "exempt" }) });
    render(<Settings />);
    expect(await screen.findByTestId("settings-no-limit")).toHaveTextContent(
      /no spending limit/i,
    );
  });

  it("explains an unenforced limit in terms the reader can act on", async () => {
    mockAll({ usage: myUsage({ limit_usd: null, reason: "custom endpoint" }) });
    render(<Settings />);
    // "custom endpoint" means nothing to an analyst. What they can do with
    // this is know it is their admin's to fix.
    const note = await screen.findByTestId("settings-no-limit");
    expect(note).toHaveTextContent(/your admin hasn't told the app what/i);
    expect(note.textContent?.toLowerCase()).not.toContain("endpoint");
  });
});

describe("AI Mode availability", () => {
  it("shows the server's own reason when it is unavailable", async () => {
    mockAll({
      status: aiStatus({ available: false, reason: "no API key configured" }),
    });
    render(<Settings />);
    // The exact string from `ai_available()`. Inventing a friendlier one here
    // would mean the app has two explanations for one condition.
    expect(await screen.findByTestId("settings-ai-reason")).toHaveTextContent(
      "no API key configured",
    );
  });

  it("shows the second reason string just as verbatim", async () => {
    mockAll({
      status: aiStatus({
        available: false,
        reason: "no model configured — ask the admin",
      }),
    });
    render(<Settings />);
    expect(await screen.findByTestId("settings-ai-reason")).toHaveTextContent(
      "no model configured — ask the admin",
    );
  });

  it("renders the tier explainer from the API, not a local copy", async () => {
    const status = aiStatus();
    mockAll({ status });
    render(<Settings />);
    expect(await screen.findByTestId("settings-ai")).toHaveTextContent(
      status.tiers.standard.description,
    );
  });
});

describe("who you are and where things live", () => {
  it("shows the username the admin will need, and who the admin is", async () => {
    mockAll();
    render(<Settings />);
    const you = await screen.findByTestId("settings-you");
    // The Windows username, displayed precisely so an admin never has to guess
    // it — a guessed username is the most common way admin transfer locks
    // everyone out.
    expect(you).toHaveTextContent("analyst1");
    expect(you).toHaveTextContent(/matched exactly/i);
    expect(you).toHaveTextContent("Destin");
  });

  it("carries the Invariant 8 public-record reminder", async () => {
    mockAll();
    render(<Settings />);
    const note = await screen.findByTestId("settings-public-record");
    expect(note).toHaveTextContent(/public-record documents only/i);
    expect(note).toHaveTextContent(/data-retention practices are not under our control/i);
  });

  it("does not ask an analyst's browser for the admin-only corpus endpoint", async () => {
    mockAll();
    render(<Settings />);
    await screen.findByTestId("settings-you");
    // It would 403. Calling it anyway would put a red error in every
    // analyst's console on a page that is working perfectly.
    expect(api.adminCorpus).not.toHaveBeenCalled();
  });

  it("shows the data folder to an admin", async () => {
    mockAll({ me: { is_admin: true, user: "Destin", admin_username: "Destin" } });
    render(<Settings />);
    expect(await screen.findByText("/share/jlbc-insight-data")).toBeInTheDocument();
  });
});

describe("the claim banner", () => {
  it("does not appear once an admin exists", async () => {
    mockAll();
    render(<Settings />);
    await screen.findByTestId("settings-you");
    expect(screen.queryByTestId("settings-claim")).toBeNull();
  });

  it("offers the claim on a fresh install", async () => {
    mockAll({ me: { admin_claimable: true, admin_username: "" } });
    vi.spyOn(api, "claimAdmin").mockResolvedValue({ admin_username: "analyst1" });
    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: /claim admin as analyst1/i }));

    expect(await screen.findByTestId("settings-claimed")).toHaveTextContent(
      /you are now the admin/i,
    );
  });

  it("warns that claiming uses up a pending reset file", async () => {
    mockAll({ me: { admin_claimable: true, admin_reset_pending: true } });
    render(<Settings />);
    // Nobody should claim by accident and then wonder where their reset went.
    expect(await screen.findByTestId("settings-reset-pending")).toHaveTextContent(
      /will use it up/i,
    );
  });

  it("surfaces the server's refusal if someone claimed first", async () => {
    mockAll({ me: { admin_claimable: true } });
    vi.spyOn(api, "claimAdmin").mockRejectedValue(
      new Error("claim admin: An admin is already configured."),
    );
    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: /claim admin/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/already configured/i),
    );
  });
});
