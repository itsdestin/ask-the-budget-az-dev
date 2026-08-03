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
