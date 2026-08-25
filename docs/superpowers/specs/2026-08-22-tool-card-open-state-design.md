# Tool-card open state survives the move into the bubble — design

2026-08-22. Closes the STATUS.md tool-cards open item: *"A card expanded
mid-search snaps shut when the answer arrives. The card physically moves into
the bubble, so React remounts it and its open state resets. Not data loss; one
click reopens. The fix hoists the open state and is a deliberate deferral, not
an oversight."* State plumbing ONLY — no visual, copy, or TC9 change.

## Problem

While a search is running, the run of tool calls renders as a standalone card
(TC6). When the first answer text arrives, TC1 placement moves that same run
INSIDE the `.chat-bubble` that follows it. The parent DOM element changes, so
React unmounts and remounts `ToolGroup`, and its local `open` state resets to
`false`. An analyst who expanded the card to watch the search sees it snap
shut the instant the answer starts streaming — precisely the moment they were
reading it.

## Evidence (file:line, verified in this worktree)

- `webapp/src/chat/ToolGroup.tsx:25` — `const [open, setOpen] = useState(false)`.
- `webapp/src/chat/AssistantTurnBubble.tsx:187` — the no-text row renders
  `<ToolGroup key={row.tools[0]!.toolUseId} …>` as a direct child of
  `.chat-turn`; line 202 renders the SAME run as a child of the
  `.chat-bubble` div once a text block exists. Same key, different parent —
  React never transfers state across parents, so the key cannot save it.
- `webapp/src/chat/ToolCard.tsx:33` — child rows inside an expanded n≥2 group
  hold their own `useState(false)` and reset identically on the move.
- `webapp/src/chat/ChatThread.tsx:268` — `AssistantTurnBubble` is keyed by
  `turn.id` (chat-types.ts:50: "the uuid of the first block"), which is stable
  for the whole turn. **The bubble component itself survives the transition**;
  only its internal ToolGroup subtree remounts.
- Run identity is stable: `AssistantTurnBubble.tsx:171–181` builds rows by
  accumulating `pendingTools`; a run's FIRST tool block never changes as blocks
  append, and cite blocks are skipped, not boundaries (line 177). So
  `tools[0].toolUseId` names the same run before and after the move.
- n=1 branch (`ToolGroup.tsx:89–119`): renders `ToolBody` directly — no child
  ToolCard, but the group's own `open` is still the expandable state, so the
  lone-running-retrieve case (the COMMON mid-search shape) is affected and is
  fixed by hoisting the group state alone.

## Design

Hoist the open state one level, to `AssistantTurnBubble` — the nearest
ancestor that survives the move — as one keyed map:

- `AssistantTurnBubble` owns `const [openCards, setOpenCards] =
  useState<Record<string, boolean>>({})` plus a stable
  `toggle(key) => setOpenCards(m => ({...m, [key]: !m[key]}))`.
- Keys are namespaced to avoid the n≥2 collision where the group's identity
  (`tools[0].toolUseId`) equals its first child's: group = `"g:" + toolUseId`,
  in-group card = `"c:" + toolUseId`.
- `ToolGroup` gains optional `open?: boolean` / `onToggle?: () => void` and a
  `cardOpen?/onCardToggle?` pass-through; when the props are absent it keeps
  its local `useState` (so `tool-group.test.tsx` / `tool-card.test.tsx`
  fixtures that render it bare stay green unmodified). `ToolCard` gets the
  same optional controlled pair.

Rejected alternatives:

1. **The reducer (`chat-reducer.ts`).** Open/closed is ephemeral view state;
   the reducer's state is the audit-shaped record that history-rehydrate
   reconstructs, and a toggle would dispatch through it and re-render the
   whole thread per click. Wrong layer, larger blast radius.
2. **A React context at ChatEngine/session level.** Buys a lifetime nobody
   asked for (surviving chat switches), costs a provider plus consumer
   plumbing, and the per-turn ancestor already survives the only transition
   in the defect. More machinery for the same observable fix.
3. **Stable key + same tree position.** Impossible: React reconciles by
   position within a parent, and the parent element genuinely changes
   (`.chat-turn` child → `.chat-bubble` child). Keys do not transfer.

Memory: entries are created only on click, keyed by toolUseId, so the map is
bounded by tool calls actually toggled in one turn (≤ the 50-step cap) and is
freed when the bubble unmounts (conversation switch / ChatEngine remount). No
pruning code is needed or wanted.

## Exact files to change

- `webapp/src/chat/AssistantTurnBubble.tsx` — own the map; pass props at both
  render sites (lines ~187 and ~202).
- `webapp/src/chat/ToolGroup.tsx` — optional controlled `open`; thread
  per-child open/toggle to `ToolCard` in the n≥2 branch.
- `webapp/src/chat/ToolCard.tsx` — optional controlled `open`.
- `webapp/src/chat/__tests__/assistant-turn-bubble.test.tsx` — new specs.
- Nothing else. No `chat-reducer.ts`, no `chat-types.ts`, no CSS.

## Test plan

No existing test crosses the mid-search → answered transition — the
"renders a run standalone while no answer text exists yet" spec
(`assistant-turn-bubble.test.tsx:254`) is a single static render, and
history-rehydrate tests are data-level. The new spec uses RTL `rerender` on
one mounted `AssistantTurnBubble`, which mirrors production exactly (the
bubble stays mounted under its stable `turn.id` key). SKETCH — run and
correct, do not transcribe:

```tsx
it("keeps an expanded card open when the answer arrives and the card moves into the bubble", () => {
  const running = { kind: "tool", toolUseId: "toolA", toolName: "retrieve",
    input: { query: "Aviation Fund" }, status: "running" } as const;
  const { container, rerender } =
    render(<AssistantTurnBubble turn={turn({ isComplete: false, blocks: [running] })} />);
  fireEvent.click(screen.getByRole("button", { name: /Searching/ }));
  expect(container.querySelector(".chat-tool-group-expansion")).not.toBeNull();

  rerender(<AssistantTurnBubble turn={turn({ blocks: [
    { ...running, status: "complete" },
    { kind: "text", uuid: "u1", text: "The Aviation Fund total is…" },
  ] })} />);
  const moved = container.querySelector(".chat-bubble .chat-tool-group")!;
  expect(moved).not.toBeNull();                       // it DID move (TC1 intact)
  expect(moved.querySelector(".chat-tool-group-expansion")).not.toBeNull(); // FAILS today
});
```

Verify it RED against current code before implementing (the final assertion
fails: remount resets `open`). Add: (a) an n≥2 variant asserting an expanded
in-group `ToolCard` also survives; (b) a guard that the moved card still
toggles closed on click; (c) collapsed-by-default is untouched (existing
specs already pin it). Mutation check after: revert the hoist in
`AssistantTurnBubble` only — the new specs must go red while every existing
tool-group/tool-card spec stays green.

## UX consequences, plainly

If you click a search card open while the assistant is still searching, it now
stays open when the answer starts appearing — the card slides into the answer
bubble with its contents still showing. Nothing else looks or behaves
differently: cards still start closed, headers read the same, and the
no-alarm collapsed treatment (TC9) is untouched.

## Risks + what NOT to do

- **Do not** move this into the reducer or persist it — an old chat reopening
  with cards pre-expanded would be new (unasked-for) behavior.
- **Do not** touch header copy, glyphs, the TC9 no-failure-signal rule, or
  the TC5 n=1 one-click expansion — this is plumbing only.
- **Known, accepted residue:** deeper per-view state (`RetrieveView.tsx:296`
  `showAll`, `primitives.tsx:194` Disclosure) still resets on the move. That
  is a rarer, second-level interaction; note it, don't chase it here.
- The stable-toggle callback must not recreate per render in a way that
  breaks memoization — `AssistantTurnBubble` is not memoized today, so this
  is a comment-level caution, not work.
- If a future change ever re-orders or re-groups runs mid-turn, `g:` keys
  could attach to a different run; today's grouping (first-id-stable, proven
  above) makes that impossible without a grouping rewrite.

## Amendments (implementation)

Implemented as designed, TDD, in the `easy-wins` worktree. Two review nits
addressed before writing code:

1. **The evidence line "Same key, different parent" was imprecise and was
   NOT copied into any comment.** Checked directly: the standalone-run render
   site (`AssistantTurnBubble.tsx`, the `!row.block` branch) passes
   `key={row.tools[0]!.toolUseId}` on `<ToolGroup>`; the in-bubble render site
   (the same run once a text block exists) passes **no `key` at all** on its
   `<ToolGroup>`. So it's not "same key, different parent" — it's "keyed vs.
   unkeyed, different parent element". The remount mechanism the design
   describes (a genuinely different parent DOM node, so React cannot
   reconcile across the transition regardless of keys) is unaffected by this
   correction; only the sentence describing the evidence was wrong. No
   comment in the implementation repeats that sentence.
2. **The sketch's `getByRole("button", { name: /Searching/ })` was a guess.**
   Read `tool-display.ts::toolHeaderSentence` for the real computed
   accessible name of a running single-tool retrieve run with
   `input: { query: "Aviation Fund" }`: verb `"Searching"`, rest
   `` ` for “Aviation Fund”…` `` (curly quotes, trailing ellipsis, no `more`/
   `then` clause for a single call) — so `ariaLabel` is exactly
   `Searching for “Aviation Fund”…`. The shipped test matches
   `/Searching for “Aviation Fund”…/`, not the bare `/Searching/` guess.

### What was built, exactly as designed

- `AssistantTurnBubble` owns `const [openCards, setOpenCards] =
  useState<Record<string, boolean>>({})` and `toggleCard(key)`. A
  `toolGroupProps(runTools)` helper (plain function, not a hook — recomputed
  per row per render, deliberately not memoized per the design's "comment-
  level caution, not work") builds `{ open, onToggle, cardOpen, onCardToggle
  }` from the run's first tool's `toolUseId`, keyed `` `g:${id}` `` for the
  group and `` `c:${id}` `` per child — passed via `{...toolGroupProps(...)}`
  at both `<ToolGroup>` render sites (the standalone TC6 branch and the
  in-bubble TC1 branch), so the same run resolves to the same map entry on
  either side of the move.
- `ToolGroup` gained optional `open?`/`onToggle?` plus a `cardOpen?:
  (toolUseId: string) => boolean` / `onCardToggle?: (toolUseId: string) =>
  void` pass-through, threaded to each child `ToolCard` in the n≥2 branch.
  Falls back to local `useState` when the controlled props are absent (`??`,
  not `||` — a controlled `open={false}` must win over the fallback).
- `ToolCard` gained the same optional controlled `open?`/`onToggle?` pair
  with the identical `??` fallback rule.
- The n=1 branch needed no separate wiring: `ToolGroup`'s own `open` state
  gates the whole `.chat-tool-group-expansion` regardless of `single`, so
  hoisting the group's state alone covers the lone-running-retrieve case
  (verified by the headline spec, which uses exactly this shape).

### Test plan — delivered as specified, plus what TDD actually showed

- The headline spec matches the sketch's shape (RTL `rerender` from a running
  n=1 turn to an answered one), corrected per nit 2 above. Run RED first
  against unmodified code: **all three new specs failed** (the two `rerender`
  specs on `expected null not to be null`; the third — "still toggles closed
  on click" — on the moved header having no expansion attached to click
  closed in the first place, i.e. the pre-fix defect manifesting three
  different ways). All 10 pre-existing specs in the file stayed green
  throughout.
- (a) n≥2 variant: opens the group, opens the FIRST in-group `ToolCard`,
  moves, asserts both the group's own expansion AND the first child's body
  survive.
- (b) re-toggle after the move: opens, moves, clicks the moved header again,
  asserts the expansion closes — proves the hoisted state is a live toggle,
  not a one-way sticky flag.
- (c) collapsed-by-default: not re-tested here: it is exactly what the 10
  pre-existing specs in this file already pin (e.g. "renders a run standalone
  while no answer text exists yet" renders unopened), and the design says so.
- Mutation check: `toolGroupProps` temporarily replaced with a stub
  returning `{}` (hoist disabled) in `AssistantTurnBubble.tsx` only. Result:
  the 3 new specs went red (same failure shapes as the pre-implementation RED
  run); `tool-group.test.tsx`, `tool-card.test.tsx`, and the 10 pre-existing
  `assistant-turn-bubble.test.tsx` specs all stayed green — confirming the
  mutation isolates exactly the hoist and nothing else. Reverted by hand
  (not `git checkout`) back to the real implementation; re-ran green.
- Full `src/chat` suite (41 files / 446 tests, read-only run, no other test
  file edited) stayed green, including `tool-body.test.tsx` (owned by
  another lane) and the pre-existing bare `ToolGroup`/`ToolCard` fixtures
  with no `open`/`onToggle` props.

No deviations from the design's file list, key scheme, or rejected
alternatives. No visual, copy, or TC9 change was made.
