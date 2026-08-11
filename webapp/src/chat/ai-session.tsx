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
//
// DEVIATION FROM THE PLAN'S SKETCH, and why: the plan drew the remount
// boundary as `AiChatHost` wrapping `Header + <Routes>` directly — i.e. the
// key that resets `useChat` on a corpus/chat switch would sit on the
// component that also renders the whole app. Building that literally and
// running it against Ai.test.tsx showed the real cost: a corpus switch would
// remount not just the conversation but Header and the CURRENT ROUTE too —
// including `Ai.tsx`'s own `useAiStatus()` probe, which has nothing to do
// with the chat. The composer would vanish for a tick while the page
// re-probed "is AI Mode available", and two of Ai.test.tsx's existing
// wrong-corpus-guard specs failed on exactly that (a synchronous
// `getByRole("textbox")` right after the switch found the probing gate
// instead). Those specs are pinned as "must stay green without editing their
// assertions" — so the fix is here, not there.
//
// The narrower boundary below keeps the property P4/P7 actually need — a
// corpus or chat switch still forces `useChat`'s internal state (refs,
// reducer, tier) to fully reset — while everything ELSE in the app (Header,
// the current route, Ai.tsx's own local state) stays mounted and untouched.
// `ChatEngine` is a HEADLESS component (renders null) that owns the `key` and
// therefore owns the reset; it reports its `useChat()` result upward through
// `onChat` into `AiSessionProvider`'s own state, which feeds a STABLE
// `ChatContext.Provider` — stable in IDENTITY, not in value — that wraps
// `children`. Nothing under that provider ever unmounts because of a
// corpus/chat switch; only `ChatEngine` itself does.

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as api from "../api";
import { initialChatState } from "./chat-types";
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

/** A fully-typed stand-in for the instant between `AiSessionProvider`
 *  mounting and `ChatEngine` reporting a real `useChat()` result. It exists so
 *  a consumer rendered in that window gets a typed object instead of `null`,
 *  which would otherwise crash `/ai` on a cold load. `AiSessionProvider`'s own
 *  `chat` state starts here; the context's OWN default stays `null`, so using
 *  either hook truly outside `<AiSessionProvider>` still throws below.
 *
 *  WHY `send`/`stop` SHOUT rather than doing nothing: with the
 *  `useLayoutEffect` mirror below, this placeholder should be genuinely
 *  unreachable — the mirror commits in the SAME commit as the render that
 *  mounted `ChatEngine`, before paint and before any test assertion. So this
 *  is insurance against a FUTURE regression (an early return added to
 *  `ChatEngine`, a dependency dropped from the mirror, an effect that throws),
 *  and the failure it must not produce is a silent one. `send: async () => {}`
 *  resolves successfully having done nothing: no busy state, no error, no
 *  turn — a composer that quietly eats the analyst's question and looks fine.
 *  Throwing makes the same regression a visible crash with a name attached.
 *  An absence must be visible; that is this codebase's standing rule. */
const NOT_MIRRORED =
  "AI Mode: the conversation was never mirrored up from ChatEngine — " +
  "the composer is wired to a placeholder, so nothing was sent. This is a " +
  "bug in chat/ai-session.tsx (see INERT_CHAT), not a server problem.";

const INERT_CHAT: UseChatResult = {
  state: initialChatState,
  send: async () => {
    console.error(NOT_MIRRORED);
    throw new Error(NOT_MIRRORED);
  },
  stop: () => {
    console.error(NOT_MIRRORED);
    throw new Error(NOT_MIRRORED);
  },
  clearError: () => {},
  tier: "standard",
  setTier: () => {},
  busy: false,
  health: null,
};

export function AiSessionProvider({ children }: { children: ReactNode }) {
  const [corpus, setCorpus] = useState<Corpus>("budget");
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  // Ratchets on every "+ New chat" so the key changes even when the analyst
  // is ALREADY in a fresh chat — otherwise pressing it twice is a no-op and
  // their view is stuck.
  const [newChatNonce, setNewChatNonce] = useState(0);
  // The live `useChat()` result, mirrored up from `ChatEngine` below. See the
  // top-of-file deviation note for why this is a mirror rather than a direct
  // call here.
  const [chat, setChat] = useState<UseChatResult>(INERT_CHAT);

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
        setCorpus(chat.corpus);
        setSelectedChatId(id);
      })
      .catch(() => {
        /* leave the current view untouched; the rail surfaces the error */
      });
  }, []);

  // Read `selectedChatId` from the closure rather than from inside a
  // `setSelectedChatId` updater. WHY: React requires a state updater to be
  // PURE, and this used to call `setNewChatNonce` from inside one. StrictMode
  // is on, so in development React invokes the updater twice and the nonce
  // ratcheted twice per delete — harmless in effect (the key changes either
  // way) but a rule violation sitting where the next reader will copy it into
  // somewhere it does matter. The extra `selectedChatId` dependency costs
  // nothing: the `session` memo below already re-creates on that value.
  const chatDeleted = useCallback(
    (id: string) => {
      if (id === selectedChatId) newChat();
    },
    [selectedChatId, newChat],
  );

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
          every new conversation.

          It lives on `ChatEngine`, not on a wrapper around `children` — see
          the top-of-file deviation note for why the boundary is this narrow. */}
      <ChatEngine
        key={`${corpus}:${selectedChatId ?? "new"}:${newChatNonce}`}
        corpus={corpus}
        resumeFrom={selectedChatId ?? undefined}
        onChat={setChat}
      />
      <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>
    </SessionContext.Provider>
  );
}

/** Headless: renders nothing, exists only to own `useChat`'s hook instance
 *  and hand its result upward. Keying THIS component (rather than a wrapper
 *  around `children`) is what confines the reset to `useChat`'s own state —
 *  everything `children` renders (Header, the current route, Ai.tsx's own
 *  local state) sits OUTSIDE this element and never unmounts because of it. */
function ChatEngine({
  corpus,
  resumeFrom,
  onChat,
}: {
  corpus: Corpus;
  resumeFrom?: string;
  onChat: (chat: UseChatResult) => void;
}) {
  const chat = useChat(corpus, resumeFrom);
  // useLayoutEffect, NOT useEffect — and this is the wrong-corpus guard, not a
  // polish detail.
  //
  // On `setCorpus`, `AiSessionProvider` re-renders, `ChatEngine` remounts on
  // its new key, but `<ChatContext.Provider value={chat}>` still carries the
  // OLD `useChat` result until this effect runs and the parent re-renders.
  // A passive `useEffect` is scheduled at normal priority and MAY RUN AFTER
  // PAINT, so a frame can exist in which the picker reads "Fiscal notes" while
  // `chat.send` is still the budget instance's closure — `use-chat.ts` bakes
  // the corpus into `send` via `useCallback(..., [corpus, safeDispatch])`. A
  // keypress in that frame posts into the WRONG CORPUS, cited and confident,
  // which is the worst failure this app has. It did not exist before this
  // refactor: the old `key` on the page's `AiConversation` swapped the hook
  // inside the same commit. `useLayoutEffect` runs synchronously in that same
  // commit, before the browser paints, which restores that property.
  //
  // The dependency list names EVERY FIELD of the result, not just the four
  // that carry values. The four callbacks are identity-stable per hook
  // instance (`send`/`stop`/`clearError` are useCallback, `setTier` is a raw
  // useState setter), so listing them costs nothing today — and it is what
  // makes the mirror correct tomorrow. The `eslint-disable-next-line
  // react-hooks/exhaustive-deps` that used to sit here, over a list of only
  // `state`/`tier`/`busy`/`health`, would have hidden a real regression: make
  // `send` depend on `tier` and the short list keeps silently serving the
  // stale closure.
  //
  // What the list must NOT contain is the whole `chat` object. `useChat`
  // returns a NEW plain object every render, so that entry would fire the
  // effect, call `onChat` (a setState in the parent), re-render this component
  // with a new-but-equivalent object, and fire again — forever. (Observed: the
  // test run hung rather than failing, which is the tell.) Listing the fields
  // instead means the effect is a no-op on a render that changed nothing.
  useLayoutEffect(() => {
    onChat(chat);
  }, [
    onChat,
    chat.state,
    chat.send,
    chat.stop,
    chat.clearError,
    chat.tier,
    chat.setTier,
    chat.busy,
    chat.health,
  ]);
  return null;
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
