// Rail reload after a background turn — the auto-title that lands unseen.
//
// STATUS.md, "AI Mode persistent conversation", fourth known Minor: a turn
// completing never re-schedules a SECOND rail read, so the server-generated
// title (which lands strictly after the client's `busy` flips false — see
// `harness/titles.py` / `app/routes/conversations.py::persist_turn`, a
// Starlette BackgroundTask) is never seen unless something ELSE happens to
// reload the rail. Design:
// docs/superpowers/specs/2026-08-22-rail-reload-background-turn-design.md.
//
// The fix extends the single existing effect in AiModePanel.tsx (the one
// that bumps `railReloadToken` on the falling edge of `chat.busy`) with a
// SECOND, delayed bump — scheduled just past the server's own title-call
// timeout (`harness/titles.py::_TIMEOUT_S`), so the rail is guaranteed one
// more read after the title has had its full chance to land. See
// ai-mode-panel-title-grace-drift.test.tsx for the anti-drift guard that
// keeps this file's assumed deadline honest against that server constant.

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiModePanel, TITLE_GRACE_MS } from "../AiModePanel";
import { initialChatState, type ChatState } from "../chat-types";
import type { UseChatResult } from "../use-chat";
import * as api from "../../api";
import { stubScrollIntoView } from "../../pages/ai-test-fixtures";

function row(over: Partial<api.HistoryRow> = {}): api.HistoryRow {
  return {
    id: "c1",
    // A real fallback_title() shape (harness/titles.py) — the truncated
    // question — NOT the empty-string / "Untitled chat" case. This is what
    // the row looks like the instant persist_turn's write lands but before
    // the (up to 20s) title call has resolved, which is the exact window
    // this fix targets.
    title: "How much did AHCCCS get in FY2026",
    corpus: "budget",
    created_at: "2026-08-22T10:00:00+00:00",
    updated_at: "2026-08-22T10:00:00+00:00",
    title_is_manual: false,
    message_count: 2,
    ...over,
  };
}

/** Minimal stand-in for useChat()'s return value, matching the shape used by
 *  ai-mode-panel-source.test.tsx. `busy` is the only field this suite drives. */
function fakeChat(busy: boolean, state: ChatState = initialChatState): UseChatResult {
  return {
    state,
    send: async () => {},
    stop: () => {},
    clearError: () => {},
    tier: "standard",
    setTier: () => {},
    busy,
    health: null,
  };
}

function mount(busy: boolean) {
  return render(
    <AiModePanel chat={fakeChat(busy)} status={null} corpus="budget" />,
  );
}

beforeEach(() => {
  stubScrollIntoView();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the delayed rail bump (the real-gap spec)", () => {
  it("re-reads the rail again after the server's title deadline, not just once on turn-end", async () => {
    vi.useFakeTimers();

    const untitled = row();
    const titled = row({ title: "AHCCCS FY 2026 funding" });
    const list = vi
      .spyOn(api, "listHistory")
      // 1) the mount fetch
      .mockResolvedValueOnce({ conversations: [untitled] })
      // 2) the immediate bump on the busy falling edge — the row exists,
      //    persist_turn's write beat the title call, but the title call
      //    itself is still in flight server-side.
      .mockResolvedValueOnce({ conversations: [untitled] })
      // 3) the delayed bump, once the title has had its full chance to land.
      .mockResolvedValue({ conversations: [titled] });

    const { rerender } = mount(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(list).toHaveBeenCalledTimes(1);

    // The turn ends.
    rerender(<AiModePanel chat={fakeChat(false)} status={null} corpus="budget" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(list).toHaveBeenCalledTimes(2);
    // Synchronous query, not findByText/waitFor: under fake timers those use
    // a real polling interval internally and hang until the test's own
    // wall-clock timeout, since nothing advances it. State from the awaited
    // flush above is already committed by this point (house pattern — see
    // Upload.test.tsx's fake-timer specs, which do the same).
    expect(
      screen.getByText("How much did AHCCCS get in FY2026"),
    ).toBeInTheDocument();

    // Nothing is scheduled to fetch again yet — this is exactly the gap the
    // spec describes: the analyst is looking at the untitled row with no
    // second read pending. Against CURRENT (unfixed) code this stays at 2
    // forever, which is what makes this spec the one that must go RED first.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TITLE_GRACE_MS);
    });
    expect(list).toHaveBeenCalledTimes(3);
    expect(screen.getByText("AHCCCS FY 2026 funding")).toBeInTheDocument();
  });
});

describe("the delayed bump's own lifecycle", () => {
  it("cancels the pending grace-delay timer on unmount", async () => {
    vi.useFakeTimers();
    const list = vi
      .spyOn(api, "listHistory")
      .mockResolvedValue({ conversations: [row()] });

    const { rerender, unmount } = mount(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    rerender(<AiModePanel chat={fakeChat(false)} status={null} corpus="budget" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const callsBeforeUnmount = list.mock.calls.length;

    unmount();

    // Advancing well past the grace delay must not fire a fetch against an
    // unmounted tree (which would also throw a setState-after-unmount
    // warning if the timer had survived).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TITLE_GRACE_MS + 5000);
    });
    expect(list.mock.calls.length).toBe(callsBeforeUnmount);
  });

  it("PINNED: a busy flip cancels a still-pending bump — a rapid follow-up cancels the timer, and the NEW turn's end reschedules it", async () => {
    // WHY this is pinned rather than just observed: the effect's cleanup
    // runs on every `chat.busy` dependency change, not only on unmount — so
    // starting a second question before the first turn's grace delay has
    // elapsed cancels that pending timer. This is the ACCEPTED behavior (the
    // design doc's rejected-alternatives section is explicit that a capped
    // poll is "more machinery than a Minor warrants"): the SECOND turn's own
    // end reschedules a fresh grace-delay bump, so nothing is lost — a
    // background turn always gets its own follow-up read, just measured from
    // whichever turn most recently ended. Without this test, a future
    // "fix" that keeps every timer alive (e.g. a list of timers instead of
    // one ref) would silently double-fire without anything failing.
    vi.useFakeTimers();
    const untitled1 = row({ id: "c1", title: "question one" });
    const untitled2 = row({ id: "c1", title: "question two" });
    const titled2 = row({ id: "c1", title: "question two, titled" });
    const list = vi
      .spyOn(api, "listHistory")
      .mockResolvedValueOnce({ conversations: [untitled1] }) // mount
      .mockResolvedValueOnce({ conversations: [untitled1] }) // turn 1 immediate bump
      .mockResolvedValueOnce({ conversations: [untitled2] }) // turn 2 immediate bump
      .mockResolvedValue({ conversations: [titled2] }); // turn 2's grace bump onward

    const { rerender } = mount(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Turn 1 ends — immediate bump (call #2), and schedules a grace-delay
    // bump ~TITLE_GRACE_MS out.
    rerender(<AiModePanel chat={fakeChat(false)} status={null} corpus="budget" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(list).toHaveBeenCalledTimes(2);

    // Well before that timer fires, the analyst asks a rapid follow-up. The
    // RISING edge itself fires no bump (the guard is the FALLING edge only —
    // "Keep the falling-edge guard" from the design doc) but its cleanup
    // cancels turn 1's still-pending grace timer.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TITLE_GRACE_MS / 3);
    });
    rerender(<AiModePanel chat={fakeChat(true)} status={null} corpus="budget" />);
    expect(list).toHaveBeenCalledTimes(2); // rising edge: no bump

    // Advance PAST where turn 1's original deadline would have landed. If
    // the cleanup had NOT cancelled it, this would already be call #3 — the
    // core property this spec pins.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TITLE_GRACE_MS);
    });
    expect(list).toHaveBeenCalledTimes(2); // still 2: turn 1's timer was cancelled, not fired

    // Turn 2 ends — its OWN immediate bump (call #3) fires...
    rerender(<AiModePanel chat={fakeChat(false)} status={null} corpus="budget" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(list).toHaveBeenCalledTimes(3);
    expect(screen.getByText("question two")).toBeInTheDocument();

    // ...and its OWN grace-delay bump (call #4) is what finally lands the
    // generated title — proving the cancellation above did not also cancel
    // this turn's own reschedule.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TITLE_GRACE_MS);
    });
    expect(list).toHaveBeenCalledTimes(4);
    expect(screen.getByText("question two, titled")).toBeInTheDocument();
  });
});
