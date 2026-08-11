// P1/P2/P3: "+ New chat" shows a row immediately, backed by no file.
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import { DRAFT_CHAT_ID, HistoryRail } from "../HistoryRail.js";
import * as api from "../../api.js";

const row = (over: Partial<api.HistoryRow> = {}): api.HistoryRow => ({
  id: "c1", title: "ADC vacancy savings", corpus: "budget",
  created_at: "2026-08-02T10:00:00+00:00", updated_at: new Date().toISOString(),
  title_is_manual: false, message_count: 2, ...over,
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [row()] });
});

function mount(props: Partial<React.ComponentProps<typeof HistoryRail>> = {}) {
  return render(
    <HistoryRail
      activeId={null} onSelect={() => {}} onNewChat={() => {}}
      collapsed={false} onToggle={() => {}} {...props}
    />,
  );
}

it("a fresh draft shows a New chat row under Today, selected", async () => {
  mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  const placeholder = await screen.findByText("New chat");
  expect(screen.getByText("Today")).toBeInTheDocument();
  const item = placeholder.closest(".history-rail-item");
  expect(item?.className).toContain("is-active");
});

it("the placeholder offers no rename and no delete — there is no file", async () => {
  mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  await screen.findByText("New chat");
  // The one stored chat still has its actions; the placeholder must not.
  expect(screen.getAllByLabelText("Rename chat")).toHaveLength(1);
  expect(screen.getAllByLabelText("Delete chat")).toHaveLength(1);
});

it("Today appears even when every stored chat is older", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({
    conversations: [row({ updated_at: "2026-07-01T10:00:00+00:00" })],
  });
  mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  await screen.findByText("New chat");
  expect(screen.getByText("Today")).toBeInTheDocument();
  expect(screen.getByText("Earlier")).toBeInTheDocument();
});

it("the real row REPLACES the placeholder once it lands with the same id", async () => {
  // After the first turn the conversation has a server id and the rail
  // reloads; the stored row now carries that id, so the synthetic one stops
  // rendering. Exactly one row, not two.
  vi.spyOn(api, "listHistory").mockResolvedValue({
    conversations: [row({ id: "srv-1", title: "ADC vacancy savings" })],
  });
  mount({ draftId: "srv-1", activeId: "srv-1" });
  await screen.findByText("ADC vacancy savings");
  expect(screen.queryByText("New chat")).toBeNull();
});

it("a live conversation not yet on disk still shows the placeholder", async () => {
  mount({ draftId: "srv-unsaved", activeId: "srv-unsaved" });
  expect(await screen.findByText("New chat")).toBeInTheDocument();
});

it("no draft means no placeholder", async () => {
  mount({ draftId: null, activeId: "c1" });
  await screen.findByText("ADC vacancy savings");
  expect(screen.queryByText("New chat")).toBeNull();
});

it("searching hides the placeholder — you are filtering stored chats", async () => {
  // Plan's sketch drove this by mutating the input's DOM value directly and
  // dispatching a raw "input" event; jsdom does not route that through
  // React's controlled-input onChange (the codebase's own history-rail.test
  // uses fireEvent.change for this exact reason), so the query state never
  // updated and the assertion below failed for the wrong reason. Matched to
  // the existing convention instead.
  vi.spyOn(api, "searchHistory").mockResolvedValue({ results: [] });
  mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  await screen.findByText("New chat");
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "aviation" } });
  await waitFor(() => expect(screen.queryByText("New chat")).toBeNull());
});

it("the placeholder never asks the server to create anything", async () => {
  const del = vi.spyOn(api, "deleteHistoryChat");
  const ren = vi.spyOn(api, "renameHistoryChat");
  mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  await screen.findByText("New chat");
  expect(del).not.toHaveBeenCalled();
  expect(ren).not.toHaveBeenCalled();
});
