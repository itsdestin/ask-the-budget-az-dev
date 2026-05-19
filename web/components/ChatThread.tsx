"use client";

import { useEffect, useMemo, useRef } from "react";

import { buildConversationResolvedChunkMap } from "@/lib/citation-extract";
import type { AssistantTurn, ChatState } from "@/state/chat-types";
import AssistantTurnBubble from "./AssistantTurnBubble";
import UserMessage from "./UserMessage";
import WelcomeHero from "./WelcomeHero";
import type { MascotState } from "./mascot/useMascotPose";
import Mascot from "./mascot/Mascot";
import MascotTyping from "./mascot/MascotTyping";
import MascotPresenting from "./mascot/MascotPresenting";

interface Props {
  state: ChatState;
  // Current mascot scene/pose, decided by useMascotPose() in page.tsx.
  mascot: MascotState;
}

export default function ChatThread({ state, mascot }: Props) {
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

  // ── Layout A — welcome / centered-scene state ────────────────────────────
  // No turns yet and not thinking: welcome hero (single instance of mascot,
  // centered, inside WelcomeHero). Also used for thinking and presenting.
  if (state.turns.length === 0 && !state.isThinking) {
    // Empty thread: show the welcome hero with mascot + sub-copy.
    // Suggestion chips live in SuggestionRow at the page level (above the input bar).
    return <WelcomeHero />;
  }

  // Thinking or presenting while turns might already exist — centered scene,
  // single instance. Presenting takes priority (it fires on the
  // isThinking true->false edge), then thinking, then fall through to Layout B.
  if (mascot.kind === "presenting" || state.isThinking) {
    return (
      // min-h-0 is load-bearing — see comment in Layout B below.
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center py-4">
        {mascot.kind === "presenting" ? (
          <MascotPresenting />
        ) : (
          <>
            <MascotTyping />
            <span className="font-sans text-fg-muted text-xs mt-2">
              Searching the budget documents…
            </span>
          </>
        )}
      </div>
    );
  }

  // ── Layout B — has-messages, resting state ───────────────────────────────
  // Two-column layout: left column has the persistent "small" mascot
  // (sticky so it stays at top of visible thread as messages scroll),
  // right column has the scrollable message list with speech-bubble styling.
  // Mascot pose comes from the MascotState when it carries one (idle/result/
  // refusal/error), otherwise falls back to "clasped".
  const avatarPose =
    mascot.kind === "idle" ||
    mascot.kind === "result" ||
    mascot.kind === "refusal" ||
    mascot.kind === "error"
      ? mascot.pose
      : "clasped";

  return (
    // outer: full flex-1 column-content area, `relative` so the mascot
    // can absolutely position itself against this box. min-h-0 is
    // load-bearing — without it the scrollable child's overflow-y-auto
    // silently never engages and the page body scrolls instead.
    <div className="flex-1 min-h-0 relative">
      {/* Scrollable messages — span the FULL chat viewport width;
          `max-w-2xl mx-auto` centers the bubbles on the viewport's midline. */}
      <div
        ref={containerRef}
        className="h-full overflow-y-auto py-6 px-4"
      >
        <div className="max-w-2xl mx-auto flex flex-col gap-5">
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
          <div ref={endRef} />
        </div>
      </div>

      {/* Persistent mascot — absolutely positioned at the BOTTOM-LEFT of
          the chat thread, aligned to sit ~8px to the left of the messages'
          left edge. The calc derives from: viewport-center (50%) minus
          half of max-w-2xl (336px) is the messages' left edge; subtract
          another 128px (120px mascot + 8px gap) for the mascot's left. */}
      <div
        className="absolute bottom-2 z-10 left-[calc(50%-464px)]"
      >
        <Mascot pose={avatarPose} size="small" />
      </div>
    </div>
  );
}
