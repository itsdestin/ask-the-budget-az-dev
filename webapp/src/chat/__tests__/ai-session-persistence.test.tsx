// P4/P5/P7: the conversation lives above the router, so a route change does
// not unmount it and does not abort a turn in flight.
import { render, screen, act, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { expect, it, vi, beforeEach } from "vitest";
import {
  AiSessionProvider,
  useAiChat,
  useAiSession,
  type AiSession,
} from "../ai-session.js";
import type { UseChatResult } from "../use-chat.js";
import * as api from "../../api.js";

beforeEach(() => vi.restoreAllMocks());

/** Reports the live conversation's turn count wherever it is mounted. */
function TurnCount() {
  const chat = useAiChat();
  return <span data-testid="turns">{chat.state.turns.length}</span>;
}

function Nav() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate("/search")}>go search</button>
      <button onClick={() => navigate("/ai")}>go ai</button>
    </>
  );
}

function Sender() {
  const chat = useAiChat();
  return <button onClick={() => void chat.send("how much for ADC?")}>ask</button>;
}

function App() {
  return (
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <Nav />
        <TurnCount />
        <Routes>
          <Route path="/ai" element={<Sender />} />
          <Route path="/search" element={<div>search page</div>} />
        </Routes>
      </AiSessionProvider>
    </MemoryRouter>
  );
}

function stubTurn() {
  vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "c1", health: { ok: true } } as never);
  return vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response("", { status: 200 }) as never,
  );
}

it("navigating away and back keeps the thread", async () => {
  stubTurn();
  render(<App />);
  await act(async () => { screen.getByText("ask").click(); });
  const before = screen.getByTestId("turns").textContent;
  expect(Number(before)).toBeGreaterThan(0);

  await act(async () => { screen.getByText("go search").click(); });
  expect(screen.getByText("search page")).toBeInTheDocument();
  // The host is above <Routes>, so the count is still readable while away.
  expect(screen.getByTestId("turns").textContent).toBe(before);

  await act(async () => { screen.getByText("go ai").click(); });
  expect(screen.getByTestId("turns").textContent).toBe(before);
});

it("a route change does not abort the stream", async () => {
  // The core of P5. `useChat`'s unmount cleanup calls abort(); if the host
  // still sits under the router, this fires and the turn dies.
  const aborted = vi.fn();
  vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "c1", health: { ok: true } } as never);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_u, init) => {
    (init as RequestInit)?.signal?.addEventListener("abort", aborted);
    return new Response("", { status: 200 }) as never;
  });

  render(<App />);
  await act(async () => { screen.getByText("ask").click(); });
  await act(async () => { screen.getByText("go search").click(); });
  expect(aborted).not.toHaveBeenCalled();
});

it("switching corpus still discards the conversation (P7)", async () => {
  stubTurn();
  function CorpusSwitch() {
    const s = useAiSession();
    return <button onClick={() => s.setCorpus("fiscal_notes")}>switch</button>;
  }
  render(
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <TurnCount />
        <CorpusSwitch />
        <Routes><Route path="/ai" element={<Sender />} /></Routes>
      </AiSessionProvider>
    </MemoryRouter>,
  );
  await act(async () => { screen.getByText("ask").click(); });
  expect(Number(screen.getByTestId("turns").textContent)).toBeGreaterThan(0);

  await act(async () => { screen.getByText("switch").click(); });
  await waitFor(() =>
    expect(screen.getByTestId("turns").textContent).toBe("0"),
  );
});

it("+ New chat discards the conversation too", async () => {
  stubTurn();
  function NewChat() {
    const s = useAiSession();
    return <button onClick={s.newChat}>new</button>;
  }
  render(
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <TurnCount />
        <NewChat />
        <Routes><Route path="/ai" element={<Sender />} /></Routes>
      </AiSessionProvider>
    </MemoryRouter>,
  );
  await act(async () => { screen.getByText("ask").click(); });
  expect(Number(screen.getByTestId("turns").textContent)).toBeGreaterThan(0);
  await act(async () => { screen.getByText("new").click(); });
  await waitFor(() =>
    expect(screen.getByTestId("turns").textContent).toBe("0"),
  );
});

// ---------------------------------------------------------------------------
// Guard 1 — the delete-in-flight-then-reselect race (`chatDeleted` in
// ai-session.tsx).
//
// This exact line has been written three ways and two were wrong: a
// functional state updater (impure — it called `setNewChatNonce` from
// inside a `setSelectedChatId` updater, which StrictMode double-invokes), a
// plain render-closure read of `selectedChatId` (pure, but racy), and the
// shipped `selectedIdRef` kept fresh on every render (pure AND correct).
// This spec pins the race the MIDDLE version had: `chatDeleted`'s only
// caller, HistoryRail.tsx:253, invokes it AFTER an await —
// `remove(chat.id).then((gone) => { if (gone) onDeleted?.(chat.id) })` — so
// if the callback reads a value captured at click time instead of the
// CURRENT selection, a delete that resolves after the analyst has already
// opened a different chat discards the chat they are now looking at.
// ---------------------------------------------------------------------------
it("a delete resolving after the analyst has opened a different chat does not discard that chat", async () => {
  vi.spyOn(api, "getHistoryChat").mockImplementation(
    async (id: string) =>
      ({
        id,
        title: "t",
        corpus: "budget",
        created_at: "",
        updated_at: "",
        title_is_manual: false,
        message_count: 0,
        messages: [],
      }) as never,
  );

  const captured: { session: AiSession | null } = { session: null };
  function Capture() {
    captured.session = useAiSession();
    return null;
  }
  function Selected() {
    const s = useAiSession();
    return <span data-testid="selected">{s.selectedChatId ?? "none"}</span>;
  }

  render(
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <Capture />
        <Selected />
      </AiSessionProvider>
    </MemoryRouter>,
  );

  // View chat A.
  await act(async () => { captured.session!.selectChat("A"); });
  expect(screen.getByTestId("selected").textContent).toBe("A");

  // Begin deleting A. The delete request is a DEFERRED PROMISE resolved by
  // hand, so the interleaving below is deterministic rather than
  // timing-dependent. This wiring mirrors HistoryRail.tsx:253 exactly: the
  // callback is bound at "click" time (here, right after A is selected) and
  // only runs once the delete resolves.
  let resolveDelete!: (gone: boolean) => void;
  const deleteInFlight = new Promise<boolean>((resolve) => {
    resolveDelete = resolve;
  });
  const onDeleted = captured.session!.chatDeleted;
  void deleteInFlight.then((gone) => {
    if (gone) onDeleted("A");
  });

  // While A's delete is still in flight, the analyst opens chat B.
  await act(async () => { captured.session!.selectChat("B"); });
  expect(screen.getByTestId("selected").textContent).toBe("B");

  // NOW the delete resolves.
  await act(async () => {
    resolveDelete(true);
    await deleteInFlight;
  });

  // B must still be the open chat — the late-resolving delete-A callback
  // must not have called newChat() on top of it.
  await waitFor(() =>
    expect(screen.getByTestId("selected").textContent).toBe("B"),
  );
});

// ---------------------------------------------------------------------------
// Guard 2 — INERT_CHAT.send must throw SYNCHRONOUSLY (ai-session.tsx).
//
// INERT_CHAT is the placeholder `chat` state starts as, for the one render
// before ChatEngine's `useLayoutEffect` mirrors the real `useChat()` result
// up. It is not exported, so this spec reaches the REAL object (not a copy)
// by capturing whatever `useAiChat()` returns on the FIRST render pass —
// which happens during React's render phase, strictly before any layout
// effect runs, so it is guaranteed to still be INERT_CHAT.
//
// `send` is deliberately a plain (non-`async`) function that throws before
// returning. MessageInput.tsx:93-97 calls `onSubmit(text); setValue("");`
// with no try/catch: a synchronous throw propagates ahead of `setValue("")`,
// so the analyst's text survives and the error is visible. An `async`
// version's throw would instead become a silent unhandled promise
// rejection while the input box cleared as if nothing happened. Someone
// will eventually "clean up" `send` to be `async` for symmetry with `stop`
// — this spec is what stops that from shipping unnoticed.
// ---------------------------------------------------------------------------
it("the INERT_CHAT placeholder's send() throws synchronously, not as a rejected promise", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});

  const captured: { chat: UseChatResult | null } = { chat: null };
  function CaptureFirstRender() {
    const chat = useAiChat();
    // Only the FIRST render's value is kept — later renders (once
    // ChatEngine's mirror lands) must not overwrite it.
    if (captured.chat === null) captured.chat = chat;
    return null;
  }

  render(
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <CaptureFirstRender />
      </AiSessionProvider>
    </MemoryRouter>,
  );

  expect(captured.chat).not.toBeNull();
  expect(() => captured.chat!.send("x")).toThrow();
});
