// The SSE client behind AI Mode. Ported from web/state/use-chat.ts (the
// retired Next.js app) and reworked for Plan 4's contract.
//
// What changed from the port, and why:
//
//   - LAZY CONVERSATION. The old hook created a conversation on mount, because
//     the whole page WAS the chat. Here AI Mode is a toggle on a page that
//     works fine without it, so a conversation is opened on the first send.
//     Creating one costs a server-side session slot (the registry evicts by
//     MAX_CONVERSATIONS), and most visitors never ask a question.
//   - TIER. Every message carries the tier; the tier is owned here so it can
//     be reset with the conversation (S16: every NEW conversation starts on
//     Standard).
//   - 409 IS NOT AN ERROR. The messages route answers 409 when a turn is
//     already streaming. That is an HTTP-level double-submit, not a model
//     failure, and rendering it as one would teach the analyst to distrust a
//     working system. `send` refuses re-entry outright, so a 409 can only come
//     from a second tab; if it does arrive it is logged and swallowed.
//   - STOP. `stop()` posts to /stop (which is what makes the harness produce
//     the designed abort) and aborts the local read so the UI stops rendering
//     immediately rather than waiting for the server to unwind.
//   - A STREAM THAT JUST ENDS is now reported. The old hook left `isThinking`
//     true forever in that case, which reads as "still working" and disables
//     the composer for good.

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import * as api from "../api.js";
import { chatActionFromProviderEvent, chatReducer } from "./chat-reducer.js";
import type { ChatAction, ChatState } from "./chat-types.js";
import { initialChatState } from "./chat-types.js";
import type { ProviderEvent } from "./provider-events.js";

export type Tier = "standard" | "deep_research";
export type Corpus = "budget" | "fiscal_notes";

export interface UseChatResult {
  state: ChatState;
  /** Ask a question. Returns a promise for tests; callers may ignore it. */
  send: (text: string) => Promise<void>;
  /** Interrupt the turn in flight. No-op when nothing is streaming. */
  stop: () => void;
  clearError: () => void;
  /** Which answer tier the next message will use. */
  tier: Tier;
  setTier: (tier: Tier) => void;
  /** True from the moment a send starts until its turn ends. Drives the
   *  composer's disabled state — the front line against a 409. */
  busy: boolean;
  /** The create-conversation health probe, or null before the first send. */
  health: { ok: boolean; reason?: string } | null;
}

type Dispatch = React.Dispatch<ChatAction>;

export function useChat(corpus: Corpus): UseChatResult {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  // S16: Standard is the default for every new conversation. A conversation
  // lives exactly as long as this hook instance, so initializing here IS the
  // reset — there is no path that re-uses a conversation id across mounts.
  const [tier, setTier] = useState<Tier>("standard");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<UseChatResult["health"]>(null);

  const conversationIdRef = useRef<string | null>(null);
  // Guards re-entry. A ref, not `busy`, because two sends inside one React
  // batch would both read the same stale state value.
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  // Distinguishes "the analyst pressed Stop" from "the network died", which
  // look identical from inside a rejected read().
  const stoppedRef = useRef(false);
  // Set false on unmount so an in-flight stream can't dispatch into a
  // torn-down reducer (React logs that as a warning and the work is wasted).
  const mountedRef = useRef(true);
  // The live tier, readable from the async send body without making `send`
  // depend on it (a changing identity would re-render every consumer).
  const tierRef = useRef<Tier>(tier);
  tierRef.current = tier;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Abandoning the read is enough: Task 8's route closes its generator on
      // client disconnect, so the server tears the turn down on its own.
      abortRef.current?.abort();
    };
  }, []);

  const safeDispatch = useCallback((action: ChatAction) => {
    if (mountedRef.current) dispatch(action);
  }, []);

  const send = useCallback(
    async (text: string): Promise<void> => {
      const question = text.trim();
      if (!question) return;
      // See the 409 note in the header: refusing here is what makes a
      // double-submit impossible from this tab.
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      stoppedRef.current = false;
      setBusy(true);
      try {
        let conversationId = conversationIdRef.current;
        if (!conversationId) {
          try {
            const handle = await api.createConversation(corpus);
            conversationId = handle.conversation_id;
            conversationIdRef.current = conversationId;
            if (mountedRef.current) setHealth(handle.health ?? { ok: true });
            // Resets the timeline — safe here because nothing has been added
            // to it yet for this question (the USER_PROMPT below is the first
            // dispatch of the turn). Doing it the other way round would wipe
            // the question the analyst just typed.
            safeDispatch({ type: "CONVERSATION_STARTED", conversationId });
          } catch (err) {
            // Show the question anyway: MessageInput has already cleared its
            // box, so dropping it here loses the analyst's words outright.
            safeDispatch({
              type: "USER_PROMPT",
              text: question,
              clientUuid: clientId(),
              timestamp: Date.now(),
            });
            safeDispatch({
              type: "TURN_ERROR",
              message:
                err instanceof Error
                  ? err.message
                  : "Couldn't start a conversation.",
            });
            return;
          }
        }
        safeDispatch({
          type: "USER_PROMPT",
          text: question,
          clientUuid: clientId(),
          timestamp: Date.now(),
        });
        await streamTurn(
          conversationId,
          question,
          tierRef.current,
          safeDispatch,
          abortRef,
          stoppedRef,
        );
      } finally {
        inFlightRef.current = false;
        if (mountedRef.current) setBusy(false);
      }
    },
    [corpus, safeDispatch],
  );

  const stop = useCallback(() => {
    if (!inFlightRef.current) return;
    stoppedRef.current = true;
    // Abort first so the screen stops moving the instant the button is
    // pressed; the POST below is what lets the harness unwind properly
    // (cancelled tool results back-filled, retry backoff woken).
    abortRef.current?.abort();
    const conversationId = conversationIdRef.current;
    if (conversationId) {
      void api.stopConversation(conversationId).catch((err: unknown) => {
        // The turn is already stopped locally; a failed stop only means the
        // server may keep streaming into a socket nobody is reading.
        console.warn("[use-chat] stop request failed:", err);
      });
    }
    safeDispatch({
      type: "TURN_COMPLETE",
      stopReason: "user_interrupt",
      uuid: "local-stop",
      timestamp: Date.now(),
    });
  }, [safeDispatch]);

  const clearError = useCallback(
    () => safeDispatch({ type: "CLEAR_ERROR" }),
    [safeDispatch],
  );

  return { state, send, stop, clearError, tier, setTier, busy, health };
}

function clientId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// ---------------------------------------------------------------------------
// The stream
// ---------------------------------------------------------------------------

/**
 * POST the message and read `\n\n`-framed SSE from the response body.
 *
 * `fetch` + ReadableStream rather than EventSource: the contract is a POST
 * with a JSON body, and EventSource can only issue GETs.
 */
async function streamTurn(
  conversationId: string,
  text: string,
  tier: Tier,
  dispatch: Dispatch,
  abortRef: React.MutableRefObject<AbortController | null>,
  stoppedRef: React.MutableRefObject<boolean>,
): Promise<void> {
  const controller =
    typeof AbortController !== "undefined" ? new AbortController() : null;
  abortRef.current = controller;

  let resp: Response;
  try {
    resp = (await fetch(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, tier }),
        ...(controller ? { signal: controller.signal } : {}),
      },
    )) as Response;
  } catch (err) {
    if (stoppedRef.current) return;
    dispatch({
      type: "CONNECTION_LOST",
      message:
        err instanceof Error ? err.message : "Network error sending message.",
    });
    return;
  }

  if (resp.status === 409) {
    // Two turns raced on one conversation — from a second tab, since `send`
    // blocks it here. Not the model's fault and not worth a red banner; just
    // release the thinking state.
    console.warn("[use-chat] a turn is already streaming on this conversation");
    dispatch({
      type: "TURN_COMPLETE",
      stopReason: "duplicate_submit",
      uuid: "local-409",
      timestamp: Date.now(),
    });
    return;
  }

  if (!resp.ok || !resp.body) {
    dispatch({ type: "TURN_ERROR", message: await httpErrorMessage(resp) });
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // "Did the server tell us how this ended?" Anything else — a dropped
  // connection, a crashed worker — must not look like a finished answer.
  let sawTerminal = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames end on a blank line. Pull every COMPLETE frame off the
      // buffer and keep the remainder: a frame routinely arrives split across
      // two network chunks, and parsing half a JSON object throws it away.
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const outcome = handleSseFrame(frame, dispatch);
        if (outcome === "terminal") sawTerminal = true;
        if (outcome === "error") {
          // `_error` is TERMINAL — no `_done` follows it. Stop reading rather
          // than waiting for a frame the contract says will never come.
          return;
        }
      }
    }
    // A last frame the server didn't blank-line-terminate before closing.
    if (buffer.trim()) {
      const outcome = handleSseFrame(buffer, dispatch);
      if (outcome === "terminal" || outcome === "error") sawTerminal = true;
    }
  } catch (err) {
    if (stoppedRef.current) return; // the analyst pressed Stop
    dispatch({
      type: "CONNECTION_LOST",
      message:
        err instanceof Error ? err.message : "The answer stream was cut off.",
    });
    return;
  }

  if (!sawTerminal && !stoppedRef.current) {
    dispatch({
      type: "CONNECTION_LOST",
      message:
        "The answer stream ended before the assistant finished. " +
        "Nothing above is necessarily complete — ask again.",
    });
  }
}

/** Read the backend's own `detail` off a non-streaming failure. FastAPI is
 *  specific ("The question is empty.", "No such conversation."), and a bare
 *  status code would throw that away. */
async function httpErrorMessage(resp: Response): Promise<string> {
  const detail = await resp
    .json()
    .then((b: { detail?: unknown }) =>
      typeof b?.detail === "string" ? b.detail : null,
    )
    .catch(() => null);
  return detail ?? `The server returned ${resp.status}.`;
}

type FrameOutcome = "event" | "terminal" | "error" | "ignored";

/** One SSE frame -> at most one ChatAction. */
function handleSseFrame(frame: string, dispatch: Dispatch): FrameOutcome {
  // A frame may carry several `data:` lines (the SSE spec joins them with
  // newlines). Comments (`:`), `event:`, `id:` and `retry:` are not ours.
  const dataLines = frame
    .split(/\r?\n/)
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart());
  if (dataLines.length === 0) return "ignored";

  let parsed: unknown;
  try {
    parsed = JSON.parse(dataLines.join("\n"));
  } catch {
    return "ignored";
  }
  if (typeof parsed !== "object" || parsed === null) return "ignored";

  const obj = parsed as {
    type?: string;
    message?: string;
    stopReason?: string;
    annotation?: unknown;
  };

  if (obj.type === "_done") {
    // `turn_complete` normally arrived just before this and already closed the
    // turn; dispatching again is a no-op on a closed turn and a safety net if
    // the harness ever ends a turn without one. The figure annotation rides
    // ONLY on this frame, so it is attached here even though the turn is
    // already closed — the reducer merges it onto the closed turn.
    dispatch({
      type: "TURN_COMPLETE",
      stopReason: obj.stopReason ?? "end_turn",
      annotation: obj.annotation,
      uuid: "done",
      timestamp: Date.now(),
    });
    return "terminal";
  }
  if (obj.type === "_error") {
    // VERBATIM. The over-limit refusal arrives here carrying the ledger's own
    // S19 sentence with the real numbers in it; re-deriving that wording in
    // the client is how two parts of one system start telling an analyst two
    // different stories about their own spending.
    dispatch({
      type: "TURN_ERROR",
      message: obj.message ?? "The assistant stopped with an error.",
    });
    return "error";
  }

  const action = chatActionFromProviderEvent(parsed as ProviderEvent);
  if (!action) return "ignored";
  dispatch(action);
  return action.type === "TURN_COMPLETE" ? "terminal" : "event";
}
