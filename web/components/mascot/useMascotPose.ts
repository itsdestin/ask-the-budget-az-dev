"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatState } from "@/state/chat-types";

export type MascotState =
  | { kind: "welcome" }
  | { kind: "idle"; pose: "clasped" }
  | { kind: "thinking" }
  | { kind: "presenting" }
  | { kind: "result"; pose: "clipboard" }
  | { kind: "refusal"; pose: "crossed" }
  | { kind: "error"; pose: "clasped" };

const PRESENTING_MS = 1500;

/**
 * Single decision point for the mascot's pose/scene. Reads chat state
 * plus an explicit refusalActive flag (refusal auto-detection is not
 * built yet — Phase 1c WS5 — so the caller passes false for v1).
 */
export function useMascotPose(state: ChatState, refusalActive: boolean): MascotState {
  // Track the isThinking true->false edge to fire the ~1.5s presenting beat.
  const wasThinking = useRef(false);
  const [presenting, setPresenting] = useState(false);

  useEffect(() => {
    if (wasThinking.current && !state.isThinking && !state.error && !refusalActive) {
      setPresenting(true);
      const t = setTimeout(() => setPresenting(false), PRESENTING_MS);
      wasThinking.current = state.isThinking;
      return () => clearTimeout(t);
    }
    wasThinking.current = state.isThinking;
  }, [state.isThinking, state.error, refusalActive]);

  if (state.error) return { kind: "error", pose: "clasped" };
  if (refusalActive) return { kind: "refusal", pose: "crossed" };
  if (state.isThinking) return { kind: "thinking" };
  if (presenting) return { kind: "presenting" };
  if (state.conversationId === null && state.turns.length === 0) {
    return { kind: "welcome" };
  }
  if (state.turns.some((t) => t.kind === "assistant")) {
    return { kind: "result", pose: "clipboard" };
  }
  return { kind: "idle", pose: "clasped" };
}
