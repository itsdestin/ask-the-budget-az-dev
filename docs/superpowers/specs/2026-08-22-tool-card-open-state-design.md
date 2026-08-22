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
