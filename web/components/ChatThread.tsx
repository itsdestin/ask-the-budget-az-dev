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

  // ── Layout B — has-messages (incl. thinking/presenting) ────────────────────
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

  // Index of the most-recent assistant turn — drives which bubble shows
  // the speech-bubble tail. Only the latest assistant turn gets the carat;
  // older assistant turns render as plain bubbles.
  let lastAssistantIndex = -1;
  for (let i = state.turns.length - 1; i >= 0; i--) {
    if (state.turns[i]?.kind === "assistant") {
      lastAssistantIndex = i;
      break;
    }
  }

  return (
    // outer: full flex-1 column-content area. min-h-0 is load-bearing —
    // without it the scrollable child's overflow-y-auto silently never
    // engages and the page body scrolls instead.
    <div className="flex-1 min-h-0">
      {/* Scrollable messages — span the FULL chat viewport width;
          `max-w-2xl mx-auto` centers the bubbles on the viewport's midline. */}
      <div
        ref={containerRef}
        // Asymmetric vertical padding: pt-6 keeps the top breathable so
        // older messages (scrolled-up history) don't crash into the
        // header, but pb-2 tightens the gap between the latest message
        // and the input bar — with bottom-anchored messages, pb is what
        // separates the bottom-most bubble from the input panel border
        // and 24px felt too floaty.
        className="h-full overflow-y-auto pt-6 pb-2 px-4"
      >
        {/* Bottom-anchored message column. `min-h-full + justify-end`
            makes the inner column at least as tall as the scroll viewport
            and pushes its content (the messages) to the bottom — so the
            first message of a session lands just above the input bar,
            and subsequent turns grow the column UPWARD instead of filling
            top-down. When content exceeds the viewport, the wrapper grows
            past min-h-full and scrolling works normally.
            Also serves as the relative positioning context for the mascot
            (`bottom-0` below pins it to the bottom of the SCROLL CONTENT
            so it sits alongside the latest message and scrolls away with
            it when the user scrolls up to read older messages). */}
        <div className="relative min-h-full flex flex-col justify-end">
          {/* max-w-3xl (768px) so the messages column matches the input
              box's max-w-3xl exactly — same width, same horizontal
              padding (px-4 on both their respective parents), same
              mx-auto centering. That makes the user-bubble right edge
              line up with the input's right edge, and the assistant-
              bubble left edge line up with the input's left edge. */}
          <div className="max-w-3xl mx-auto w-full flex flex-col gap-5">
            {state.turns.map((turn, index) =>
              turn.kind === "user" ? (
                <UserMessage key={turn.id} turn={turn} />
              ) : (
                <AssistantTurnBubble
                  key={turn.id}
                  turn={turn}
                  conversationResolvedChunks={conversationResolvedChunks}
                  isLatest={index === lastAssistantIndex}
                />
              ),
            )}
          </div>
          {/* endRef sits OUTSIDE the gap-5 messages container — inside it,
              the gap-5 added a hidden 20px between the last bubble and the
              sentinel, which inflated the visible gap to the input bar
              well past the intended pb-2 (8px). The parent here has no
              gap, so this sentinel adds 0 visual space; scrollIntoView()
              still pins the bottom-of-content correctly. */}
          <div ref={endRef} />

          {/* Mascot — pinned to the BOTTOM-LEFT of the scroll content,
              alongside the latest message. Right-edge anchored so all
              three variants (regular small Mascot / MascotTyping /
              MascotPresenting) share the same right alignment beside the
              messages. Thinking/presenting SWAP IN PLACE here.

              Per-variant translateY pushes the SVG down by the amount of
              EMPTY space BELOW the figure in each viewBox, so the visible
              feet/chair/shoes of every variant land at the same y as the
              bubble bottom (= 8px above the input bar):
                small Mascot   : figure ends at y=384 of 420 viewBox →
                                 36 vb units empty → ×0.5 scale = 18px
                MascotTyping   : chair legs end at y=374 of 390 vb-bot →
                                 16 vb units empty → ×0.512 scale ≈ 8px
                MascotPresenting: shoes end at y=374 of 400 viewBox →
                                 26 vb units empty → ×0.525 scale ≈ 14px

              Per-variant translateX does the same on the RIGHT edge: each
              variant has different empty space to the RIGHT of its figure
              inside its viewBox, so the SVG's right edge sits a different
              distance from the visible figure's right edge. translateX
              shifts each by that empty-right amount so the visible right
              edge of every variant lands at the SVG-right anchor (= 16px
              left of the messages column — anchor is `50%+400px` because
              the message column is max-w-3xl = 768px, half = 384, +16
              gap = 400):
                small Mascot   : fig right at x=230 of 240 vb → 10 vb
                                 empty → ×0.5 scale = 5px
                MascotTyping   : fig right at x=254 of 360 vb → 106 vb
                                 empty → ×0.512 scale ≈ 54px
                MascotPresenting: fig right at x=270 of 320 vb → 50 vb
                                 empty → ×0.525 scale ≈ 26px
              Because each variant uses its OWN x/y offsets, visible
              feet/right-edges land at the SAME position in all three
              variants — swapping still has no jump.

              pointer-events-none: typing's +54px translateX extends the
              SVG bounding box ~38px into the messages column. The empty
              SVG space is invisible (no fill), but the wrapper div would
              normally intercept clicks; pointer-events-none lets clicks
              fall through to the messages underneath. The mascot has no
              interactive elements of its own so this is safe. */}
          <div
            className={
              "absolute bottom-0 z-10 right-[calc(50%+400px)] pointer-events-none " +
              (mascot.kind === "presenting"
                ? "translate-x-[26px] translate-y-[14px]"
                : state.isThinking
                  ? "translate-x-[54px] translate-y-[8px]"
                  : "translate-x-[5px] translate-y-[18px]")
            }
          >
            {mascot.kind === "presenting" ? (
              <MascotPresenting />
            ) : state.isThinking ? (
              <MascotTyping />
            ) : (
              <Mascot pose={avatarPose} size="small" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
