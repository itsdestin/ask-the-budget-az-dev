# Chat History Implementation — Session Handoff

> **SUPERSEDED — 2026-08-03.** This handoff was written while the branch was
> still local and unfinished. Since then: the branch was pushed and merged via
> PR to master; the rail CSS was written (`0363d27`); the empty-title fallback
> was committed (`55037b4`); and a review session fixed several real bugs
> (transcript wiped on resume, corpus mismatch on select, sticky stale marks,
> the mid-turn delete/rename race) — see STATUS.md → "AI Mode chat history"
> for the current state. The file below remains accurate about what the 10
> commits BUILT and the design decisions; treat its "NOT done" list as
> historical.

**Date:** 2026-08-02 (session ran into 2026-08-03)
**Branch:** `chat-history` (local only, NOT pushed to GitHub)
**Worktree:** `/home/destin/ask-the-budget-az-worktrees/chat-history`
**Plan:** `docs/superpowers/plans/2026-08-02-ai-mode-chat-history.md`
**Spec:** `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md`

---

## What was built

All 10 implementation tasks from the plan are complete (Tasks 1–10).
Task 11 (documentation/status) was started but not finished — the spec
amendment was partially written (H4/H5/H6 edits committed) but HANDBOOK.md,
STATUS.md, and CLAUDE.md were not updated.

### 10 commits, in order:

1. `b1c31be` — **feat(history): per-device transcript store**
   `harness/history.py` + `tests/test_harness_history.py` (10 tests)
   Transcript dataclass, atomic save (tmp+os.replace), load, list_all
   (newest-first, messages stripped), delete, rename. AST import-allowlist
   test pins Invariant 7 (no `store.config`). Transcript sizes measured:
   Standard lookup 7.2 KB, Deep Research 26.4 KB, list_all over 200 copies
   9.7 ms — no-index design holds.

2. `3eaa44d` — **feat(history): persist a transcript when a turn ends or aborts**
   `app/routes/conversations.py` + `tests/test_history_persistence.py` (4 tests)
   `persist_turn()` called from `_release_turn` BackgroundTask after
   `registry.end_turn`. Swallows its own errors. Uses `getattr` for
   `session.history` so fakes without it are a no-op.

3. `f1e6b57` — **feat(history): list, read, rename and delete routes**
   `app/routes/history.py` + `app/main.py` + `tests/test_history_routes.py` (8 tests)
   Four routes: `GET /api/history`, `GET /api/history/{id}`,
   `PATCH /api/history/{id}`, `DELETE /api/history/{id}`. Registered above
   the `/{path:path}` catch-all. Traversal ids → 400.

4. `a0c2f47` — **feat(history): search titles and message text with snippets**
   `harness/history.py` + `app/routes/history.py` + `tests/test_history_search.py` (9 tests)
   `search()` scans `user` and `assistant` prose only — NOT `tool` messages
   (their `content` is a JSON string, so isinstance(str) doesn't exclude
   them). Route `/api/history/search` registered BEFORE
   `/api/history/{conversation_id}` so "search" isn't captured as an id.
   Route-ordering regression test added.

5. `5f2fb69` — **feat(history): auto-name a chat, ledgered under its own tier**
   `harness/titles.py` + `app/routes/conversations.py` + `tests/test_harness_titles.py` (12 tests)
   + `webapp/src/admin/CostsPanel.tsx` + `CostsPanel.test.tsx` (4 tests)
   One non-streaming LLM call after the first exchange. Falls back to
   truncation on every failure (no key, blocked, provider error, malformed
   reply). Ledgered under tier `"title"` so it never reads as analyst spend.
   OpenRouter `usage: {include: true}` gated on provider. `CostsPanel`
   shows `"Chat naming"` instead of raw key `"title"`.

6. `8c0a913` — **feat(history): resume a stored chat by seeding HarnessSession history**
   `app/routes/conversations.py` + `tests/test_history_resume.py` (8 tests)
   `POST /api/conversations` accepts optional `resume_from`. Loads stored
   transcript, adopts stored corpus (not requested), reuses original id,
   seeds `HarnessSession(history=...)` via `extra` dict (only when resuming,
   so existing fakes don't break). `ConversationRegistry.get_or_add()` added
   for atomic check-then-add. Busy conversation → 409.

7. `720a919` — **feat(history): client bindings and the history hook**
   `webapp/src/api.ts` + `webapp/src/chat/use-history.ts` + `use-history.test.ts` (5 tests)
   Five API bindings + `createConversation(corpus, resumeFrom?)`. Hook:
   load on mount, 200ms debounce search, stale-response guard (seq number),
   optimistic remove with rollback on failure.

8. `93e5759` — **feat(history): collapsible history rail (amends redesign D1)**
   `webapp/src/chat/HistoryRail.tsx` + `AiModePanel.tsx` + `Ai.tsx` +
   `history-rail.test.tsx` (6 tests) + `ai-test-fixtures.ts`
   Rail mounted left of chat in AiModePanel. Auto-collapses when source
   panel opens. Collapsed state persists in localStorage (guarded against
   throws). Ai.tsx owns `selectedChatId`, keys conversation on
   `` `${corpus}:${selectedChatId ?? "new"}` ``. Test fixtures updated to
   stub `/api/history` and `/api/history/search`.

9. `e9e3134` — **feat(history): lazy rehydration — live on open, session rebuilt on send**
   `webapp/src/chat/history-rehydrate.ts` + `chat-types.ts` + `chat-reducer.ts`
   + `use-chat.ts` + `history-rehydrate.test.ts` (7 tests)
   + `use-chat-resume.test.ts` (3 tests)
   `rehydrateTurns()` converts stored OpenAI-format messages → `Turn[]`.
   Run boundaries = user messages. Tool calls + replies merge into one
   AssistantTurn. Malformed JSON arguments → `input: {}` (no throw). Orphan
   tool calls → status "failed". Timestamps fabricated from `created_at`.
   New `REHYDRATED` ChatAction (reducer resets to initialChatState + turns).
   `useChat(corpus, resumeFrom?)` fetches transcript on mount (no
   conversation created), passes `resumeFrom` to `createConversation` on
   first send via `resumeFromRef`.

10. `6409102` — **feat(history): mark citations whose source no longer resolves**
    `webapp/src/pdf/PdfViewer.tsx` + `CitationChip.tsx` + `citation-context.tsx`
    + `AiModePanel.tsx` + `pdf-viewer-stale.test.tsx` (5 tests)
    + `citation-chip-stale.test.tsx` (4 tests)
    H5 as amended: click-time chunk fetch in PdfViewer (direct `fetch`, not
    `api.chunk`, to preserve status code). Two unresolvable shapes: 404 →
    "gone", 200 but quote moved → "moved". 503 NOT marked stale. Verdict
    published on citation bus (`markUnresolvable`/`subscribeUnresolvable`
    added). Chip renders failed treatment + accessible name says "source
    no longer available". Verified quote still shown (Invariant 2).
    Normalization via `normalizeForMatch` (S23). PdfViewer gains `corpus`
    prop. Race guard via `checkSeqRef`.

---

## Test counts

| Suite | Baseline | After | Delta |
|---|---|---|---|
| Python (pytest) | 2157 passed, 5 skipped | 2209 passed, 5 skipped | +52 |
| Webapp (vitest) | 575 passed | 605 passed | +30 |

Both `tsc -b` and `npx tsc -b` are clean.

---

## What's NOT done

- **Task 11 (documentation) — partially started, not finished.**
  - Spec amendments for H4/H5/H6 were written and committed (in the
    `6409102` commit? No — they're in the uncommitted working tree).
    Actually: the H4/H5/H6 spec edits are **uncommitted** in the worktree.
  - `docs/HANDBOOK.md` does not exist yet (Plan 5 Track 5 owns the file).
  - `STATUS.md` not updated.
  - `CLAUDE.md` not updated.
  - The plan's Step 1 says to write the three spec amendments back into the
    spec. The H4/H5/H6 text was edited in
    `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` but
    NOT committed. Revert or finish — Destin said to stop on docs.

- **The branch has NOT been pushed to GitHub.** It's local-only at
  `/home/destin/ask-the-budget-az-worktrees/chat-history`.

- **The `ai-mode-ui-redesign` branch does not exist in this worktree.** The
  plan's Global Constraints say to rebase onto it, but it was local-only on
  the main checkout and not present here. The rail was built on `master` as
  a result. If that branch lands changes to `Ai.tsx` or the AI Mode
  stylesheet, the rail commit may need rebasing.

- **The `citation-linking` branch also does not exist here.** Task 10's
  citation work was built on `master`. If that branch changes what a
  `Citation` carries, the span-comparison in `PdfViewer` changes with it.

- **No CSS was written for the rail.** The `HistoryRail.tsx` component uses
  class names (`history-rail`, `history-rail-item`, etc.) but the
  corresponding styles were not added to any stylesheet. The rail will
  render unstyled — functional but ugly. Destin needs to see it and decide
  on the visual design.

- **The `ai-panel-layout` wrapper div** added to `AiModePanel.tsx` for the
  rail has no CSS either. The flexbox layout needs to be written.

---

## Files created

### Python
- `harness/history.py` — transcript store
- `harness/titles.py` — auto-naming
- `app/routes/history.py` — HTTP routes
- `tests/test_harness_history.py` — 10 tests
- `tests/test_history_persistence.py` — 4 tests
- `tests/test_history_routes.py` — 9 tests (8 + 1 route-order)
- `tests/test_history_search.py` — 9 tests
- `tests/test_harness_titles.py` — 12 tests
- `tests/test_history_resume.py` — 8 tests

### TypeScript
- `webapp/src/chat/HistoryRail.tsx` — the rail component
- `webapp/src/chat/use-history.ts` — history data hook
- `webapp/src/chat/history-rehydrate.ts` — wire messages → Turn[]
- `webapp/src/chat/__tests__/use-history.test.ts` — 5 tests
- `webapp/src/chat/__tests__/history-rail.test.tsx` — 6 tests
- `webapp/src/chat/__tests__/history-rehydrate.test.ts` — 7 tests
- `webapp/src/chat/__tests__/use-chat-resume.test.ts` — 3 tests
- `webapp/src/chat/__tests__/citation-chip-stale.test.tsx` — 4 tests
- `webapp/src/pdf/__tests__/pdf-viewer-stale.test.tsx` — 5 tests
- `webapp/src/admin/CostsPanel.test.tsx` — 4 tests

## Files modified

### Python
- `app/routes/conversations.py` — `persist_turn`, `resume_from`, `get_or_add`, `default_session_factory` history param
- `app/main.py` — history router registration

### TypeScript
- `webapp/src/api.ts` — 5 history bindings + `createConversation` resume param
- `webapp/src/chat/AiModePanel.tsx` — rail mount, `viewerOpen` auto-collapse, `corpus` prop to PdfViewer
- `webapp/src/chat/CitationChip.tsx` — unresolvable marking
- `webapp/src/chat/citation-context.tsx` — `markUnresolvable`/`subscribeUnresolvable`/`useUnresolvable`
- `webapp/src/chat/chat-types.ts` — `REHYDRATED` action
- `webapp/src/chat/chat-reducer.ts` — `REHYDRATED` handler
- `webapp/src/chat/use-chat.ts` — `resumeFrom` param, rehydration effect
- `webapp/src/pages/Ai.tsx` — `selectedChatId`, key on `corpus:chatId`, pass history props
- `webapp/src/pdf/PdfViewer.tsx` — click-time staleness check, `corpus` prop, `StaleState`
- `webapp/src/admin/CostsPanel.tsx` — `TIER_LABELS` display map
- `webapp/src/pages/ai-test-fixtures.ts` — stub `/api/history` and `/api/history/search`

### Docs
- `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` — H4/H5/H6 amendments (UNCOMMITTED)

---

## How to run it

```bash
cd ~/ask-the-budget-az-worktrees/chat-history
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
  .venv/bin/uvicorn app.main:create_app --factory --port 9300
```

Then open `http://127.0.0.1:9300` in a browser. Chat history files are
stored at `~/.local/share/JLBC-Insight/conversations/` (XDG fallback on
Linux; `%LOCALAPPDATA%\JLBC-Insight\conversations\` on Windows).

The webapp must be built first: `cd webapp && npm run build`.

---

## Key design decisions worth knowing

1. **Browsing is free, continuing costs.** Opening a stored chat fetches
   the transcript and renders it — no server session is created. The
   session is only rebuilt on the first send, when `resumeFrom` is passed
   to `createConversation`.

2. **Search excludes tool messages.** A `tool` result's `content` is a
   JSON string, so `isinstance(str)` doesn't exclude it. The role-based
   filter (`user`/`assistant` only) is what distinguishes prose from
   payload.

3. **`resume_from` reuses `POST /api/conversations`, not a new route.**
   A parallel "resume" endpoint would drift; reusing create makes a
   rehydrated conversation indistinguishable from a fresh one downstream.

4. **The `extra` dict pattern** (`extra = {"history": ...} if stored else {}`)
   is what avoids breaking ~25 existing test fakes that don't accept a
   `history` keyword.

5. **Staleness check uses direct `fetch`, not `api.chunk`**, because
   `api.chunk` wraps the error and loses the status code — we need 404
   vs 503 to distinguish "chunk gone" from "share offline."

6. **No CSS for the rail.** The component is functional but unstyled.
   Destin needs to see it and decide on the visual design before styles
   are written.
