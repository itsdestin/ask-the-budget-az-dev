"use client";

// Client-side chat state hook. Talks to /api/conversations and
// /api/conversations/:id/messages, parses the SSE stream, and pumps
// every event into the chat reducer.

import { useCallback, useEffect, useReducer, useRef } from "react";

import type { ProviderEvent } from "@/lib/types";
import { chatActionFromProviderEvent, chatReducer } from "./chat-reducer";
import type { ChatState } from "./chat-types";
import { initialChatState } from "./chat-types";

interface UseChatResult {
  state: ChatState;
  send: (text: string) => void;
  clearError: () => void;
  /** True until /api/conversations has resolved with a conversationId. */
  starting: boolean;
}

export function useChat(): UseChatResult {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const startingRef = useRef(true);
  const startedRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);

  // Lazy-create a conversation on first mount. If creation fails we
  // surface the error via the reducer so the UI can render a banner
  // and a retry path (the user retries by reloading; v1 doesn't have a
  // retry button yet — Phase 1c WS4b polish).
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void (async () => {
      try {
        const resp = await fetch("/api/conversations", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        });
        const body = (await resp.json()) as
          | { conversationId: string }
          | { error: string; message?: string };
        if (!resp.ok || !("conversationId" in body)) {
          const msg =
            "message" in body && body.message
              ? body.message
              : `Couldn't start a conversation (HTTP ${resp.status}).`;
          dispatch({ type: "TURN_ERROR", message: msg });
          startingRef.current = false;
          return;
        }
        conversationIdRef.current = body.conversationId;
        dispatch({
          type: "CONVERSATION_STARTED",
          conversationId: body.conversationId,
        });
      } catch (err) {
        dispatch({
          type: "TURN_ERROR",
          message:
            err instanceof Error
              ? err.message
              : "Couldn't reach the budget app server.",
        });
      } finally {
        startingRef.current = false;
      }
    })();
  }, []);

  const send = useCallback((text: string) => {
    const conversationId = conversationIdRef.current;
    if (!conversationId) {
      dispatch({
        type: "TURN_ERROR",
        message: "Conversation isn't ready yet — try again in a moment.",
      });
      return;
    }
    const clientUuid =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    dispatch({
      type: "USER_PROMPT",
      text,
      clientUuid,
      timestamp: Date.now(),
    });

    void streamTurn(conversationId, text, dispatch);
  }, []);

  const clearError = useCallback(() => {
    dispatch({ type: "CLEAR_ERROR" });
  }, []);

  return {
    state,
    send,
    clearError,
    starting: startingRef.current,
  };
}

/**
 * POST the user message and read SSE-framed ProviderEvents from the
 * response body. Each `data: {json}` line becomes a ChatAction.
 */
async function streamTurn(
  conversationId: string,
  text: string,
  dispatch: React.Dispatch<Parameters<typeof chatReducer>[1]>,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      },
    );
  } catch (err) {
    dispatch({
      type: "CONNECTION_LOST",
      message:
        err instanceof Error ? err.message : "Network error sending message.",
    });
    return;
  }

  if (!resp.ok || !resp.body) {
    dispatch({
      type: "TURN_ERROR",
      message: `Server returned ${resp.status}.`,
    });
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames end on a blank line. Pull each complete frame off the
    // buffer; keep partials for the next chunk.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      handleSseFrame(frame, dispatch);
    }
  }
  // Flush any trailing frame the stream ended without a blank line on.
  if (buffer.trim()) handleSseFrame(buffer, dispatch);
}

function handleSseFrame(
  frame: string,
  dispatch: React.Dispatch<Parameters<typeof chatReducer>[1]>,
): void {
  // Each frame may contain one or more `data:` lines. We only care
  // about the data; ignore comments, event:, id:, retry:.
  const dataLines = frame
    .split(/\r?\n/)
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart());
  if (dataLines.length === 0) return;
  const payload = dataLines.join("\n");

  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch {
    return;
  }

  if (typeof parsed !== "object" || parsed === null) return;
  const obj = parsed as { type?: string; message?: string; code?: string };

  if (obj.type === "_done") {
    // Already-handled — turn_complete fired earlier in the stream.
    return;
  }
  if (obj.type === "_error") {
    dispatch({
      type: "TURN_ERROR",
      message: obj.message ?? "Server error during turn.",
    });
    return;
  }

  const action = chatActionFromProviderEvent(parsed as ProviderEvent);
  if (action) dispatch(action);
}
