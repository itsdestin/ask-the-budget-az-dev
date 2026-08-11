"""Resume a stored chat by seeding HarnessSession history (Plan: H2).

`POST /api/conversations` accepts an optional `resume_from` id, loads the
stored transcript, and seeds the session with its messages. The session
seam is faked so no test here reaches the retrieval stack or reads real
settings.json.
"""
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
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))

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
