import { renderHook, waitFor, act } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import { useChat } from "../use-chat";
import * as api from "../../api";

beforeEach(() => vi.restoreAllMocks());

it("opening a stored chat creates NO conversation", async () => {
  // The whole point of H2: browsing history must cost nothing.
  const create = vi.spyOn(api, "createConversation");
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 2,
    messages: [{ role: "user", content: "earlier" }],
  } as never);
  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(result.current.state.turns.length).toBeGreaterThan(0));
  expect(create).not.toHaveBeenCalled();
});

it("the first send resumes from the stored id", async () => {
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 1, messages: [],
  } as never);
  const create = vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "old1", health: { ok: true } } as never);
  // Stub streamTurn so send doesn't try a real fetch.
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("", { status: 200 }) as never,
  );
  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(api.getHistoryChat).toHaveBeenCalled());
  await act(() => result.current.send("next question"));
  expect(create).toHaveBeenCalledWith("budget", "old1");
});

it("a new chat still creates without a resume id", async () => {
  const create = vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "n1", health: { ok: true } } as never);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("", { status: 200 }) as never,
  );
  const { result } = renderHook(() => useChat("budget"));
  await act(() => result.current.send("hello"));
  expect(create).toHaveBeenCalledWith("budget", undefined);
});
