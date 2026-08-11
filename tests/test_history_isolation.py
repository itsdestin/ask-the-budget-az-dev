"""The suite must never write into the analyst's own chat history.

Found 2026-08-11 by LAUNCHING THE APP and reading the history rail, after a
full review had already passed over this code: the real directory held 157
transcripts, 151 of them test fixtures ("biggest agencies" x60, "fy2026
appropriations" x51). Every `pytest` run added eight more.

Nothing in the offline review could have caught it. The write is a side
effect of a `BackgroundTask` that `TestClient` runs on the way out of a
`with` block, so it happens in tests that never mention history — and the
assertion that would have failed lives on a directory no test looks at.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness import history


class FakeSession:
    """Enough of a session to complete one turn — which is the trigger.

    `persist_turn` runs from `_release_turn`, and `_release_turn` only fires
    on a MESSAGE, not on conversation creation. An earlier version of this
    test only POSTed to /api/conversations, so it passed with the protection
    removed and would have shipped as a test proving nothing.
    """

    def __init__(self, *, history=None, **kw):
        self.history = list(history or [{"role": "user", "content": "q"},
                                        {"role": "assistant", "content": "a"}])

    def stream_turn(self, text, *, tier=None):
        yield {"type": "turn_complete", "stopReason": "end_turn"}
        yield {"type": "_done", "finalAnswer": "a", "stopReason": "end_turn"}


def _real_conversations_dir() -> Path:
    """Where history WOULD live with no env override — computed the way
    `conversations_dir()` computes it, but without creating anything."""
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "JLBC-Insight" / "conversations"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "JLBC-Insight" / "conversations"


def test_the_autouse_fixture_redirects_history_away_from_the_real_directory():
    """The conftest fixture is the whole protection, so pin that it applies."""
    override = os.environ.get(history.HISTORY_DIR_ENV)
    assert override, "conftest's _isolate_chat_history did not run"
    assert Path(override).resolve() != _real_conversations_dir().resolve()
    assert history.conversations_dir().resolve() == Path(override).resolve()


def test_driving_a_conversation_to_completion_writes_nowhere_near_home(tmp_path, monkeypatch):
    """The actual failure shape: a route test that says nothing about history
    still persists a transcript, because `_release_turn` rides a BackgroundTask.

    Asserted against the REAL directory's file count rather than against the
    tmp one, because the bug was never "the write happened" — it was "the
    write happened THERE".
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    real = _real_conversations_dir()
    before = len(list(real.glob("*.json"))) if real.is_dir() else 0

    def factory(conversation_id, *, corpus, tier, user, history=None):
        return FakeSession(history=history)

    with TestClient(create_app(
        provider=StubSearchProvider(), static_dir=None,
        session_factory=factory, ingest_worker=None,
    )) as client:
        created = client.post("/api/conversations", json={"corpus": "budget"})
        assert created.status_code == 200
        cid = created.json()["conversation_id"]
        # The turn is what triggers the teardown that persists.
        answered = client.post(f"/api/conversations/{cid}/messages",
                               json={"text": "how much for ADC?"})
        assert answered.status_code == 200
        answered.read()

    after = len(list(real.glob("*.json"))) if real.is_dir() else 0
    assert after == before, (
        f"the suite wrote {after - before} transcript(s) into {real} — that is "
        "an analyst's own chat list on the deployment target"
    )
