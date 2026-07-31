// The scrolling message list plus the single mascot instance that lives
// beside it. Ported from web/components/ChatThread.tsx; layout translated
// from Tailwind utilities to the `.chat-thread*` rules in app.css, behavior
// unchanged.

import { useEffect, useMemo, useRef } from "react";

import { buildConversationResolvedChunkMap } from "./citation-extract.js";
import type { AssistantTurn, ChatState } from "./chat-types.js";
import AssistantTurnBubble from "./AssistantTurnBubble.js";
import UserMessage from "./UserMessage.js";
import WelcomeHero from "./WelcomeHero.js";
import type { MascotState } from "./mascot/useMascotPose.js";
import Mascot from "./mascot/Mascot.js";
import MascotTyping from "./mascot/MascotTyping.js";
import MascotPresenting from "./mascot/MascotPresenting.js";

interface Props {
  state: ChatState;
  /** Current mascot scene/pose, decided by useMascotPose() at the page level. */
  mascot: MascotState;
}

export default function ChatThread({ state, mascot }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Whether to follow the bottom on new content. Flipped by the handlers
  // below whenever the user scrolls away from the bottom. Held as a ref (not
  // state) so the auto-scroll effect can read the current value without
  // re-rendering when it flips.
  const stickToBottomRef = useRef(true);

  // Conversation-wide chunk-id -> resolved-metadata map, so a cite() that
  // references a chunk from an earlier turn (which the system prompt allows)
  // still resolves to its doc_id + page for the source viewer. Cheap — pure
  // walks over already-parsed turn blocks.
  const conversationResolvedChunks = useMemo(() => {
    const assistantTurns = state.turns.filter(
      (t): t is AssistantTurn => t.kind === "assistant",
    );
    return buildConversationResolvedChunkMap(assistantTurns);
  }, [state.turns]);

  // Track user-initiated scroll-up to break the bottom-sticking loop:
  //
  //   - WHEEL / TOUCHMOVE / ARROW-UP / PAGE-UP / HOME proactively set
  //     stickToBottom = false. This happens BEFORE the scroll event fires,
  //     because a programmatic scrollIntoView({behavior:"smooth"}) animation
  //     can drown out a single wheel-tick — the animation keeps pulling
  //     toward the bottom while the user's wheel-up tries to pull away.
  //     Reacting to the INPUT exits the loop immediately.
  //   - SCROLL only ever RE-ENGAGES stickiness: scrolling back within 5px of
  //     the bottom resumes following. The asymmetry (break on any scroll-up,
  //     narrow window to re-engage) is what stops the "barely scrolled up but
  //     yanked back" behavior.
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
      // Touch-drag DOWN on screen = content scrolls UP visually = "user wants
      // to see history" — break sticking.
      if (y - touchStartY > 5) stickToBottomRef.current = false;
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "Home") {
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

  // Auto-scroll on every state change, but ONLY when the user is already near
  // the bottom. If they scrolled up to read history mid-stream, leave them
  // alone. A sentinel div is used because the browser default
  // scrollIntoView({block:"end"}) jumps past the input bar.
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [state.turns, state.isThinking]);

  // -- Layout A: welcome ----------------------------------------------------
  // No turns yet and not thinking. Suggestion chips live in SuggestionRow at
  // the page level, above the input bar.
  if (state.turns.length === 0 && !state.isThinking) {
    return <WelcomeHero />;
  }

  // -- Layout B: has messages (incl. thinking/presenting) -------------------
  // Mascot pose comes from the MascotState when it carries one, otherwise
  // falls back to "clasped".
  const avatarPose =
    mascot.kind === "idle" ||
    mascot.kind === "result" ||
    mascot.kind === "refusal" ||
    mascot.kind === "error"
      ? mascot.pose
      : "clasped";

  // Index of the most-recent assistant turn — drives which bubble gets the
  // speech-bubble tail.
  let lastAssistantIndex = -1;
  for (let i = state.turns.length - 1; i >= 0; i--) {
    if (state.turns[i]?.kind === "assistant") {
      lastAssistantIndex = i;
      break;
    }
  }

  // Which mascot scene renders, and which offset class positions it. The
  // three scenes have different empty space inside their viewBoxes, so each
  // needs its own nudge to land its visible feet in the same spot — see the
  // .chat-mascot-slot rules in app.css.
  const scene = mascot.kind === "presenting"
    ? "presenting"
    : state.isThinking
      ? "thinking"
      : "idle";

  return (
    <div className="chat-thread">
      <div ref={containerRef} className="chat-thread-scroll">
        <div className="chat-thread-anchor">
          <div className="chat-thread-column">
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
          {/* The sentinel sits OUTSIDE the gap-bearing column: inside it, the
              column gap added invisible space between the last bubble and the
              sentinel, inflating the visible gap to the input bar. */}
          <div ref={endRef} />

          <div className={`chat-mascot-slot is-${scene}`}>
            {scene === "presenting" ? (
              <MascotPresenting />
            ) : scene === "thinking" ? (
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
