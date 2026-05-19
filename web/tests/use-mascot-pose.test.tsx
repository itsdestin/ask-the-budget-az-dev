import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import { useMascotPose } from "../components/mascot/useMascotPose";
import type { ChatState } from "../state/chat-types";
import { initialChatState } from "../state/chat-types";

function Probe({ state, refusalActive }: { state: ChatState; refusalActive: boolean }) {
  const m = useMascotPose(state, refusalActive);
  return <span>{m.kind}</span>;
}

function render(state: ChatState, refusalActive = false): string {
  return renderToString(<Probe state={state} refusalActive={refusalActive} />);
}

const base = initialChatState;

describe("useMascotPose", () => {
  it("welcome when there is no conversation and no turns", () => {
    expect(render(base)).toContain("welcome");
  });

  it("idle when a conversation exists, has turns, and is not thinking", () => {
    const state: ChatState = {
      ...base,
      conversationId: "c1",
      turns: [{ kind: "user", id: "u1", text: "hi", pending: false, timestamp: 1 }],
    };
    expect(render(state)).toContain("idle");
  });

  it("thinking when isThinking is true", () => {
    const state: ChatState = { ...base, conversationId: "c1", isThinking: true };
    expect(render(state)).toContain("thinking");
  });

  it("refusal when refusalActive is true (overrides idle)", () => {
    const state: ChatState = { ...base, conversationId: "c1",
      turns: [{ kind: "user", id: "u1", text: "x", pending: false, timestamp: 1 }] };
    expect(render(state, true)).toContain("refusal");
  });

  it("error when state.error is set", () => {
    const state: ChatState = { ...base, conversationId: "c1", error: "boom" };
    expect(render(state)).toContain("error");
  });
});
