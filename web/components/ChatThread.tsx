"use client";

import { useEffect, useMemo, useRef } from "react";

import { buildConversationResolvedChunkMap } from "@/lib/citation-extract";
import type { AssistantTurn, ChatState } from "@/state/chat-types";
import AssistantTurnBubble from "./AssistantTurnBubble";
import UserMessage from "./UserMessage";

interface Props {
  state: ChatState;
}

export default function ChatThread({ state }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Whether to follow the bottom on new content. Flipped by the
  // scroll handler whenever the user scrolls away from the bottom
  // beyond STICKY_THRESHOLD_PX. Held as a ref (not state) so the
  // auto-scroll effect can read the current value without
  // re-rendering when it flips.
  const stickToBottomRef = useRef(true);

  // Build a conversation-wide chunk-id → resolved-metadata map so a
  // cite() that references a chunk from an earlier turn (allowed by
  // the system prompt) still resolves to its doc_id + page in the
  // PdfViewer. Recomputed when turns change; cheap because it's
  // pure walks over already-parsed turn blocks.
  const conversationResolvedChunks = useMemo(() => {
    const assistantTurns = state.turns.filter(
      (t): t is AssistantTurn => t.kind === "assistant",
    );
    return buildConversationResolvedChunkMap(assistantTurns);
  }, [state.turns]);

  // Track user-initiated scroll-up to break the bottom-sticking
  // loop. Approach:
  //
  //   - WHEEL / TOUCHMOVE / ARROW-UP / PAGE-UP / HOME proactively
  //     flip stickToBottomRef = false. We do this BEFORE the scroll
  //     event fires because a programmatic scrollIntoView({behavior:
  //     "smooth"}) animation can drown out a single user wheel-tick
  //     in some browsers — the animation keeps pulling toward the
  //     bottom while the user's wheel-up tries to pull away. By
  //     reacting to the input directly, we exit the loop immediately.
  //   - SCROLL is used ONLY to re-engage stickiness: if the user
  //     manually scrolls back within 5px of the bottom, we resume
  //     following. The asymmetric threshold (proactive break on
  //     any user-scroll-up, narrow window to re-engage) is what
  //     stops the previous "barely scrolled up but yanked back"
  //     behavior the user reported on 2026-05-12.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const BOTTOM_REENGAGE_PX = 5;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distanceFromBottom <= BOTTOM_REENGAGE_PX) {
        stickToBottomRef.current = true;
      }
    }
    function onWheel(e: WheelEvent) {
      if (e.deltaY < 0) stickToBottomRef.current = false;
    }
    let touchStartY = 0;
    function onTouchStart(e: TouchEvent) {
      touchStartY = e.touches[0]?.clientY ?? 0;
    }
    function onTouchMove(e: TouchEvent) {
      const y = e.touches[0]?.clientY ?? 0;
      // Touch-drag DOWN on screen = content scrolls UP visually =
      // "user wants to see history" — break sticking.
      if (y - touchStartY > 5) stickToBottomRef.current = false;
    }
    function onKeyDown(e: KeyboardEvent) {
      if (
        e.key === "ArrowUp" ||
        e.key === "PageUp" ||
        e.key === "Home"
      ) {
        stickToBottomRef.current = false;
      }
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("keydown", onKeyDown);
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  // Auto-scroll on every state change, but ONLY when the user is
  // already near the bottom. If they've scrolled up to read history
  // mid-stream, leave them alone — the previous unconditional
  // scrollIntoView yanked them back every state tick. The browser
  // default `scrollIntoView({block: "end"})` jumps past the input
  // bar; we use a sentinel div instead.
  useEffect(() => {
    if (!stickToBottomRef.current) return;
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
    <div
      ref={containerRef}
      // min-h-0 is load-bearing — flex children default to
      // min-height: auto, which makes overflow-y-auto silently NOT
      // engage when content grows past the parent's bound. Without
      // this, the page body scrolls instead of the chat thread,
      // the scroll listener never fires on the correct element,
      // and "stop following bottom" doesn't work.
      className="flex-1 min-h-0 overflow-y-auto px-4 py-6"
    >
      <div className="max-w-3xl mx-auto flex flex-col gap-5">
        {state.turns.map((turn) =>
          turn.kind === "user" ? (
            <UserMessage key={turn.id} turn={turn} />
          ) : (
            <AssistantTurnBubble
              key={turn.id}
              turn={turn}
              conversationResolvedChunks={conversationResolvedChunks}
            />
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
