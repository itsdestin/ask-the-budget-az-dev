# AI Mode Chat History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An analyst can browse, search, rename, delete and resume their own past AI Mode conversations, stored on their own machine.

**Architecture:** The app server writes one JSON transcript per conversation into a private per-user directory (`%LOCALAPPDATA%\JLBC-Insight\conversations\`). A new `app/routes/history.py` reads that directory for the rail and for search. Resuming reuses the EXISTING `POST /api/conversations` with a `resume_from` id, which loads the transcript and hands it to `HarnessSession(history=...)` — a constructor parameter that already exists. Nothing is stored in the browser.

**Tech Stack:** Python 3.12 + FastAPI + pytest (server); Vite + React 18 + vitest (webapp). `uv` for Python deps, `npm` for the webapp.

**Spec:** `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md` (H1–H6, A1).

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Work in a worktree**, and **rebase onto `ai-mode-ui-redesign` rather than racing it** — that branch is redesigning `webapp/src/pages/Ai.tsx` and the AI Mode stylesheet, which Tasks 7–10 also touch. Create with `git worktree add ~/ask-the-budget-az-worktrees/chat-history -b chat-history origin/master`.
- **Invariant 7:** `harness/history.py` MUST NOT import `store.config` or otherwise learn where the shared drive is. Pinned by an AST test in Task 1, modelled on `tests/test_create_document.py:338`.
- **Invariant 2:** a citation that no longer resolves is rendered VISIBLY MARKED. Never silently dropped, never quietly accepted.
- **No paid API may be load-bearing.** History — including listing, opening, searching, renaming and resuming — MUST work with no OpenRouter key configured. Only the auto-generated *title* degrades (to truncation).
- **S19:** every model call is recorded in the ledger. Title calls use tier `"title"` so they never inflate what reads as analyst spending.
- **Annotate non-trivial code with a WHY comment.** The project owner is a non-developer who relies on comments to understand what code does and why.
- **Run the full suite before each commit:** `.venv/bin/python -m pytest tests/ -q` (baseline on `origin/master` at time of writing: **1921 passed**) and, for webapp tasks, `cd webapp && npm run test`.
- **Do NOT run `eval/run_eval.py`.** This work touches neither `retrieval/`, `ingest/`, `chunking/` nor `harness/system-prompt.md`.
- Transcript JSON is written **tmp-file + `os.replace`**, the atomic-write convention used throughout `ingest/jobs.py` and `store/documents.py`.

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
| `webapp/src/chat/use-chat.ts` | **Modify.** Accept a resumed transcript; pass `resume_from` on lazy create. |
| `webapp/src/pages/Ai.tsx` | **Modify.** Mount the rail; wire selection. |
| `webapp/src/chat/CitationChip.tsx` | **Modify.** Add the unresolvable state. |

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


def test_an_id_that_is_not_a_bare_filename_is_refused():
    """Path traversal: an id reaches this module from an HTTP path segment."""
    for evil in ("../secrets", "a/b", "a\\b", "", ".", ".."):
        with pytest.raises(ValueError):
            history.load(evil)


def test_this_module_never_imports_store_config():
    """Invariant 7: history must not be able to learn where the share is.

    Same guard, same reason as tests/test_create_document.py — writes here
    are confined to the user's own machine by construction, not by intent.
    """
    tree = ast.parse(MODULE_SOURCE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
    assert not any(m == "store.config" or m.startswith("store.") for m in imported)
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
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
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
    t.updated_at = now_iso()
    save(t)
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness_history.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1929 passed` (1921 baseline + 8)

- [ ] **Step 6: Commit**

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_persistence.py -q`
Expected: FAIL — fixtures undefined / no transcript written.

Write the three fixtures in the same file, following the existing SSE-driving pattern in `tests/test_conversations_route.py` (which drives the real ASGI stack via `tests/live_request.py`, because `TestClient` buffers a "streamed" response into a `BytesIO` and cannot exercise the disconnect path).

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
                messages=list(entry.session.history),
            )
        )
    except Exception as exc:                      # noqa: BLE001
        print(f"jlbc-insight: could not save chat history: {exc}", file=sys.stderr, flush=True)
```

Call it from the same teardown that already calls `registry.end_turn(entry, token)` — both the normal path (`app/routes/conversations.py:453`) and the `BackgroundTask` disconnect path (`:506`). Add `from harness import history` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_persistence.py tests/test_conversations_route.py -q`
Expected: PASS, with no regression in the existing conversation tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1932 passed`

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
from harness import history


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    return TestClient(create_app(ingest_worker=None))


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

Register in `app/main.py` beside the other routers:

```python
from app.routes import history as history_routes
app.include_router(history_routes.router)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_routes.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1940 passed`

- [ ] **Step 6: Commit**

```bash
git add app/routes/history.py app/main.py harness/history.py tests/test_history_routes.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_history_search.py -q`
Expected: FAIL — `AttributeError: module 'harness.history' has no attribute 'search'`

- [ ] **Step 3: Implement `search`**

Append to `harness/history.py`:

```python
_SNIPPET_RADIUS = 90


def search(query: str, limit: int = 50) -> list[tuple[Transcript, str]]:
    """Chats matching `query` in their title or any message, newest first.

    A plain scan, deliberately: an index over a few hundred small files buys
    milliseconds and costs a whole class of drift bug, because an index that
    disagrees with the files it describes fails silently. If this ever gets
    slow, THAT is the moment to add one.
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
            content = message.get("content")
            if not isinstance(content, str):
                continue          # tool_calls carry lists/dicts, not prose
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
Expected: `1949 passed`

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
import httpx
import pytest

from harness import titles
from harness.settings import Settings


def _ok_transport(text="ADC vacancy savings"):
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 6},
        })
    return httpx.MockTransport(handler)


def test_fallback_is_the_truncated_question():
    assert titles.fallback_title("What did ADC save from vacancies in FY2025?").startswith("What did ADC save")


def test_fallback_never_exceeds_sixty_characters():
    assert len(titles.fallback_title("x" * 500)) <= 60


def test_a_successful_call_returns_the_model_title(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
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
    def boom(request):
        return httpx.Response(500, json={"error": "nope"})
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(boom))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_blocked_user_falls_back_and_never_calls(monkeypatch):
    """Over the spend limit must not mean a failed chat title."""
    monkeypatch.setattr(titles, "check_limit", lambda **k: (False, "over limit"))
    def explode(request):
        raise AssertionError("must not call while blocked")
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(explode))
    assert got == titles.fallback_title("What did ADC save?")


def test_the_call_is_ledgered_under_its_own_tier(monkeypatch):
    """S19: title spend must never read as analyst spend in the admin panel."""
    seen = {}
    monkeypatch.setattr(titles, "record_usage",
                        lambda **kw: seen.update(kw))
    titles.generate_title("q", "a", user="destin",
                          settings=_settings_with_key(), transport=_ok_transport())
    assert seen["tier"] == "title"
    assert seen["user"] == "destin"


def test_a_rambling_reply_is_truncated_not_used_raw(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    got = titles.generate_title("q", "a", user="d", settings=_settings_with_key(),
                                transport=_ok_transport("Sure! Here is a title: " + "x" * 300))
    assert len(got) <= 60
```

Write `_settings_with_key()` in the same file, building a `Settings` with an
OpenRouter key and a Standard tier model — copy the shape from
`tests/test_harness_session.py`, which already constructs one.

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
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer[:2000]}"},
        ],
        "max_tokens": 24,
        "stream": False,
    }
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
        record_usage(
            user=user, tier=TITLE_TIER, model=model,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cost_usd=usage.get("cost"),
        )
    except Exception:                              # noqa: BLE001
        return fallback

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
    stored = history.load(entry.id)
    if stored and not stored.title and not stored.title_is_manual:
        first_q = next((m.get("content", "") for m in stored.messages
                        if m.get("role") == "user"), "")
        first_a = next((m.get("content", "") for m in stored.messages
                        if m.get("role") == "assistant" and m.get("content")), "")
        stored.title = titles.generate_title(first_q, first_a, user=current_user())
        history.save(stored)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_harness_titles.py tests/test_history_persistence.py -q`
Expected: PASS

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1957 passed`

- [ ] **Step 6: Commit**

```bash
git add harness/titles.py harness/constants.py app/routes/conversations.py tests/test_harness_titles.py
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
from harness import history


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    return TestClient(create_app(ingest_worker=None))


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
    registry = client.app.state.conversation_registry
    entry = registry.get(r.json()["conversation_id"])
    assert [m["content"] for m in entry.session.history] == ["earlier question", "earlier answer"]


def test_resuming_adopts_the_stored_corpus_not_the_requested_one(client):
    """A stored chat must reopen on the corpus it was recorded against.

    Otherwise it answers fiscal-note questions out of the budget corpus,
    cited and confident — the exact failure the Ai.tsx remount guards.
    """
    _seed()
    r = client.post("/api/conversations", json={"corpus": "budget", "resume_from": "old1"})
    entry = client.app.state.conversation_registry.get(r.json()["conversation_id"])
    assert entry.corpus == "fiscal_notes"


def test_resuming_an_unknown_id_is_404_not_a_blank_chat(client):
    r = client.post("/api/conversations", json={"corpus": "budget", "resume_from": "nope"})
    assert r.status_code == 404


def test_creating_without_resume_from_is_unchanged(client):
    r = client.post("/api/conversations", json={"corpus": "budget"})
    assert r.status_code == 200
    assert r.json()["resumed"] is False
    entry = client.app.state.conversation_registry.get(r.json()["conversation_id"])
    assert entry.session.history == []


def test_a_resumed_conversation_keeps_its_original_id(client):
    """Continuing a chat must update that chat, not fork a second one."""
    _seed()
    r = client.post("/api/conversations", json={"corpus": "fiscal_notes", "resume_from": "old1"})
    assert r.json()["conversation_id"] == "old1"
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

Then in `create_conversation`, before minting the id:

```python
    stored = None
    if body.resume_from:
        try:
            stored = history.load(body.resume_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad conversation id")
        if stored is None:
            raise HTTPException(status_code=404, detail="no such conversation")

    # Keep the ORIGINAL id so continuing a chat updates it rather than
    # forking a second transcript with the same content.
    conversation_id = stored.id if stored else uuid.uuid4().hex
    # The stored corpus wins over whatever the client asked for: the
    # transcript was recorded against one corpus and answering it out of the
    # other would be wrong, cited and confident.
    corpus = stored.corpus if stored else body.corpus

    session = _session_factory(request)(
        conversation_id, corpus=corpus, tier=DEFAULT_TIER, user=current_user(),
        history=list(stored.messages) if stored else None,
    )
```

and add `"resumed": stored is not None` to the returned dict.

Confirm `_session_factory`'s `default_session_factory` forwards `history=` to
`HarnessSession`; extend its signature if not.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_history_resume.py tests/test_conversations_route.py -q`
Expected: PASS

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1962 passed`

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
- Modify: `webapp/src/pages/Ai.tsx`, the AI Mode stylesheet
- Test: `webapp/src/chat/__tests__/HistoryRail.test.tsx`

**Interfaces:**
- Consumes: `useHistory` from Task 7.
- Produces: `<HistoryRail activeId={...} onSelect={(id) => void} onNewChat={() => void} collapsed={boolean} onToggle={() => void} />`.

**This task amends D1 of `2026-08-01-ai-mode-ui-redesign-design.md`.** Read that
spec's D1 and D2 first. Rebase onto `ai-mode-ui-redesign` before starting.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/chat/__tests__/HistoryRail.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { HistoryRail } from "../HistoryRail";
import * as api from "../../api";

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

Run: `cd webapp && npx vitest run src/chat/__tests__/HistoryRail.test.tsx`
Expected: FAIL — cannot resolve `../HistoryRail`.

- [ ] **Step 3: Implement `HistoryRail.tsx`**

Build the component to satisfy those tests: a `<nav>` with an accessible name,
a **New chat** button, a `role="searchbox"` input bound to `useHistory().setQuery`,
and chats grouped into `Today` / `Yesterday` / `Earlier` by `updated_at`. Each
chat is a button showing its title, plus its snippet when searching. Hover
reveals rename and delete. When `collapsed`, render only the toggle button with
`aria-label="Chat history"`.

- [ ] **Step 4: Mount it in `Ai.tsx` and style it**

Add the rail to the left of the chat region. Two rules from the A1 amendment
are load-bearing and must be implemented, not assumed:

```tsx
// The rail auto-collapses when the source panel opens. D1 gives the chat
// region ONE content measure (~768px); a rail plus that column plus a PDF
// panel would crush the thread, which is the exact problem D1 exists to
// prevent. The rail yields, the thread does not.
useEffect(() => {
  if (sourcePanelOpen) setRailCollapsed(true);
}, [sourcePanelOpen]);
```

Persist the collapsed flag per device in `localStorage` — this is UI
preference, not history, so it does not belong in the transcript store.

The rail is its own scroll container. D2 says `.chat-thread-scroll` is the only
scroller **in the chat region**; the rail sits outside it, so D2 is unaffected.

- [ ] **Step 5: Run the tests and the full webapp suite**

Run: `cd webapp && npm run test`
Expected: PASS, no regressions.

Run: `cd webapp && npx tsc -b`
Expected: clean. (`tsc -b` is stricter than `tsc --noEmit` and rejects unused imports the dev check allows.)

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/HistoryRail.tsx webapp/src/pages/Ai.tsx webapp/src/styles webapp/src/chat/__tests__/HistoryRail.test.tsx
git commit -m "feat(history): collapsible history rail (amends redesign D1)"
```

---

## Task 9: Open and lazily resume a stored chat

**Files:**
- Modify: `webapp/src/chat/use-chat.ts`, `webapp/src/pages/Ai.tsx`
- Test: `webapp/src/chat/__tests__/use-chat-resume.test.ts`

**Interfaces:**
- Consumes: `api.getHistoryChat`, `api.createConversation(corpus, resumeFrom)`.
- Produces: `useChat(corpus, resumeFrom?: string)`.

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/use-chat-resume.test.ts`
Expected: FAIL — `useChat` takes one argument.

- [ ] **Step 3: Implement**

Extend `useChat(corpus, resumeFrom?)`:

- On mount, when `resumeFrom` is set, fetch the transcript and dispatch it into
  the reducer as a completed timeline. **Do not** create a conversation.
- Keep `conversationIdRef` null until the first send, so the existing lazy-create
  branch at `use-chat.ts:107` still governs.
- At that branch, pass `resumeFrom` through:

```typescript
// H2: the model session is rebuilt HERE, on the first send, not when the
// chat was opened. Browsing an old chat costs nothing; continuing it is
// what costs, and that is the analyst's own choice.
const handle = await api.createConversation(corpus, resumeFromRef.current);
```

In `Ai.tsx`, key the chat component on `` `${corpus}:${selectedChatId ?? "new"}` ``
so selecting a different stored chat remounts the hook. **The existing
`key={corpus}` remount must survive** — three specs in
`webapp/src/pages/Ai.test.tsx` fail if corpus switching stops starting a new
conversation, and those protect against answering fiscal-note questions out of
the budget corpus.

- [ ] **Step 4: Run the tests**

Run: `cd webapp && npx vitest run src/chat src/pages`
Expected: PASS, including the three existing corpus-remount specs.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/chat/use-chat.ts webapp/src/pages/Ai.tsx webapp/src/chat/__tests__/use-chat-resume.test.ts
git commit -m "feat(history): lazy rehydration — live on open, session rebuilt on send"
```

---

## Task 10: The unresolvable-citation state (spec H5)

**Files:**
- Modify: `webapp/src/chat/CitationChip.tsx`, `webapp/src/chat/citation-context.tsx`
- Test: `webapp/src/chat/__tests__/CitationChip.stale.test.tsx`

**Interfaces:**
- Consumes: `/api/chunks/{id}`, which already 404s for a missing chunk.
- Produces: a `"unresolvable"` chip state.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/chat/__tests__/CitationChip.stale.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CitationChip } from "../CitationChip";

it("marks a chip whose chunk no longer exists", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("", { status: 404 }) as never);
  render(<CitationChip citation={{ chunkId: "gone-0001", quote: "Spending rose $2.4 million." }} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByText(/source no longer available/i)).toBeInTheDocument();
});

it("still shows the verified quote on an unresolvable citation", async () => {
  // Invariant 2: visibly marked, never silently dropped. The quote WAS
  // verified when written — that is a fact about the past.
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("", { status: 404 }) as never);
  render(<CitationChip citation={{ chunkId: "gone-0001", quote: "Spending rose $2.4 million." }} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByText(/Spending rose \$2.4 million/)).toBeInTheDocument();
});

it("does not check the corpus until the chip is clicked", async () => {
  // Verifying on open would cost a round-trip per citation, which is what
  // lazy rehydration exists to avoid.
  const f = vi.spyOn(globalThis, "fetch");
  render(<CitationChip citation={{ chunkId: "c-0001", quote: "q" }} />);
  await waitFor(() => expect(f).not.toHaveBeenCalled());
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/CitationChip.stale.test.tsx`
Expected: FAIL — no unresolvable state.

- [ ] **Step 3: Implement**

Add an `unresolvable` state to the chip: when the click-time `/api/chunks/{id}`
fetch 404s, render the chip with the existing failed-citation styling plus the
words "source no longer available", and show the stored quote in the tooltip
with a line explaining the document has been re-ingested since.

Reuse the existing failed-citation visual treatment rather than inventing a
third one — the palette has no error colour (`--az-red` is `#2f55c4`, a blue),
which is a known open item.

- [ ] **Step 4: Run the tests**

Run: `cd webapp && npm run test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add webapp/src/chat/CitationChip.tsx webapp/src/chat/citation-context.tsx webapp/src/chat/__tests__/CitationChip.stale.test.tsx
git commit -m "feat(history): mark citations whose source no longer resolves"
```

---

## Task 11: Documentation and status

**Files:**
- Modify: `docs/HANDBOOK.md` (create the section if the file does not exist yet — Plan 5 Track 5 owns the file), `STATUS.md`, `CLAUDE.md`

- [ ] **Step 1: Write the handbook paragraph**

Under the existing confidentiality/data-concerns material, add: where chat
history is stored (`%LOCALAPPDATA%\JLBC-Insight\conversations\`), that it is
per-person and per-machine and never on the shared drive, that it is plain
text an administrator can read or delete with File Explorer, and that **the
first question and answer of each chat are sent to OpenRouter to generate the
chat's name** — which is the one part of history that leaves the machine.

- [ ] **Step 2: Update `STATUS.md`**

Add a section recording what shipped, the storage location, the amendment to
the AI Mode UI redesign's D1, and the two follow-ups below.

- [ ] **Step 3: Update `CLAUDE.md`**

Add `conversations/` to the "what must travel for a fresh device" discussion in
`STATUS.md` — noting that it deliberately does NOT travel, because history is
per-device by design.

- [ ] **Step 4: Run everything**

```bash
.venv/bin/python -m pytest tests/ -q
cd webapp && npm run test && npx tsc -b
```

- [ ] **Step 5: Commit**

```bash
git add docs/HANDBOOK.md STATUS.md CLAUDE.md
git commit -m "docs: chat history — storage location, confidentiality, D1 amendment"
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
