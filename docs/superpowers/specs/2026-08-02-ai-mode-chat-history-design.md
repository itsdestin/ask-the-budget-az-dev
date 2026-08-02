# AI Mode chat history — design

**Status:** approved in brainstorming 2026-08-02. Not yet planned or built.

**Goal.** An analyst can browse, search and resume their own past AI Mode
conversations, stored on their own machine, with a UI in the shape they already
know from other chat tools.

**Scope discipline.** Destin's framing was "this doesn't need to be anything
fancy." Auto-naming and search were added deliberately on top of that; folders,
pinning, export, sharing and cross-device sync were considered and are OUT.

---

## Context that constrains the design

Facts to check before changing anything here — each one changed a decision
below.

1. **Every analyst runs their own copy of the app.** Plan 5 Track 3 ships one
   Windows bundle to ~20 PCs; `launcher.pyw` calls `create_app()` locally. Only
   the corpus and `settings.json` live on the share. So "local" already means
   "the machine the server is running on", and per-device history needs no
   device concept of its own.
2. **Conversations today are memory-only.** `app/routes/conversations.py`
   holds a `ConversationRegistry`, LRU-capped at `MAX_CONVERSATIONS = 40`,
   lost on restart.
3. **`HarnessSession.__init__` already accepts `history=`**
   (`harness/session.py`). Rehydration is an existing supported path, not
   something this design invents. This is the single biggest reason the
   feature is small.
4. **`harness/documents.py` already resolves a private per-user directory** —
   `%LOCALAPPDATA%\JLBC-Insight\documents\`, with an XDG fallback so CI and a
   dev Linux box work. That resolver is the model for this one.
5. **The webapp uses no browser storage at all today.** Nothing to migrate,
   and no precedent being broken.
6. **The AI Mode UI redesign is approved and in flight** — spec
   `2026-08-01-ai-mode-ui-redesign-design.md`, currently spec-only on branch
   `ai-mode-ui-redesign`. Its D1 specifies ONE column at `--ai-col` (~768px),
   D2 specifies ONE scroll container, D6 spends the right side on the source
   panel. **This design amends D1** — see A1 below. It is an amendment on the
   record, not a silent contradiction.

---

## Decisions

### H1 — History is files on the local disk, written by the server

One JSON file per conversation at
`%LOCALAPPDATA%\JLBC-Insight\conversations\<conversation_id>.json`. **The
directory is the index — there is no separate index file.**

An earlier draft of this spec carried an `index.json` cache for the rail. It
was dropped in self-review as a direct contradiction of H4: if a linear scan
is fast enough to search message *bodies*, it is certainly fast enough to list
*headers*. A summary file that can disagree with the files it summarises is a
whole class of bug bought for nothing.

**Why not browser storage.** IndexedDB was the smaller build — no server code
at all — but it dies when site data is cleared, does not follow an analyst
between Edge and Chrome, is invisible to whoever supports them, and is really
per-browser-profile rather than per-device.

**Why not the share.** History on the network drive would follow an analyst to
any PC, but it puts every analyst's questions somewhere ~20 colleagues can
read. That is a confidentiality decision, not a technical one, and the answer
is no.

**Invariant 7 holds by construction.** The resolver lives beside
`harness/documents.py`'s and has no way to learn where the share is —
it must not import `store.config`. Pin this with the same AST-based
import-allowlist test that already guards `harness/documents.py`.

**Written after each completed turn, and on stop/abort.** A cancelled turn is
still a turn the analyst had, and losing it because they hit stop would be a
surprise.

**Side effect worth keeping:** LRU eviction stops being data loss. An evicted
conversation is now merely one that is not in memory.

### H2 — Lazy rehydration: live on open, paid only on send

Opening a stored chat renders it **fully live** — transcript, citations, tool
rows, composer enabled. No banner, no "Continue" button, no server session, no
tokens.

On the first send, `useChat` does what it already does for a new chat — creates
the conversation lazily — except it posts the stored history, and the server
constructs `HarnessSession(history=stored)`.

**Why this shape.** Destin's words: "i don't want to 'pay' to re-enter a chat
we're only reading, but i also don't think a separate continue button is
necessary." A read-only mode with an explicit Continue was rejected as
unnecessary chrome; always-live was rejected because re-entering a long Deep
Research thread would cost real money to merely re-read.

The client cannot tell a rehydrated chat from a fresh one after the first send,
and neither can the analyst.

**The corpus travels with the transcript.** Switching corpus already starts a
new conversation by remounting on `key={corpus}` — a stored chat must reopen on
the corpus it was recorded against, or it would answer fiscal-note questions
out of the budget corpus, cited and confident. Three existing specs in
`webapp/src/pages/Ai.test.tsx` protect the remount; this must not defeat them.

### H3 — Auto-naming is one LLM call, and never load-bearing

After the first exchange completes, one short non-streaming call (no tools)
asks for a 3–6 word title. New module `harness/titles.py` — `session.py`
always streams with tool schemas, so there is no existing plain-completion
path to reuse.

**Model: the Standard tier's configured model.** No new admin setting.
Considered and rejected: a separately-configured "task model" (the Open WebUI /
LibreChat pattern). The concern behind it — titling silently inheriting an
expensive answer model — is largely neutralised by S16 decision 8, which keeps
first-party flagships off the shortlist, so Standard is a cheap model by
construction. A title is ~100 tokens against a lookup's ~$0.0127. Adding a
fourth model dropdown to an admin page that took seven review rounds is not
worth it. **If this ever does matter, adding a task-model setting is a small,
contained change.**

**Recorded in the ledger under its own tier, `"title"`.** S19 records every
call; without a distinct tier these would quietly inflate what reads as
analyst spending in the admin breakdown.

**It never blocks and never fails a chat.** No API key, AI Mode off, user over
their spend limit, provider error, offline — every one of these falls back to
the first ~60 characters of the opening question. Naming is a convenience.
This also keeps history working with **zero API key**, consistent with search,
fiscal notes and upload.

**A manual rename is never overwritten.** The stored record carries whether the
title was auto-generated or analyst-set.

### H4 — Search covers titles and message text

A server-side scan over stored transcripts, returning matching chats with the
matching line as a snippet and the term highlighted.

**No index, deliberately.** A linear scan over a few hundred small JSON files
is milliseconds, and an index is a thing that silently drifts out of sync with
the files it describes. If it ever gets slow, that is the moment to add one.

Title-only search was rejected: auto titles are 3–6 words, so anything
discussed mid-conversation would be unfindable. Semantic search over history
(free, via the local ONNX embedder) was rejected as less predictable than
keywords for finding a conversation you half-remember.

### H5 — A stale citation is marked, never silently dropped

A stored citation whose `chunk_id` no longer resolves — the document was
re-ingested since — renders as a chip visibly marked "source no longer
available", with the verified quote still shown and a tooltip explaining why.

**Resolved when the chip is clicked, not when the chat opens.** Verifying every
citation on open would mean a corpus round-trip per citation, which would make
browsing cost exactly what H2 exists to avoid.

This is **Invariant 2 applied to history**: failed citations are visibly
stripped, not silently dropped or quietly accepted. The quote is still shown
because it *was* verified when written — that is a fact about the past, not a
claim about the present corpus.

**This will happen.** Chunk ids move on re-ingest; the Layer 1 eval already
lost 41% of its ground-truth ids to exactly this, and nothing re-binds them.

### H6 — Retention: keep everything, delete manually

Transcripts are kilobytes. An analyst losing a chat they wanted is a worse
outcome than disk use. Delete is per-chat and explicit. No cap, no expiry.

---

## API surface

Five routes, in a new `app/routes/history.py`. All read and write only the
local conversations directory; none touches the corpus or the share.

| Route | Purpose |
|---|---|
| `GET /api/history` | List chats, newest first: id, title, corpus, created, updated, message count. Reads headers only. |
| `GET /api/history/{id}` | One full transcript, for rendering a stored chat. |
| `GET /api/history/search?q=` | Matching chats with a snippet per match (H4). |
| `PATCH /api/history/{id}` | Rename. Sets the analyst-set flag so H3 never overwrites it. |
| `DELETE /api/history/{id}` | Delete one chat. |

Rehydration (H2) deliberately adds **no** route: it extends the existing
`POST /api/conversations` with an optional `resume_from` conversation id. The
server loads that transcript and passes it to `HarnessSession(history=...)`.
Reusing the create path is what makes a rehydrated chat indistinguishable from
a fresh one downstream — a parallel "resume" endpoint would be a second code
path doing the same job, and the two would drift.

Writing is not an endpoint. The server persists a transcript itself when a
turn completes or aborts (H1); the client never uploads history it holds.
That keeps the file on disk the single source of truth and means a crashed
browser tab cannot lose or corrupt a chat.

---

## Amendment to the AI Mode UI redesign

### A1 — D1 gains a collapsible left rail

`2026-08-01-ai-mode-ui-redesign-design.md` D1 specifies one column and one left
edge. This design adds a **collapsible history rail** to the left of that
column, and **amends D1 accordingly**.

Constraints that keep the amendment honest:

- The rail is collapsible, and **auto-collapses when the source panel opens**.
  A rail plus a 768px thread plus a PDF panel would crush the thread — the
  one-content-measure rule in D1 exists for a reason and still governs.
- The rail is its own scroll container. D2 says `.chat-thread-scroll` is the
  only scroller *in the chat region*; the rail sits outside it. D2's actual
  target — 12 nested scrollers inside the thread — is unaffected.
- Collapsed state persists per device.

Rail contents: **New chat**, a search box, then chats newest-first grouped
Today / Yesterday / Earlier. Rename and delete on hover. Searching switches the
rail to results with snippets.

**Overlay drawer was the safer option and was considered** — it touches the
approved skeleton not at all. Destin chose the rail because it matches what
analysts know from other chat tools, which was the original ask.

**Sequencing:** the redesign is spec-only and in flight in its own worktree.
Whoever implements this must rebase onto the redesign rather than race it —
both touch `webapp/src/pages/Ai.tsx` and the AI Mode stylesheet.

---

## Testing

**Server**

- Write/read round-trip; a rehydrated history is identical to what was stored.
- A corrupt transcript degrades to skipping that one chat — it must never
  break the rail. (Same policy split as `store/documents.py`: read paths
  degrade, the write path raises.)
- Path confinement: the conversations resolver cannot reach the share, pinned
  by the AST import-allowlist test that already guards `harness/documents.py`.
- Title fallback fires on every failure mode: no key, AI Mode off, over spend
  limit, provider error, malformed reply.
- A title call lands in the ledger under tier `"title"` and nowhere else.
- Search returns the right chats and a snippet containing the term.
- A stop/abort mid-turn still persists the turn.

**Client**

- Rail grouping and ordering; collapsed state persists; rail auto-collapses
  when the source panel opens.
- Rehydration fires on send and NOT on open — assert no conversation is
  created merely by opening a stored chat. This is the property H2 exists for.
- A stored chat reopens on its recorded corpus.
- Stale-citation chip renders marked, with the quote still visible.
- Search results render snippets; clearing search restores the list.

---

## Follow-ups this creates

- **The Administrator Handbook needs a paragraph.** History writes analysts'
  questions to disk in plain text, and the first exchange of each chat is sent
  to OpenRouter for naming. Both are the right trade for a local tool, and both
  belong next to the existing confidentiality section so a successor knows the
  files exist, where they are, and how to delete them.
- **`MAX_CONVERSATIONS = 40` may want revisiting** once eviction is no longer
  data loss — but not in this work.
