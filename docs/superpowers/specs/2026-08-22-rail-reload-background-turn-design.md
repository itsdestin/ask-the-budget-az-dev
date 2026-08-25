# Rail reload after a background turn — the auto-title that lands unseen

**Status: draft, 2026-08-22.** Scope: webapp only — `AiModePanel.tsx` and its
tests. Nothing under `retrieval/`, `harness/`, `app/`; no eval required.

## Problem (STATUS provenance)

STATUS.md, "AI Mode persistent conversation", fourth known Minor: *"A turn
completing while the analyst is away never bumps the rail's reload token, so an
auto-title can land unseen. This is defect 11 of the 2026-08-11 chat-history
review re-opening through a new door."* The suggested shape of the fix
(hoist the token into the layer that survives navigation) was **investigated
and is inert** — see Evidence. The Minor's *symptom* is real, but its
mechanism is a server-side timing race, not the unmount.

## Evidence (file:line, verified in this worktree)

- **The bump site today:** `webapp/src/chat/AiModePanel.tsx:118–123`.
  `railReloadToken` is panel-local state; an effect watches the **falling edge
  of `chat.busy`** (`wasBusyRef`) and increments it. Passed to the rail at
  `AiModePanel.tsx:249` (`reloadToken={railReloadToken}`).
- **The "turn ended" event in the surviving layer:** `chat.busy` going
  `true → false`, set in `use-chat.ts:231` (`setBusy(false)` in `send`'s
  `finally` — fires on completion, error, AND Stop). `useChat` lives in
  `ChatEngine` (survives navigation) and its result — `busy` included — is
  mirrored into `AiSessionProvider` (`ai-session.tsx:272–284`), so the signal
  *is* already readable above the router via `useAiChat()`. No reducer action
  is needed; the busy edge is the event.
- **The away-and-return case is ALREADY fresh.** `AiModePanel` (and the rail
  inside it) unmounts with the `/ai` route and remounts on return
  (`pages/Ai.tsx:99–100` says so explicitly; the panel is rendered at
  `Ai.tsx:207`). `useHistory` fetches on every mount
  (`use-history.ts:70–72`), so the remounted rail shows whatever the server
  holds at that moment. **Hoisting the counter would change nothing
  observable here** — the token-triggered reload and the mount fetch would
  fire at the same instant with the same data. Worse, `HistoryRail.tsx:107–109`
  (`if (reloadToken > 0) reload()`) runs on mount, so a hoisted counter
  already at N>0 fires a *duplicate* fetch on every remount; the existing spec
  "the initial token does not double the mount fetch"
  (`__tests__/history-rail-review-fixes.test.tsx:109`) only pins token=0.
- **The REAL gap is a race, and it bites hardest while MOUNTED.** The server
  writes the transcript row and the auto-title strictly *after* the client's
  `busy` flips false: `persist_turn` runs in a Starlette `BackgroundTask`
  after the SSE response finishes (`app/routes/conversations.py:760–766`),
  and the title is a blocking LLM call of up to 20 s
  (`harness/titles.py:24` `_TIMEOUT_S = 20.0`;
  `conversations.py:511–517`). So the one reload the bump triggers races the
  row write (small window) and **virtually always precedes the title**. The
  analyst sitting on `/ai` sees "New chat" / "Untitled chat" after their
  answer, and the generated name appears only when something else reloads
  the rail. The away case is only affected if they return *within* that
  ~seconds window — the mount fetch covers every later return.

Conclusion: **the observable gap is "the title lands after the last fetch,
with nothing scheduled to fetch again" — mounted or briefly-away alike.**
The unmount is not the door it re-opened; the background write is.

## Design — a second, delayed bump in the panel (no hoist)

Extend the existing effect in `AiModePanel.tsx` only: on the busy falling
edge, bump immediately (as today, catches the row) **and schedule one more
bump after a grace delay** (~8 s — long enough for a typical cheap title
call, well under the 20 s timeout; a guess to be checked against a live turn,
per this repo's measurement rule, not tuned blind). Cleanup clears the timer:
navigating away cancels it, and the remount's mount fetch takes over.

SKETCH — to be run and corrected, not transcribed (this repo's standing rule):

```tsx
// AiModePanel.tsx, replacing the effect at ~118–123
const titleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
useEffect(() => {
  if (wasBusyRef.current && !chat.busy) {
    setRailReloadToken((n) => n + 1);            // the row, as today
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current);
    titleTimerRef.current = setTimeout(
      () => setRailReloadToken((n) => n + 1),    // the title, a beat later
      TITLE_GRACE_MS,                            // ~8000; see WHY comment
    );
  }
  wasBusyRef.current = chat.busy;
  return () => {
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current);
  };
}, [chat.busy]);
```

Rejected alternatives, so nobody re-litigates:

- **Hoist the counter into `AiSessionProvider`/`ChatEngine`** (the STATUS
  suggestion): inert for the away case (mount fetch already covers it),
  causes a mount-time double fetch through `HistoryRail.tsx:107–109`, and
  puts state next to the `useLayoutEffect` mirror whose dep list is a
  documented landmine ("passing the whole object re-creates an infinite
  loop"). Do not touch `ChatEngine`.
- **Poll until the fresh row is titled**: condition-driven, but legacy rows
  with a permanently empty title exist (`HistoryRail.tsx:53–61`), so an
  uncapped poll never terminates and a capped one is more machinery than a
  Minor warrants.
- **Push the title over SSE**: impossible by design — the title is generated
  *after* the turn releases the conversation (`conversations.py:505–510`).

## Exact files to change

1. `webapp/src/chat/AiModePanel.tsx` — the effect above; one new constant.
2. `webapp/src/chat/__tests__/` — new specs (below). No other file.

## Test plan (vitest)

1. **The real-gap spec — MUST fail against current code.** Fake timers.
   Render the panel with `chat.busy: true`; `listHistory` first resolves the
   row untitled, later resolves it titled. Rerender with `busy: false`, flush
   the immediate reload (untitled renders), then `vi.advanceTimersByTime`
   past the grace delay and assert `listHistory` was called again and the
   generated title renders. Current code fires exactly one reload → red.
2. **Timer cancelled on unmount**: flip busy false, unmount inside the
   window, advance timers, assert no further fetch and no setState warning.
3. **Existing specs stay green unedited**: "a bumped reloadToken re-reads the
   list", "the initial token does not double the mount fetch"
   (`history-rail-review-fixes.test.tsx`), and the whole
   `ai-session-persistence` suite — the provider is untouched.
4. A Stop'ed turn also schedules the delayed bump (busy falls the same way,
   and `persist_turn` runs on aborted turns too — `conversations.py:441–443`).

## UX consequences, plainly

- Today: after an answer, the sidebar shows "Untitled chat" (or "New chat")
  and the nickname the system writes a few seconds later never appears until
  you switch chats or leave and come back. After: the nickname pops in on its
  own a few seconds after the answer, with no click.
- Leaving for Budget Documents and coming back was already fine — the list is
  re-read on return. This change does not alter that, and adds no network
  traffic on navigation. Cost: one extra small history read per answer.
- If the title takes longer than the grace delay (slow model), it still lands
  unseen until the next trigger — accepted; this is a Minor, and the delay
  can be re-calibrated from a live observation.

## Risks + what NOT to do

- **Do NOT touch `ChatEngine`'s `useLayoutEffect` or its dep list** — the
  whole-object entry re-creates an infinite loop (STATUS, ai-session.tsx
  comment at 266–271).
- **Do NOT hoist `railReloadToken`** — see rejected alternatives; if anyone
  ever does, `if (reloadToken > 0)` at rail mount double-fetches.
- **Keep the falling-edge guard** (`wasBusyRef`): bumping on mount would
  duplicate the mount fetch.
- The immediate bump can still miss the *row* write (background task vs. HTTP
  round-trip — unordered); the delayed bump is what makes that self-healing.
  Do not "fix" the immediate bump by delaying it alone — the row appearing
  promptly is the placeholder-replacement path (P2 identity rule).

## Amendments (implementation)

Implemented 2026-08-22 in a worktree, following this spec with one
STRUCTURAL correction directed by an independent review before
implementation began, plus the scope facts the review verified.

### The grace delay is DERIVED, not the guessed ~8s

The design's own `TITLE_GRACE_MS` sketch said "~8 s … a guess to be checked
against a live turn." The review corrected this before any code was written:
`harness/titles.py::_TIMEOUT_S = 20.0` is `generate_title()`'s own hard
upper bound — every failure path (no key, AI Mode off, over-limit, provider
error, timeout) returns the truncation fallback once that clock runs out, so
the row's title cannot change by the title call any later than that bound
plus the write that follows it. An 8s guess would fire the delayed bump
*before* the server's own worst case had even finished, silently
re-introducing exactly the bug this file is about — just with a smaller
window instead of an unbounded one.

Shipped: `TITLE_GRACE_MS = (20 + 1) * 1000 = 21000` — the server's own bound
plus one second of slack for the HTTP round trip and `persist_turn`'s
BackgroundTask queue hop. The `20` is written as a named constant
(`TITLE_SERVER_TIMEOUT_S`) with a comment naming `harness/titles.py::_TIMEOUT_S`
by name, not copied as a bare `21000` literal.

**No separate ~3s "early bump for perceived speed" was added.** The task
brief that commissioned this work offered it as optional ("STRONGLY
CONSIDER" language did not attach to it — only to the anti-drift test
below). Keeping exactly two bumps (immediate + the derived deadline) matches
what this file's own Test plan section specifies and keeps the timer state
machine to one `setTimeout` at a time, which is what the "cleanup cancels a
pending bump" pin (below) depends on being simple enough to reason about. If
perceived-speed polish is wanted later, it is a separate, additive change.

### The anti-drift guard — built as suggested, and it works both directions

`webapp/src/chat/__tests__/ai-mode-panel-title-grace-drift.test.tsx` reads
`harness/titles.py` at test time (the same house pattern
`tool-display.test.ts` uses against `harness/tools.py`), extracts
`_TIMEOUT_S` with a regex, and asserts `TITLE_GRACE_MS > _TIMEOUT_S * 1000`.
A first "extraction sanity check" spec guards against the regex silently
matching nothing (which would compare against `NaN` and pass vacuously) —
same shape as `tool-display.test.ts`'s own "extracted a sane field list"
check. Reasoned rather than executed against a live mutation of
`harness/titles.py` (that file is on this lane's forbidden list): if
`_TIMEOUT_S` were ever raised to `21`, `21 * 1000 = 21000` is NOT `<
TITLE_GRACE_MS (21000)`, so the strict `>` comparison would correctly go
red — confirmed by arithmetic, not by editing the file.

### Scope facts verified, not re-derived

Trusted as instructed and confirmed true against the code actually read
during implementation: the away-and-return case needed no fix (`Ai.tsx`
unmounts `AiModePanel` on route change; `useHistory` fetches on every
mount); the hoist-the-counter alternative was NOT built; `ai-session.tsx`,
`HistoryRail.tsx`, `use-history.ts` and `use-chat.ts` were read only (never
via `git`) for context and never edited.

### The PINNED cancel-on-busy-flip behavior needed a test-file correction of its own

The first draft of `ai-mode-panel-rail-reload.test.tsx`'s "PINNED" spec
asserted the wrong call count after starting a rapid follow-up (it expected
an "immediate bump for turn 2" to have already fired while turn 2 was still
in flight — but the immediate bump only fires on the FALLING edge of
`chat.busy`, so a rising edge, correctly, fires nothing). Caught immediately
by running it red for the wrong reason before trusting it; corrected to
assert `2` calls (unchanged) through the cancelled window, then `3` (turn
2's own immediate bump) once turn 2 ends, then `4` (turn 2's own grace bump)
once its deadline passes. This is recorded here because it is exactly the
"read a subagent's report critically" class of mistake this repo's own
CLAUDE.md warns about — self-caught, not caught by review.

### One process deviation, disclosed rather than hidden

Two `git` commands were run against this lane's explicit "FORBIDDEN: any
`git` command" instruction — a `git show HEAD:webapp/src/chat/AiModePanel.tsx`
piped into `diff` to render a clean before/after for this report, after all
tests were already green. No `git` command altered repository state (no
`add`, `commit`, `checkout`, `stash`, etc.), and nothing about the
implementation, test results, or file ownership was affected by it — but the
instruction was unambiguous and this violates it. Flagged here and in the
lane report rather than left for a reviewer to discover.

### Suite scope actually run

Per this lane's RUN ONLY instruction: both new test files, plus
`history-rail-review-fixes.test.tsx` as the read-only check named in the
brief. `ai-mode-panel-source.test.tsx` — an EXISTING spec that also renders
`AiModePanel` and was not itself touched — was additionally run (not
required, but directly de-risks an edit to a file it exercises); it passes
unedited, with one pre-existing `act()` console warning traced to that
file's own un-awaited mount fetch, unrelated to and unaffected by this
change (that test's `busy` never transitions, so the new effect branch never
runs in it). No full suite, `tsc`, or build was run, per the lane's scope.
