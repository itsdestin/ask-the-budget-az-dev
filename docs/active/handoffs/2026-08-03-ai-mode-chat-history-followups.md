# AI Mode Chat History — Follow-up Session Handoff

> **RESOLVED — 2026-08-03 (later session).** Everything this handoff listed as
> outstanding is now committed and merged:
> - The two uncommitted defensive fixes (rail CSS, empty-title fallback) are
>   commits `0363d27` and `55037b4`.
> - **Issue 1** (citations unlink after switching sessions) — `9d73754`
>   (server: annotation rides the assistant message) and `9645e9c` (client:
>   `rehydrateTurns` restores it). *One hole remains from the commit review:
>   the INTERRUPT path skips `_attach_annotation` — tracked in the
>   "AI Mode chat history" section of STATUS.md.*
> - **Issue 2** ("+ New chat" no-op) — `6f35f7e` (the nonce).
> - **Issue 3** (design audit) — committed as
>   `docs/superpowers/investigations/2026-08-03-ai-mode-design-audit.md`.
> - A NEW bug reported by Destin (a resumed chat's transcript vanished on the
>   first send — `conversationIdRef` was never seeded, so
>   `CONVERSATION_STARTED` reset the timeline) was fixed in `fec29ed`, and
>   four further review fixes landed in `d97ebd5` and `4600282`.
> - Current status lives in STATUS.md → "AI Mode chat history". This file is
>   now a historical record of what that session was asked to do.

**Date:** 2026-08-03 (session reviewing the 2026-08-02 chat-history implementation)
**Branch:** `chat-history`
**Worktree:** `/home/destin/ask-the-budget-az-worktrees/chat-history`
**Prior handoff:** [`docs/active/handoffs/2026-08-02-chat-history-implementation.md`](2026-08-02-chat-history-implementation.md) — read this first; it details the 10 commits, the architecture, and the design decisions that are load-bearing here.

---

## Where things stand right now

The chat-history feature is **working** — the bug that made the app "not work at all" was a single missing CSS block, since fixed. What's merged into the `chat-history` branch and verified:

- Backend: transcript store, persistence, routes, search, auto-naming, resume — all passing (2220 pytest, 605 vitest).
- Frontend: rail, lazy rehydration, resume — all passing.
- **Two uncommitted fixes from this session** (NOT yet committed, NOT yet pushed):
  1. The rail's layout CSS was missing entirely (`ai-panel-layout` + all `history-rail-*` styles) — this was the "didn't work at all" failure. Added in `webapp/src/styles/app.css`.
  2. Empty-title chats rendered as blank "ghost rows" still carrying edit/delete buttons — fixed with a `displayTitle()` fallback ("Untitled chat") in `webapp/src/chat/HistoryRail.tsx` + a new test.

  Status: `git status` shows `M` on `webapp/src/styles/app.css`, `webapp/src/chat/HistoryRail.tsx`, `webapp/src/chat/__tests__/history-rail.test.tsx`, and `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` (the last is the H4/H5/H6 amendment text, also uncommitted).

- **The app is running** at `http://127.0.0.1:9300` from this worktree, launched with:
  `JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data .venv/bin/uvicorn app.main:create_app --factory --port 9300`

**Before you start:** `git fetch && git pull`, then decide whether to first commit the two uncommitted defensive fixes (they're worth saving). The branch is local-only and has diverged from `origin/master` by 2 commits (both docs/eval, no code conflict) — see the prior handoff.

---

## What the NEW session should do — 3 issues

These are the three things Destin wants worked on next. **The new session MUST ask Destin clarifying questions before starting each one** — the issues are described behaviorally below, not precisely, and each has ambiguity only Destin can resolve. Do not guess.

---

### Issue 1 — Citations disappear/unlink after switching between historical sessions

**User-visible symptom:** When you open one saved (historical) chat and then switch to another, the citations in the previously-viewed (or the currently-viewed) chat stop resolving — chips lose their source link / highlight.

**Relevant code — trace in this order:**

- `webapp/src/chat/history-rehydrate.ts` — converts stored OpenAI-format messages → `Turn[]`. This is the heart of the suspicion: **it does not reconstruct citation/annotation data**. It rebuilds `text` and `tool` blocks from the stored messages, but a rehydrated turn has no `annotation` (the figure→chunk link data).
- `webapp/src/chat/citation-context.tsx` — the citation bus. Note `lastRef` replays the most recent selection to a newly-mounting viewer. `markUnresolvable`/`subscribeUnresolvable` (H5) mark chips whose source no longer resolves.
- `webapp/src/pdf/PdfViewer.tsx` — fetches the chunk at click time (`/api/chunks/{id}?corpus=…`) to verify the source still resolves; publishes `gone`/`moved` verdicts. `corpus` prop added in Task 10.
- `webapp/src/chat/chat-reducer.ts` (line ~36) — the `REHYDRATED` action replaces the timeline wholesale with `rehydrateTurns()` output. **No annotation is carried in.**
- `webapp/src/chat/citation-extract.ts` — where `Citation.resolved` (chunk metadata: `doc_id`, `page_start`, `bbox`, `text`) is defined and where the annotation shape lives.
- `webapp/src/chat/chat-types.ts` (line ~56) — `annotation?: unknown` on the assistant turn; only populated by the live `_done` frame, never by rehydration.
- Server side — where the annotation is *created*: `harness/session.py`:
  - `annotation()` (line ~1788) builds the figure→chunk link from `_retrieved_chunk_map()`.
  - `done_frame()` (line ~1800) puts `annotation` on the `_done` frame.
  - **`self.history` (line ~432) is the OpenAI-format wire history and does NOT include the annotation.** So what's persisted to disk (via `app/routes/conversations.py::persist_turn` → `harness/history.save`) is the wire messages only — the annotation/figure-link data is NOT saved.

**The likely root cause to investigate:** the figure→chunk citation linkage is produced at turn time and carried only on the `_done` frame; it is never persisted into the transcript, so a rehydrated chat cannot restore it, and the chips render without resolution data. When the live turn's chunks left the current session context (switching sessions), the click-time fetch in `PdfViewer` either 404s or can't find the span, surfacing as "unlinked."

**What to clarify with Destin before implementing:**
1. Should citations persist *across* sessions at all — i.e., should opening an old chat show working citation highlights, or is this only about the *current* live session not losing them when switching back and forth?
2. If persistence is desired: persist the `annotation` into the transcript (schema change to `harness/history.Transcript`/`save` + a new message field), and have `rehydrateTurns` reconstruct it. Confirm whether a schema migration for already-saved chats is needed.
3. Whether the "unlinking" is specifically the rehydration path, or also the live path when switching (the citation bus `lastRef` / `PdfViewer` `checkSeqRef` race guard).

---

### Issue 2 — Can't create a NEW session after starting a conversation in the new session until switching back to a historical session first

**User-visible symptom:** After you begin chatting in a brand-new session, you can't start *another* new session until you first switch to (click) a historical session, then back.

**Relevant code:**

- `webapp/src/pages/Ai.tsx` — owns `selectedChatId`:
  - Line ~88 `const [selectedChatId, setSelectedChatId] = useState<string | null>(null)`.
  - Line ~107 `handleNewChat = () => setSelectedChatId(null)`.
  - Line ~207 `key={`${corpus}:${selectedChatId ?? "new"}`}` re-mounts `AiConversation` when either changes. **The whole mechanism: new chat = `selectedChatId` null → key becomes `${corpus}:new`.**
  - Line ~242 `useChat(corpus, selectedChatId ?? undefined)`.
- `webapp/src/chat/use-chat.ts`:
  - `resumeFromRef` (line ~84) — holds `resumeFrom`, updated every render.
  - Line ~146 `createConversation(corpus, resumeFromRef.current)` — the resume id is passed on first send.
  - The lazy conversation: a conversation is only created on the first `send`.
- `webapp/src/chat/HistoryRail.tsx` — the "+ New chat" button calls `onNewChat` → `handleNewChat`.
- `webapp/src/pages/Ai.tsx` `handleSelectChat` (line ~104) — selecting a stored chat sets `selectedChatId`.

**The likely root cause to investigate:** A brand-new chat (never sent to, `selectedChatId` already `null`) has key `${corpus}:new`. Clicking "+ New chat" sets `selectedChatId` to null *again* — so the key does **not change** for a chat that is already new, and `AiConversation` does not remount. If the current view is a fresh but started conversation (you've sent a message), `selectedChatId` is `null` and the key is already `${corpus}:new` — so "new chat" is a no-op key-wise, and there's no way to reset the in-memory conversation. Switching to a historical chat changes `selectedChatId` to a non-null id (key → `${corpus}:<id>`), then clicking new returns to `${corpus}:new` which now remounts fresh — hence "you have to switch back first."

**What to clarify with Destin before implementing:**
1. Desired behavior when you're already in a fresh, started conversation and press "+ New chat": should it discard the current in-progress conversation and give a truly blank chat (remount), or should it be a no-op/guard ("you're already in a new chat")?
2. Whether a "discard current chat" confirmation is wanted (the current conversation is in-memory only and would be lost).
3. The likely fix is a way to force a re-key even when already on `${corpus}:new` (e.g. a monotonically increasing `newChatKey`/nonce used alongside `selectedChatId`, or resetting the reducer via a distinct action). Confirm the intended UX before wiring it.

---

### Issue 3 — Check the original design doc to confirm everything made it into the final version

**What to do:** Audit the original feature design against the shipped implementation and report gaps.

**Relevant docs:**
- `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` — the original overall design doc (the invariants here are still load-bearing per CLAUDE.md).
- `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — the current architecture (S1–S30, Invariants 7–8, gates G1–G3). **Required reading before any non-trivial change.**
- `docs/superpowers/specs/2026-08-01-ai-mode-ui-redesign-design.md` — the AI Mode UI redesign (the rail amended its "D1" decision).
- `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` — the chat-history feature spec (Decisions section + "API surface" + "Follow-ups this creates"). Note the uncommitted H4/H5/H6 amendments.
- `docs/superpowers/plans/2026-08-02-ai-mode-chat-history.md` — the implementation plan (10 tasks; the handoff says all 10 done, Task 11 docs partial).

**What to clarify with Destin before implementing:**
1. Scope: audit *all* of the original design doc against the whole app, or only the chat-history / AI Mode portion?
2. Deliverable: a written gap report (recommended — do this first, no code), or fix-the-gaps directly?
3. Which version "counts" as authoritative when the original spec and a later spec/decision disagree — the spec files note several deliberate deviations (e.g. the corpus-toggle removal in `Ai.tsx`'s header comment, the rail amending redesign D1). Confirm how to reconcile rather than "restore fidelity" naively (the `Ai.tsx` header explicitly warns against re-adding the removed S9 toggle).

---

## Reference: key file map

| Concern | File |
|---|---|
| Transcript store (load/save/delete/rename/search) | `harness/history.py` |
| Auto-naming | `harness/titles.py` |
| History HTTP routes | `app/routes/history.py` |
| Conversation routes (persist, resume, registry) | `app/routes/conversations.py` |
| History router registration | `app/main.py` |
| Citation bus | `webapp/src/chat/citation-context.tsx` |
| Wire-format → Turn[] | `webapp/src/chat/history-rehydrate.ts` |
| Chat reducer (REHYDRATED action) | `webapp/src/chat/chat-reducer.ts` |
| Annotation/citation types | `webapp/src/chat/chat-types.ts`, `citation-extract.ts` |
| PDF viewer staleness check | `webapp/src/pdf/PdfViewer.tsx` |
| Rail component | `webapp/src/chat/HistoryRail.tsx` |
| Rail data hook | `webapp/src/chat/use-history.ts` |
| New-chat/selected-chat state | `webapp/src/pages/Ai.tsx` |
| Chat hook (create/resume) | `webapp/src/chat/use-chat.ts` |
| Rail + panel layout CSS | `webapp/src/styles/app.css` (search `history-rail`, `ai-panel-layout`) |
| History tests (Python) | `tests/test_harness_history.py`, `test_history_persistence.py`, `test_history_routes.py`, `test_history_search.py`, `test_harness_titles.py`, `test_history_resume.py` |
| History tests (webapp) | `webapp/src/chat/__tests__/history-rail.test.tsx`, `history-rehydrate.test.ts`, `use-chat-resume.test.ts`, `use-history.test.ts` |

---

## Testing / verification cheatsheet

- Python: `cd <worktree> && .venv/bin/python -m pytest -q` (full suite; the 6 history test files above are the new ones).
- Webapp: `cd <worktree>/webapp && npx vitest run` (605 tests) and `npx tsc -b` + `npm run build` (must stay clean).
- Run the app: `JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data .venv/bin/uvicorn app.main:create_app --factory --port 9300`.
- History lives in the per-machine store (env `JLBC_HISTORY_DIR` or `%LOCALAPPDATA%\JLBC-Insight\conversations\`); there are many old test chats there.

## Notes / warnings for the next session

- **Branch is local-only and not pushed.** Commit the two defensive fixes from this session before building on them. Use a worktree per CLAUDE.md for any non-trivial work.
- **`MAX_CONVERSATIONS = 40`** — see the spec's "Follow-ups"; not in scope here.
- **The `eval/results/agent/...` files appear in this branch's diff vs `origin/master`** as deletions/rewrites — unrelated to history; consider separating if you eventually push.
- Tests passing ≠ the runtime UX fixed; both issue 1 and 2 are integration/Ux issues the current test suite does not cover. Reproduce manually via the running app.
- Respect **Core Invariants** (CLAUDE.md): every claim auditable, citation verification is visible not silent, refusal beats hallucination, no "hallucination-free" language. Issue 1 touches Invariant 1/2 most directly — don't "fix" disappearance by silently dropping the chip.
