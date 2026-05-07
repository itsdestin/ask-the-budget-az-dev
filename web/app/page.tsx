"use client";

import { useState } from "react";

import ChatThread from "@/components/ChatThread";
import MessageInput from "@/components/MessageInput";
import PdfViewer from "@/components/PdfViewer";
import { useCitationSelected } from "@/state/citation-context";
import { useChat } from "@/state/use-chat";

export default function Page() {
  const { state, send, clearError, starting } = useChat();

  // The PDF panel is hidden until the first citation chip is
  // clicked, then stays open for the rest of the session. PdfViewer
  // owns the "which citation is current" state — this flag just
  // controls whether the side column is allocated at all.
  // Open on ANY chip click, even when the citation lacks resolved
  // metadata: the viewer renders a useful empty state in that case
  // ("we couldn't find source metadata for this citation"), which
  // is much better than the click silently doing nothing.
  const [viewerOpen, setViewerOpen] = useState(false);
  useCitationSelected(() => {
    setViewerOpen(true);
  });

  return (
    <div className="h-screen flex flex-col bg-canvas">
      <header className="border-b border-edge bg-panel/60 px-4 py-2 text-sm text-fg-2">
        <div className="flex items-center justify-between">
          <span className="font-bold text-fg">Ask the Budget AZ</span>
          <div className="flex items-center gap-3">
            {viewerOpen && (
              <button
                type="button"
                onClick={() => setViewerOpen(false)}
                className="text-xs text-fg-muted hover:text-fg-2 underline"
                title="Close the source-viewer panel"
              >
                close source panel
              </button>
            )}
            {state.conversationId && (
              <span
                className="text-xs text-fg-muted truncate max-w-[16ch]"
                title={state.conversationId}
              >
                session {state.conversationId.slice(0, 8)}…
              </span>
            )}
          </div>
        </div>
      </header>

      {state.error && (
        <div className="border-b border-red-400/30 bg-red-400/10 text-red-400 text-sm px-4 py-2">
          <div className="flex items-start gap-3">
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

      {/* Two-column when the viewer is open; chat takes the full width
          otherwise. The chat column itself caps content with the
          existing `max-w-3xl mx-auto` inside ChatThread, so it doesn't
          stretch awkwardly when the viewer is closed. */}
      <div className="flex-1 min-h-0 flex flex-row">
        <div
          className={
            viewerOpen ? "flex-1 min-w-0 flex flex-col border-r border-edge" : "flex-1 flex flex-col"
          }
        >
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
        {viewerOpen && (
          <aside className="flex-1 min-w-0 hidden md:flex md:flex-col">
            <PdfViewer />
          </aside>
        )}
      </div>
    </div>
  );
}
