"use client";

import { useState } from "react";

import ChatThread from "@/components/ChatThread";
import Footer from "@/components/Footer";
import MessageInput from "@/components/MessageInput";
import PdfViewer from "@/components/PdfViewer";
import SuggestionRow from "@/components/SuggestionRow";
import Mascot from "@/components/mascot/Mascot";
import type { MascotPose } from "@/components/mascot/types";
import { type MascotState, useMascotPose } from "@/components/mascot/useMascotPose";
import { useCitationSelected } from "@/state/citation-context";
import { useChat } from "@/state/use-chat";

/** True when the mascot state carries a `pose` (the idle/result/refusal/error
 *  variants). Narrows the union so `mascot.pose` is type-safe to read. */
function hasMascotPose(
  m: MascotState,
): m is Extract<MascotState, { pose: MascotPose }> {
  return (
    m.kind === "idle" ||
    m.kind === "result" ||
    m.kind === "refusal" ||
    m.kind === "error"
  );
}

export default function Page() {
  const { state, send, clearError, starting } = useChat();

  // Single decision point for the mascot's scene/pose. The second
  // arg is refusalActive — refusal auto-detection isn't built yet
  // (deferred to Phase 1c WS5), so v1 always passes false.
  const mascot = useMascotPose(state, false);

  // The persistent nook + header mascot need a concrete pose. Only
  // the idle/result/refusal/error variants of MascotState carry a
  // `pose` field, so narrow via the type predicate before reading it;
  // the welcome/thinking/presenting scenes fall back to "clasped".
  const headerPose = hasMascotPose(mascot) ? mascot.pose : "clasped";

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
      {/* ── header ─────────────────────────────────────────────── flex-shrink-0 */}
      <header className="flex-shrink-0 border-b border-edge bg-panel/60 px-4 py-2 text-sm text-fg-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Mascot pose={headerPose} size="chip" />
            <span className="font-serif font-bold text-fg">
              Ask the Budget AZ
            </span>
          </div>
          <div className="flex items-center gap-3">
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
          otherwise. The chat column itself caps content with the
          existing `max-w-3xl mx-auto` inside ChatThread, so it doesn't
          stretch awkwardly when the viewer is closed. */}
      <div className="flex-1 min-h-0 flex flex-row">
        {/* `min-h-0` here is load-bearing: without it the flex-col
            child (ChatThread) doesn't get a bounded height, its
            overflow-y-auto can't engage, and the document body
            scrolls instead — breaking ChatThread's scroll listener
            and the "stop following bottom when user scrolls up"
            UX. See ChatThread.tsx for the corresponding fix on its
            own outer div. */}
        <div
          className={
            // `relative` anchors the absolutely-positioned mascot nook
            // (bottom-left of the chat column) below.
            viewerOpen
              ? "relative flex-1 min-w-0 min-h-0 flex flex-col border-r border-edge"
              : "relative flex-1 min-h-0 flex flex-col"
          }
        >
          {/* Chat column now contains ONLY ChatThread + the nook mascot.
              MessageInput has moved to page level (below this block). */}
          <ChatThread
            state={state}
            mascot={mascot}
          />
          {/* Persistent mascot nook — only shown for the resting
              scenes (idle/result/refusal/error). Hidden during
              welcome/thinking/presenting, which have their own
              centered mascot art. */}
          {hasMascotPose(mascot) && (
            <div className="absolute left-2.5 bottom-2 z-10">
              <Mascot pose={headerPose} size="chip" />
            </div>
          )}
        </div>
        {viewerOpen && (
          <aside className="flex-1 min-w-0 hidden md:flex md:flex-col">
            <PdfViewer />
          </aside>
        )}
      </div>

      {/* ── suggestion row (welcome state only) ───────────────── flex-shrink-0 */}
      {/* Only rendered when there are no turns — disappears as soon as
          the user sends their first message. SuggestionRow is a
          horizontally-scrollable strip pinned above the input bar. */}
      {state.turns.length === 0 && <SuggestionRow onPick={send} />}

      {/* ── message input bar ─────────────────────────────────── flex-shrink-0 */}
      {/* Moved OUT of the chat column so it is structurally pinned at the
          page level, always above the footer. The pl-24 offset that kept
          the input clear of the nook mascot is no longer needed here
          because the nook lives inside the chat column above. */}
      <div className="flex-shrink-0 border-t border-edge bg-panel/60 px-4 py-3">
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
