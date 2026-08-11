// "Can AI answers actually run here?" — asked once per page mount.
//
// Its own module rather than a named export of AiModePanel, because Home
// consumes it and Home has no panel: importing a hook from a component file
// named for a surface the importer doesn't render is the kind of stray edge
// that turns into a circular import later.

import { useEffect, useState } from "react";

import * as api from "../api.js";
import type { AiStatus } from "../api.js";

/** What a failed probe resolves to. It is a real "unavailable" ANSWER, not a
 *  null: a card or a toggle that lit up because a probe errored would promise
 *  a feature the server never claimed. Making failure an answer rather than an
 *  absence is what lets `null` mean "still asking", so the UI can tell the two
 *  apart and not explain a control it has not finished checking. */
const PROBE_FAILED: AiStatus = {
  available: false,
  reason: "the app server could not be reached",
  tiers: {},
  user_usage: { month_usd: null, limit_usd: null, warned: false },
};

/** The last verdict this tab received, from any mount of this hook.
 *
 *  WHY a module-level value rather than per-hook state: the hook had no memory
 *  at all, so every remount went back to `null` — i.e. back to "probing" — for
 *  a network round trip. That was invisible while AI Mode's conversation lived
 *  inside the page and died with it. Now that the conversation survives a trip
 *  to Budget Documents (spec P4), the analyst who does exactly what P4 was
 *  built for — start a Deep Research turn, go read something else, come back —
 *  was shown "Checking whether AI answers are available…" on top of their live
 *  answer. Worse in the tail: a hiccuped probe resolves to a REAL
 *  `PROBE_FAILED` verdict, so they would read "AI Mode is currently
 *  unavailable" while a paid turn streamed invisibly behind it.
 *
 *  Seeding from here renders the previous answer immediately and refreshes
 *  silently. It is deliberately NOT a replacement for the probe — the effect
 *  below still runs on every mount, because a re-probe is how this client
 *  notices an administrator adding an API key without anyone reloading the
 *  page. The first ever load in a tab has no verdict yet, so it starts `null`
 *  and shows the honest probing state, exactly as before. */
let lastVerdict: AiStatus | null = null;

/** Test-only: forget the cached verdict, so a spec starts from a cold tab. */
export function __resetAiStatusCache(): void {
  lastVerdict = null;
}

/** `null` only until this tab has ever had an answer; never null afterwards. */
export function useAiStatus(): AiStatus | null {
  const [status, setStatus] = useState<AiStatus | null>(lastVerdict);
  useEffect(() => {
    let ignore = false;
    const settle = (s: AiStatus) => {
      // The cache is written even when this mount has been superseded: the
      // verdict is a fact about the SERVER, not about this component, and
      // throwing it away would make the next mount probe from cold again.
      lastVerdict = s;
      if (!ignore) setStatus(s);
    };
    api.aiStatus().then(settle, () => settle(PROBE_FAILED));
    return () => {
      ignore = true;
    };
  }, []);
  return status;
}
