import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import { HistoryRail } from "../HistoryRail.js";
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

it("renders chats under a day heading", async () => {
  render(<HistoryRail activeId={null} onSelect={() => {}}
                      onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  expect(await screen.findByText("ADC vacancy savings")).toBeInTheDocument();
  expect(screen.getByText("Today")).toBeInTheDocument();
});

it("groups an older chat separately", async () => {
  const old = row({ id: "c2", title: "Old chat", updated_at: "2026-07-01T10:00:00+00:00" });
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [row(), old] });
  render(<HistoryRail activeId={null} onSelect={() => {}}
                      onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  await screen.findByText("Old chat");
  expect(screen.getByText("Earlier")).toBeInTheDocument();
});

it("selecting a chat calls onSelect with its id", async () => {
  const onSelect = vi.fn();
  render(<HistoryRail activeId={null} onSelect={onSelect}
                      onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  fireEvent.click(await screen.findByText("ADC vacancy savings"));
  expect(onSelect).toHaveBeenCalledWith("c1");
});

it("collapsed hides the list but keeps the expand control reachable", async () => {
  render(<HistoryRail activeId={null} onSelect={() => {}}
                      onNewChat={() => {}}
                      collapsed={true} onToggle={() => {}} />);
  await waitFor(() => expect(screen.queryByText("ADC vacancy savings")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: /chat history/i })).toBeInTheDocument();
});

it("shows a snippet on search results", async () => {
  vi.spyOn(api, "searchHistory").mockResolvedValue({
    results: [{ ...row(), snippet: "…the Florence prison closure…" }],
  });
  render(<HistoryRail activeId={null} onSelect={() => {}}
                      onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "Florence" } });
  expect(await screen.findByText(/Florence prison closure/)).toBeInTheDocument();
});

it("an empty history explains itself rather than rendering nothing", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
  render(<HistoryRail activeId={null} onSelect={() => {}}
                      onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  expect(await screen.findByText(/no saved chats yet/i)).toBeInTheDocument();
});
