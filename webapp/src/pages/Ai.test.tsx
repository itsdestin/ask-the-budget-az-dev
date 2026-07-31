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

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Ai } from "./Ai";
import * as api from "../api";
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
      <Ai />
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

const corpusChip = (name: RegExp) => screen.getByRole("button", { name });

/** Every POST that opened a conversation, with the corpus it asked for. */
function createdCorpora(calls: { url: string; init?: RequestInit }[]): string[] {
  return calls
    .filter((c) => c.url === "/api/conversations")
    .map((c) => (JSON.parse(c.init!.body as string) as { corpus: string }).corpus);
}

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("AI Mode page — the corpus picker", () => {
  it("opens on the budget corpus with the picker showing it", async () => {
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(corpusChip(/budget documents/i)).toHaveAttribute("aria-pressed", "true");
    expect(corpusChip(/fiscal notes/i)).toHaveAttribute("aria-pressed", "false");
  });

  it("asks the fiscal-note corpus when Fiscal notes is picked", async () => {
    const { calls } = stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");

    fireEvent.click(corpusChip(/fiscal notes/i));
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

    fireEvent.click(corpusChip(/fiscal notes/i));
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

    fireEvent.click(corpusChip(/fiscal notes/i));
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

    fireEvent.click(screen.getByRole("button", { name: "Deep Research" }));
    expect(screen.getByRole("button", { name: "Deep Research" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(corpusChip(/fiscal notes/i));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Standard" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByRole("button", { name: "Deep Research" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("warns that switching corpus starts a new conversation", async () => {
    stubConversationFetch();
    mountAi();
    await screen.findByTestId("ai-panel");
    expect(
      screen.getByText(/switching corpus starts a new conversation/i),
    ).toBeInTheDocument();
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
    fireEvent.click(corpusChip(/fiscal notes/i));
    await waitFor(() =>
      expect(screen.queryByText(/Aviation Fund balance/)).toBeNull(),
    );
  });
});

describe("AI Mode page — the gate", () => {
  it("explains the missing key instead of showing a composer", async () => {
    // Migrated from the two toggle suites, where the same fact dimmed a pill.
    // The tab is always reachable now, so the page itself has to say why it
    // cannot answer — and must not offer a box that swallows the question.
    stubConversationFetch();
    mountAi({ ...AI_STATUS, available: false, reason: "no API key configured" });
    expect(await screen.findByTestId("ai-gate")).toHaveTextContent(
      "AI answers require an API key — ask your admin.",
    );
    expect(screen.getByText(/no API key configured/)).toBeInTheDocument();
    expect(screen.queryByTestId("ai-panel")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("says it is still checking while the probe is in flight", async () => {
    // "Needs an API key" before anyone has checked would state a cause nobody
    // knows yet.
    stubConversationFetch();
    vi.spyOn(api, "aiStatus").mockReturnValue(new Promise<api.AiStatus>(() => {}));
    render(
      <MemoryRouter>
        <Ai />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("ai-gate")).toHaveTextContent(
      "Checking whether AI answers are available on this server…",
    );
  });
});

describe("AI Mode page — the panel behaviours that moved here", () => {
  it("defaults to Standard and explains the tiers from the API", async () => {
    stubConversationFetch();
    mountAi();
    const standard = await screen.findByRole("button", { name: "Standard" });
    expect(standard).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: /what's the difference/i }));
    // Every example string comes from GET /api/ai/status — nothing in the
    // webapp retypes the S16 sentences.
    const popover = document.getElementById("ai-tier-pop")!;
    for (const tier of Object.values(AI_STATUS.tiers)) {
      for (const example of tier.examples) {
        expect(
          within(popover).getAllByText(new RegExp(escapeRe(example))).length,
        ).toBeGreaterThan(0);
      }
    }
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
