// Three rail defects found by review 2026-08-11.
//
//  - Delete was one click on a ✕ sitting beside the ✎, with no confirmation
//    and (per H6) no expiry and no undo anywhere in the design.
//  - Deleting the OPEN chat never told the page, so the thread kept rendering
//    a transcript that no longer existed.
//  - `useHistory` fetched on mount only, so a new chat's row — and the title
//    the server generates for it seconds later — never appeared until
//    something remounted the rail.
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

function mount(props: Partial<React.ComponentProps<typeof HistoryRail>> = {}) {
  return render(
    <HistoryRail
      activeId={null}
      onSelect={() => {}}
      onNewChat={() => {}}
      collapsed={false}
      onToggle={() => {}}
      {...props}
    />,
  );
}

it("one click on ✕ does NOT delete — it asks", async () => {
  const del = vi.spyOn(api, "deleteHistoryChat").mockResolvedValue(undefined as never);
  mount();
  await screen.findByText("ADC vacancy savings");

  fireEvent.click(screen.getByLabelText("Delete chat"));
  expect(del).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Confirm delete chat")).toBeInTheDocument();
  // And the chat is still on the list.
  expect(screen.getByText("ADC vacancy savings")).toBeInTheDocument();
});

it("the second click deletes", async () => {
  const del = vi.spyOn(api, "deleteHistoryChat").mockResolvedValue(undefined as never);
  mount();
  await screen.findByText("ADC vacancy savings");

  fireEvent.click(screen.getByLabelText("Delete chat"));
  fireEvent.click(screen.getByLabelText("Confirm delete chat"));
  await waitFor(() => expect(del).toHaveBeenCalledWith("c1"));
});

it("starting a rename disarms a pending delete", async () => {
  mount();
  await screen.findByText("ADC vacancy savings");
  fireEvent.click(screen.getByLabelText("Delete chat"));
  fireEvent.click(screen.getByLabelText("Rename chat"));
  expect(screen.queryByLabelText("Confirm delete chat")).toBeNull();
});

it("deleting a chat reports it, so the page can close it", async () => {
  vi.spyOn(api, "deleteHistoryChat").mockResolvedValue(undefined as never);
  const onDeleted = vi.fn();
  mount({ onDeleted });
  await screen.findByText("ADC vacancy savings");

  fireEvent.click(screen.getByLabelText("Delete chat"));
  fireEvent.click(screen.getByLabelText("Confirm delete chat"));
  await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("c1"));
});

it("a FAILED delete reports nothing — the chat still exists", async () => {
  vi.spyOn(api, "deleteHistoryChat").mockRejectedValue(new Error("disk is full"));
  const onDeleted = vi.fn();
  mount({ onDeleted });
  await screen.findByText("ADC vacancy savings");

  fireEvent.click(screen.getByLabelText("Delete chat"));
  fireEvent.click(screen.getByLabelText("Confirm delete chat"));
  // The optimistic removal is rolled back, and the page must NOT deselect.
  expect(await screen.findByText("ADC vacancy savings")).toBeInTheDocument();
  expect(onDeleted).not.toHaveBeenCalled();
});

it("a bumped reloadToken re-reads the list", async () => {
  const list = vi.spyOn(api, "listHistory")
    .mockResolvedValue({ conversations: [row()] });
  const { rerender } = mount({ reloadToken: 0 });
  await screen.findByText("ADC vacancy savings");
  expect(list).toHaveBeenCalledTimes(1);

  list.mockResolvedValue({
    conversations: [row(), row({ id: "c2", title: "Just asked" })],
  });
  rerender(
    <HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                 collapsed={false} onToggle={() => {}} reloadToken={1} />,
  );
  expect(await screen.findByText("Just asked")).toBeInTheDocument();
});

it("the initial token does not double the mount fetch", async () => {
  const list = vi.spyOn(api, "listHistory")
    .mockResolvedValue({ conversations: [row()] });
  mount({ reloadToken: 0 });
  await screen.findByText("ADC vacancy savings");
  expect(list).toHaveBeenCalledTimes(1);
});
