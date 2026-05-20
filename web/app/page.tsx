"use client";

import { useState } from "react";

import ChatThread from "@/components/ChatThread";
import Footer from "@/components/Footer";
import MessageInput from "@/components/MessageInput";
import PdfViewer from "@/components/PdfViewer";
import SuggestionRow from "@/components/SuggestionRow";
import SystemHealthBanner from "@/components/SystemHealthBanner";
import { useMascotPose } from "@/components/mascot/useMascotPose";
import { useCitationSelected } from "@/state/citation-context";
import { useChat } from "@/state/use-chat";

export default function Page() {
  const { state, send, clearError, starting, health } = useChat();

  // Single decision point for the mascot's scene/pose. The second
  // arg is refusalActive — refusal auto-detection isn't built yet
  // (deferred to Phase 1c WS5), so v1 always passes false.
  // The mascot is now a SINGLE instance that lives inside ChatThread —
  // no header chip and no nook mascot. page.tsx only passes the state down.
  const mascot = useMascotPose(state, false);

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
    <div className="h-screen overflow-hidden flex flex-col bg-canvas">
      {/* ── header ─────────────────────────────────────────────── flex-shrink-0
           3-col grid so the brand is centered in the viewport while the
           right-side controls stay right-aligned. */}
      <header className="flex-shrink-0 border-b border-edge bg-panel/60 px-4 py-2 text-sm text-fg-2">
        <div className="grid grid-cols-3 items-center">
          <div />
          <div className="flex justify-center">
            <span className="font-serif font-bold text-fg">
              Ask the Budget AZ
            </span>
          </div>
          <div className="flex justify-end items-center gap-3">
            {viewerOpen && (
              <button
                type="button"
                onClick={() => setViewerOpen(false)}
                className="border border-edge rounded px-2 py-0.5 text-xs hover:bg-panel"
                title="Close the source-viewer panel"
              >
                close source panel
              </button>
            )}
            {/* Session-id chip removed — it's an internal identifier with no
                value to an analyst at-a-glance and just adds header clutter.
                state.conversationId is still tracked in state and used
                everywhere it's actually needed (audit log writes, debugging,
                conversation continuation), it's just not surfaced in the UI. */}
          </div>
        </div>
      </header>

      {/* ── sidecar health banner (conditional) ─────────────────── flex-shrink-0
           Surfaced from the /api/conversations response, which carries the
           probe result from YouCodedSessionProvider.startConversation
           (Decision Q1). Shown BEFORE the user types their first question
           so they don't discover a dead sidecar mid-answer. */}
      {health && !health.ok && (
        <div className="flex-shrink-0">
          <SystemHealthBanner reason={health.reason} />
        </div>
      )}

      {/* ── error banner (conditional) ─────────────────────────── flex-shrink-0 */}
      {state.error && (
        <div className="flex-shrink-0 border-b border-red-400/30 bg-red-400/10 text-red-400 text-sm px-4 py-2">
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

      {/* ── main content — flex-1, two-column when PDF viewer is open ─────────── */}
      {/* Two-column when the viewer is open; chat takes the full width
          otherwise. ChatThread internally handles a left-mascot / right-messages
          split for Layout B (has-messages), or a centered layout for welcome/
          thinking/presenting scenes. */}
      <div className="flex-1 min-h-0 flex flex-row">
        {/* `min-h-0` here is load-bearing: without it the flex-col
            child (ChatThread) doesn't get a bounded height, its
            overflow-y-auto can't engage, and the document body
            scrolls instead — breaking ChatThread's scroll listener
            and the "stop following bottom when user scrolls up"
            UX. See ChatThread.tsx for the corresponding fix on its
            own outer div. */}
        {/* The chat column no longer needs `relative` since the nook mascot
            is gone — the single mascot instance lives inside ChatThread. */}
        <div
          className={
            viewerOpen
              ? "flex-1 min-w-0 min-h-0 flex flex-col border-r border-edge"
              : "flex-1 min-h-0 flex flex-col"
          }
        >
          <ChatThread
            state={state}
            mascot={mascot}
          />
        </div>
        {viewerOpen && (
          <aside className="flex-1 min-w-0 hidden md:flex md:flex-col">
            <PdfViewer />
          </aside>
        )}
      </div>

      {/* ── suggestion chips (welcome only) — float on the canvas above
            the input bar, NOT inside its container. No border/background
            of their own; they just sit on the chat canvas. ────────── */}
      {state.turns.length === 0 && (
        <div className="flex-shrink-0">
          <SuggestionRow onPick={send} />
        </div>
      )}

      {/* ── input bar — its own bordered/panel container. ─────────────── */}
      <div className="flex-shrink-0 border-t border-edge bg-panel/60 px-4 pt-2 pb-2">
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

      {/* ── footer ─────────────────────────────────────────────── flex-shrink-0 */}
      <Footer connected={state.error === null} />
    </div>
  );
}
