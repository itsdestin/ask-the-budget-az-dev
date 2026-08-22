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
