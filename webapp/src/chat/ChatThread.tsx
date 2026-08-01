// The scrolling message list plus the single mascot instance that lives
// beside it. Ported from web/components/ChatThread.tsx; layout translated
// from Tailwind utilities to the `.chat-thread*` rules in app.css, behavior
// unchanged.

import { useEffect, useMemo, useRef, useState } from "react";

import { buildConversationResolvedChunkMap } from "./citation-extract.js";
import type { AssistantTurn, ChatState } from "./chat-types.js";
import AssistantTurnBubble from "./AssistantTurnBubble.js";
import UserMessage from "./UserMessage.js";
import WelcomeHero from "./WelcomeHero.js";
import RefusalBanner from "./RefusalBanner.js";
import type { detectRefusal } from "./RefusalBanner.js";
import type { MascotState } from "./mascot/useMascotPose.js";
import Mascot from "./mascot/Mascot.js";
import MascotTyping from "./mascot/MascotTyping.js";
import MascotPresenting from "./mascot/MascotPresenting.js";

/** Below this measured width the chat column can no longer fit the content
 *  measure (--ai-col) PLUS the mascot standing beside it, so the mascot docks
 *  off rather than clipping mid-body against the column edge.
 *
 *  1084 is DERIVED, not eyeballed — the full per-scene derivation lives in
 *  chat-css-contract.test.ts, which also pins this constant.
 *
 *  WHY this is measured in JavaScript and not with a CSS container query:
 *  `container-type` applies layout containment, and a layout-contained element
 *  becomes the containing block for every `position: fixed` descendant. The
 *  citation tooltip is fixed-position precisely so it escapes this scroller's
 *  overflow clip — and it carries the reason a citation FAILED validation, so
 *  clipping it is a Core Invariant 2 failure, not a styling nit. Putting
 *  `container-type` on the scroller (or any ancestor) silently re-clips it.
 *  A ResizeObserver reports the same content-box width a container query
 *  would have, with no containment side effect. */
const MASCOT_DOCK_PX = 1084;

interface Props {
  state: ChatState;
  /** Current mascot scene/pose, decided by useMascotPose() at the page level. */
  mascot: MascotState;
  /** Latest-turn refusal info, computed by AiModePanel. Rendered in the
   *  thread FLOW (after the turns) so it appears via autoscroll when fresh
   *  and scrolls away with history — instead of permanently eating thread
   *  height as panel chrome, which is what it used to do. */
  refusal?: ReturnType<typeof detectRefusal>;
}

export default function ChatThread({ state, mascot, refusal }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const anchorRef = useRef<HTMLDivElement | null>(null);
  // Whether to follow the bottom on new content. Flipped by the handlers
  // below whenever the user scrolls away from the bottom. Held as a ref (not
  // state) so the auto-scroll effect can read the current value without
  // re-rendering when it flips.
  const stickToBottomRef = useRef(true);
  // Mirrors stickToBottomRef into render-visible state, purely to decide
  // whether the jump-to-bottom pill is shown. The ref stays the source of
  // truth the effects read from; this is a display-only shadow of it.
  const [atBottom, setAtBottom] = useState(true);
  // True when the scroller is narrower than MASCOT_DOCK_PX — see that
  // constant for why this is measured here rather than in CSS. Starts false
  // (mascot visible), which is also the state a browser without ResizeObserver
  // keeps: the pre-existing "he might clip" behavior, never a missing mascot.
  const [mascotCramped, setMascotCramped] = useState(false);

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
  //   - SCROLL only ever RE-ENGAGES stickiness: scrolling back within
  //     BOTTOM_REENGAGE_PX of the bottom resumes following. The asymmetry
  //     (break on any scroll-up, narrow window to re-engage) is what stops
  //     the "barely scrolled up but yanked back" behavior.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // 32px, not 5px: wheel physics rarely land a user EXACTLY on the bottom
    // edge, and a re-stick window that narrow made autoscroll feel broken —
    // you returned to the bottom and new messages still didn't follow.
    const BOTTOM_REENGAGE_PX = 32;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distanceFromBottom <= BOTTOM_REENGAGE_PX;
      if (near) stickToBottomRef.current = true;
      // Guarded setState so a wheel burst doesn't re-render per frame.
      setAtBottom((prev) => (prev === near ? prev : near));
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

  // Pin = set scrollTop past the end and let the browser clamp. The old
  // smooth scrollIntoView animated toward the bottom for hundreds of ms,
  // which fought the user's wheel and made the unstick handlers hair-trigger.
  const pin = () => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  // Auto-scroll on every state change, but ONLY when the user is already near
  // the bottom (or hasn't scrolled away). If they scrolled up to read history
  // mid-stream, leave them alone.
  useEffect(() => {
    if (stickToBottomRef.current) pin();
  }, [state.turns, state.isThinking]);

  // Local growth the data layer can't see (a tool row expanding at the
  // bottom) also re-pins — mirror of YouCoded's content ResizeObserver.
  useEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor || typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(() => {
      if (stickToBottomRef.current) pin();
    });
    obs.observe(anchor);
    return () => obs.disconnect();
  }, []);

  // Mascot dock/undock. Watches the SCROLLER's own inline size — a
  // ResizeObserver entry's `contentRect.width` is the observed element's
  // content box, i.e. exactly the number a CSS container query would have
  // reported, so MASCOT_DOCK_PX carries over from the container-query version
  // unchanged. Kept as a separate observer from the re-pin one above so the
  // two concerns stay independently readable.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver((entries) => {
      // contentRect is guaranteed by the spec, but a polyfill or a partial
      // test double can omit it, and a missing measurement must degrade to
      // "leave the mascot as it is" rather than crash the whole thread.
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      const cramped = rect.width < MASCOT_DOCK_PX;
      // Guarded so a drag-resize doesn't re-render the whole thread per frame.
      setMascotCramped((prev) => (prev === cramped ? prev : cramped));
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Sending a message re-arms following — the user asked a question, they
  // want to see the answer arrive.
  const lastTurn = state.turns[state.turns.length - 1];
  useEffect(() => {
    if (lastTurn?.kind === "user") {
      stickToBottomRef.current = true;
      setAtBottom(true);
      pin();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurn?.id]);

  const jumpToBottom = () => {
    stickToBottomRef.current = true;
    setAtBottom(true);
    pin();
  };

  // -- Layout A: welcome ----------------------------------------------------
  // No turns yet and not thinking. Suggestion chips live in SuggestionRow at
  // the page level, above the input bar. Rendered INSIDE the scroller (below)
  // rather than as an early return, so there is exactly one scroll container
  // on the page in every state — see the .chat-thread-scroll CSS contract.
  const isEmpty = state.turns.length === 0 && !state.isThinking;

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
        <div ref={anchorRef} className="chat-thread-anchor">
          {isEmpty ? (
            <WelcomeHero />
          ) : (
            <>
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
                {/* In-flow, not panel chrome: scrolls away with history once a
                    newer turn lands, and appears via the pin-to-bottom effect
                    above like any other new content — instead of permanently
                    eating thread height, which is what it used to do as a
                    sibling of the scroller. */}
                {refusal && <RefusalBanner refusal={refusal} />}
              </div>
              {/* `is-cramped` visually hides (never unmounts) the mascot when
                  the column is too narrow for him — see MASCOT_DOCK_PX. */}
              <div
                className={`chat-mascot-slot is-${scene}${
                  mascotCramped ? " is-cramped" : ""
                }`}
              >
                {scene === "presenting" ? (
                  <MascotPresenting />
                ) : scene === "thinking" ? (
                  <MascotTyping />
                ) : (
                  <Mascot pose={avatarPose} size="small" />
                )}
              </div>
            </>
          )}
        </div>
      </div>
      {/* Only meaningful once there is a thread to scroll back into — the
          welcome state has nothing below the fold to jump to. */}
      {!atBottom && !isEmpty && (
        <button type="button" className="chat-jump" onClick={jumpToBottom}>
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
