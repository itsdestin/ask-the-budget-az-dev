"""A live conversation outlives its bookkeeping, and resume is atomic.

Two defects found by review on 2026-08-11:

  - `create_conversation` raised 404 on a missing transcript BEFORE it looked
    in the registry, so deleting a chat's row from the rail killed the live
    conversation the analyst still had open on screen.
  - `ConversationRegistry.get_or_add` was written to make the resume path
    atomic and was never called; the route still did `get` then `add`, so two
    tabs resuming the same chat each built a session and the second replaced
    the first without closing it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history


class FakeSession:
    def __init__(self, *, history=None, **kw):
        self.history = list(history or [])
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def built():
    """Every session this app builds, in construction order."""
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, built):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))

    def factory(conversation_id, *, corpus, tier, user, history=None):
        session = FakeSession(history=history)
        built.append(session)
        return session

    return TestClient(create_app(
        provider=StubSearchProvider(), static_dir=None,
        session_factory=factory, ingest_worker=None,
    ))


def _store(conversation_id="chat1", messages=None):
    now = history.now_iso()
    history.save(history.Transcript(
        id=conversation_id, title="t", corpus="budget",
        created_at=now, updated_at=now,
        messages=messages or [{"role": "user", "content": "q1"},
                              {"role": "assistant", "content": "a1"}],
    ))


def _resume(client, conversation_id="chat1"):
    return client.post("/api/conversations",
                       json={"corpus": "budget", "resume_from": conversation_id})


def test_deleting_the_row_does_not_kill_the_open_conversation(client):
    """Reproduced before the fix as a permanent 404 on every later message."""
    _store()
    assert _resume(client).status_code == 200

    assert client.delete("/api/history/chat1").status_code == 200

    again = _resume(client)
    assert again.status_code == 200, again.text
    assert again.json()["conversation_id"] == "chat1"
    assert again.json()["resumed"] is True


def test_an_id_with_neither_a_session_nor_a_transcript_is_still_a_404(client):
    assert _resume(client, "never-existed").status_code == 404


def test_a_traversal_id_is_still_a_400(client):
    assert _resume(client, "../escape").status_code == 400


def test_resuming_twice_reuses_the_one_session(client, built):
    _store()
    first = _resume(client)
    second = _resume(client)
    assert first.json()["conversation_id"] == second.json()["conversation_id"]
    assert len(built) == 1, "the second resume built a second session"
    assert built[0].closed is False


def test_a_second_resume_that_misses_the_lookup_still_gets_one_session(
    client, built, monkeypatch
):
    """The race `get_or_add` exists for, made deterministic.

    Two tabs resuming at once can BOTH see `registry.get(...) -> None`, because
    the lookup and the insert used to be two separate trips. Racing real
    threads through TestClient does not reliably hit that window — an earlier
    version of this test did exactly that and PASSED against the unfixed code,
    which is worse than no test. So the window is forced open instead: `get`
    always misses, and the property under test is that the insert still
    refuses to build (or strand) a second session.
    """
    _store()
    first = _resume(client)
    assert first.status_code == 200
    assert len(built) == 1

    from app.routes.conversations import ConversationRegistry
    monkeypatch.setattr(ConversationRegistry, "get", lambda self, cid: None)

    second = _resume(client)
    assert second.status_code == 200
    assert second.json()["conversation_id"] == "chat1"
    # An abandoned session is the leak: built, never registered, never closed.
    assert len(built) == 1, f"{len(built)} sessions built for one conversation"
    assert built[0].closed is False


def test_the_stored_transcript_wins_when_memory_is_behind(client, built):
    _store()
    _resume(client)
    assert len(built[0].history) == 2

    # Disk moves ahead of the live session (should not happen with one
    # process; the guard exists so it cannot answer from a shorter history).
    _store(messages=[{"role": "user", "content": "q1"},
                     {"role": "assistant", "content": "a1"},
                     {"role": "user", "content": "q2"},
                     {"role": "assistant", "content": "a2"}])
    _resume(client)
    assert len(built[0].history) == 4
    assert len(built) == 1, "the reseed replaced the session instead of updating it"
