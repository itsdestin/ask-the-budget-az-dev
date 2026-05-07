"use client";

import ChatThread from "@/components/ChatThread";
import MessageInput from "@/components/MessageInput";
import { useChat } from "@/state/use-chat";

export default function Page() {
  const { state, send, clearError, starting } = useChat();

  return (
    <div className="h-screen flex flex-col bg-canvas">
      <header className="border-b border-edge bg-panel/60 px-4 py-2 text-sm text-fg-2">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <span className="font-bold text-fg">Ask the Budget AZ</span>
          {state.conversationId && (
            <span
              className="text-xs text-fg-muted truncate"
              title={state.conversationId}
            >
              session {state.conversationId.slice(0, 8)}…
            </span>
          )}
        </div>
      </header>

      {state.error && (
        <div className="border-b border-red-400/30 bg-red-400/10 text-red-400 text-sm px-4 py-2">
          <div className="max-w-3xl mx-auto flex items-start gap-3">
            <span className="font-bold">⚠</span>
            <span className="flex-1">{state.error}</span>
            <button
              type="button"
              onClick={clearError}
              className="text-xs underline hover:no-underline"
            >
              dismiss
            </button>
          </div>
        </div>
      )}

      <ChatThread state={state} />

      <MessageInput
        onSubmit={send}
        disabled={
          starting || state.isThinking || state.conversationId === null
        }
        placeholder={
          starting
            ? "Connecting to YouCoded…"
            : state.conversationId
              ? undefined
              : "Couldn't start a conversation. Open YouCoded and reload."
        }
      />
    </div>
  );
}
