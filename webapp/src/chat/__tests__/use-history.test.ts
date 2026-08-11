import { renderHook, waitFor, act } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import { useHistory } from "../use-history";
import * as api from "../../api";

const ROW: api.HistoryRow = {
  id: "c1", title: "ADC vacancy savings", corpus: "budget",
  created_at: "2026-08-02T10:00:00+00:00", updated_at: "2026-08-02T10:05:00+00:00",
  title_is_manual: false, message_count: 2,
};

beforeEach(() => vi.restoreAllMocks());

it("loads chats on mount", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  expect(result.current.chats[0].title).toBe("ADC vacancy savings");
});

it("switches to search results when a query is set", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  const search = vi.spyOn(api, "searchHistory")
    .mockResolvedValue({ results: [{ ...ROW, snippet: "…Florence prison…" }] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  act(() => result.current.setQuery("Florence"));
  await waitFor(() => expect(search).toHaveBeenCalledWith("Florence"));
  expect(result.current.chats[0].snippet).toContain("Florence");
});

it("clearing the query restores the full list", async () => {
  const list = vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  vi.spyOn(api, "searchHistory").mockResolvedValue({ results: [] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  act(() => result.current.setQuery("zzz"));
  await waitFor(() => expect(result.current.chats).toHaveLength(0));
  act(() => result.current.setQuery(""));
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  expect(list).toHaveBeenCalledTimes(2);
});

it("a failed load surfaces an error instead of an empty list", async () => {
  vi.spyOn(api, "listHistory").mockRejectedValue(new Error("nope"));
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.error).toBeTruthy());
});

it("remove drops the chat locally without a refetch", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  vi.spyOn(api, "deleteHistoryChat").mockResolvedValue({ deleted: "c1" });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  await act(() => result.current.remove("c1"));
  expect(result.current.chats).toHaveLength(0);
});
