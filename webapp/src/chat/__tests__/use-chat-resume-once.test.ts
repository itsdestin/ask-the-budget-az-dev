// Resume is a ONE-TIME handover (review, 2026-08-11).
//
// `isResume` was `conversationId === resumeFrom`, and the server returns the
// same id it was given, so that stayed true for the life of the hook: every
// message re-POSTed /api/conversations. Wasteful on its own, and it was the
// mechanism that made a deleted history row permanently fatal to a live
// conversation — each message re-entered a create path that could 404.
import { renderHook, waitFor, act } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import { useChat } from "../use-chat";
import * as api from "../../api";

beforeEach(() => vi.restoreAllMocks());

function stubStoredChat() {
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 1, messages: [],
  } as never);
  // A fresh Response per call: a Response body is a stream that can only be
  // read once, and this test deliberately sends several messages.
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response("", { status: 200 }) as never,
  );
  return vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "old1", health: { ok: true } } as never);
}

it("a resumed chat creates the conversation once, however many messages follow", async () => {
  const create = stubStoredChat();
  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(api.getHistoryChat).toHaveBeenCalled());

  await act(() => result.current.send("first"));
  expect(create).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledWith("budget", "old1");

  await act(() => result.current.send("second"));
  await act(() => result.current.send("third"));
  expect(create).toHaveBeenCalledTimes(1);
});

it("a failed handover is retried on the next message", async () => {
  // The latch must not strand a chat whose very first create failed — that
  // would leave `send` posting to a conversation the server never made.
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 1, messages: [],
  } as never);
  // A fresh Response per call: a Response body is a stream that can only be
  // read once, and this test deliberately sends several messages.
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response("", { status: 200 }) as never,
  );
  const create = vi.spyOn(api, "createConversation")
    .mockRejectedValueOnce(new Error("server said no"))
    .mockResolvedValue({ conversation_id: "old1", health: { ok: true } } as never);

  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(api.getHistoryChat).toHaveBeenCalled());

  await act(() => result.current.send("first"));
  await act(() => result.current.send("second"));
  expect(create).toHaveBeenCalledTimes(2);
});
