// Anti-drift guard: the rail's delayed grace-bump deadline
// (AiModePanel.tsx's TITLE_GRACE_MS) must always exceed the server's own
// title-call timeout (harness/titles.py::_TIMEOUT_S). If a server engineer
// ever raises that constant without knowing this file exists, the client
// would schedule its "catch the title" read BEFORE the server has finished
// trying — titles would land after the last fetch again, silently, exactly
// the bug this whole change exists to close.
//
// Same house pattern as tool-display.test.ts's
// "filter-field copy tables — no drift from harness/tools.py": read the
// Python source at test time rather than hand-copying the number, so a
// future server-side change fails HERE instead of shipping a race quietly.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { TITLE_GRACE_MS } from "../AiModePanel";

describe("TITLE_GRACE_MS tracks harness/titles.py's own timeout", () => {
  const titlesPy = readFileSync(
    resolve(process.cwd(), "../harness/titles.py"),
    "utf-8",
  );

  const match = titlesPy.match(/_TIMEOUT_S\s*=\s*([\d.]+)/);

  it("extracted a sane timeout from harness/titles.py (extraction sanity check)", () => {
    // Without this, a regex that silently matched nothing would make the
    // real assertion below vacuously true — it would compare TITLE_GRACE_MS
    // against `NaN`, and `21000 > NaN` is false, so a broken extraction
    // fails loudly rather than passing for the wrong reason. Still worth a
    // named check: a maintainer reading a failure here should not have to
    // work out on their own whether the regex or the constant moved.
    expect(match).not.toBeNull();
    const seconds = Number(match?.[1]);
    expect(Number.isFinite(seconds)).toBe(true);
    expect(seconds).toBeGreaterThan(0);
  });

  it("schedules its grace-delay bump strictly AFTER the server's own title-call bound", () => {
    const serverTimeoutS = Number(match![1]);
    // generate_title() (harness/titles.py) returns the truncation fallback
    // on every failure path once _TIMEOUT_S elapses — that is the hard upper
    // bound on when the title can still change. The client deadline must sit
    // past it, not merely equal to it: equal would race the HTTP round trip
    // and persist_turn's BackgroundTask queue hop.
    expect(TITLE_GRACE_MS).toBeGreaterThan(serverTimeoutS * 1000);
  });
});
