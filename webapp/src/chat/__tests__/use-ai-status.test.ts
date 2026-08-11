// Pins `use-ai-status.ts`'s module-level verdict cache DIRECTLY.
//
// WHY this file exists rather than relying on
// `Ai.return-mid-turn.test.tsx`'s two specs: those specs pass even with the
// cache deleted, because `Ai.tsx`'s own `hasConversation` guard is ALSO
// sufficient to keep the gate off a conversation that already has an answer
// on screen — see that file's header comment. So a reviewer who deletes the
// cache (its only visible cost is the cross-spec leak Finding 3 found) would
// see every existing suite stay green. This test bypasses `Ai.tsx` entirely
// and calls the hook straight, so it fails for exactly the reason the cache
// exists: a second mount, with a probe that never settles, must not read as
// "still probing" if an earlier mount in this tab already got an answer.
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api";
import { useAiStatus } from "../use-ai-status";
import { AI_STATUS } from "../../pages/ai-test-fixtures";

// The global reset in `test-setup.ts` already clears the cache before this
// test runs; restated here so the test is legible on its own (and so it
// stays correct if the global reset is ever narrowed to specific files).
beforeEach(() => vi.restoreAllMocks());

it("seeds a remount from the last verdict instead of restarting at null", async () => {
  // First mount: a real probe settles with a real verdict.
  vi.spyOn(api, "aiStatus").mockResolvedValueOnce(AI_STATUS);
  const first = renderHook(() => useAiStatus());
  await waitFor(() => expect(first.result.current).not.toBeNull());
  first.unmount();

  // Second mount — the "come back to /ai" case — fires its OWN probe, and
  // that probe never settles (server down without actively refusing the
  // connection). Without the module-level cache, `useState<AiStatus |
  // null>(null)` is this mount's seed and `status` stays null for as long as
  // the test lets it run: `probing` reads true on the very first render.
  vi.spyOn(api, "aiStatus").mockReturnValue(new Promise<api.AiStatus>(() => {}));
  const second = renderHook(() => useAiStatus());

  // Asserted synchronously, with no `waitFor` — the whole point is that the
  // cached verdict is present on the FIRST render, before the (never-settling)
  // effect has any chance to run.
  expect(second.result.current).not.toBeNull();
  expect(second.result.current).toEqual(AI_STATUS);
});
