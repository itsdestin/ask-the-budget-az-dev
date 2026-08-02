/**
 * The annotation has to survive the trip from the `_done` frame to the
 * turn the renderer reads.
 *
 * This is the seam no component test can cover: `turn_complete` closes the
 * turn, and the annotation arrives one frame LATER on `_done`. A reducer
 * that only writes to an OPEN turn drops every figure chip in production
 * while every unit test stays green.
 */
import { describe, expect, it } from "vitest";
import { chatReducer } from "../chat-reducer.js";
import { initialChatState, type AssistantTurn, type ChatState } from "../chat-types.js";

const ANNOTATION = { figures: [{ text: "$1,000,000", start: 0, end: 10, index: 1,
  verdict: "linked", primary: null, additional: [], derived_from: [] }] };

function openTurn() {
  let s = chatReducer(initialChatState, {
    type: "USER_PROMPT", text: "how much?", clientUuid: "c1", timestamp: 1,
  });
  s = chatReducer(s, {
    type: "ASSISTANT_TEXT", uuid: "u1", text: "It was $1,000,000.", timestamp: 2,
  });
  return s;
}

function lastAssistant(state: ChatState) {
  const turns = state.turns.filter((t) => t.kind === "assistant");
  return turns[turns.length - 1] as AssistantTurn;
}

describe("annotation wiring", () => {
  it("attaches to a turn that turn_complete already closed", () => {
    let s = openTurn();
    // turn_complete: closes the turn, carries no annotation.
    s = chatReducer(s, {
      type: "TURN_COMPLETE", stopReason: "end_turn", uuid: "u1", timestamp: 3,
    });
    expect(lastAssistant(s).isComplete).toBe(true);
    // _done: arrives after, and is the only frame with the annotation.
    s = chatReducer(s, {
      type: "TURN_COMPLETE", stopReason: "end_turn", annotation: ANNOTATION,
      uuid: "done", timestamp: 4,
    });
    expect(lastAssistant(s).annotation).toEqual(ANNOTATION);
  });

  it("a later frame without an annotation does not erase one already set", () => {
    let s = openTurn();
    s = chatReducer(s, {
      type: "TURN_COMPLETE", stopReason: "end_turn", annotation: ANNOTATION,
      uuid: "u1", timestamp: 3,
    });
    s = chatReducer(s, {
      type: "TURN_COMPLETE", stopReason: "end_turn", uuid: "done", timestamp: 4,
    });
    expect(lastAssistant(s).annotation).toEqual(ANNOTATION);
  });

  it("a done frame with no turn at all is still harmless", () => {
    const s = chatReducer(initialChatState, {
      type: "TURN_COMPLETE", stopReason: "end_turn", annotation: ANNOTATION,
      uuid: "done", timestamp: 1,
    });
    expect(s.turns).toEqual([]);
    expect(s.isThinking).toBe(false);
  });
});
