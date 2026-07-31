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

/** `null` while the answer is in flight; never null afterwards. */
export function useAiStatus(): AiStatus | null {
  const [status, setStatus] = useState<AiStatus | null>(null);
  useEffect(() => {
    let ignore = false;
    api.aiStatus().then(
      (s) => {
        if (!ignore) setStatus(s);
      },
      () => {
        if (!ignore) setStatus(PROBE_FAILED);
      },
    );
    return () => {
      ignore = true;
    };
  }, []);
  return status;
}
