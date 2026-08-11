// AI Mode as its own destination (2026-07-31), with the corpus picked inside it.
//
// Most of what is asserted here was asserted before against the per-page AI Mode
// toggle (Search.ai-mode.test.tsx / FiscalNotes.ai-mode.test.tsx): the tier
// control reads its copy off the wire, the fiscal-note corpus gets no budget
// starter chips, a 409 is not an error, an over-limit `_error` renders verbatim.
// Those behaviours did not change — only where they live — so the specs moved
// rather than being deleted.
//
// The one genuinely NEW property, and the reason this file exists at all, is
// "switching corpus starts a new conversation". `useChat` reads its corpus only
// when it creates a conversation, and then holds that conversation_id for the
// life of the hook — so without a remount an analyst's fiscal-note question
// would be answered out of the BUDGET corpus, cited and confident. The page
// remounts via key={corpus}; the two specs below are what stop that mechanism
// from being "simplified" away.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Ai } from "./Ai";
import * as api from "../api";
import { AiSessionProvider } from "../chat/ai-session";
import { __resetAiStatusCache } from "../chat/use-ai-status";
import {
  AI_STATUS,
  sseResponse,
  stubConversationFetch,
  stubScrollIntoView,
} from "./ai-test-fixtures";

function mountAi(status = AI_STATUS) {
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter>
      <AiSessionProvider>
        <Ai />
      </AiSessionProvider>
    </MemoryRouter>,
  );
}

/** The composer inside AiModePanel (MessageInput's textarea). */
const composer = () => screen.getByRole("textbox");

/** Send a question the way the analyst does: type, then Enter. */
async function ask(text: string) {
  const box = composer();
  fireEvent.change(box, { target: { value: text } });
  await act(async () => {
    fireEvent.keyDown(box, { key: "Enter" });
  });
}

/** Open the ask bar's tools menu. Both settings live behind it now, so every
 *  spec that used to click a segmented pill has to open this first. */
function openTools() {
  fireEvent.click(screen.getByTestId("ask-tools-button"));
}

/** A toggle inside the tools menu, opening the menu if it is shut. */
function tool(id: "tool-deep-research" | "tool-fiscal-notes") {
  if (!screen.queryByTestId(id)) openTools();
  return screen.getByTestId(id);
}

/** Flip a toggle the way an analyst does: open the menu, click the row. */
function toggle(id: "tool-deep-research" | "tool-fiscal-notes") {
  fireEvent.click(tool(id));
}

/** Every POST that opened a conversation, with the corpus it asked for. */
function createdCorpora(calls: { url: string; init?: RequestInit }[]): string[] {
  return calls
    .filter((c) => c.url === "/api/conversations")
    .map((c) => (JSON.parse(c.init!.body as string) as { corpus: string }).corpus);
}

beforeEach(() => stubScrollIntoView());
// `useAiStatus` remembers the last verdict this tab received, so that returning
// to /ai mid-conversation does not flash the probing gate over a live answer
// (see Ai.return-mid-turn.test.tsx). The memory is module-level — one per tab —
// so specs that need a COLD tab, like the "still checking" one below, have to
// clear it. Without this, that spec reads the verdict an earlier spec in this
// file left behind and never sees the probing state at all.
beforeEach(() => __resetAiStatusCache());
afterEach(() => vi.unstubAllGlobals());

describe("AI Mode page — the corpus picker", () => {
  it("opens on the budget corpus, with the toggle off and the box saying so", async () => {
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    // The placeholder is the permanent statement — the toggle is behind a menu
    // that spends most of its life closed.
    expect(screen.getByRole("textbox")).toHaveAttribute(
      "placeholder",
      "Ask about the budget…",
    );
    expect(tool("tool-fiscal-notes")).toHaveAttribute("aria-checked", "false");
  });

  it("asks the fiscal-note corpus when Fiscal notes is picked", async () => {
    const { calls } = stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");

    toggle("tool-fiscal-notes");
    await ask("have we noted a parks bill before?");

    expect(createdCorpora(calls)).toEqual(["fiscal_notes"]);
  });

  it("starts a NEW conversation when the corpus changes mid-session", async () => {
    // The trap this page is built around. If the picker only changed a prop,
    // `useChat` would keep using the conversation it opened against the FIRST
    // corpus: the second question would POST to /api/conversations/conv-1/
    // messages with no second create, and a fiscal-note question would be
    // answered out of budget documents.
    const { calls } = stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");

    await ask("how much for provider rates?");
    await screen.findByText("how much for provider rates?");

    toggle("tool-fiscal-notes");
    await ask("have we noted a parks bill before?");

    // TWO creates, in order, with the corpus each question was actually asked
    // against — not one create followed by a mis-routed message.
    expect(createdCorpora(calls)).toEqual(["budget", "fiscal_notes"]);
  });

  it("clears the thread when the corpus changes", async () => {
    // The visible half of the same fact: a new conversation cannot show the old
    // one's turns, and leaving them on screen would imply the assistant still
    // has that context.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");

    await ask("how much for provider rates?");
    await screen.findByText("how much for provider rates?");

    toggle("tool-fiscal-notes");
    await waitFor(() =>
      expect(screen.queryByText("how much for provider rates?")).toBeNull(),
    );
  });

  it("resets the tier to Standard when the corpus changes (S16)", async () => {
    // S16: every NEW conversation starts on Standard. A corpus switch IS a new
    // conversation, so a Deep Research selection must not survive it — silently
    // carrying it over would spend ~44x on a question the analyst re-scoped.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");

    toggle("tool-deep-research");
    expect(tool("tool-deep-research")).toHaveAttribute("aria-checked", "true");

    toggle("tool-fiscal-notes");
    // Visibly back off: the remount resets the tier, and an analyst who left
    // Deep Research on must be able to SEE that it is no longer on.
    await waitFor(() =>
      expect(tool("tool-deep-research")).toHaveAttribute("aria-checked", "false"),
    );
  });

  it("shows a pip on the closed menu whenever a non-default setting is live", async () => {
    // Both settings are invisible once the menu shuts, and both are
    // consequential — Deep Research costs ~44x a Standard answer, and the
    // corpus decides which documents a citation can come from. Without this
    // badge an analyst can spend that money with no cue on screen.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(screen.queryByTestId("ask-tools-pip")).toBeNull();

    toggle("tool-deep-research");
    expect(screen.getByTestId("ask-tools-pip")).toBeInTheDocument();

    toggle("tool-deep-research");
    expect(screen.queryByTestId("ask-tools-pip")).toBeNull();
  });

  it("renames the box when the corpus changes", async () => {
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    toggle("tool-fiscal-notes");
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveAttribute(
        "placeholder",
        "Ask about fiscal notes…",
      ),
    );
  });

  it("says the switch discards the conversation, in the toggle that does it", async () => {
    // The warning used to be a standing line on the page, which made it
    // wallpaper. It is now part of the description of the control that causes
    // it — read at the moment of the click, which is the only moment it means
    // anything.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(tool("tool-fiscal-notes")).toHaveTextContent(
      /starts a new conversation/i,
    );
  });

  it("names each corpus's scope where the corpus is chosen", async () => {
    // "AI Mode" alone does not tell an analyst which documents an answer was
    // built from, and that is the first thing a citation audit depends on.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(tool("tool-fiscal-notes")).toHaveTextContent(/fiscal notes/i);
  });
});

describe("AI Mode page — starter questions", () => {
  it("offers the budget starters on the budget corpus", async () => {
    stubConversationFetch();
    mountAi();
    expect(await screen.findByText(/Aviation Fund balance/)).toBeInTheDocument();
  });

  it("offers none on the fiscal-note corpus — the shipped starters are budget questions", async () => {
    // Migrated from FiscalNotes.ai-mode.test.tsx. SuggestionRow hardcodes budget
    // questions; pointed at the fiscal-note corpus they are guaranteed empty
    // retrievals, so a coordinator's first click would land in the refusal
    // banner.
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    toggle("tool-fiscal-notes");
    await waitFor(() =>
      expect(screen.queryByText(/Aviation Fund balance/)).toBeNull(),
    );
  });
});

describe("AI Mode page — the gate", () => {
  it("takes the whole page, and does not offer a box that swallows the question", async () => {
    stubConversationFetch();
    mountAi({ ...AI_STATUS, available: false, reason: "no API key configured" });
    const gate = await screen.findByTestId("ai-gate");
    expect(gate).toHaveTextContent("AI Mode is currently unavailable");
    expect(gate).toHaveTextContent(/contact your administrator/i);
    expect(screen.queryByTestId("ai-panel")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("keeps the server's reason, addressed to the person who can act on it", async () => {
    // /api/ai/status is the ONLY thing that knows whether the key is missing,
    // the model is unset, or the config failed to load. That sentence is what
    // an administrator needs; dropping it would leave nobody able to fix this.
    stubConversationFetch();
    mountAi({ ...AI_STATUS, available: false, reason: "no model configured" });
    const gate = await screen.findByTestId("ai-gate");
    expect(gate).toHaveTextContent(/for your administrator/i);
    expect(gate).toHaveTextContent("no model configured");
  });

  it("offers the parts of the app that still work", async () => {
    // Search and fiscal notes need no API key — a hard spec constraint, not
    // luck. A dead end that failed to say so would make the app look far more
    // broken than it is.
    stubConversationFetch();
    mountAi({ ...AI_STATUS, available: false, reason: "no API key configured" });
    await screen.findByTestId("ai-gate");
    expect(screen.getByRole("link", { name: /search budget documents/i }))
      .toHaveAttribute("href", "/search");
    expect(screen.getByRole("link", { name: /browse fiscal notes/i }))
      .toHaveAttribute("href", "/fiscal-notes");
  });

  it("says it is still checking while the probe is in flight", async () => {
    // "Needs an API key" before anyone has checked would state a cause nobody
    // knows yet.
    stubConversationFetch();
    vi.spyOn(api, "aiStatus").mockReturnValue(new Promise<api.AiStatus>(() => {}));
    render(
      <MemoryRouter>
        <AiSessionProvider>
          <Ai />
        </AiSessionProvider>
      </MemoryRouter>,
    );
    const gate = await screen.findByTestId("ai-gate");
    expect(gate).toHaveTextContent(
      "Checking whether AI answers are available on this server…",
    );
    // Must NOT have decided anything yet — no verdict, and no way out offered
    // for a problem that may not exist.
    expect(gate).not.toHaveTextContent(/currently unavailable/i);
    expect(gate).not.toHaveTextContent(/contact your administrator/i);
    expect(screen.queryByRole("link", { name: /search budget documents/i })).toBeNull();
  });
});

describe("AI Mode page — the panel behaviours that moved here", () => {
  it("defaults to Standard, and explains Deep Research from the API", async () => {
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(tool("tool-deep-research")).toHaveAttribute("aria-checked", "false");
    // The S16 sentence comes off the wire — nothing in the webapp retypes it.
    // It sits in the toggle rather than behind a "What's the difference?" link
    // because copy describing a decision belongs where the decision is made.
    expect(tool("tool-deep-research")).toHaveTextContent(
      new RegExp(escapeRe(AI_STATUS.tiers.deep_research.description)),
    );
  });

  it("renders Deep Research inert, with the server's reason, when no model is set", async () => {
    // An admin can wire up Standard and leave Deep Research without a model.
    stubConversationFetch();
    mountAi({
      ...AI_STATUS,
      tiers: {
        ...AI_STATUS.tiers,
        deep_research: {
          ...AI_STATUS.tiers.deep_research,
          available: false,
          reason: "no model configured for Deep Research",
        },
      },
    });
    await screen.findByTestId("ai-panel");
    const row = tool("tool-deep-research");
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row).toHaveTextContent("no model configured for Deep Research");

    fireEvent.click(row);
    expect(tool("tool-deep-research")).toHaveAttribute("aria-checked", "false");
  });

  it("renders an over-limit _error message verbatim in the thread", async () => {
    const message =
      "You've reached your monthly AI usage limit ($25.00) — ask jlbcadmin to raise it.";
    stubConversationFetch(
      sseResponse([`data: ${JSON.stringify({ type: "_error", message })}\n\n`]),
    );
    mountAi();
    await screen.findByTestId("ai-panel");
    await ask("spend everything");

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("does not render a 409 as a failure", async () => {
    stubConversationFetch({ ok: false, status: 409, json: async () => ({ detail: "busy" }) });
    mountAi();
    await screen.findByTestId("ai-panel");
    await ask("q");

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/409/)).toBeNull();
  });
});

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
