"use client";

import { useEffect, useRef } from "react";

import type { ChatState } from "@/state/chat-types";
import AssistantTurnBubble from "./AssistantTurnBubble";
import UserMessage from "./UserMessage";

interface Props {
  state: ChatState;
}

export default function ChatThread({ state }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on every state change so streaming text + new tool
  // cards stay in view. The browser default `scrollIntoView({block: "end"})`
  // jumps past the input bar; we use a sentinel div instead.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [state.turns, state.isThinking]);

  if (state.turns.length === 0 && !state.isThinking) {
    return (
      <div className="flex-1 flex items-center justify-center text-fg-muted text-sm px-6 py-12">
        <div className="max-w-md text-center">
          <h1 className="text-lg font-bold text-fg mb-2">
            Ask the Budget AZ
          </h1>
          <p>
            Multi-turn Q&amp;A over Arizona state budget documents. Cited
            answers; refusal beats hallucination.
          </p>
          <p className="mt-3 text-xs text-fg-faint">
            Currently the corpus covers a 5-document slice. Volume ingest
            is running separately; recall improves as it lands.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto flex flex-col gap-5">
        {state.turns.map((turn) =>
          turn.kind === "user" ? (
            <UserMessage key={turn.id} turn={turn} />
          ) : (
            <AssistantTurnBubble key={turn.id} turn={turn} />
          ),
        )}
        {state.isThinking && (
          <div className="text-fg-muted text-sm italic px-1">
            Thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
