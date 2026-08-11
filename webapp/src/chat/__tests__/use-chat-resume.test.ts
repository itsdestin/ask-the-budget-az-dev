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

it("the first send of a resumed chat KEEPS the rehydrated turns", async () => {
  // The reported bug: open a stored chat (turns on screen), send a message,
  // and the transcript vanished — because send() dispatched CONVERSATION_STARTED
  // without keepTurns, and the reducer reset the timeline to initialChatState.
  // After the fix the resumed send passes keepTurns and the rehydrated turns
  // survive (plus the new user prompt appended on top).
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 2,
    messages: [
      { role: "user", content: "earlier question" },
      { role: "assistant", content: "earlier answer" },
    ],
  } as never);
  const create = vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "old1", health: { ok: true } } as never);
  // Stub the SSE stream fetch so send() doesn't hit the network.
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("", { status: 200 }) as never,
  );
  const { result } = renderHook(() => useChat("budget", "old1"));
  // Wait for the rehydrated turns to land (user + assistant = 2).
  await waitFor(() => expect(result.current.state.turns).toHaveLength(2));

  await act(() => result.current.send("next question"));

  // The resume create still went out with the stored id…
  expect(create).toHaveBeenCalledWith("budget", "old1");
  // …but the timeline was NOT wiped: the two rehydrated turns are still
  // there, with the new user prompt appended (3 total).
  expect(result.current.state.turns.length).toBeGreaterThanOrEqual(3);
  expect(result.current.state.turns[0]).toMatchObject({ kind: "user", text: "earlier question" });
  expect(result.current.state.turns[2]).toMatchObject({ kind: "user", text: "next question" });
  // And the conversation id is the resumed chat's id, not a fresh one.
  expect(result.current.state.conversationId).toBe("old1");
});
