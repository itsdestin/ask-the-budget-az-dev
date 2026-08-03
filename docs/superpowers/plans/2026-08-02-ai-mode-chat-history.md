# AI Mode Chat History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An analyst can browse, search, rename, delete and resume their own past AI Mode conversations, stored on their own machine.

**Architecture:** The app server writes one JSON transcript per conversation into a private per-user directory (`%LOCALAPPDATA%\JLBC-Insight\conversations\`). A new `app/routes/history.py` reads that directory for the rail and for search. Resuming reuses the EXISTING `POST /api/conversations` with a `resume_from` id, which loads the transcript and hands it to `HarnessSession(history=...)` — a constructor parameter that already exists. Nothing is stored in the browser.

**Tech Stack:** Python 3.12 + FastAPI + pytest (server); Vite + React 18 + vitest (webapp). `uv` for Python deps, `npm` for the webapp.

**Spec:** `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` (H1–H6, A1).

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Work in a worktree**, and **rebase onto `ai-mode-ui-redesign` rather than racing it** — that branch is redesigning `webapp/src/pages/Ai.tsx` and the AI Mode stylesheet, which Tasks 7–10 also touch. Create with `git worktree add ~/ask-the-budget-az-worktrees/chat-history -b chat-history origin/master`. It is not the only branch in the way — see **"Branch collisions to plan around"** at the end of this plan before starting Task 10.
- **Invariant 7:** `harness/history.py` MUST NOT import `store.config` or otherwise learn where the shared drive is. Pinned by an AST test in Task 1 modelled on `tests/test_create_document.py:338` — which is an **allowlist of import roots**, not a `store`-denylist, and Task 1 copies that shape deliberately.
- **Invariant 2:** a citation that no longer resolves is rendered VISIBLY MARKED. Never silently dropped, never quietly accepted.
- **No paid API may be load-bearing.** History — including listing, opening, searching, renaming and resuming — MUST work with no OpenRouter key configured. Only the auto-generated *title* degrades (to truncation).
- **S19:** every model call is recorded in the ledger. Title calls use tier `"title"` so they never inflate what reads as analyst spending.
- **Annotate non-trivial code with a WHY comment.** The project owner is a non-developer who relies on comments to understand what code does and why.
- **Run the full suite before each commit:** `.venv/bin/python -m pytest tests/ -q` (baseline on `origin/master` at time of writing: **1921 passed**, verified by collection) and, for webapp tasks, `cd webapp && npm run test`. The per-task expected counts below are arithmetic on that baseline — re-derive them if you add or drop a spec.
- **Do NOT run `eval/run_eval.py`.** This work touches neither `retrieval/`, `ingest/`, `chunking/` nor `harness/system-prompt.md`.
- Transcript JSON is written **tmp-file + `os.replace`**, the atomic-write convention used throughout `ingest/jobs.py` and `store/documents.py`.
- **Facts about the existing code that several tasks get wrong if assumed** — all verified against `origin/master` while writing this plan:
  - The conversation registry lives at **`app.state.conversations`** (`app/main.py:175`), NOT `app.state.conversation_registry`.
  - `check_limit(user, settings)` takes its arguments **positionally** and returns a **`LimitStatus`** whose `.status` is `"allowed" | "warn" | "blocked"` (`harness/ledger.py:652`). It is not a `(bool, str)` tuple.
  - The session seam is `make(conversation_id, *, corpus, tier, user)` — both `default_session_factory` (`app/routes/conversations.py:325`) and every test fake (`tests/test_conversations_route.py:122`). **Adding a keyword unconditionally breaks ~25 existing tests.**
  - `CitationChip` is a **default** export taking `{citation: Citation, inlineText?}` and requires a `CitationBusProvider` ancestor. It performs no network I/O at all.
  - In AI Mode a citation's source is resolved **entirely client-side** from `citation.resolved` (`webapp/src/pdf/PdfViewer.tsx:32`). `GET /api/chunks/{id}` is used only by the search page's `SourcePanel`.
  - Route-registration order in `app/main.py` is load-bearing: the `/{path:path}` catch-all swallows anything registered after it.
  - `webapp/src/chat/__tests__/` uses **kebab-case** filenames (`citation-chip.test.tsx`, `use-chat.test.ts`) and `.js`-suffixed relative imports for source modules.

---

## Spec amendments this plan makes

Three decisions in `2026-08-02-ai-mode-chat-history-design.md` rest on premises
that do not hold against the shipped code. They are amended here rather than
worked around silently, and **Task 11 writes them back into the spec** so the
two documents do not drift.

**H4 is narrowed to conversation prose.** `HarnessSession.history` stores every
tool result verbatim (`harness/session.py:1052`), and a tool result's `content`
is a JSON **string** — so an `isinstance(content, str)` filter does not exclude
it. Searching the raw message list means searching the corpus text that
`retrieve()` returned: "Florence" would match a chat where a retrieved passage
happened to mention Florence though nobody discussed it, and the snippet would
be a slice of a JSON payload. Search therefore scans `user` and `assistant`
prose only (Task 4).

**H5's detection is amended, and it is not a 404.** H5 assumes a stale citation
is caught by `chunk_id` failing to resolve. On a rehydrated chat, `resolved`
(doc_id, page, bbox, text) comes from the **stored** retrieve output, so a chip
whose document has since been re-ingested still renders as a perfectly ordinary
working citation and opens a page that may no longer contain the quote — the UI
would show "couldn't pinpoint", which reads as a highlight miss rather than a
stale source. That is the silent-acceptance shape Invariant 2 exists to
prevent, and it is the COMMON case; a hard 404 is the rarer one. Task 10
therefore checks at click time, in the viewer, and treats **two** shapes as
unresolvable: the chunk is gone (404), or the chunk exists but no longer
contains the stored quote.

**H6's sizing claim is unverified and probably wrong by one to two orders of
magnitude.** "Transcripts are kilobytes" was written before anyone looked at
what is in `history`: a standard turn's `retrieve()` result carries ~15 chunks
of full passage text and the Plan 4 Deep Research dogfood pulled 41. Every one
of those is stored. This matters because "the directory is the index" (H1) and
"a linear scan is milliseconds" (H4) both depend on it, and `list_all()` fully
JSON-parses every file on every rail load and every debounced keystroke. Task 1
Step 5 **measures** it against a real transcript and records the number; the
threshold and the fallback are written down there.

**What must NOT be done about size:** do not prune tool results out of the
stored history. `_repair_history` (`harness/session.py:1061`) documents why —
an assistant `tool_calls` message without its matching `{"role": "tool"}` reply
is a malformed request that the provider 400s, and the analyst experiences that
as "the conversation is broken now". Anything that trims history has to trim
whole call/reply pairs or nothing.

---

## File Structure

| File | Responsibility |
|---|---|
| `harness/history.py` | **Create.** Directory resolution, transcript read/write/list/delete/rename, search. Pure functions + dataclass. No FastAPI, no `store.config`. |
| `harness/titles.py` | **Create.** One non-streaming LLM call producing a short title; falls back to truncation on every failure. |
| `app/routes/history.py` | **Create.** Five HTTP routes over `harness/history.py`. |
| `app/routes/conversations.py` | **Modify.** Persist on turn end; accept `resume_from` on create. |
| `app/main.py` | **Modify.** Register the history router. |
| `webapp/src/api.ts` | **Modify.** Client bindings for the five routes + `resume_from`. |
| `webapp/src/chat/HistoryRail.tsx` | **Create.** The collapsible rail: list, grouping, search, rename, delete. |
| `webapp/src/chat/use-history.ts` | **Create.** Data hook for the rail. |
| `webapp/src/chat/history-rehydrate.ts` | **Create.** Stored OpenAI-format messages → `Turn[]`. The one piece of Task 9 that is real work. |
| `webapp/src/chat/chat-types.ts` | **Modify.** One new `ChatAction` — `REHYDRATED`. |
| `webapp/src/chat/chat-reducer.ts` | **Modify.** Handle `REHYDRATED`. |
| `webapp/src/chat/use-chat.ts` | **Modify.** Accept a resumed transcript; pass `resume_from` on lazy create. |
| `webapp/src/pages/Ai.tsx` | **Modify.** Own `selectedChatId`; key the conversation on corpus + chat. |
| `webapp/src/chat/AiModePanel.tsx` | **Modify.** Mount the rail; it owns `viewerOpen`, which the rail's auto-collapse reads. |
| `webapp/src/pdf/PdfViewer.tsx` | **Modify.** Click-time staleness check (H5 as amended). |
| `webapp/src/chat/CitationChip.tsx` | **Modify.** Render the unresolvable marking. |
| `webapp/src/admin/CostsPanel.tsx` | **Modify.** Display label for the new `title` ledger tier. |

---

## Task 1: The transcript store

**Files:**
- Create: `harness/history.py`
- Test: `tests/test_harness_history.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `conversations_dir() -> Path`; `Transcript` dataclass with fields `id: str`, `title: str`, `title_is_manual: bool`, `corpus: str`, `created_at: str`, `updated_at: str`, `messages: list[dict]`; `save(t: Transcript) -> None`; `load(conversation_id: str) -> Transcript | None`; `list_all() -> list[Transcript]` (newest first, messages EXCLUDED); `delete(conversation_id: str) -> bool`; `rename(conversation_id: str, title: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_harness_history.py
import ast
import json
from pathlib import Path

import pytest

from harness import history

MODULE_SOURCE_PATH = Path(history.__file__)


@pytest.fixture(autouse=True)
def _tmp_history(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    yield


def _t(**kw):
    base = dict(
        id="abc123", title="ADC vacancy savings", title_is_manual=False,
        corpus="budget", created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:05:00+00:00",
        messages=[{"role": "user", "content": "hi"}],
    )
    base.update(kw)
    return history.Transcript(**base)


def test_a_saved_transcript_round_trips_exactly():
    history.save(_t())
    got = history.load("abc123")
    assert got is not None
    assert got.messages == [{"role": "user", "content": "hi"}]
    assert got.corpus == "budget"
    assert got.title_is_manual is False


def test_listing_omits_messages_but_keeps_the_count():
    """The rail needs a count without paying for a second read of every file."""
    history.save(_t(messages=[{"role": "user", "content": "a"},
                              {"role": "assistant", "content": "b"}]))
    rows = history.list_all()
    assert len(rows) == 1
    assert rows[0].messages == []
    assert rows[0].message_count == 2


def test_the_count_is_never_persisted():
    """A stored count could disagree with the stored messages."""
    history.save(_t())
    raw = json.loads((history.conversations_dir() / "abc123.json").read_text())
    assert "message_count" not in raw


def test_listing_is_newest_first():
    history.save(_t(id="old", updated_at="2026-08-01T00:00:00+00:00"))
    history.save(_t(id="new", updated_at="2026-08-02T00:00:00+00:00"))
    assert [r.id for r in history.list_all()] == ["new", "old"]


def test_a_corrupt_transcript_is_skipped_not_fatal():
    """One bad file must never take down the whole rail."""
    history.save(_t(id="good"))
    bad = history.conversations_dir() / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert [r.id for r in history.list_all()] == ["good"]
    assert history.load("bad") is None


def test_delete_removes_the_file_and_reports_whether_it_existed():
    history.save(_t())
    assert history.delete("abc123") is True
    assert history.load("abc123") is None
    assert history.delete("abc123") is False


def test_rename_sets_the_manual_flag_so_auto_naming_cannot_overwrite_it():
    history.save(_t())
    assert history.rename("abc123", "Corrections vacancies") is True
    got = history.load("abc123")
    assert got.title == "Corrections vacancies"
    assert got.title_is_manual is True


def test_renaming_does_not_move_a_chat_to_the_top_of_the_rail():
    """`updated_at` means "last thing the analyst SAID", not "last write".

    The rail sorts on it. If a rename bumped it, retitling a chat from March
    would reorder it above this morning's — a rename is bookkeeping, not
    conversation.
    """
    history.save(_t(id="old", updated_at="2026-08-01T00:00:00+00:00"))
    history.save(_t(id="new", updated_at="2026-08-02T00:00:00+00:00"))
    history.rename("old", "Renamed")
    assert [r.id for r in history.list_all()] == ["new", "old"]


def test_an_id_that_is_not_a_bare_filename_is_refused():
    """Path traversal: an id reaches this module from an HTTP path segment."""
    for evil in ("../secrets", "a/b", "a\\b", "", ".", ".."):
        with pytest.raises(ValueError):
            history.load(evil)


def test_this_module_imports_nothing_that_knows_where_the_share_is():
    """Invariant 7: history must not be able to learn where the share is.

    Same guard, same SHAPE, same reason as
    tests/test_create_document.py:338 — an ALLOWLIST of import roots, not a
    denylist of `store`. A denylist only refuses the spelling somebody
    thought of; `harness.settings`, `store`, `retrieval` and `app` all reach
    the share in one or two hops, and an allowlist refuses every one of them
    including the ones added next year.
    """
    allowed = {"__future__", "dataclasses", "datetime", "json", "os", "pathlib"}
    tree = ast.parse(MODULE_SOURCE_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots <= allowed, f"unexpected imports: {sorted(roots - allowed)}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness_history.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.history'`

- [ ] **Step 3: Implement `harness/history.py`**

```python
"""Per-device AI Mode chat history (spec 2026-08-02, H1).

WHY these files live under %LOCALAPPDATA% and not the shared drive: every
analyst runs their own copy of the app (Plan 5 Track 3 ships one bundle to
~20 PCs), so "this machine" is already "this analyst". Putting transcripts on
the share would expose every analyst's questions to ~20 colleagues.

INVARIANT 7: this module must never import `store.config`. Not importing it is
what makes the confinement structural rather than a promise — there is no code
path here that can learn where the share is. `tests/test_harness_history.py`
pins that with an AST check.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR_ENV = "JLBC_HISTORY_DIR"
_APP_FOLDER = "JLBC-Insight"


@dataclass
class Transcript:
    id: str
    title: str
    corpus: str
    created_at: str
    updated_at: str
    title_is_manual: bool = False
    messages: list[dict] = field(default_factory=list)
    # Kept separately so `list_all()` can strip the bodies and STILL report a
    # count. Without it the rail would need a second read of every file, which
    # is exactly what stripping was meant to avoid. Derived on read, never
    # persisted — a stored count could disagree with the stored messages.
    message_count: int = 0


def conversations_dir() -> Path:
    """Where transcripts live. Created if missing.

    Resolution mirrors `harness.documents.documents_dir()` exactly, for the
    same reasons: an env override for tests, %LOCALAPPDATA% on the real
    Windows deployment, and an XDG fallback so CI and a dev Linux box work.
    Home-rooted either way — never the share.
    """
    raw = os.environ.get(HISTORY_DIR_ENV)
    if raw:
        root = Path(raw)
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / _APP_FOLDER / "conversations"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        root = Path(base) / _APP_FOLDER / "conversations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(conversation_id: str) -> Path:
    # The id arrives from an HTTP path segment, so it is untrusted input.
    # Anything that is not a bare filename could escape the directory.
    if (
        not conversation_id
        or conversation_id in {".", ".."}
        or "/" in conversation_id
        or "\\" in conversation_id
        or os.path.basename(conversation_id) != conversation_id
    ):
        raise ValueError(f"not a bare conversation id: {conversation_id!r}")
    return conversations_dir() / f"{conversation_id}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(transcript: Transcript) -> None:
    """Write one transcript atomically.

    tmp + os.replace, the convention used by ingest/jobs.py and
    store/documents.py: a crash mid-write must not leave a half file that
    the reader would then have to treat as corrupt.
    """
    path = _path_for(transcript.id)
    payload = asdict(transcript)
    # Derived on read, never written: a persisted count could disagree with
    # the messages beside it, and then the rail would lie.
    payload.pop("message_count", None)
    # APPEND to the filename rather than `with_suffix`: with_suffix replaces
    # the last dotted segment, so an id that ever contains a dot would have
    # part of itself eaten and the replace would land on the wrong file.
    # Ids are uuid4 hex today; this costs nothing and removes the trap.
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> Transcript | None:
    """One transcript, or None if it is unreadable.

    READ paths degrade, deliberately — the same split store/documents.py
    makes. One corrupt file must not blank an analyst's whole history list;
    it should cost them that one chat and nothing else.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        messages = list(raw.get("messages") or [])
        return Transcript(
            id=raw["id"], title=raw.get("title", ""), corpus=raw.get("corpus", "budget"),
            created_at=raw.get("created_at", ""), updated_at=raw.get("updated_at", ""),
            title_is_manual=bool(raw.get("title_is_manual", False)),
            messages=messages, message_count=len(messages),
        )
    except (OSError, ValueError, KeyError):
        return None


def load(conversation_id: str) -> Transcript | None:
    path = _path_for(conversation_id)
    return _read(path) if path.is_file() else None


def list_all() -> list[Transcript]:
    """Every transcript, newest first, WITHOUT message bodies.

    The directory IS the index — there is deliberately no summary file. A
    summary that can disagree with the files it summarises is a bug class
    bought for nothing, and a scan of a few hundred small files is
    milliseconds.
    """
    out: list[Transcript] = []
    for path in conversations_dir().glob("*.json"):
        t = _read(path)
        if t is not None:
            t.messages = []
            out.append(t)
    out.sort(key=lambda t: t.updated_at, reverse=True)
    return out


def delete(conversation_id: str) -> bool:
    path = _path_for(conversation_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def rename(conversation_id: str, title: str) -> bool:
    t = load(conversation_id)
    if t is None:
        return False
    t.title = title
    # Set once and never unset: auto-naming checks this flag so an analyst's
    # own title is never overwritten by a later model-generated one.
    t.title_is_manual = True
    # `updated_at` is deliberately NOT touched. The rail sorts on it, and it
    # means "when did this conversation last have something said in it" — a
    # rename is bookkeeping. Bumping it would float a retitled March chat
    # above this morning's.
    save(t)
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness_history.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Measure what a real transcript actually weighs**

H1 ("the directory is the index") and H4 ("a linear scan is milliseconds")
both rest on H6's claim that transcripts are kilobytes, and nobody has
checked. `list_all()` fully JSON-parses every file on every rail load and
every debounced search keystroke, so if the claim is wrong the rail is what
pays.

Take one real `HarnessSession.history` — the cheapest source is an existing
Layer 2 eval transcript under `eval/results/agent/*/` (they embed full
retrieved-chunk text, which is exactly the payload in question), or a live
turn if you have a key — write it through `save()`, and record:

- the file size for a Standard lookup and, if available, a Deep Research turn;
- `list_all()` wall time over 200 copies of the larger one.

**Write both numbers into the module docstring** next to the "the directory
IS the index" comment, so the next person weighing an index change is arguing
with a measurement instead of an assumption.

Decision rule, chosen now so it is not chosen under pressure later: if
`list_all()` over 200 transcripts exceeds ~300 ms, do NOT add an index file
(H1 rejected that for good reasons) and do NOT trim tool results from the
stored history (see "Spec amendments" — a dangling `tool_calls` message is a
provider 400). Write the header fields a second time into the FIRST 512 bytes
of each file and give `list_all()` a bounded read, or accept the cost and say
so in STATUS. Record whichever you chose in Task 11.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1931 passed` (1921 baseline + 10)

- [ ] **Step 7: Commit**

```bash
git add harness/history.py tests/test_harness_history.py
git commit -m "feat(history): per-device transcript store, confined to %LOCALAPPDATA%"
```

---

## Task 2: Persist a transcript when a turn ends

**Files:**
- Modify: `app/routes/conversations.py`
- Test: `tests/test_history_persistence.py`

**Interfaces:**
- Consumes: `harness.history.{Transcript, save, load, now_iso}` from Task 1.
- Produces: a module-level `persist_turn(entry: _Conversation) -> None` in `app/routes/conversations.py`, called from the turn-teardown path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_persistence.py
import pytest

from harness import history


@pytest.fixture(autouse=True)
def _tmp_history(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    yield


def test_a_completed_turn_is_written_to_disk(persisted_conversation):
    """persisted_conversation drives one real turn through the SSE route."""
    conversation_id = persisted_conversation
    stored = history.load(conversation_id)
    assert stored is not None
    assert any(m.get("role") == "user" for m in stored.messages)
    assert stored.corpus == "budget"


def test_an_aborted_turn_is_still_written(aborted_conversation):
    """A cancelled turn is still a turn the analyst had.

    Losing it because they pressed stop would be a surprise, and stop is a
    designed action here, not an error.
    """
    stored = history.load(aborted_conversation)
    assert stored is not None
    assert stored.messages != []


def test_persisting_never_breaks_a_turn(monkeypatch, persisted_conversation_factory):
    """History is a convenience; it must never fail an analyst's answer."""
    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(history, "save", boom)
    conversation_id = persisted_conversation_factory()   # must not raise
    assert history.load(conversation_id) is None


def test_a_session_with_no_history_attribute_is_a_no_op_not_an_error():
    """The session_factory seam does not oblige a session to expose history.

    Every fake in tests/test_conversations_route.py is such a session. Reading
    the attribute unguarded would raise inside persist_turn, get swallowed by
    its own except, and print a scary line on ~25 unrelated tests — noise that
    trains the next person to ignore that line.
    """
    from app.routes import conversations as route

    class NoHistory:
        pass

    entry = route._Conversation(id="x1", session=NoHistory(), corpus="budget")
    route.persist_turn(entry)                 # must not raise
    assert history.load("x1") is None         # and must not write a stub
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_persistence.py -q`
Expected: FAIL — fixtures undefined / no transcript written.

Write the three fixtures in the same file, following the existing SSE-driving pattern in `tests/test_conversations_route.py` (which drives the real ASGI stack via `tests/live_request.py`, because `TestClient` buffers a "streamed" response into a `BytesIO` and cannot exercise the disconnect path).

**The fake session these fixtures inject must carry a `history` list** and
append to it as its frames are consumed — `tests/test_conversations_route.py`'s
`FakeSession` (`:62`) deliberately does not, and `persist_turn` writes nothing
for a session that has none. Build the app the way that file does —
`create_app(provider=StubSearchProvider(), static_dir=None, session_factory=…)`
— so no test in this file touches the real LanceDB corpus or the SPA build.

- [ ] **Step 3: Implement `persist_turn` and call it**

In `app/routes/conversations.py`, add near the other module-level helpers:

```python
def persist_turn(entry: _Conversation) -> None:
    """Write this conversation's transcript to the analyst's own disk.

    Called on EVERY turn teardown, including an aborted one — a cancelled
    turn is still a turn the analyst had.

    Swallows its own errors on purpose. History is a convenience; a full
    disk or a locked file must never turn a working answer into a failed
    one. The cost of being wrong here is one missing chat in a list, which
    is visible and survivable.
    """
    try:
        # getattr, not entry.session.history: the session_factory seam does
        # not oblige a session to keep a history list, and a fake that
        # doesn't must be a no-op rather than an exception this function
        # then has to swallow and print about.
        messages = getattr(entry.session, "history", None)
        if messages is None:
            return
        existing = history.load(entry.id)
        now = history.now_iso()
        history.save(
            history.Transcript(
                id=entry.id,
                title=existing.title if existing else "",
                title_is_manual=existing.title_is_manual if existing else False,
                corpus=entry.corpus,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                messages=list(messages),
            )
        )
    except Exception as exc:                      # noqa: BLE001
        print(f"jlbc-insight: could not save chat history: {exc}", file=sys.stderr, flush=True)
```

**Call it from exactly ONE place: the end of `_release_turn`
(`app/routes/conversations.py:506`), AFTER `registry.end_turn(entry, token)`.**
Three reasons, each of which the obvious two-call-site version gets wrong:

- `_release_turn` is the `BackgroundTask`, and its own docstring records why
  it is the only reliable hook — it runs after a normal response finishes AND
  after a client disconnect, and it calls `frames.close()`, which drives the
  generator's `finally`. So one call site already covers both paths. Adding a
  second inside `_turn_frames`'s `finally` would persist twice per ordinary
  turn for no gain.
- Persisting is I/O, and Task 5 hangs an LLM call off the same function. Doing
  that before `end_turn` leaves the conversation `busy`, so the analyst's next
  question gets the 409 from `begin_turn` — a working app that appears to
  refuse input for no visible reason.
- A sync `BackgroundTask` runs in Starlette's threadpool, so blocking there
  does not stall the event loop. Blocking inside the streaming generator's
  teardown holds the response open instead.

Add `from harness import history` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_persistence.py tests/test_conversations_route.py -q`
Expected: PASS, with no regression in the existing conversation tests — **and no
`could not save chat history` lines on stderr** from the fakes that have no
history attribute. Check with `-s`; a swallowed exception printing on 25
unrelated tests is the failure mode that trains people to ignore that line.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1935 passed` (1931 + 4)

- [ ] **Step 6: Commit**

```bash
git add app/routes/conversations.py tests/test_history_persistence.py
git commit -m "feat(history): persist a transcript when a turn ends or aborts"
```

---

## Task 3: List, read, rename and delete routes

**Files:**
- Create: `app/routes/history.py`
- Modify: `app/main.py`
- Test: `tests/test_history_routes.py`

**Interfaces:**
- Consumes: everything `harness.history` produces in Task 1.
- Produces: `GET /api/history`, `GET /api/history/{id}`, `PATCH /api/history/{id}`, `DELETE /api/history/{id}`. List rows are `{id, title, corpus, created_at, updated_at, message_count}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_routes.py
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history


@pytest.fixture
def client(tmp_path, monkeypatch):
    # provider + static_dir are not optional here, they are what keeps this
    # file off the real corpus: create_app() with neither runs the LanceDB
    # startup probe and looks for a built SPA. Same call shape as
    # tests/test_conversations_route.py:108.
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    return TestClient(
        create_app(
            provider=StubSearchProvider(), static_dir=None, ingest_worker=None
        )
    )


def _seed(cid="c1", title="ADC vacancy savings", n=2):
    history.save(history.Transcript(
        id=cid, title=title, corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:05:00+00:00",
        messages=[{"role": "user", "content": "q"}] * n,
    ))


def test_list_returns_rows_without_message_bodies(client):
    _seed()
    r = client.get("/api/history")
    assert r.status_code == 200
    row = r.json()["conversations"][0]
    assert row["id"] == "c1"
    assert row["message_count"] == 2
    assert "messages" not in row


def test_get_one_returns_the_full_transcript(client):
    _seed()
    r = client.get("/api/history/c1")
    assert r.status_code == 200
    assert len(r.json()["messages"]) == 2


def test_get_one_missing_is_404(client):
    assert client.get("/api/history/nope").status_code == 404


def test_rename(client):
    _seed()
    r = client.patch("/api/history/c1", json={"title": "Corrections vacancies"})
    assert r.status_code == 200
    assert history.load("c1").title == "Corrections vacancies"
    assert history.load("c1").title_is_manual is True


def test_rename_rejects_an_empty_title(client):
    _seed()
    assert client.patch("/api/history/c1", json={"title": "   "}).status_code == 422


def test_delete(client):
    _seed()
    assert client.delete("/api/history/c1").status_code == 200
    assert history.load("c1") is None


def test_a_traversal_id_is_rejected_not_served(client):
    assert client.get("/api/history/..%2F..%2Fsettings").status_code in (400, 404)


def test_history_works_with_no_api_key(client, monkeypatch):
    """No paid API is load-bearing — listing must not need AI Mode at all."""
    _seed()
    assert client.get("/api/history").status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_routes.py -q`
Expected: FAIL — 404 on every route (router not registered).

- [ ] **Step 3: Implement the routes**

```python
# app/routes/history.py
"""HTTP surface over the local chat-history store (spec H1, H4).

Every route here reads and writes ONLY the analyst's own machine. Nothing in
this module touches the corpus or the shared drive.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from harness import history

router = APIRouter()


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title cannot be blank")
        return v.strip()


def _row(t: history.Transcript) -> dict:
    return {
        "id": t.id, "title": t.title, "corpus": t.corpus,
        "created_at": t.created_at, "updated_at": t.updated_at,
        "title_is_manual": t.title_is_manual,
        "message_count": t.message_count,
    }


def _load_or_404(conversation_id: str) -> history.Transcript:
    # ValueError is the store refusing a non-bare id (traversal); surface it
    # as 400 rather than letting it become a 500.
    try:
        t = history.load(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad conversation id")
    if t is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    return t


@router.get("/api/history")
def list_history() -> dict:
    # One read per file: `list_all` records message_count while stripping the
    # bodies, so the count never costs a second pass over the directory.
    return {"conversations": [_row(t) for t in history.list_all()]}


@router.get("/api/history/{conversation_id}")
def get_history(conversation_id: str) -> dict:
    t = _load_or_404(conversation_id)
    row = _row(t)
    row["messages"] = t.messages
    return row


@router.patch("/api/history/{conversation_id}")
def rename_history(conversation_id: str, body: RenameBody) -> dict:
    _load_or_404(conversation_id)
    history.rename(conversation_id, body.title)
    return _row(_load_or_404(conversation_id))


@router.delete("/api/history/{conversation_id}")
def delete_history(conversation_id: str) -> dict:
    _load_or_404(conversation_id)
    history.delete(conversation_id)
    return {"deleted": conversation_id}
```

Register in `app/main.py` beside the other routers — **above the
`/{path:path}` catch-all**, which `app/main.py:177` documents as swallowing
`/api/*` for anything registered after it:

```python
from app.routes import history as history_routes
app.include_router(history_routes.router)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_routes.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1943 passed` (1935 + 8)

- [ ] **Step 6: Commit**

```bash
git add app/routes/history.py app/main.py tests/test_history_routes.py
git commit -m "feat(history): list, read, rename and delete routes"
```

---

## Task 4: Search across titles and message text

**Files:**
- Modify: `harness/history.py`, `app/routes/history.py`
- Test: `tests/test_history_search.py`

**Interfaces:**
- Consumes: `harness.history.list_all`, `harness.history.load`.
- Produces: `harness.history.search(query: str, limit: int = 50) -> list[tuple[Transcript, str]]` returning `(transcript_without_messages, snippet)`; `GET /api/history/search?q=` returning `{"results": [{...row, "snippet": str}]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_search.py
import pytest

from harness import history


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))


def _seed(cid, title, texts):
    history.save(history.Transcript(
        id=cid, title=title, corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at=f"2026-08-02T10:0{len(cid)}:00+00:00",
        messages=[{"role": "assistant", "content": t} for t in texts],
    ))


def test_matches_message_text_not_just_the_title():
    _seed("a", "Budget question", ["The Florence prison closure saved $12.4 M."])
    hits = history.search("Florence")
    assert [t.id for t, _ in hits] == ["a"]


def test_matches_the_title_too():
    _seed("a", "Florence closure", ["unrelated body"])
    assert [t.id for t, _ in history.search("Florence")] == ["a"]


def test_the_snippet_contains_the_matching_line():
    _seed("a", "Budget question", ["line one", "The Florence prison closure saved money."])
    _t, snippet = history.search("Florence")[0]
    assert "Florence" in snippet
    assert "line one" not in snippet


def test_search_is_case_insensitive():
    _seed("a", "Budget question", ["FLORENCE prison"])
    assert history.search("florence")


def test_no_match_returns_nothing():
    _seed("a", "Budget question", ["something else"])
    assert history.search("Florence") == []


def test_results_omit_message_bodies():
    _seed("a", "Budget question", ["Florence prison"])
    t, _ = history.search("Florence")[0]
    assert t.messages == []


def test_a_corrupt_file_does_not_break_search():
    _seed("good", "Budget question", ["Florence prison"])
    (history.conversations_dir() / "bad.json").write_text("{oops", encoding="utf-8")
    assert [t.id for t, _ in history.search("Florence")] == ["good"]


def test_an_empty_query_returns_nothing_rather_than_everything():
    _seed("a", "Budget question", ["Florence"])
    assert history.search("   ") == []


def test_retrieved_corpus_text_is_not_searched():
    """H4 as amended: search the CONVERSATION, not what retrieve() returned.

    A tool result's `content` is a JSON string, so a plain isinstance(str)
    filter does not exclude it. Without this, "Florence" matches every chat
    where some retrieved passage happened to mention Florence, and the
    snippet is a slice of a JSON payload.
    """
    history.save(history.Transcript(
        id="a", title="Budget question", corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:00:00+00:00",
        messages=[
            {"role": "user", "content": "what did ADC spend?"},
            {"role": "tool", "tool_call_id": "t1", "name": "retrieve",
             "content": '{"chunks": [{"text": "Florence prison closure"}]}'},
            {"role": "assistant", "content": "ADC spent $1.2 billion."},
        ],
    ))
    assert history.search("Florence") == []
    assert [t.id for t, _ in history.search("ADC")] == ["a"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_search.py -q`
Expected: FAIL — `AttributeError: module 'harness.history' has no attribute 'search'`

- [ ] **Step 3: Implement `search`**

Append to `harness/history.py`:

```python
_SNIPPET_RADIUS = 90

# H4 as amended: only what was SAID is searchable. `role: "tool"` messages
# carry retrieve() output — full corpus passage text, as a JSON string — so
# including them would turn "find the chat where we discussed Florence" into
# "find every chat where a retrieved passage mentioned Florence", and hand
# back a slice of JSON as the snippet. An isinstance(str) check does NOT
# exclude them; the role is what distinguishes prose from payload.
_SEARCHABLE_ROLES = {"user", "assistant"}


def search(query: str, limit: int = 50) -> list[tuple[Transcript, str]]:
    """Chats matching `query` in their title or their prose, newest first.

    A plain scan, deliberately: an index over a few hundred small files buys
    milliseconds and costs a whole class of drift bug, because an index that
    disagrees with the files it describes fails silently. If this ever gets
    slow, THAT is the moment to add one — see Task 1 Step 5 for the measured
    size this assumption rests on.
    """
    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[tuple[Transcript, str]] = []
    for path in conversations_dir().glob("*.json"):
        t = _read(path)
        if t is None:
            continue
        snippet = ""
        for message in t.messages:
            if message.get("role") not in _SEARCHABLE_ROLES:
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue          # an assistant tool_calls turn has no prose
            found = content.lower().find(needle)
            if found >= 0:
                start = max(0, found - _SNIPPET_RADIUS)
                end = min(len(content), found + len(needle) + _SNIPPET_RADIUS)
                snippet = ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")
                break
        if not snippet and needle in t.title.lower():
            snippet = t.title
        if snippet:
            t.messages = []
            hits.append((t, snippet))

    hits.sort(key=lambda pair: pair[0].updated_at, reverse=True)
    return hits[:limit]
```

Add the route to `app/routes/history.py` **above** `get_history`, because
`/api/history/search` would otherwise be captured by `/api/history/{conversation_id}`:

```python
@router.get("/api/history/search")
def search_history(q: str = "") -> dict:
    # Declared BEFORE /api/history/{conversation_id} on purpose: FastAPI
    # matches in declaration order, so a later literal route loses to an
    # earlier path parameter and "search" would be read as an id.
    return {"results": [dict(_row(t), snippet=snippet) for t, snippet in history.search(q)]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_search.py tests/test_history_routes.py -q`
Expected: PASS

- [ ] **Step 5: Add a route-ordering regression test**

```python
# append to tests/test_history_routes.py
def test_search_is_not_swallowed_by_the_id_route(client):
    """Route order is load-bearing; a refactor that reorders them breaks this."""
    assert client.get("/api/history/search?q=anything").status_code == 200
```

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1953 passed` (1943 + 9 search + 1 route-order)

- [ ] **Step 6: Commit**

```bash
git add harness/history.py app/routes/history.py tests/test_history_search.py tests/test_history_routes.py
git commit -m "feat(history): search titles and message text with snippets"
```

---

## Task 5: Auto-naming

**Files:**
- Create: `harness/titles.py`
- Modify: `app/routes/conversations.py`
- Test: `tests/test_harness_titles.py`

**Interfaces:**
- Consumes: `harness.settings.{load_settings, ai_available}`, `harness.ledger.record_usage`, `harness.history`.
- Produces: `harness.titles.fallback_title(question: str) -> str`; `harness.titles.generate_title(question: str, answer: str, *, user: str, settings=None, transport=None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_harness_titles.py
import json

import httpx
import pytest

from harness import titles
from harness.ledger import LimitStatus
from harness.settings import Settings


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Keep these tests off the office ledger.

    `check_limit` reads `data_dir()/usage/` — on a dev box that is the real
    shared corpus directory. Any test here that does not stub check_limit
    would read it for real.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "data"))


def _allowed(*_a, **_kw):
    return LimitStatus(status="allowed", message=None, reason=None,
                       limit_usd=None, month_usd=0.0)


def _ok_transport(text="ADC vacancy savings", record=None):
    def handler(request):
        if record is not None:
            record["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 6,
                      "cost": 0.00004},
        })
    return httpx.MockTransport(handler)


def test_fallback_is_the_truncated_question():
    assert titles.fallback_title("What did ADC save from vacancies in FY2025?").startswith("What did ADC save")


def test_fallback_never_exceeds_sixty_characters():
    assert len(titles.fallback_title("x" * 500)) <= 60


def test_a_successful_call_returns_the_model_title(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    got = titles.generate_title("q", "a", user="destin",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_no_api_key_falls_back_without_calling_anything():
    def explode(request):
        raise AssertionError("must not call the provider without a key")
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=Settings(), transport=httpx.MockTransport(explode))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_provider_error_falls_back(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    def boom(request):
        return httpx.Response(500, json={"error": "nope"})
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(boom))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_blocked_user_falls_back_and_never_calls(monkeypatch):
    """Over the spend limit must not mean a failed chat title.

    NOTE the stub shape: check_limit takes (user, settings) POSITIONALLY and
    returns a LimitStatus. A `lambda **k: (False, "…")` stub raises TypeError
    at the call — outside generate_title's try — which would defeat the very
    property this test asserts.
    """
    blocked = LimitStatus(status="blocked", message="over limit", reason=None,
                          limit_usd=10.0, month_usd=10.0)
    monkeypatch.setattr(titles, "check_limit", lambda *_a, **_kw: blocked)
    def explode(request):
        raise AssertionError("must not call while blocked")
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(explode))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_warned_user_is_still_titled(monkeypatch):
    """"warn" is not "blocked" — only blocked stops the call."""
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    warned = LimitStatus(status="warn", message="80%", reason=None,
                         limit_usd=10.0, month_usd=8.5)
    monkeypatch.setattr(titles, "check_limit", lambda *_a, **_kw: warned)
    got = titles.generate_title("q", "a", user="d",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_the_call_is_ledgered_under_its_own_tier(monkeypatch):
    """S19: title spend must never read as analyst spend in the admin panel."""
    seen = {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage",
                        lambda **kw: seen.update(kw))
    titles.generate_title("q", "a", user="destin",
                          settings=_settings_with_key(), transport=_ok_transport())
    assert seen["tier"] == "title"
    assert seen["user"] == "destin"


def test_openrouter_is_asked_for_the_dollar_cost(monkeypatch):
    """Without `usage: {include: true}` OpenRouter returns no `cost`.

    The row would then be written with cost_usd=None, which (a) sums as zero
    in month_total, so title spend is invisible to the S19 limit it is
    supposed to be counted against, and (b) increments
    rows_with_unknown_cost, which the admin page explains to the analyst as
    "older requests … made before prices were set up" — an explanation that
    would be false and unfixable.
    """
    seen, record = {}, {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", lambda **kw: seen.update(kw))
    titles.generate_title("q", "a", user="d", settings=_settings_with_key(),
                          transport=_ok_transport(record=record))
    assert record["body"]["usage"] == {"include": True}
    assert seen["cost_usd"] == 0.00004


def test_a_custom_endpoint_is_not_sent_the_openrouter_extension(monkeypatch):
    """S15: a strict OpenAI-compatible server rejects unknown top-level
    fields outright. Same gate harness/session.py:935 applies."""
    record = {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", lambda **kw: None)
    titles.generate_title("q", "a", user="d",
                          settings=_settings_with_key(provider="custom"),
                          transport=_ok_transport(record=record))
    assert "usage" not in record["body"]


def test_a_ledger_failure_does_not_throw_away_a_paid_for_title(monkeypatch):
    """record_usage RAISES by contract (harness/ledger.py) — the money is
    already spent by then, so losing the title too is the worst outcome."""
    def boom(**_kw):
        raise OSError("share full")
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", boom)
    got = titles.generate_title("q", "a", user="d",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_a_rambling_reply_is_truncated_not_used_raw(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    got = titles.generate_title("q", "a", user="d", settings=_settings_with_key(),
                                transport=_ok_transport("Sure! Here is a title: " + "x" * 300))
    assert len(got) <= 60
```

Write `_settings_with_key(provider="openrouter")` in the same file, building a
`Settings` with a key and a Standard tier model — copy the shape from
`tests/test_harness_session.py`, which already constructs one. The `provider`
parameter feeds the custom-endpoint spec above; on `"custom"` it must also
carry both per-million prices, or `check_limit`'s `has_pricing` branch changes
what is being tested.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness_titles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.titles'`

- [ ] **Step 3: Implement `harness/titles.py`**

```python
"""Auto-naming for a chat (spec H3).

One short non-streaming call after the first exchange. `harness/session.py`
always streams WITH tool schemas, so there is no existing plain-completion
path to reuse — hence a separate small module.

THE RULE THAT MATTERS: this never blocks and never fails a chat. No key, AI
Mode off, over the spend limit, provider error, malformed reply — every one
falls back to truncating the question. Naming is a convenience, and history
must keep working with no OpenRouter key at all, exactly like search, fiscal
notes and upload do.
"""
from __future__ import annotations

import sys

import httpx

from harness.ledger import check_limit, record_usage
from harness.settings import Settings, ai_available, load_settings

TITLE_TIER = "title"
MAX_TITLE_CHARS = 60
_TIMEOUT_S = 20.0

_PROMPT = (
    "Give a 3-6 word title for this exchange between a fiscal analyst and a "
    "budget research tool. Reply with the title only — no quotes, no preamble."
)


def fallback_title(question: str) -> str:
    """The free, always-available title: the question, truncated."""
    flat = " ".join((question or "").split())
    if len(flat) <= MAX_TITLE_CHARS:
        return flat or "New chat"
    return flat[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def generate_title(
    question: str,
    answer: str,
    *,
    user: str,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    settings = settings if settings is not None else load_settings()
    fallback = fallback_title(question)

    ok, _reason = ai_available(settings, "standard")
    if not ok:
        return fallback

    # check_limit takes user and settings POSITIONALLY and returns a
    # LimitStatus whose `.status` is "allowed" | "warn" | "blocked" — it is
    # NOT a (bool, str) tuple. "warn" still permits the call.
    if check_limit(user, settings).status == "blocked":
        # Being over the office spend cap must not also cost you a readable
        # chat list. The cap governs answers, not bookkeeping.
        return fallback

    model = settings.tiers["standard"].model
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer[:2000]}"},
        ],
        "max_tokens": 24,
        "stream": False,
    }
    if settings.provider.provider == "openrouter":
        # OpenRouter's vendor extension, and the ONLY way `usage.cost` comes
        # back — exactly as harness/session.py:935 does it. Without it every
        # title row records cost_usd=None, which sums as zero (so title spend
        # never counts against the S19 limit it is supposed to count against)
        # and increments rows_with_unknown_cost, which the admin page
        # explains as "older requests, made before prices were set up".
        # Gated because a strict OpenAI-compatible server (S15) rejects
        # unknown top-level fields outright.
        body["usage"] = {"include": True}
    # The endpoint comes from settings, NOT a literal: S15's custom-endpoint
    # escape hatch means base_url is admin-configurable, and hardcoding
    # openrouter.ai here would silently ignore it.
    url = settings.provider.base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT_S) as client:
            response = client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {settings.provider.api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        text = (payload["choices"][0]["message"]["content"] or "").strip().strip('"')
        usage = payload.get("usage") or {}
    except Exception:                              # noqa: BLE001
        return fallback

    # Ledgered OUTSIDE the block above, and separately guarded: record_usage
    # raises by contract (harness/ledger.py's FAILURE CONTRACT). By the time
    # it runs the call has happened and the money is spent, so a share that
    # is full must cost us the ledger row — not the title we already paid
    # for.
    try:
        record_usage(
            user=user, tier=TITLE_TIER, model=model,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cost_usd=usage.get("cost"),
        )
    except Exception as exc:                       # noqa: BLE001
        print(f"jlbc-insight: could not ledger a title call: {exc}",
              file=sys.stderr, flush=True)

    if not text:
        return fallback
    # A model that ignores "title only" and writes a sentence must not put a
    # paragraph in the rail.
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_TITLE_CHARS else flat[: MAX_TITLE_CHARS - 1].rstrip() + "…"
```

Verified while writing this plan: there is no `OPENROUTER_URL` constant, and
there should not be one. `harness/session.py` builds its endpoint from
`settings.provider.base_url` for a reason — S15 lets an admin point the app at
a custom endpoint, and a module-level literal would quietly ignore that. This
module derives the URL the same way.

- [ ] **Step 4: Wire it into the first turn**

In `persist_turn` (Task 2), after saving, name the chat if it has no title yet:

```python
    # Title only once, on the first completed exchange, and never over a
    # title the analyst set themselves.
    #
    # This is a blocking HTTP call of up to _TIMEOUT_S. It is safe HERE and
    # nowhere earlier: persist_turn's single call site is at the END of
    # _release_turn, after registry.end_turn has released the conversation,
    # in a BackgroundTask (a threadpool, not the event loop). Move this call
    # any earlier in the teardown and the conversation stays `busy` for the
    # duration, so the analyst's next question gets a 409 from begin_turn.
    stored = history.load(entry.id)
    if stored and not stored.title and not stored.title_is_manual:
        first_q = next((m.get("content", "") for m in stored.messages
                        if m.get("role") == "user"), "")
        first_a = next((m.get("content", "") for m in stored.messages
                        if m.get("role") == "assistant" and m.get("content")), "")
        stored.title = titles.generate_title(first_q, first_a, user=current_user())
        history.save(stored)
```

`generate_title` never returns empty — `fallback_title` bottoms out at
"New chat" — so this runs at most once per conversation even when every
provider call fails.

- [ ] **Step 5: Label the new tier where an admin will read it**

`GET /api/admin/usage`'s "By answer mode" tab renders the raw tier key
(`webapp/src/admin/CostsPanel.tsx:128`), so without this the office admin sees
a row labelled `title` next to "standard" and "deep_research" with no way to
tell what it is. Add a display map in `CostsPanel.tsx` — `title` → **"Chat
naming"** — and a vitest spec in a new `webapp/src/admin/CostsPanel.test.tsx`
(that directory colocates its specs — `ModelPicker.test.tsx`,
`Toggle.test.tsx` — rather than using a `__tests__` folder) asserting the raw
key never reaches the page. Keep the stored key `"title"`: it is a machine
key, and renaming it later would orphan every row already written.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_harness_titles.py tests/test_history_persistence.py -q`
Expected: PASS (12 title specs)

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1965 passed` (1953 + 12)

Run: `cd webapp && npm run test`
Expected: PASS, +1 spec.

- [ ] **Step 7: Commit**

```bash
git add harness/titles.py app/routes/conversations.py tests/test_harness_titles.py \
        webapp/src/admin/CostsPanel.tsx webapp/src/admin/CostsPanel.test.tsx
git commit -m "feat(history): auto-name a chat, ledgered under its own tier, never load-bearing"
```

---

## Task 6: Resume — rehydrate a stored transcript

**Files:**
- Modify: `app/routes/conversations.py`
- Test: `tests/test_history_resume.py`

**Interfaces:**
- Consumes: `harness.history.load`.
- Produces: `POST /api/conversations` accepts optional `resume_from: str | None`. Response gains `"resumed": bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_resume.py
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history


class FakeSession:
    """Minimal stand-in that records the history it was seeded with.

    A resume test must NOT fall through to default_session_factory: that
    builds a real HarnessSession, which pulls in the retrieval stack and
    reads the real settings.json.
    """

    def __init__(self, *, history=None, **kw):
        self.history = list(history or [])
        self.built_with = kw


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))

    def factory(conversation_id, *, corpus, tier, user, history=None):
        return FakeSession(history=history, id=conversation_id, corpus=corpus,
                           tier=tier, user=user)

    return TestClient(create_app(
        provider=StubSearchProvider(), static_dir=None,
        session_factory=factory, ingest_worker=None,
    ))


def _seed(cid="old1"):
    history.save(history.Transcript(
        id=cid, title="ADC", corpus="fiscal_notes",
        created_at="2026-08-02T10:00:00+00:00", updated_at="2026-08-02T10:00:00+00:00",
        messages=[{"role": "user", "content": "earlier question"},
                  {"role": "assistant", "content": "earlier answer"}],
    ))


def test_resuming_seeds_the_session_history(client):
    _seed()
    r = client.post("/api/conversations", json={"corpus": "fiscal_notes", "resume_from": "old1"})
    assert r.status_code == 200
    assert r.json()["resumed"] is True
    # `app.state.conversations` — NOT conversation_registry (app/main.py:175).
    registry = client.app.state.conversations
    entry = registry.get(r.json()["conversation_id"])
    assert [m["content"] for m in entry.session.history] == ["earlier question", "earlier answer"]


def test_resuming_adopts_the_stored_corpus_not_the_requested_one(client):
    """A stored chat must reopen on the corpus it was recorded against.

    Otherwise it answers fiscal-note questions out of the budget corpus,
    cited and confident — the exact failure the Ai.tsx remount guards.
    """
    _seed()
    r = client.post("/api/conversations", json={"corpus": "budget", "resume_from": "old1"})
    entry = client.app.state.conversations.get(r.json()["conversation_id"])
    assert entry.corpus == "fiscal_notes"


def test_resuming_an_unknown_id_is_404_not_a_blank_chat(client):
    r = client.post("/api/conversations", json={"corpus": "budget", "resume_from": "nope"})
    assert r.status_code == 404


def test_a_traversal_resume_id_is_refused(client):
    r = client.post("/api/conversations",
                    json={"corpus": "budget", "resume_from": "../settings"})
    assert r.status_code == 400


def test_creating_without_resume_from_is_unchanged(client):
    r = client.post("/api/conversations", json={"corpus": "budget"})
    assert r.status_code == 200
    assert r.json()["resumed"] is False
    entry = client.app.state.conversations.get(r.json()["conversation_id"])
    assert entry.session.history == []


def test_a_resumed_conversation_keeps_its_original_id(client):
    """Continuing a chat must update that chat, not fork a second one."""
    _seed()
    r = client.post("/api/conversations", json={"corpus": "fiscal_notes", "resume_from": "old1"})
    assert r.json()["conversation_id"] == "old1"


def test_resuming_a_conversation_that_is_still_open_reuses_it(client):
    """Reusing the stored id means the registry key can already be taken.

    `ConversationRegistry.add` assigns `_items[id] = entry` outright, so a
    second create for the same id would silently replace a live session
    WITHOUT closing it — leaking its httpx client and leaving /stop and the
    next message addressing a different object under the same id.
    """
    _seed()
    first = client.post("/api/conversations",
                        json={"corpus": "fiscal_notes", "resume_from": "old1"})
    entry = client.app.state.conversations.get("old1")
    second = client.post("/api/conversations",
                         json={"corpus": "fiscal_notes", "resume_from": "old1"})
    assert second.status_code == 200
    assert second.json()["conversation_id"] == first.json()["conversation_id"]
    # The SAME object, not a replacement.
    assert client.app.state.conversations.get("old1") is entry


def test_resuming_a_conversation_that_is_mid_answer_is_refused(client):
    """409, the same answer begin_turn already gives a double-submit."""
    _seed()
    client.post("/api/conversations", json={"corpus": "fiscal_notes", "resume_from": "old1"})
    client.app.state.conversations.get("old1").busy = True
    r = client.post("/api/conversations",
                    json={"corpus": "fiscal_notes", "resume_from": "old1"})
    assert r.status_code == 409
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_resume.py -q`
Expected: FAIL — `resume_from` is rejected as an unknown field / `resumed` missing.

- [ ] **Step 3: Implement**

In `app/routes/conversations.py`:

```python
class CreateConversationBody(BaseModel):
    corpus: str = Field(default="budget", pattern="^(budget|fiscal_notes)$")
    # Continuing a stored chat reuses THIS route rather than getting its own.
    # A parallel "resume" endpoint would be a second code path doing the same
    # job, and the two would drift; reusing create is what makes a rehydrated
    # conversation indistinguishable from a fresh one downstream.
    resume_from: str | None = None
```

Then in `create_conversation`, **after** the existing
`ok, reason = ai_available(load_settings(), DEFAULT_TIER)` line (it is already
the first statement in the body) and before the id is minted — so the early
return below reuses `ok`/`reason` instead of computing the health block twice:

```python
    stored = None
    if body.resume_from:
        try:
            stored = history.load(body.resume_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad conversation id")
        if stored is None:
            raise HTTPException(status_code=404, detail="no such conversation")

        # A resumed id is NOT unique the way uuid4() is, so it can already be
        # in the registry — the analyst reopened a chat they already
        # continued this session, or has it open in a second tab.
        # `ConversationRegistry.add` would overwrite the entry outright and
        # never close the old session, so /stop and the next message would
        # address a different object under the same id while the first kept
        # streaming and billing. Reuse it instead.
        live = _registry(request).get(stored.id)
        if live is not None:
            if live.busy:
                # Same answer begin_turn gives a double-submit, for the same
                # reason: this conversation is mid-answer.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This conversation is still answering the previous "
                        "question. Wait for it to finish before reopening it."
                    ),
                )
            health: dict[str, Any] = {"ok": ok}      # `ok`/`reason` from above
            if reason:
                health["reason"] = reason
            return {
                "conversation_id": live.id,
                "health": health,
                "tier_default": DEFAULT_TIER,
                "resumed": True,
            }

    # Keep the ORIGINAL id so continuing a chat updates it rather than
    # forking a second transcript with the same content.
    conversation_id = stored.id if stored else uuid.uuid4().hex
    # The stored corpus wins over whatever the client asked for: the
    # transcript was recorded against one corpus and answering it out of the
    # other would be wrong, cited and confident.
    corpus = stored.corpus if stored else body.corpus

    # `history=` is passed ONLY when resuming. Passing it unconditionally
    # would break every session_factory that does not accept it — which is
    # all of them today: default_session_factory (:325) and the ~25 call
    # sites behind tests/test_conversations_route.py's `factory_for` (:122).
    extra = {"history": list(stored.messages)} if stored else {}
    session = _session_factory(request)(
        conversation_id, corpus=corpus, tier=DEFAULT_TIER, user=current_user(),
        **extra,
    )
```

and add `"resumed": stored is not None` to the returned dict.

Extend `default_session_factory` to take `history: list[dict] | None = None`
and forward it — `HarnessSession.__init__` already accepts it
(`harness/session.py:400`). **Keep the default**, so the existing no-history
call is byte-identical.

**The `get`-then-`add` above is check-then-act, and `ConversationRegistry`
exists because that shape goes wrong under concurrency** (its own docstring
says so — FastAPI runs `def` handlers in a threadpool, so two tabs really can
be inside this route at once). The version written above is no worse than
today's behaviour if it loses the race, but the honest fix is six lines in the
registry: a `get_or_add(entry_factory)` that does the lookup and the insert
under `_lock` and returns `(entry, created)`. Prefer that; it is where the
lock already lives, and it keeps `create_conversation` from reaching into
registry internals to reason about a race the registry owns.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_resume.py tests/test_conversations_route.py -q`
Expected: PASS — and specifically no `TypeError: make() got an unexpected
keyword argument 'history'` from the existing fakes, which is what the
`extra` dict above exists to prevent.

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1973 passed` (1965 + 8)

- [ ] **Step 5: Commit**

```bash
git add app/routes/conversations.py tests/test_history_resume.py
git commit -m "feat(history): resume a stored chat by seeding HarnessSession history"
```

---

## Task 7: Client API bindings and the history hook

**Files:**
- Modify: `webapp/src/api.ts`
- Create: `webapp/src/chat/use-history.ts`
- Test: `webapp/src/chat/__tests__/use-history.test.ts`

**Interfaces:**
- Produces: `api.listHistory()`, `api.getHistoryChat(id)`, `api.searchHistory(q)`, `api.renameHistoryChat(id, title)`, `api.deleteHistoryChat(id)`; `createConversation(corpus, resumeFrom?)`. Hook `useHistory()` returning `{chats, loading, error, query, setQuery, reload, rename, remove}`.

- [ ] **Step 1: Write the failing tests**

```typescript
// webapp/src/chat/__tests__/use-history.test.ts
import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useHistory } from "../use-history";
import * as api from "../../api";

const ROW = {
  id: "c1", title: "ADC vacancy savings", corpus: "budget",
  created_at: "2026-08-02T10:00:00+00:00", updated_at: "2026-08-02T10:05:00+00:00",
  title_is_manual: false, message_count: 2,
};

beforeEach(() => vi.restoreAllMocks());

it("loads chats on mount", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  expect(result.current.chats[0].title).toBe("ADC vacancy savings");
});

it("switches to search results when a query is set", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  const search = vi.spyOn(api, "searchHistory")
    .mockResolvedValue({ results: [{ ...ROW, snippet: "…Florence prison…" }] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  act(() => result.current.setQuery("Florence"));
  await waitFor(() => expect(search).toHaveBeenCalledWith("Florence"));
  expect(result.current.chats[0].snippet).toContain("Florence");
});

it("clearing the query restores the full list", async () => {
  const list = vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  vi.spyOn(api, "searchHistory").mockResolvedValue({ results: [] });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  act(() => result.current.setQuery("zzz"));
  await waitFor(() => expect(result.current.chats).toHaveLength(0));
  act(() => result.current.setQuery(""));
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  expect(list).toHaveBeenCalledTimes(2);
});

it("a failed load surfaces an error instead of an empty list", async () => {
  vi.spyOn(api, "listHistory").mockRejectedValue(new Error("nope"));
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.error).toBeTruthy());
});

it("remove drops the chat locally without a refetch", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [ROW] });
  vi.spyOn(api, "deleteHistoryChat").mockResolvedValue({ deleted: "c1" });
  const { result } = renderHook(() => useHistory());
  await waitFor(() => expect(result.current.chats).toHaveLength(1));
  await act(() => result.current.remove("c1"));
  expect(result.current.chats).toHaveLength(0);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/use-history.test.ts`
Expected: FAIL — cannot resolve `../use-history`.

- [ ] **Step 3: Implement the API bindings**

Append to `webapp/src/api.ts`, following the existing `fail()` convention:

```typescript
export interface HistoryRow {
  id: string; title: string; corpus: "budget" | "fiscal_notes";
  created_at: string; updated_at: string;
  title_is_manual: boolean; message_count: number;
  snippet?: string;
}

export async function listHistory(): Promise<{ conversations: HistoryRow[] }> {
  const r = await fetch("/api/history");
  if (!r.ok) await fail(r, "load chat history");
  return r.json();
}

export async function searchHistory(q: string): Promise<{ results: HistoryRow[] }> {
  const r = await fetch(`/api/history/search?q=${encodeURIComponent(q)}`);
  if (!r.ok) await fail(r, "search chat history");
  return r.json();
}

export async function getHistoryChat(id: string): Promise<HistoryRow & { messages: unknown[] }> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`);
  if (!r.ok) await fail(r, "open chat");
  return r.json();
}

export async function renameHistoryChat(id: string, title: string): Promise<HistoryRow> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) await fail(r, "rename chat");
  return r.json();
}

export async function deleteHistoryChat(id: string): Promise<{ deleted: string }> {
  const r = await fetch(`/api/history/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok) await fail(r, "delete chat");
  return r.json();
}
```

Change `createConversation` to take an optional resume id:

```typescript
export async function createConversation(
  corpus: "budget" | "fiscal_notes",
  resumeFrom?: string,
): Promise<ConversationHandle> {
  const r = await fetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resumeFrom ? { corpus, resume_from: resumeFrom } : { corpus }),
  });
  if (!r.ok) await fail(r, "start conversation");
  return r.json();
}
```

Then write `webapp/src/chat/use-history.ts` implementing the hook to satisfy
the tests above: load on mount, debounce `query` by 200 ms, call
`searchHistory` when the trimmed query is non-empty and `listHistory` when it
is empty, expose `rename`/`remove` that update local state optimistically.

Two things the tests above will not catch on their own:

- **Drop a stale response.** With a 200 ms debounce, a fast typist can have
  two searches in flight; the slower one must not overwrite the newer result.
  Keep a request sequence number and ignore any answer that is not the latest.
- **`remove` is optimistic — put the row back if the DELETE fails.** A chat
  that vanishes from the rail and is still on disk is worse than an error.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/use-history.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add webapp/src/api.ts webapp/src/chat/use-history.ts webapp/src/chat/__tests__/use-history.test.ts
git commit -m "feat(history): client bindings and the history hook"
```

---

## Task 8: The collapsible rail

**Files:**
- Create: `webapp/src/chat/HistoryRail.tsx`
- Modify: `webapp/src/chat/AiModePanel.tsx`, the AI Mode stylesheet
- Test: `webapp/src/chat/__tests__/history-rail.test.tsx` (kebab-case — that
  directory's convention; `HistoryRail.test.tsx` would be the only outlier)

**Interfaces:**
- Consumes: `useHistory` from Task 7.
- Produces: `<HistoryRail activeId={...} onSelect={(id) => void} onNewChat={() => void} collapsed={boolean} onToggle={() => void} />`.

**This task amends D1 of `2026-08-01-ai-mode-ui-redesign-design.md`.** Read that
spec's D1 and D2 first. Rebase onto `ai-mode-ui-redesign` before starting.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/chat/__tests__/history-rail.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { HistoryRail } from "../HistoryRail.js";
import * as api from "../../api.js";

const row = (over = {}) => ({
  id: "c1", title: "ADC vacancy savings", corpus: "budget",
  created_at: "2026-08-02T10:00:00+00:00", updated_at: new Date().toISOString(),
  title_is_manual: false, message_count: 2, ...over,
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [row()] });
});

it("renders chats under a day heading", async () => {
  render(<HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  expect(await screen.findByText("ADC vacancy savings")).toBeInTheDocument();
  expect(screen.getByText("Today")).toBeInTheDocument();
});

it("groups an older chat separately", async () => {
  const old = row({ id: "c2", title: "Old chat", updated_at: "2026-07-01T10:00:00+00:00" });
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [row(), old] });
  render(<HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  await screen.findByText("Old chat");
  expect(screen.getByText("Earlier")).toBeInTheDocument();
});

it("selecting a chat calls onSelect with its id", async () => {
  const onSelect = vi.fn();
  render(<HistoryRail activeId={null} onSelect={onSelect} onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  fireEvent.click(await screen.findByText("ADC vacancy savings"));
  expect(onSelect).toHaveBeenCalledWith("c1");
});

it("collapsed hides the list but keeps the expand control reachable", async () => {
  render(<HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                      collapsed={true} onToggle={() => {}} />);
  await waitFor(() => expect(screen.queryByText("ADC vacancy savings")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: /chat history/i })).toBeInTheDocument();
});

it("shows a snippet on search results", async () => {
  vi.spyOn(api, "searchHistory").mockResolvedValue({
    results: [{ ...row(), snippet: "…the Florence prison closure…" }],
  });
  render(<HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "Florence" } });
  expect(await screen.findByText(/Florence prison closure/)).toBeInTheDocument();
});

it("an empty history explains itself rather than rendering nothing", async () => {
  vi.spyOn(api, "listHistory").mockResolvedValue({ conversations: [] });
  render(<HistoryRail activeId={null} onSelect={() => {}} onNewChat={() => {}}
                      collapsed={false} onToggle={() => {}} />);
  expect(await screen.findByText(/no saved chats yet/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/history-rail.test.tsx`
Expected: FAIL — cannot resolve `../HistoryRail.js`.

- [ ] **Step 3: Implement `HistoryRail.tsx`**

Build the component to satisfy those tests: a `<nav>` with an accessible name,
a **New chat** button, a `role="searchbox"` input bound to `useHistory().setQuery`,
and chats grouped into `Today` / `Yesterday` / `Earlier` by `updated_at`. Each
chat is a button showing its title, plus its snippet when searching. Hover
reveals rename and delete. When `collapsed`, render only the toggle button with
`aria-label="Chat history"`.

- [ ] **Step 4: Mount it in `AiModePanel.tsx` and style it**

**Not `Ai.tsx`** — the source panel's open state is `viewerOpen` in
`webapp/src/chat/AiModePanel.tsx:209`, set by
`useCitationSelected(() => setViewerOpen(true))`. `Ai.tsx` owns the corpus
picker and renders `<AiConversation>`; it has no idea whether the viewer is
open, so the auto-collapse rule cannot be written there without lifting state
for no reason.

Add the rail to the left of the chat region. Two rules from the A1 amendment
are load-bearing and must be implemented, not assumed:

```tsx
// The rail auto-collapses when the source panel opens. D1 gives the chat
// region ONE content measure (~768px); a rail plus that column plus a PDF
// panel would crush the thread, which is the exact problem D1 exists to
// prevent. The rail yields, the thread does not.
useEffect(() => {
  if (viewerOpen) setRailCollapsed(true);
}, [viewerOpen]);
```

Auto-collapse must not become a trap: closing the source panel leaves the rail
collapsed (it does not spring back), and the toggle stays reachable, so an
analyst who re-expands it while a source is open is not fought by the effect
on the next citation click. Write a spec for that — it is the difference
between "yields politely" and "cannot be opened".

Persist the collapsed flag per device in `localStorage` — this is UI
preference, not history, so it does not belong in the transcript store. Guard
the read: a `localStorage` that throws (private mode, a locked-down profile)
must default to expanded rather than break the panel.

The rail is its own scroll container. D2 says `.chat-thread-scroll` is the only
scroller **in the chat region**; the rail sits outside it, so D2 is unaffected.

- [ ] **Step 5: Run the tests and the full webapp suite**

Run: `cd webapp && npm run test`
Expected: PASS, no regressions.

Run: `cd webapp && npx tsc -b`
Expected: clean. (`tsc -b` is stricter than `tsc --noEmit` and rejects unused imports the dev check allows.)

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/HistoryRail.tsx webapp/src/chat/AiModePanel.tsx webapp/src/styles \
        webapp/src/chat/__tests__/history-rail.test.tsx
git commit -m "feat(history): collapsible history rail (amends redesign D1)"
```

---

## Task 9: Open and lazily resume a stored chat

**Files:**
- Create: `webapp/src/chat/history-rehydrate.ts`
- Modify: `webapp/src/chat/chat-types.ts`, `webapp/src/chat/chat-reducer.ts`,
  `webapp/src/chat/use-chat.ts`, `webapp/src/pages/Ai.tsx`
- Test: `webapp/src/chat/__tests__/history-rehydrate.test.ts`,
  `webapp/src/chat/__tests__/use-chat-resume.test.ts`

**Interfaces:**
- Consumes: `api.getHistoryChat`, `api.createConversation(corpus, resumeFrom)`.
- Produces: `rehydrateTurns(messages: unknown[]): Turn[]`; a `REHYDRATED`
  `ChatAction`; `useChat(corpus, resumeFrom?: string)`.

> **This is the largest task in the plan, and the spec makes it sound like a
> prop change.** The stored transcript is OpenAI-format wire history — `user`
> messages, `assistant` messages carrying `tool_calls` whose `arguments` are a
> JSON **string**, and `tool` replies keyed by `tool_call_id`. The UI timeline
> is `Turn[]` of `AssistantBlock[]` (`webapp/src/chat/chat-types.ts:16`), built
> today only by the reducer's `from-provider-event` path. Nothing converts
> between them. That converter is this task's real content; the `resumeFrom`
> plumbing is the easy half.
>
> **What it buys, and it is a lot:** citation chips are extracted from an
> assistant turn's tool blocks, and `citation.resolved` comes from the
> `retrieve` tool result in the same turn. Restore the tool blocks faithfully
> and every chip, tool card and source link in a reopened chat works with no
> further wiring — which is exactly what H2 promises ("renders fully live").
> Get the tool blocks wrong and a reopened chat renders as prose with dead
> citations.

- [ ] **Step 1: The converter — its own red-green cycle, before any wiring**

Write `webapp/src/chat/__tests__/history-rehydrate.test.ts` first, watch it
fail on the missing module, then implement. It is a pure function over plain
data, so it is testable without React and should be finished and green before
`use-chat` is touched.

`webapp/src/chat/history-rehydrate.ts` — `rehydrateTurns(messages) => Turn[]`:

- `role: "user"` → a `UserTurn` with `pending: false`.
- `role: "assistant"` → an `AssistantTurn`. Its `content` (when non-empty)
  becomes a `kind: "text"` block; each entry of its `tool_calls` becomes a
  `kind: "tool"` block with `toolUseId = call.id`, `toolName =
  call.function.name`, and `input = JSON.parse(call.function.arguments)`.
- The following `role: "tool"` messages fill in `output` on the block whose
  `toolUseId` matches their `tool_call_id`, and set `status`
  (`"complete"`/`"failed"`) plus `isError`. A cancelled-turn back-fill
  (`harness/session.py:1093`) arrives as an ordinary tool reply, so it needs
  no special case.
- Consecutive assistant/tool messages **merge into one `AssistantTurn`** until
  the next `user` message. The loop appends an assistant message and its tool
  replies together, so run-boundaries are exactly the user messages.
- `isComplete: true` on every rehydrated turn — the turn is over by
  definition.

Specs to write, each one a shape that really occurs in stored history:

1. a plain user/assistant pair round-trips to two turns;
2. an assistant turn with `tool_calls` + replies produces text and tool blocks
   **in arrival order** (the reducer's contract, and what makes text → tool
   card → text render the way it did live);
3. `arguments` that is not valid JSON yields `input: {}` and does not throw —
   a truncated tool call is a real shape (`ToolExecutor` has a message for it),
   and one bad chat must not fail to open;
4. a tool call with no matching reply still renders (status `"failed"`), since
   a torn file or an older transcript can contain one;
5. an unknown role is skipped rather than rendered;
6. the whole thing on an empty list returns `[]`.

**Timestamps are fabricated and must be labelled as such.** `Turn.timestamp`
is required, and `HarnessSession.history` records no per-message time — the
transcript has only `created_at`/`updated_at`. Derive them from the
transcript's `created_at` (all equal is fine) and put a comment saying so, so
nobody later reads a rehydrated turn's clock as evidence of when it happened.

- [ ] **Step 2: Write the failing tests**

```typescript
// webapp/src/chat/__tests__/use-chat-resume.test.ts
import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useChat } from "../use-chat";
import * as api from "../../api";

beforeEach(() => vi.restoreAllMocks());

it("opening a stored chat creates NO conversation", async () => {
  // The whole point of H2: browsing history must cost nothing.
  const create = vi.spyOn(api, "createConversation");
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 2,
    messages: [{ role: "user", content: "earlier" }],
  } as never);
  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(result.current.timeline.length).toBeGreaterThan(0));
  expect(create).not.toHaveBeenCalled();
});

it("the first send resumes from the stored id", async () => {
  vi.spyOn(api, "getHistoryChat").mockResolvedValue({
    id: "old1", title: "t", corpus: "budget", created_at: "", updated_at: "",
    title_is_manual: false, message_count: 1, messages: [],
  } as never);
  const create = vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "old1", health: { ok: true } } as never);
  const { result } = renderHook(() => useChat("budget", "old1"));
  await waitFor(() => expect(api.getHistoryChat).toHaveBeenCalled());
  await act(() => result.current.send("next question"));
  expect(create).toHaveBeenCalledWith("budget", "old1");
});

it("a new chat still creates without a resume id", async () => {
  const create = vi.spyOn(api, "createConversation")
    .mockResolvedValue({ conversation_id: "n1", health: { ok: true } } as never);
  const { result } = renderHook(() => useChat("budget"));
  await act(() => result.current.send("hello"));
  expect(create).toHaveBeenCalledWith("budget", undefined);
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/use-chat-resume.test.ts`
Expected: FAIL — `useChat` takes one argument.

- [ ] **Step 4: Implement**

Add one action to `chat-types.ts` — `{ type: "REHYDRATED"; conversationId:
string | null; turns: Turn[] }` — and handle it in `chat-reducer.ts` by
returning `{...initialChatState, conversationId, turns}`. It is deliberately
shaped like `CONVERSATION_STARTED` (which already resets to
`initialChatState`, `chat-reducer.ts:30`): opening a stored chat replaces the
timeline wholesale, it never merges into one.

Then extend `useChat(corpus, resumeFrom?)`:

- On mount, when `resumeFrom` is set, fetch the transcript, run
  `rehydrateTurns` and dispatch `REHYDRATED` with `conversationId: null`.
  **Do not** create a conversation.
- Guard the fetch against unmount and against a changed `resumeFrom` — the
  hook already keeps `mountedRef` for exactly this.
- A failed fetch dispatches `TURN_ERROR` with the server's message; it must
  not leave a blank panel that looks like an empty chat.
- Keep `conversationIdRef` null until the first send, so the existing
  lazy-create branch at `use-chat.ts:107` still governs. Hold `resumeFrom` in
  a ref (`resumeFromRef`) rather than closing over the prop — `send` is a
  `useCallback` keyed on `[corpus, safeDispatch]`, and adding a dependency
  there would rebuild it on every render of the panel.
- At that branch, pass `resumeFrom` through:

```typescript
// H2: the model session is rebuilt HERE, on the first send, not when the
// chat was opened. Browsing an old chat costs nothing; continuing it is
// what costs, and that is the analyst's own choice.
const handle = await api.createConversation(corpus, resumeFromRef.current);
```

In `Ai.tsx`, key `<AiConversation>` on
`` `${corpus}:${selectedChatId ?? "new"}` `` (today `key={corpus}`,
`webapp/src/pages/Ai.tsx:163`) so selecting a different stored chat remounts
the hook. **The existing corpus remount must survive** — the comment at
`Ai.tsx:153` explains why it is load-bearing and three specs in
`webapp/src/pages/Ai.test.tsx` fail if corpus switching stops starting a new
conversation, which is what protects against answering fiscal-note questions
out of the budget corpus. Prefixing the corpus keeps that property by
construction: any corpus change still changes the key.

Selecting a stored chat must also set `corpus` from the transcript's own
`corpus` field, or the picker and the thread disagree — the rail lists both
corpora, and the server will resume on the stored one regardless (Task 6).

- [ ] **Step 5: Run the tests**

Run: `cd webapp && npx vitest run src/chat src/pages`
Expected: PASS, including the three existing corpus-remount specs.

Run: `cd webapp && npx tsc -b`
Expected: clean. Non-optional here — this task adds a `ChatAction` variant, and
the reducer's exhaustive switch is what makes a missed case a compile error
rather than a silently dropped action at runtime.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/history-rehydrate.ts webapp/src/chat/chat-types.ts \
        webapp/src/chat/chat-reducer.ts webapp/src/chat/use-chat.ts webapp/src/pages/Ai.tsx \
        webapp/src/chat/__tests__/history-rehydrate.test.ts \
        webapp/src/chat/__tests__/use-chat-resume.test.ts
git commit -m "feat(history): lazy rehydration — live on open, session rebuilt on send"
```

---

## Task 10: The unresolvable-citation state (spec H5, as amended)

**Files:**
- Modify: `webapp/src/pdf/PdfViewer.tsx`, `webapp/src/chat/CitationChip.tsx`,
  `webapp/src/chat/citation-context.tsx`
- Test: `webapp/src/pdf/__tests__/pdf-viewer-stale.test.tsx` (that directory is
  kebab-case too — `pdf-viewer.test.tsx`, `source-panel.test.tsx`),
  `webapp/src/chat/__tests__/citation-chip-stale.test.tsx`

**Interfaces:**
- Consumes: `api.chunk(chunkId, corpus)` → `GET /api/chunks/{id}`, which 404s
  for a missing chunk (`app/routes/pdf.py:395`) and returns `text` for one
  that exists.
- Produces: an `"unresolvable"` presentation, reached from the viewer.

> **Read the H5 amendment at the top of this plan before starting.** The
> original task said "the chip consumes the existing 404". Three things are
> wrong with that, all verified:
>
> 1. `CitationChip` is a **default** export taking `{citation: Citation,
>    inlineText?}` and requiring a `CitationBusProvider` ancestor. It performs
>    no network I/O — clicking it calls `bus.select(citation)` and nothing
>    else.
> 2. In AI Mode the source is resolved **entirely client-side** from
>    `citation.resolved` (`webapp/src/pdf/PdfViewer.tsx:32`). `api.chunk()` is
>    used only by the search page's `SourcePanel`. So there is no 404 on this
>    path today to consume.
> 3. **A 404 is the rarer shape.** On a rehydrated chat `resolved` comes from
>    the STORED retrieve output, so a citation into a re-ingested document
>    still carries a docId and page and renders as an ordinary working
>    citation — it opens a page that may no longer contain the quote, and the
>    existing strict-bbox search reports "couldn't pinpoint", which reads as a
>    highlighting miss. That is quiet acceptance of a stale citation, which is
>    precisely what Invariant 2 forbids.
>
> So the check belongs at the click, in the viewer, and it has two outcomes.

- [ ] **Step 1: Write the failing tests**

Two files, because the behaviour spans two components.

`webapp/src/pdf/__tests__/pdf-viewer-stale.test.tsx` — the detection:

1. **404 → unresolvable.** `api.chunk` rejects with the route's 404; the
   viewer renders "source no longer available" naming the chunk id, and does
   NOT render a PDF canvas.
2. **200 but the stored quote is gone → unresolvable.** `api.chunk` resolves
   with `text` that does not contain the citation's quote; same state, with
   wording that says the document was re-ingested and this passage moved.
3. **200 and the quote is present → today's behaviour, unchanged.** The
   viewer opens the page and highlights, and the existing PdfViewer specs
   still pass.
4. **Nothing is fetched until a citation is selected.** Verifying on open
   would cost one round-trip per citation, which is what H2 exists to avoid.
5. **A 503 is NOT reported as a stale citation.** The share being offline
   means "we cannot tell", and telling an analyst their citation is dead when
   the network hiccupped is a worse lie than saying nothing. Render the
   store's own error.

`webapp/src/chat/__tests__/citation-chip-stale.test.tsx` — the marking. Follow
the existing `citation-chip.test.tsx` exactly: default import with a `.js`
suffix, a full `Citation` object from its `citation()` helper, wrapped in
`CitationBusProvider`.

6. a citation the viewer has reported unresolvable renders with the
   failed-citation treatment and an accessible name that says the source is no
   longer available;
7. **the verified quote is still shown** — Invariant 2: it *was* verified when
   written, which is a fact about the past, not a claim about the present
   corpus.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/pdf/__tests__/pdf-viewer-stale.test.tsx src/chat/__tests__/citation-chip-stale.test.tsx`
Expected: FAIL — no unresolvable state.

- [ ] **Step 3: Implement**

In `PdfViewer`'s `useCitationSelected` handler, before rendering `<Loaded>`:
call `api.chunk(citation.chunkId, corpus)` and classify —

- rejected as 404 → `unresolvable("gone")`;
- resolved, but the cited span —
  `citation.resolved.text.slice(citation.spanStart, citation.spanEnd)`; there
  is no `quote` field on `Citation` — does not appear in the returned `text` →
  `unresolvable("moved")`;
- resolved and present → the existing `Loaded` path, unchanged;
- any other failure → the existing error surface, NOT an unresolvable state.

**`PdfViewer` takes no props today** (`webapp/src/pdf/PdfViewer.tsx:25`) and
`api.chunk` needs a corpus. `AiModePanel` renders it at `:231` and knows the
corpus, so pass it as a prop — one required prop on a component with one call
site, rather than a new context. Default it to `"budget"` only if the search
page also mounts this component; check before assuming (`SourcePanel` is a
different component and already passes its own corpus).

Guard the async: two fast citation clicks race, and the panel must render the
verdict for the citation the analyst clicked LAST. `SourcePanel` already
solves this by matching the response's echoed `chunk_id` against the pending
request (which is why `/api/chunks/{id}` echoes it at all) — do the same.

Normalize before comparing, using the same `normalizeForMatch` the citation
extractor already uses (`webapp/src/chat/citation-extract.ts`). The server
does the same thing for the same reason (S23): a quote that is faithful but
differs by a smart quote or a collapsed line break is not a stale citation,
and calling it one would produce false alarms on live chats, not just
rehydrated ones.

Publish the verdict on the citation bus so the chip can mark itself; the bus
is already the one coupling between chip and viewer (`CitationChip.tsx:10`
says so), and threading a second channel would give the two components two
ways to disagree.

Reuse the existing failed-citation visual treatment rather than inventing a
third one — the palette has no error colour (`--az-red` is `#2f55c4`, a blue),
which is a known open item.

**This applies to live chats too, and that is correct.** A chunk can be
re-ingested while a conversation is open; the same check catches it. Nothing
here is history-specific except how often it fires.

- [ ] **Step 4: Run the tests**

Run: `cd webapp && npm run test && npx tsc -b`
Expected: PASS and clean — including the existing `pdf-viewer.test.tsx` and
`citation-chip.test.tsx` specs, which must not change behaviour for a citation
that still resolves. If `PdfViewer` gains a required prop, `tsc -b` is what
catches every call site.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/pdf/PdfViewer.tsx webapp/src/chat/CitationChip.tsx \
        webapp/src/chat/citation-context.tsx \
        webapp/src/pdf/__tests__/pdf-viewer-stale.test.tsx \
        webapp/src/chat/__tests__/citation-chip-stale.test.tsx
git commit -m "feat(history): mark citations whose source no longer resolves"
```

---

## Task 11: Documentation and status

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md`,
  `docs/HANDBOOK.md` (create the section if the file does not exist yet —
  Plan 5 Track 5 owns the file), `STATUS.md`, `CLAUDE.md`

- [ ] **Step 1: Write the three spec amendments back into the spec**

The "Spec amendments this plan makes" section at the top of this plan changes
H4, H5 and H6. A plan that silently contradicts its spec is a drift source —
the exact failure STATUS.md's opening paragraph exists to prevent. Amend the
spec in place, dated, the way `S8` and `S9` were amended:

- **H4** — searches conversation prose only; tool results are corpus text, not
  conversation, and their `content` is a string so a type check does not
  exclude them.
- **H5** — the detection is a click-time chunk fetch with TWO stale shapes
  (chunk gone; chunk present but the cited span is no longer in it), located
  in the viewer rather than the chip, because AI Mode resolves sources
  client-side from the stored retrieve output and would otherwise render a
  stale citation as a working one.
- **H6** — record the measured transcript size from Task 1 Step 5, replacing
  "transcripts are kilobytes", and record which of the two options that step
  chose. Add the constraint that history may never be pruned to whole
  `tool_calls`/reply pairs or not at all.

- [ ] **Step 2: Write the handbook paragraph**

Under the existing confidentiality/data-concerns material, add: where chat
history is stored (`%LOCALAPPDATA%\JLBC-Insight\conversations\`), that it is
per-person and per-machine and never on the shared drive, that it is plain
text an administrator can read or delete with File Explorer, and that **the
first question and answer of each chat are sent to OpenRouter to generate the
chat's name** — which is the one part of history that leaves the machine.

- [ ] **Step 3: Update `STATUS.md`**

Add a section recording what shipped, the storage location, the amendment to
the AI Mode UI redesign's D1, and the two follow-ups below.

- [ ] **Step 4: Update `CLAUDE.md`**

Add `conversations/` to the "what must travel for a fresh device" discussion in
`STATUS.md` — noting that it deliberately does NOT travel, because history is
per-device by design.

- [ ] **Step 5: Run everything**

```bash
.venv/bin/python -m pytest tests/ -q
cd webapp && npm run test && npx tsc -b
```

Capture the pytest exit code directly rather than piping into `tail` — a pipe
returns `tail`'s status and hides a failure (the convention recorded in
STATUS.md's "Working conventions").

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md \
        docs/HANDBOOK.md STATUS.md CLAUDE.md
git commit -m "docs: chat history — storage location, confidentiality, H4/H5/H6 + D1 amendments"
```

---

## Follow-ups this work creates

- **`MAX_CONVERSATIONS = 40` may want revisiting.** LRU eviction is no longer
  data loss, so the cap is now purely a memory bound. Not changed here.
- **The rail is unverified in a real browser on a JLBC machine**, the same gap
  Session A recorded for the admin page. jsdom applies no stylesheet, so
  layout and paint-order bugs — exactly the class that produced the admin
  page's clipped picker and dead toggle hitboxes — are structurally invisible
  to the vitest suite.
- **Transcript size is now measured but not managed** (Task 1 Step 5). If the
  office accumulates hundreds of Deep Research chats, `list_all()`'s full
  parse per rail load is the thing that degrades first. The bounded-header
  read is written down there; nobody has built it.
- **`title` rows will not appear in any pre-existing month's ledger**, so an
  admin comparing months sees a new line item appear from nowhere. Worth one
  sentence in the handbook's cost section rather than a code change.
- **Nothing rebinds a stale citation**, only marks it. That is the same
  standing gap as `eval/refresh_chunk_ids.py` (deleted 2026-08-01, nothing
  replaces it) — H5 makes the damage visible, which is all it claims to do.

---

## Branch collisions to plan around

Three unmerged local branches touch this surface. `git branch` at time of
writing: `ai-mode-ui-redesign` and `citation-linking` are both local-only —
neither is on `origin`.

- **`ai-mode-ui-redesign`** redesigns `Ai.tsx` and the AI Mode stylesheet.
  Tasks 8–9 rebase onto it, as the Global Constraints already say.
- **`citation-linking`** touches `CitationChip.tsx` / `citation-extract.ts` /
  the citation surface — the same files as **Task 10**, which the original
  plan did not account for. Land Task 10 last, and check that branch's diff
  before writing it: if it changes what a `Citation` carries, this task's
  span-comparison changes with it.
