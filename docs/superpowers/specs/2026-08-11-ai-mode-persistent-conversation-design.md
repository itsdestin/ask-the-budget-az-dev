# AI Mode persistent conversation — design

**Status:** approved in brainstorming 2026-08-11. Planned, built, browser-tested and MERGED the same day (`28567f0`). Current state lives in `STATUS.md`, not here.

**Goal.** Two things an analyst asked for after using the shipped chat history:

1. **"+ New chat" shows up immediately.** The new conversation appears in the
   history rail under *Today*, visibly selected, the moment it is started —
   instead of only after leaving it.
2. **The conversation survives a tab switch.** Clicking Budget Documents or
   Fiscal Notes and coming back leaves the thread as it was, and a query that
   was still running keeps running while you are away.

**Scope discipline.** No indicator of any kind while a turn runs in the
background — asked for explicitly and declined (Destin, 2026-08-11). No
server change. No cross-restart resumption of an in-flight turn. No new
storage.

---

## Context that constrains the design

Each of these changed a decision below. Check them before changing anything
here.

1. **The rail's data is the directory.** `GET /api/history` lists
   `%LOCALAPPDATA%\JLBC-Insight\conversations\`, and decision H1 says the
   directory IS the index — there is deliberately no summary file. So the rail
   can only show what has a file.
2. **A chat gets a file at turn TEARDOWN, not at creation.**
   `persist_turn` runs from `_release_turn`. A conversation that has never
   completed a turn has nothing on disk, by construction.
3. **Browsing is free (H2).** Opening a stored chat creates no server session
   and spends nothing; the session is rebuilt on the first send. "+ New chat"
   creating a server session eagerly would break that property for the same
   reason.
4. **Zero-message transcripts are DEBRIS, and we have the evidence.** On
   2026-08-11 the real history directory held 157 transcripts, 151 of them
   test output, including 20 titled "New chat" with zero messages. They were
   deleted. A design that writes an empty transcript on "+ New chat"
   re-creates exactly that shape. See P1.
5. **The conversation is keyed on `${corpus}:${selectedChatId}:${nonce}`**
   (`webapp/src/pages/Ai.tsx`). That remount is not a re-render hint — it is
   the mechanism that stops a budget conversation answering out of the
   fiscal-note corpus, "cited and confident". Three specs in `Ai.test.tsx`
   fail if it is removed. Anything that writes to `selectedChatId` mid-
   conversation remounts and wipes the thread. See P3.
6. **Leaving `/ai` aborts the turn today, deliberately.** `<Route path="/ai"
   element={<Ai />} />` unmounts on navigation; `useChat`'s cleanup calls
   `abortRef.current?.abort()`. The route closes its generator on client
   disconnect, so the server tears the turn down too. That behaviour exists
   because a closed tab used to leave a model streaming and billing into a
   dead socket — a real defect, fixed in Plan 4. **This design must keep the
   closed-tab case and change only the route-change case.** See P5.
7. **The rail already re-reads on turn end.** `reloadToken`, added
   2026-08-11, bumps when a turn completes. P2 depends on it and adds nothing.
8. **A stopped turn now persists its partial answer.** `_abandon_turn`
   (2026-08-11) records the partial answer and its annotation on the hang-up
   path. So even today a tab switch loses the LIVE turn but keeps what was
   written — which is why this is a UX fix, not a data-loss fix.

---

## Decisions

### P1 — the new-chat row is a CLIENT-SIDE placeholder, never a file

"+ New chat" renders a synthetic row at the top of *Today*, titled
"New chat" and marked active. It is not backed by a transcript, it offers no
rename and no delete, and if the analyst never asks anything it leaves
nothing on disk and nothing to clean up.

**How long it lives, stated exactly, because P4 changes the obvious answer:**
the placeholder lives exactly as long as the conversation it stands for. So it
**survives a tab switch** — the host does not unmount (P4), the draft is still
the current conversation, and a row that vanished on the way to Budget
Documents would contradict the second half of this design. It disappears on a
page reload, on a corpus switch, on opening another chat, or on pressing
"+ New chat" again — every one of which replaces the conversation itself.

**Rejected: write an empty transcript immediately.** It would survive reloads
and other tabs, which is the only thing the placeholder cannot do. It also
re-creates the zero-message rows deleted as debris hours earlier (context 4),
contradicts H2's "browsing is free", and would need its own sweeper. The
capability is not worth the class of bug.

**Rejected: keep the placeholder until reload but still no file.** Strictly
more state for a case nobody described.

### P2 — the placeholder is replaced by IDENTITY, not by timing

A brand-new conversation has **no id at all** until the first send — `useChat`
creates it lazily and the server mints the uuid. So the draft carries a
client-side sentinel (`"draft"`), and the rule reads: the rail shows the
synthetic row while the current conversation is the sentinel, **or** has a
real id that is absent from the list returned by `/api/history`. The sentinel
is never sent to the server and never compared against a stored id. When the
first turn completes, `reloadToken` fires, the real row arrives carrying that
same id, the id is now present, and the synthetic row stops rendering. The
selection is already correct because the highlight keys on the same id.

Matching on identity rather than on "a turn finished" means there is no window
in which both rows exist and no window in which neither does. A timing-based
swap would flicker or double-render under a slow list fetch.

### P3 — the live conversation id is NOT written to `selectedChatId`

The rail's highlight reads `selectedChatId ?? liveConversationId`.
`liveConversationId` is reported upward by `useChat` once the server has
minted one, and is used for the highlight and the P2 identity check only.

Writing it into `selectedChatId` would change the conversation's `key`
(context 5) and remount it mid-answer — wiping the thread the analyst is
watching. This is the same class of bug as the "resumed chat wiped on send"
defect fixed on 2026-08-03, and it is the single easiest way to get this
feature wrong.

### P4 — the conversation moves ABOVE the router

```
AiSessionProvider              corpus, selected chat, nonce   — never remounts
  └ AiChatHost   key=…         useChat + the SSE stream       — remounts on corpus/chat switch
      └ Header + <Routes>      /ai renders the view from context
```

`AiSessionProvider` owns the state that `Ai.tsx` owns today. `AiChatHost`
calls `useChat` and publishes the result through a second context; it renders
its children, so the whole app sits inside it. `/ai` becomes a view that
consumes both contexts instead of owning the hook.

Because the host is above `<Routes>`, navigating to Budget Documents does not
unmount it, `useChat`'s cleanup never runs, `abort()` is never called, and the
turn keeps streaming.

**The `key` must move with the host, not be dropped.** It is still
`${corpus}:${selectedChatId ?? "new"}:${nonce}`, and it still remounts on a
corpus switch — that is context 5's safety mechanism and it survives this
change unchanged.

**Rejected: keep `<Ai />` always mounted and hide it with CSS.** It leaves a
large subtree mounted on every page and leaks `ai-fullpage`'s pinned-viewport
shell — which sets `overflow` on `<html>` — onto pages whose content runs past
one screen. That is the exact bug `useFullPageChatShell` was written to avoid.

**Rejected: buffer frames server-side and re-attach on return.** A genuinely
bigger feature (resumable SSE, a per-conversation frame buffer, a cursor). It
only pays off across a browser restart, which is not what was asked for, and
it would put replay state in the one process the whole office shares.

### P5 — a CLOSED TAB must still abort; only a ROUTE CHANGE must not

The two cases are different and the distinction is the whole safety argument
of context 6. After P4 they are naturally distinguished: a route change no
longer unmounts the host, so nothing aborts; closing the tab or the browser
unloads the page, drops the socket, and the server's disconnect path tears the
turn down exactly as it does today.

No new code is needed to keep the closed-tab behaviour — but a spec must pin
it, because a later refactor that hoists the host differently could silently
lose it, and the symptom (a model billing into a dead socket) is invisible
from the app.

### P6 — what is preserved, stated exactly

**Preserved across a tab switch:** the conversation and its id, every turn in
the thread, the in-flight stream, the tier, and the corpus.

**NOT preserved:** the open PDF source panel, thread scroll position, and
unsent text in the composer. These live in `AiModePanel`, below the router.

Hoisting them too was considered and dropped: it is more surface for less
payoff, and the source panel in particular holds the citation bus, whose
replay semantics would need re-thinking above a router. If the reset turns out
to annoy in use, the panel is the piece to hoist next.

### P7 — switching corpus or opening another chat still ENDS the turn

Both already mean "a different conversation", and both already remount by
`key`. The corpus case is load-bearing (context 5). This design does not
change either, and does not add a confirmation: the analyst chose to go
somewhere else, and `_abandon_turn` now keeps whatever the turn had produced.

### P8 — no background indicator

Asked for explicitly and declined. A turn running while the analyst is on
another tab shows nothing anywhere: no pip on the nav pill, no toast, no
badge. Recorded as a decision so it is not "added back as an improvement" —
the ask was for the conversation to keep working, not to be reported on.

---

## Testing

Webapp-only. **No server change in either half**, so the CLAUDE.md eval rule
does not apply and no eval is run.

The specs that carry the design:

1. **Route change preserves the thread.** Navigate `/ai` → `/search` → `/ai`
   and assert the turns are still there.
2. **An in-flight turn is not aborted by a route change.** The strongest
   spec here: drive a turn, navigate away mid-stream, and assert the abort
   signal never fired and frames still arrive. Verify it FAILS with the host
   under the router, or it proves nothing.
3. **Corpus switch still ends the conversation.** The existing `Ai.test.tsx`
   specs must keep passing through the hoist; they are the wrong-corpus
   guard.
4. **The placeholder appears on "+ New chat"**, under *Today*, selected.
5. **The placeholder is replaced, not duplicated**, when the real row lands
   with the same id.
6. **An abandoned placeholder writes no file** — assert `/api/history` was
   never asked to create anything and the row is simply gone.

---

## Open, deliberately

- **Nothing survives a browser restart mid-turn.** The partial answer is
  persisted by `_abandon_turn`; the turn itself is gone. Resumable SSE is P4's
  rejected option and stays rejected until someone asks for it.
- **The source panel resets** (P6). Revisit only if it annoys in real use.
