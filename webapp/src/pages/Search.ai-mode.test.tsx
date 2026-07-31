// Budget Search — AI Mode toggle, tier control, and the guarantee that OFF is
// the shipped page untouched (spec S12: the results presentation was iterated
// live with Destin and must not move).

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Search } from "./Search";
import * as api from "../api";
import {
  AI_STATUS,
  sseResponse,
  stubConversationFetch,
  stubScrollIntoView,
} from "./ai-test-fixtures";

const RESULT = {
  chunk_id: "c1",
  doc_id: "d1",
  doc_title: "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
  snippet: "…provider rate increases…",
  page: 14,
  score: 0.91,
  doc_type: "baseline-per-agency",
  fiscal_year: 2027,
  publisher: "jlbc",
  agencies: ["ahcccs"],
  doc_url: "https://www.azjlbc.gov/27baseline/axs.pdf",
  doc_meta: "Agency Budget Detail · Baseline Book · FY 2027",
};

function mountWithResults(status = AI_STATUS) {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT],
    total: 1,
    provider: "lance",
  });
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}>
      <Search />
    </MemoryRouter>,
  );
}

const toggle = () => screen.getByRole("button", { name: /ai mode/i });

beforeEach(() => stubScrollIntoView());
afterEach(() => vi.unstubAllGlobals());

describe("Search — AI Mode toggle", () => {
  it("renders an unpressed pill in the page header and the shipped results below", async () => {
    stubConversationFetch();
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    // The subhero is the page-header band; the pill belongs to it, not to the
    // search card or the results panel.
    expect(toggle().closest(".subhero")).not.toBeNull();
  });

  it("leaves the results list byte-identical across an on/off round trip", async () => {
    stubConversationFetch();
    const view = mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    const before = view.container.querySelector(".results")!.innerHTML;

    fireEvent.click(toggle());
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-pressed", "true"));
    expect(view.container.querySelector(".results")).toBeNull();

    fireEvent.click(toggle());
    await waitFor(() =>
      expect(view.container.querySelector(".results")).not.toBeNull(),
    );
    expect(view.container.querySelector(".results")!.innerHTML).toBe(before);
  });

  it("sends the search box to the conversation instead of running a search", async () => {
    const { calls } = stubConversationFetch();
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    const searchCallsBefore = (api.search as unknown as { mock: { calls: unknown[] } })
      .mock.calls.length;

    fireEvent.click(toggle());
    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "how much for provider rates?" } });
    await act(async () => {
      fireEvent.submit(box.closest("form")!);
    });

    // The question went to the thread…
    await screen.findByText("how much for provider rates?");
    expect(
      calls.filter((c) => c.url === "/api/conversations/conv-1/messages"),
    ).toHaveLength(1);
    // …and no keyword search was fired for it.
    expect(
      (api.search as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
    ).toBe(searchCallsBefore);
  });

  it("defaults every new conversation to Standard and explains the tiers from the API", async () => {
    stubConversationFetch();
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    fireEvent.click(toggle());

    const standard = await screen.findByRole("button", { name: "Standard" });
    const deep = screen.getByRole("button", { name: "Deep Research" });
    expect(standard).toHaveAttribute("aria-pressed", "true");
    expect(deep).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: /what's the difference/i }));
    // Every example string comes from GET /api/ai/status — nothing in the
    // webapp retypes the S16 sentences. `within` the popover, and getAllByText
    // because the server's `description` embeds its own examples, so each
    // sentence legitimately appears twice inside it.
    const popover = document.getElementById("ai-tier-pop")!;
    for (const tier of Object.values(AI_STATUS.tiers)) {
      for (const example of tier.examples) {
        expect(
          within(popover).getAllByText(new RegExp(escapeRe(example))).length,
        ).toBeGreaterThan(0);
      }
    }

    fireEvent.click(deep);
    expect(deep).toHaveAttribute("aria-pressed", "true");
  });

  it("dims the toggle with the admin tooltip when no key is configured", async () => {
    stubConversationFetch();
    mountWithResults({
      ...AI_STATUS,
      available: false,
      reason: "no API key configured",
      tiers: {
        standard: { ...AI_STATUS.tiers.standard!, available: false, reason: "no API key configured" },
        deep_research: { ...AI_STATUS.tiers.deep_research!, available: false, reason: "no API key configured" },
      },
    });
    await screen.findByText(/Health Care Cost Containment/);

    await waitFor(() =>
      expect(toggle()).toHaveAttribute("aria-disabled", "true"),
    );
    expect(toggle()).toHaveAttribute(
      "title",
      "AI answers require an API key — ask your admin.",
    );
    // Clicking a gated control must not open a surface that cannot work.
    fireEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("renders an over-limit _error message verbatim in the thread", async () => {
    const message =
      "You've reached your monthly AI usage limit ($25.00) — ask jlbcadmin to raise it.";
    stubConversationFetch(
      sseResponse([`data: ${JSON.stringify({ type: "_error", message })}\n\n`]),
    );
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    fireEvent.click(toggle());

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "spend everything" } });
    await act(async () => {
      fireEvent.submit(box.closest("form")!);
    });

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("does not render a 409 as a failure", async () => {
    stubConversationFetch({ ok: false, status: 409, json: async () => ({ detail: "busy" }) });
    mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    fireEvent.click(toggle());

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "q" } });
    await act(async () => {
      fireEvent.submit(box.closest("form")!);
    });

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/409/)).toBeNull();
  });
});

describe("Search — passage rows are keyboard reachable", () => {
  it("opens the source panel from the keyboard", async () => {
    stubConversationFetch();
    vi.spyOn(api, "chunk").mockResolvedValue({
      chunk_id: "c1",
      doc_id: "d1",
      page: 14,
      bbox: null,
      text: "…provider rate increases…",
      source_format: "pdf",
      pdf_unavailable_reason: null,
    });
    const view = mountWithResults();
    await screen.findByText(/Health Care Cost Containment/);
    fireEvent.click(screen.getByRole("button", { name: /1 passage/i }));

    const row = view.container.querySelector('[data-chunk-id="c1"]') as HTMLElement;
    // A new user-facing action on the provenance path cannot be mouse-only.
    expect(row.tabIndex).toBe(0);
    expect(row).toHaveAttribute("role", "button");
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    expect(await screen.findByLabelText("Source passage")).toBeInTheDocument();
  });
});

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
