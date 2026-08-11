"""persist_turn's read-modify-writes are transactions, not adjacent writes.

Three defects found by review on 2026-08-11, all the same shape: the store's
per-id lock made each WRITE atomic, and nothing made the load→mutate→save
around it atomic. Auto-naming stretches that window across a blocking HTTP
call of up to twenty seconds, which is what turned a theoretical race into
reproducible data loss.

Each test here was verified FAILING against the pre-fix code.
"""
from __future__ import annotations

import threading

import pytest

from app.routes import conversations as conv
from harness import history


class FakeSession:
    def __init__(self, messages):
        self.history = messages


TURN1 = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
TURN2 = TURN1 + [{"role": "user", "content": "q2"},
                 {"role": "assistant", "content": "a2"}]


def _entry(messages, conversation_id="chat1"):
    return conv._Conversation(
        id=conversation_id, session=FakeSession(messages), corpus="budget"
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(conv, "current_user", lambda: "tester")
    return tmp_path


@pytest.fixture
def slow_title(monkeypatch):
    """Stand in for `titles.generate_title`, blocking until released.

    The window is what the defects live in, so the test opens it explicitly
    rather than hoping a real call is slow enough to lose a race in.

    ONLY THE FIRST call blocks, and this matters — an earlier version blocked
    every call, so the second turn's own title call sat in the same window and
    timed out, `persist_turn` swallowed the failure, and the stale write under
    test never happened. The guard then PASSED against the unfixed code, which
    is the failure mode a regression test exists to not have. Later calls
    return at once, exactly as they would once the first chat is titled.
    """
    entered, release = threading.Event(), threading.Event()
    first = threading.Lock()
    taken: list[int] = []

    def fake(question, answer, *, user, **kw):
        with first:
            mine = not taken
            taken.append(1)
        if mine:
            entered.set()
            # Generous, because it is a deadlock detector, not a race window:
            # the test always releases it explicitly.
            assert release.wait(30), "the test never released the title call"
        return "Generated Title"

    monkeypatch.setattr(conv.titles, "generate_title", fake)
    return entered, release


def _persist_in_background(entry):
    thread = threading.Thread(target=conv.persist_turn, args=(entry,))
    thread.start()
    return thread


def test_a_turn_finishing_during_the_title_call_is_not_erased(store, slow_title):
    """The worst of the three: reproduced at 4 messages -> 2."""
    entered, release = slow_title
    thread = _persist_in_background(_entry(TURN1))
    assert entered.wait(5)

    conv.persist_turn(_entry(TURN2))                 # turn 2 lands mid-call
    assert history.load("chat1").message_count == 4

    release.set()
    thread.join(5)
    assert history.load("chat1").message_count == 4, "the title write reverted turn 2"


def test_a_chat_deleted_during_the_title_call_stays_deleted(store, slow_title):
    entered, release = slow_title
    thread = _persist_in_background(_entry(TURN1))
    assert entered.wait(5)

    assert history.delete("chat1") is True
    release.set()
    thread.join(5)
    assert history.load("chat1") is None, "the title write resurrected a deleted chat"


def test_a_rename_during_the_title_call_wins(store, slow_title):
    """And keeps `title_is_manual`, or auto-naming re-arms against a title
    the analyst chose."""
    entered, release = slow_title
    thread = _persist_in_background(_entry(TURN1))
    assert entered.wait(5)

    assert history.rename("chat1", "Analyst's own title") is True
    release.set()
    thread.join(5)

    stored = history.load("chat1")
    assert stored.title == "Analyst's own title"
    assert stored.title_is_manual is True


def test_a_rename_during_the_transcript_write_is_not_reverted(store, monkeypatch):
    """The same race one step earlier, on the load→save that has no HTTP call
    in it at all. Narrow, but it is the window the old comment claimed the
    lock already closed."""
    monkeypatch.setattr(conv.titles, "generate_title", lambda *a, **k: "T")
    conv.persist_turn(_entry(TURN1))
    assert history.rename("chat1", "Mine") is True

    conv.persist_turn(_entry(TURN2))
    stored = history.load("chat1")
    assert stored.title == "Mine"
    assert stored.title_is_manual is True
    assert stored.message_count == 4


def test_the_title_call_does_not_hold_the_chats_write_lock(store, slow_title):
    """A twenty-second network call must not freeze the rail. If the lock were
    held across it, this rename would block until the release below."""
    entered, release = slow_title
    thread = _persist_in_background(_entry(TURN1))
    assert entered.wait(5)

    renamed = threading.Event()

    def rename():
        history.rename("chat1", "Typed while naming")
        renamed.set()

    rename_thread = threading.Thread(target=rename)
    rename_thread.start()
    assert renamed.wait(5), "the rail was blocked behind the title call"

    release.set()
    thread.join(5)
    rename_thread.join(5)
    assert history.load("chat1").title == "Typed while naming"


def test_an_already_titled_chat_never_calls_the_namer_again(store, monkeypatch):
    calls: list[tuple] = []

    def fake(question, answer, *, user, **kw):
        calls.append((question, answer))
        return "Generated Title"

    monkeypatch.setattr(conv.titles, "generate_title", fake)
    conv.persist_turn(_entry(TURN1))
    conv.persist_turn(_entry(TURN2))
    assert len(calls) == 1, "auto-naming re-ran on a chat that already had a title"
