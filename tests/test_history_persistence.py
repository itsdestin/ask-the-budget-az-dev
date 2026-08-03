"""Persist a transcript to disk when a turn ends or aborts (Plan: chat history).

Follows the existing SSE-driving pattern in tests/test_conversations_route.py:
create_app(provider=StubSearchProvider(), static_dir=None, session_factory=…)
so no test here touches the real LanceDB corpus or the SPA build. The fake
session these fixtures inject carries a `history` list and appends to it as
its frames are consumed — the existing FakeSession deliberately does not, and
persist_turn writes nothing for a session that has none.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history

USER = "analyst1"


@pytest.fixture(autouse=True)
def _tmp_history(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    # Keep these tests off the office ledger / real settings.
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    monkeypatch.setenv("JLBC_USER", USER)
    yield


class _HistorySession:
    """A fake session that carries and appends to a `history` list.

    HarnessSession.history is the list persist_turn reads. The existing
    FakeSession in test_conversations_route.py has no `history` attribute,
    so persist_turn must treat it as a no-op — this session is what proves
    the POSITIVE path (something is written).
    """

    def __init__(self, frames=None, hold: threading.Event | None = None):
        self.history: list[dict] = []
        self.hold = hold
        self.closed = False
        self._frames = frames if frames is not None else _DEFAULT_FRAMES

    def stream_turn(self, text, *, tier=None):
        self.history.append({"role": "user", "content": text})
        try:
            for frame in self._frames:
                yield frame
                if self.hold is not None:
                    self.hold.wait(timeout=0.2)
            self.history.append({"role": "assistant", "content": "The answer."})
        except GeneratorExit:
            # Mirror HarnessSession's back-fill of a cancelled tool call — a
            # cancelled turn still has a user message and whatever assistant
            # frames were produced before the interrupt.
            self.history.append({"role": "assistant", "content": "[interrupted]"})
            raise

    def close(self):
        self.closed = True


_DEFAULT_FRAMES = [
    {"type": "user_message", "text": "hi"},
    {"type": "assistant_text_delta", "uuid": "u1", "text": "The answer."},
    {"type": "turn_complete", "stopReason": "end_turn"},
    {
        "type": "_done",
        "stopReason": "end_turn",
        "finalAnswer": "The answer.",
        "citations": [],
        "retrievedChunkIds": [],
        "usage": {"cost": 0.002},
    },
]


def _build_app(session=None, **kw):
    if session is None:
        session = _HistorySession()
    def factory(conversation_id, *, corpus, tier, user):
        return session
    kw.setdefault("session_factory", factory)
    kw.setdefault("ingest_worker", None)
    return create_app(provider=StubSearchProvider(), static_dir=None, **kw), session


def _run_turn(app) -> str:
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/conversations", json={"corpus": "budget"})
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]
    r2 = c.post(f"/api/conversations/{cid}/messages", json={"text": "hi"})
    assert r2.status_code == 200, r2.text
    return cid


@pytest.fixture
def persisted_conversation():
    app, _session = _build_app()
    return _run_turn(app)


@pytest.fixture
def persisted_conversation_factory():
    def _make():
        app, _session = _build_app()
        return _run_turn(app)
    return _make


@pytest.fixture
def aborted_conversation():
    """Drive a turn that gets interrupted mid-stream (GeneratorExit)."""
    session = _HistorySession(hold=threading.Event())
    app, session = _build_app(session=session)
    from tests.live_request import LiveRequest

    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/conversations", json={"corpus": "budget"})
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]

    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "hi"},
    )
    turn.wait_started()
    turn.hang_up()
    return cid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The mid-turn delete / rename races (persist_turn runs on a BackgroundTask
# AFTER end_turn, so the analyst can delete or rename the chat from the rail
# while its turn is still streaming).
# ---------------------------------------------------------------------------


class _StaticSession:
    """A session whose `history` is whatever the test seeds it with."""

    def __init__(self, messages):
        self.history = messages


def _entry(cid, messages):
    from app.routes import conversations as route

    return route._Conversation(id=cid, session=_StaticSession(messages), corpus="budget")


# A continuation: more than the opening exchange (a first turn is 1 user + at
# most 1 assistant; this has two full exchanges).
_CONTINUATION = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "q2"},
    {"role": "assistant", "content": "a2"},
]


def test_a_mid_turn_delete_is_not_resurrected_by_the_turn_end_write(monkeypatch):
    """The analyst deletes a chat from the rail while its turn is streaming.

    persist_turn then finds nothing on disk (existing is None) — but this is a
    CONTINUATION, so 'no file' means 'deleted', and writing would resurrect
    the chat as an untitled ghost. The delete must win.
    """
    from app.routes import conversations as route

    monkeypatch.setattr(route.titles, "generate_title", lambda *a, **k: "")
    # Seed a chat as if turn 1 already persisted, then delete it (the rail's
    # DELETE). Turn 2's teardown then runs persist_turn against a missing file.
    history.save(history.Transcript(
        id="gone1", title="t", corpus="budget", created_at="c", updated_at="u",
        messages=_CONTINUATION[:2],
    ))
    assert history.delete("gone1") is True

    route.persist_turn(_entry("gone1", list(_CONTINUATION)))

    assert history.load("gone1") is None, "a deleted chat was resurrected by persist_turn"


def test_a_first_turn_still_creates_the_file(monkeypatch):
    """The guard must not swallow a conversation's FIRST persist — that path
    is always existing-is-None and is the normal way a transcript appears."""
    from app.routes import conversations as route

    monkeypatch.setattr(route.titles, "generate_title", lambda *a, **k: "")
    route.persist_turn(_entry("new1", [{"role": "user", "content": "q1"},
                                       {"role": "assistant", "content": "a1"}]))

    stored = history.load("new1")
    assert stored is not None
    assert [m["content"] for m in stored.messages] == ["q1", "a1"]


def test_a_tool_calling_first_turn_is_not_mistaken_for_a_deleted_continuation(monkeypatch):
    """A first turn that calls tools is [user, assistant(tool_calls), tool,
    assistant(answer)] — TWO assistant messages on the very first turn. The
    first-vs-deleted check must key on the USER count (one), or a tool-using
    first turn reads as a 'deleted continuation' and is never written."""
    from app.routes import conversations as route

    monkeypatch.setattr(route.titles, "generate_title", lambda *a, **k: "")
    tool_first_turn = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "function": {"name": "retrieve", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
        {"role": "assistant", "content": "a1"},
    ]
    route.persist_turn(_entry("tooly1", tool_first_turn))

    stored = history.load("tooly1")
    assert stored is not None, "a tool-calling first turn was wrongly skipped"
    assert stored.messages[0]["content"] == "q1"


def test_concurrent_saves_are_serialized_by_the_write_lock():
    """The per-id write lock makes save/rename/delete mutually exclusive.

    persist_turn's turn-end write rides a BackgroundTask thread while a rail
    rename rides a request thread; both call history.save for the SAME id.
    This is the mechanism those fixes rely on, tested directly at the store
    layer (no LLM titling, no app code): two threads hammer save() and
    rename() on one id, and every completed write must be a WHOLE record —
    never a torn mix of one writer's title and the other's messages.
    """
    import threading

    cid = "race1"
    history.save(history.Transcript(
        id=cid, title="seed", corpus="budget", created_at="c", updated_at="u",
        messages=[{"role": "user", "content": "q1"}],
    ))

    def writer(tag):
        for i in range(30):
            history.save(history.Transcript(
                id=cid, title=f"{tag}-{i}", corpus="budget", created_at="c",
                updated_at="u", messages=[{"role": "user", "content": f"{tag}-{i}"}],
            ))

    def renamer():
        for i in range(30):
            history.rename(cid, f"manual-{i}")

    threads = [threading.Thread(target=writer, args=("a",)),
               threading.Thread(target=writer, args=("b",)),
               threading.Thread(target=renamer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Whatever landed last, the record on disk is coherent: its title and its
    # single user message came from the SAME write, and rename always set the
    # manual flag alongside its own title. A torn record (title from one
    # writer, body from another, or a manual title without the flag) means the
    # writes interleaved.
    stored = history.load(cid)
    assert stored is not None
    body = stored.messages[0]["content"]
    if stored.title_is_manual:
        assert stored.title.startswith("manual-")
    else:
        # A plain save: title and body share the writer's tag and index.
        assert stored.title == body


def test_rename_holds_the_write_lock_across_its_read_modify_write():
    """rename() must own the id's write lock for its WHOLE load→mutate→save.

    This is the property the mid-turn rename fix rests on: while rename is
    mid-flight, a concurrent save (a turn-end persist) must block. Probed
    directly: grab the id's lock, then confirm a rename on another thread
    cannot complete until it is released. With no lock (or a lock taken only
    around the inner save) the rename would finish while we hold the id.
    """
    import threading
    import time

    cid = "lockprobe1"
    history.save(history.Transcript(
        id=cid, title="before", corpus="budget", created_at="c", updated_at="u",
        messages=[{"role": "user", "content": "q1"}],
    ))

    lock = history._write_lock(cid)
    done = threading.Event()

    def run_rename():
        history.rename(cid, "after")
        done.set()

    with lock:
        t = threading.Thread(target=run_rename)
        t.start()
        # The rename must NOT finish while we hold the id's lock.
        assert not done.wait(timeout=0.5), \
            "rename completed while the id's write lock was held"
    # Once released, the rename proceeds.
    assert done.wait(timeout=5), "rename did not complete after the lock was released"
    t.join()
    assert history.load(cid).title == "after"
