// P4/P5/P7: the conversation lives above the router, so a route change does
// not unmount it and does not abort a turn in flight.
import { render, screen, act, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { expect, it, vi, beforeEach } from "vitest";
import { AiSessionProvider, useAiChat, useAiSession } from "../ai-session.js";
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
