// The scroll model: welcome renders inside the ONE scroller; the refusal
// banner is part of the thread flow (scrolls with history) rather than
// permanent chrome; a jump-to-bottom pill appears when scrolled up.
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import ChatThread from "../ChatThread";
import type { AssistantTurn } from "../chat-types";
import type { RefusalReason } from "../RefusalBanner";

const idleMascot = { kind: "idle", pose: "clasped" } as never;

// Minimal fixtures in the same shape as refusal-banner.test.tsx's `turn()` /
// CHUNK builders — duplicated rather than imported because that file exports
// neither, and the two suites test different things (detection logic there,
// layout/scroll behavior here).
const assistantTurnFixture: AssistantTurn = {
  kind: "assistant",
  id: "a1",
  blocks: [{ kind: "text", uuid: "u1", text: "AHCCCS gets $12.3 M." }],
  isComplete: true,
  stopReason: "end_turn",
  timestamp: 1,
};

const refusalFixture: RefusalReason = { kind: "no_retrieval" };

it("empty state renders the welcome INSIDE the thread scroller", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [], isThinking: false, error: null } as never}
      mascot={idleMascot}
    />,
  );
  const scroller = container.querySelector(".chat-thread-scroll")!;
  expect(scroller).not.toBeNull();
  expect(scroller.querySelector(".chat-welcome")).not.toBeNull();
});

it("renders the refusal banner inside the thread column when passed", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
      refusal={refusalFixture}
    />,
  );
  const column = container.querySelector(".chat-thread-column")!;
  expect(column.querySelector(".chat-refusal")).not.toBeNull();
});

it("shows the jump-to-bottom pill only when scrolled away from the bottom", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
    />,
  );
  expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();
  const scroller = container.querySelector(".chat-thread-scroll")!;
  // Simulate being 200px above the bottom.
  Object.defineProperty(scroller, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(scroller, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(scroller, "scrollTop", { value: 400, writable: true, configurable: true });
  fireEvent.scroll(scroller);
  expect(screen.getByRole("button", { name: /Jump to latest/ })).toBeInTheDocument();
});
