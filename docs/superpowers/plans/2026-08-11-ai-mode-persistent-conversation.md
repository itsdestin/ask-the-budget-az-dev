# AI Mode persistent conversation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "+ New chat" appears in the history rail immediately as a selected row, and an AI Mode conversation — including a query still streaming — survives navigating to Budget Documents or Fiscal Notes and back.

**Architecture:** Two independent changes. Task 1 adds a client-side placeholder row to the rail, backed by no file. Task 2 moves the conversation's state and its `useChat` hook above `<Routes>` into two contexts, so a route change no longer unmounts the SSE stream. `/ai` becomes a view that reads both contexts.

**Tech Stack:** React 18, react-router-dom v6, TypeScript, Vitest + @testing-library/react. Webapp only.

**How to read the code blocks.** They are sketches — write them, run them,
and correct them against what the compiler and the tests actually say. Do not
transcribe them as if they were the finished diff. The PROSE and the comments
are the part that holds: they carry the reasons, and a reason is what stops a
decision being undone in six months.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-11-ai-mode-persistent-conversation-design.md` (P1–P8). Read it before starting.
- **No server change.** Nothing under `app/`, `harness/`, `retrieval/`, `ingest/`, `chunking/` or `citation/` is touched, so the CLAUDE.md eval rule does not apply and no eval is run.
- **No transcript is ever written for an unused chat** (P1). The placeholder is client-side only.
- **Never write the live conversation id into `selectedChatId`** (P3). It is part of the conversation's React `key`; writing it remounts mid-answer and wipes the thread.
- **The `key` stays `${corpus}:${selectedChatId ?? "new"}:${newChatNonce}`** (P4). It is the wrong-corpus safety mechanism, not a re-render hint.
- **A closed tab must still abort the turn** (P5). Only a route change must stop aborting.
- **No background indicator of any kind** (P8) — no pip, no toast, no badge.
- Run `npx vitest run` and `./node_modules/.bin/tsc -b` from `webapp/` before every commit. Both must be clean.

---

## File Structure

| File | Responsibility |
|---|---|
| `webapp/src/chat/HistoryRail.tsx` | **Modify.** Renders the placeholder row and marks it active. |
| `webapp/src/chat/AiModePanel.tsx` | **Modify.** Computes `activeId` / `draftId` from the chat state and passes them down. |
| `webapp/src/styles/app.css` | **Modify.** One rule for the non-interactive placeholder row. |
| `webapp/src/chat/ai-session.tsx` | **Create.** `AiSessionProvider` (corpus / selected chat / nonce + handlers) and the keyed `AiChatHost` that owns `useChat`. Two contexts, two hooks. |
| `webapp/src/App.tsx` | **Modify.** Wrap `<Header/>` + `<Routes>` in `AiSessionProvider`. |
| `webapp/src/pages/Ai.tsx` | **Modify.** Drops its own state and the `AiConversation` wrapper; reads both contexts. |
| `webapp/src/pages/Ai.test.tsx`, `Ai.fullpage.test.tsx` | **Modify.** Their mount helpers wrap in `AiSessionProvider`. |
| `webapp/src/chat/__tests__/history-rail-placeholder.test.tsx` | **Create.** Task 1's specs. |
| `webapp/src/chat/__tests__/ai-session-persistence.test.tsx` | **Create.** Task 2's specs. |

Task 1 and Task 2 touch disjoint files except `AiModePanel.tsx`/`Ai.tsx`, so do them in order.

---

### Task 1: The placeholder row

**Files:**
- Modify: `webapp/src/chat/HistoryRail.tsx`
- Modify: `webapp/src/chat/AiModePanel.tsx`
- Modify: `webapp/src/styles/app.css`
- Test: `webapp/src/chat/__tests__/history-rail-placeholder.test.tsx`

**Interfaces:**
- Consumes: `api.HistoryRow` (`{id, title, corpus, created_at, updated_at, title_is_manual, message_count, snippet?}`), the existing `HistoryRailProps`, and `chat.state.conversationId: string | null` — which ALREADY exists on `ChatState` and is set by the `CONVERSATION_STARTED` and `REHYDRATED` reducer cases. No new upward reporting is needed.
- Produces: `export const DRAFT_CHAT_ID = "draft"` from `HistoryRail.tsx`, and a new optional prop `draftId?: string | null` on `HistoryRailProps`.

- [ ] **Step 1: Write the failing tests**

Create `webapp/src/chat/__tests__/history-rail-placeholder.test.tsx`:

```tsx
// P1/P2/P3: "+ New chat" shows a row immediately, backed by no file.
import { render, screen, waitFor } from "@testing-library/react";
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
  vi.spyOn(api, "searchHistory").mockResolvedValue({ results: [] });
  const { container } = mount({ draftId: DRAFT_CHAT_ID, activeId: DRAFT_CHAT_ID });
  await screen.findByText("New chat");
  const box = container.querySelector(".history-rail-search") as HTMLInputElement;
  box.value = "aviation";
  box.dispatchEvent(new Event("input", { bubbles: true }));
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/history-rail-placeholder.test.tsx`
Expected: FAIL — `DRAFT_CHAT_ID` is not exported from `HistoryRail.tsx`.

- [ ] **Step 3: Add the export and the prop to `HistoryRail.tsx`**

Add above `interface HistoryRailProps`:

```tsx
/** The current conversation's stand-in id, before the server has minted a
 *  real one. A brand-new chat has NO id until the first send — `useChat`
 *  creates the conversation lazily — so the rail needs something to key the
 *  placeholder on. Never sent to the server, never compared to a stored id. */
export const DRAFT_CHAT_ID = "draft";
```

Add to `HistoryRailProps`:

```tsx
  /** The current conversation, when it has NOT been persisted yet — either
   *  the DRAFT_CHAT_ID sentinel or a live server id whose transcript has not
   *  been written. Non-null only for a NEW chat: a chat opened from the rail
   *  already has a row on the way, and treating it as a draft would flash a
   *  "New chat" placeholder over it while the list loads. */
  draftId?: string | null;
```

- [ ] **Step 4: Insert the placeholder into the grouped rows**

In the component body, after `const { chats, ... } = useHistory();` and the existing `useState` calls, replace the later `const groups = groupChats(chats);` and `const searching = ...` lines with:

```tsx
  const searching = query.trim().length > 0;
  // The placeholder shows while the current NEW conversation has no row of
  // its own — either it has no server id yet, or it has one and the turn that
  // would write its transcript has not finished. Matching on IDENTITY rather
  // than on "a turn completed" means there is never a moment with two rows or
  // with none: when the real row arrives carrying the same id, this predicate
  // simply goes false. Hidden while searching — a search filters what is
  // stored, and the draft is not.
  const showPlaceholder =
    !searching && draftId != null && !chats.some((c) => c.id === draftId);

  const groups = useMemo(() => {
    const base = groupChats(chats);
    if (!showPlaceholder || draftId == null) return base;
    const placeholder = {
      id: draftId,
      title: "New chat",
      // Unused by this component's rendering; present to satisfy HistoryRow.
      corpus: "budget",
      created_at: "",
      updated_at: "",
      title_is_manual: false,
      message_count: 0,
    } as ReturnType<typeof useHistory>["chats"][number];
    // Inserted AFTER grouping rather than given a fake timestamp and grouped:
    // a synthetic `updated_at` of "now" would be recomputed on every render
    // and is a lie in the data rather than a decision in the view.
    const today = base.find((g) => g.label === "Today");
    if (!today) return [{ label: "Today", chats: [placeholder] }, ...base];
    return base.map((g) =>
      g === today ? { ...g, chats: [placeholder, ...g.chats] } : g,
    );
  }, [chats, showPlaceholder, draftId]);
```

Change the React import at the top of the file to include `useMemo`:

```tsx
import { useEffect, useMemo, useState } from "react";
```

- [ ] **Step 5: Render the placeholder row without actions**

Inside `{group.chats.map((chat) => (` , immediately after the opening `<div key={chat.id} className={...}>`, the whole body currently renders the rename input or the chat button plus the actions. Wrap that body so the placeholder takes a different branch. Replace the contents of that `<div>` with:

```tsx
                  {chat.id === draftId ? (
                    // No button: there is nothing to select (it is already the
                    // current chat) and nothing to open. No rename or delete
                    // either — both address a file that does not exist.
                    <span className="history-rail-chat history-rail-chat-static">
                      <span className="history-rail-chat-title">New chat</span>
                    </span>
                  ) : (
                    <>
                      {/* ...the existing editingId / button / actions body,
                          unchanged, moved inside this fragment... */}
                    </>
                  )}
```

Keep every line of the existing body verbatim inside the `<>...</>` fragment — the rename input branch, the chat button, and the `history-rail-actions` block.

- [ ] **Step 6: Add the one CSS rule**

In `webapp/src/styles/app.css`, immediately after the `.history-rail-chat-snippet{...}` rule:

```css
/* The draft row. Same box as a real chat so the rail does not jump when the
   real row replaces it, but not a button — there is nothing behind it yet. */
.history-rail-chat-static{cursor:default;}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/history-rail-placeholder.test.tsx`
Expected: PASS, 8 tests.

- [ ] **Step 8: Wire `AiModePanel` to compute the two ids**

In `webapp/src/chat/AiModePanel.tsx`, change the `HistoryRail` import to also take the sentinel:

```tsx
import { DRAFT_CHAT_ID, HistoryRail } from "./HistoryRail.js";
```

Add just above the `return (` in `PanelBody`:

```tsx
  // P3: the live id drives the rail's HIGHLIGHT and the placeholder's
  // identity, and is deliberately NOT written back into `selectedChatId` —
  // that value is part of the conversation's React key, so assigning it
  // mid-answer would remount the conversation and wipe the thread the analyst
  // is reading. Same class of bug as the "resumed chat wiped on send" defect
  // fixed 2026-08-03.
  const liveId = chat.state.conversationId;
  // A chat opened from the rail is never a draft: its row is already on disk
  // (or on its way), so treating it as one would flash a placeholder over it.
  const draftId = selectedChatId == null ? liveId ?? DRAFT_CHAT_ID : null;
  const activeId = selectedChatId ?? liveId ?? DRAFT_CHAT_ID;
```

Change the `<HistoryRail ... />` element's `activeId` line and add `draftId`:

```tsx
          activeId={activeId}
          draftId={draftId}
```

- [ ] **Step 9: Run the whole webapp suite and the typecheck**

Run: `cd webapp && ./node_modules/.bin/tsc -b && npx vitest run`
Expected: `tsc` exit 0; all tests pass (693 + 8 = 701).

- [ ] **Step 10: Commit**

```bash
git add webapp/src/chat/HistoryRail.tsx webapp/src/chat/AiModePanel.tsx \
        webapp/src/styles/app.css \
        webapp/src/chat/__tests__/history-rail-placeholder.test.tsx
git commit -m "feat(ai): a new chat appears in the rail immediately (P1-P3)

Client-side placeholder row, never a file: writing an empty transcript
would re-create the zero-message rows deleted as debris on 2026-08-11,
and would contradict H2's browsing-is-free. Replaced by IDENTITY when
the real row lands with the same id, so there is never a moment with two
rows or none. The live id drives the highlight only and is never written
to selectedChatId, which is part of the conversation's key."
```

---

### Task 2: The conversation moves above the router

**Files:**
- Create: `webapp/src/chat/ai-session.tsx`
- Modify: `webapp/src/App.tsx`
- Modify: `webapp/src/pages/Ai.tsx`
- Modify: `webapp/src/pages/Ai.test.tsx`, `webapp/src/pages/Ai.fullpage.test.tsx`
- Test: `webapp/src/chat/__tests__/ai-session-persistence.test.tsx`

**Interfaces:**
- Consumes: `useChat(corpus: Corpus, resumeFrom?: string): UseChatResult` from `./use-chat`; `api.getHistoryChat(id)`; `Corpus` type.
- Produces:
  - `AiSessionProvider({ children }: { children: ReactNode })`
  - `useAiSession(): { corpus: Corpus; setCorpus: (c: Corpus) => void; selectedChatId: string | null; selectChat: (id: string) => void; newChat: () => void; chatDeleted: (id: string) => void }`
  - `useAiChat(): UseChatResult`

- [ ] **Step 1: Write the failing tests**

Create `webapp/src/chat/__tests__/ai-session-persistence.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/ai-session-persistence.test.tsx`
Expected: FAIL — cannot resolve `../ai-session.js`.

- [ ] **Step 3: Create `webapp/src/chat/ai-session.tsx`**

```tsx
// The AI Mode conversation, hoisted ABOVE the router (spec P4).
//
// WHY this exists rather than living in pages/Ai.tsx, where it used to:
// `<Route path="/ai" element={<Ai />} />` unmounts on navigation, and
// `useChat`'s cleanup aborts the SSE read — which the server sees as a client
// disconnect and treats as "tear this turn down". So clicking Budget
// Documents killed a query in flight. A Deep Research turn is ~5 minutes and
// ~$0.56, which is exactly when an analyst wants to go read something else.
//
// Mounting the hook above <Routes> means a route change is no longer an
// unmount, so nothing aborts. CLOSING THE TAB STILL DOES (P5): the page
// unloads, the socket drops, and the server's disconnect path tears the turn
// down exactly as before. That distinction is the whole safety argument — the
// abort-on-close behaviour exists because a closed tab once left a model
// streaming and billing into a dead socket.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as api from "../api";
import { useChat, type Corpus, type UseChatResult } from "./use-chat";

export interface AiSession {
  corpus: Corpus;
  setCorpus: (corpus: Corpus) => void;
  /** The stored chat being viewed, or null for a new one. */
  selectedChatId: string | null;
  selectChat: (id: string) => void;
  newChat: () => void;
  /** Call when a chat is deleted, so the page closes it if it is the open one. */
  chatDeleted: (id: string) => void;
}

const SessionContext = createContext<AiSession | null>(null);
const ChatContext = createContext<UseChatResult | null>(null);

export function AiSessionProvider({ children }: { children: ReactNode }) {
  const [corpus, setCorpus] = useState<Corpus>("budget");
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  // Ratchets on every "+ New chat" so the key changes even when the analyst
  // is ALREADY in a fresh chat — otherwise pressing it twice is a no-op and
  // their view is stuck.
  const [newChatNonce, setNewChatNonce] = useState(0);

  const newChat = useCallback(() => {
    setSelectedChatId(null);
    setNewChatNonce((n) => n + 1);
  }, []);

  // Selecting a stored chat must ALSO move the corpus picker to that chat's
  // corpus: the server adopts the stored corpus on resume regardless of what
  // the client asked for, so a stale picker would have the thread answering
  // out of one corpus while the UI claimed another. The transcript is fetched
  // here rather than trusting the rail row, so the corpus and the rehydration
  // body come from the same read — and a chat we cannot read is never
  // selected at all.
  const selectChat = useCallback((id: string) => {
    void api
      .getHistoryChat(id)
      .then((chat) => {
        setCorpus(chat.corpus as Corpus);
        setSelectedChatId(id);
      })
      .catch(() => {
        /* leave the current view untouched; the rail surfaces the error */
      });
  }, []);

  const chatDeleted = useCallback((id: string) => {
    setSelectedChatId((current) => {
      if (current !== id) return current;
      setNewChatNonce((n) => n + 1);
      return null;
    });
  }, []);

  const session = useMemo<AiSession>(
    () => ({ corpus, setCorpus, selectedChatId, selectChat, newChat, chatDeleted }),
    [corpus, selectedChatId, selectChat, newChat, chatDeleted],
  );

  return (
    <SessionContext.Provider value={session}>
      {/* The key is UNCHANGED from when this lived in pages/Ai.tsx, and it is
          load-bearing: `useChat` reads the corpus only when it lazily creates
          the conversation, so without a remount an analyst who asks a budget
          question and then switches to Fiscal notes keeps sending into the
          BUDGET conversation — cited, confident, and out of the wrong corpus.
          Remounting also resets the tier to Standard, which S16 requires of
          every new conversation. */}
      <AiChatHost
        key={`${corpus}:${selectedChatId ?? "new"}:${newChatNonce}`}
        corpus={corpus}
        resumeFrom={selectedChatId ?? undefined}
      >
        {children}
      </AiChatHost>
    </SessionContext.Provider>
  );
}

/** Owns the hook, so the `key` above is what starts a fresh conversation.
 *  A separate component for the same reason it always was: a key on the
 *  provider would remount the session state too. */
function AiChatHost({
  corpus,
  resumeFrom,
  children,
}: {
  corpus: Corpus;
  resumeFrom?: string;
  children: ReactNode;
}) {
  const chat = useChat(corpus, resumeFrom);
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useAiSession(): AiSession {
  const ctx = useContext(SessionContext);
  if (ctx === null) {
    throw new Error("useAiSession must be used inside <AiSessionProvider>");
  }
  return ctx;
}

export function useAiChat(): UseChatResult {
  const ctx = useContext(ChatContext);
  if (ctx === null) {
    throw new Error("useAiChat must be used inside <AiSessionProvider>");
  }
  return ctx;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/ai-session-persistence.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Verify the abort spec actually arms**

Temporarily move `<AiChatHost>` inside the `<Routes>` element of the test's `App` (i.e. wrap only `<Sender/>`), re-run, and confirm `a route change does not abort the stream` FAILS. Then undo. A spec that cannot fail proves nothing — this is the one that carries P5.

Run: `cd webapp && npx vitest run src/chat/__tests__/ai-session-persistence.test.tsx -t "does not abort"`
Expected while temporarily broken: FAIL. After undoing: PASS.

- [ ] **Step 6: Mount the provider above the routes**

In `webapp/src/App.tsx`, add the import and wrap the body of `AppRoutes`:

```tsx
import { AiSessionProvider } from "./chat/ai-session";
```

```tsx
export function AppRoutes() {
  return (
    // The AI Mode conversation is mounted HERE, above <Routes>, so navigating
    // to another page does not unmount it and does not abort a turn in
    // flight (spec P4/P5). It is inert until the first question.
    <AiSessionProvider>
      <Header />
      <Routes>
        {/* ...every existing <Route .../> unchanged... */}
      </Routes>
    </AiSessionProvider>
  );
}
```

- [ ] **Step 7: Make `pages/Ai.tsx` a view**

Delete the `useState` declarations for `corpus`, `selectedChatId` and `newChatNonce`, the `handleSelectChat` / `handleNewChat` / `handleChatDeleted` functions, the `AiConversation` component, and the `useChat` and `api` imports. Add:

```tsx
import { useAiChat, useAiSession } from "../chat/ai-session";
```

At the top of `export function Ai()`:

```tsx
  // Owned by AiSessionProvider, above the router — see chat/ai-session.tsx.
  // This page renders the conversation; it no longer holds it, which is what
  // lets the conversation outlive a trip to Budget Documents.
  const { corpus, setCorpus, selectedChatId, selectChat, newChat, chatDeleted } =
    useAiSession();
  const chat = useAiChat();
```

Replace the `<AiConversation ... />` element (and its `key`, which now lives on the host) with:

```tsx
          <AiModePanel
            chat={chat}
            status={status}
            corpus={corpus}
            corpusOptions={CORPORA}
            onCorpusChange={setCorpus}
            selectedChatId={selectedChatId}
            onSelectChat={selectChat}
            onNewChat={newChat}
            onDeleteChat={chatDeleted}
          />
```

Keep `useFullPageChatShell()` in this component — the pinned-viewport class must apply only on `/ai`.

- [ ] **Step 8: Update the two page test harnesses**

In `webapp/src/pages/Ai.test.tsx`, change `mountAi`:

```tsx
function mountAi(status = AI_STATUS) {
  vi.spyOn(api, "aiStatus").mockResolvedValue(status);
  return render(
    <MemoryRouter>
      <AiSessionProvider>
        <Ai />
      </AiSessionProvider>
    </MemoryRouter>,
  );
}
```

Add `import { AiSessionProvider } from "../chat/ai-session";` to both
`Ai.test.tsx` and `Ai.fullpage.test.tsx`, and apply the same wrap to every
`render(` call in each file.

- [ ] **Step 9: Run the whole suite and the typecheck**

Run: `cd webapp && ./node_modules/.bin/tsc -b && npx vitest run`
Expected: `tsc` exit 0; all tests pass. The existing corpus-remount specs in
`Ai.test.tsx` must be GREEN without being edited — they are the wrong-corpus
guard, and the hoist must not weaken them.

- [ ] **Step 10: Build, then drive it in a real browser**

```bash
cd webapp && npm run build
cd .. && uv run uvicorn app.main:create_app --factory --port 9300
```

Check by hand, because jsdom applies no stylesheet and every UI defect on this
branch's predecessor was found this way:
1. Press "+ New chat" — a selected "New chat" row appears under Today at once.
2. Ask a question. When the answer lands the row keeps its place and takes a
   real title; there is never a second row.
3. Ask a Deep Research question, and while it is still streaming click Budget
   Documents, wait, then click AI Mode. The answer is there or still arriving.
4. Switch corpus mid-conversation — the thread resets, as it must.
5. Close the tab mid-turn and confirm the server logs the turn ending rather
   than streaming on.

- [ ] **Step 11: Commit**

```bash
git add webapp/src/chat/ai-session.tsx webapp/src/App.tsx webapp/src/pages/Ai.tsx \
        webapp/src/pages/Ai.test.tsx webapp/src/pages/Ai.fullpage.test.tsx \
        webapp/src/chat/__tests__/ai-session-persistence.test.tsx
git commit -m "feat(ai): the conversation survives a tab switch (P4-P7)

useChat moves above <Routes> into AiSessionProvider + AiChatHost, so a
route change is no longer an unmount and no longer aborts the SSE read.
Closing the tab still aborts — that distinction is the safety argument,
since abort-on-close exists because a closed tab once left a model
streaming and billing into a dead socket.

The corpus/chat/nonce key moves with the host unchanged; it is the
wrong-corpus guard, and Ai.test.tsx's existing remount specs pass
untouched."
```

---

## Self-Review

**Spec coverage.** P1 → Task 1 Steps 3–6 (client-side only, no file; pinned by "never asks the server to create anything"). P2 → Step 4's `showPlaceholder` identity predicate, pinned by "the real row REPLACES the placeholder". P3 → Step 8's `liveId`/`draftId`/`activeId`, with the reason in the comment. P4 → Task 2 Steps 3, 6, 7. P5 → Task 2 Step 1's abort spec plus Step 5's verification that it arms; the closed-tab half is pinned by Step 10.5 (manual — jsdom cannot unload a page). P6 → stated in Step 10's browser checks; no code, since the reset is what happens by default. P7 → Task 2's corpus-switch and new-chat specs. P8 → no indicator appears anywhere in this plan.

**Placeholder scan.** Clean. Task 1 Step 5 says "the existing body, unchanged" rather than repeating ~40 lines — that is a move, not an omission, and the surrounding branch is given in full.

**Type consistency.** `DRAFT_CHAT_ID` is exported from `HistoryRail.tsx` in Task 1 and imported by `AiModePanel.tsx` in the same task. `draftId` is `string | null` at every site. `useAiSession` returns `selectChat` / `newChat` / `chatDeleted`; `Ai.tsx` Step 7 passes them as `onSelectChat` / `onNewChat` / `onDeleteChat`, matching `AiModePanel`'s existing prop names. `Corpus` is imported from `./use-chat` in `ai-session.tsx`, the same module `Ai.tsx` imports it from today.

**One risk worth naming for the implementer.** `useChat` now runs on every page, including for an install with no API key. It is inert — the rehydrate effect returns immediately without a `resumeFrom`, and nothing else runs until `send` is called — but if a future change gives it a mount-time fetch, that fetch will fire on Home.
