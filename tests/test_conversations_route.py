"""Conversation SSE + /api/ai/status (Plan 4 Task 8).

Nothing here reaches OpenRouter, LanceDB or an ONNX model. Two seams do
the work: `create_app(session_factory=…)` swaps in a fake tool loop, and
`JLBC_DATA_DIR` points settings/ledger at a tmp share. The over-limit
test deliberately uses a REAL `HarnessSession` — S19's spend check runs
before any HTTP, so the real refusal path is exercisable offline, and
that is the only way to prove the analyst sees the ledger's exact
wording rather than a re-typed copy of it.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.constants import DEFAULT_TIER
from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    reset_settings_cache,
    save_settings,
)
from tests.live_request import LiveRequest

USER = "analyst1"


@pytest.fixture(autouse=True)
def isolated_share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    # No auth exists (spec S11) — the route reports the OS user of the
    # process. Pinning it keeps these tests from depending on whoever is
    # logged in on the machine running them.
    monkeypatch.setenv("JLBC_USER", USER)
    reset_settings_cache()
    yield
    reset_settings_cache()


def configure_ai(**overrides) -> None:
    """Write a settings.json that makes AI Mode available."""
    settings = Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        tiers={
            "standard": TierConfig(model="vendor/standard"),
            "deep_research": TierConfig(model="vendor/deep"),
        },
        admin_username="dana",
        **overrides,
    )
    save_settings(settings)
    reset_settings_cache()


class FakeSession:
    """Stands in for HarnessSession. Records what it was asked to do and
    whether its stream was closed from underneath it."""

    def __init__(self, frames=None, hold: threading.Event | None = None):
        self.frames = frames if frames is not None else _DEFAULT_FRAMES
        self.hold = hold
        self.turns: list[tuple[str, str | None]] = []
        self.closed = False
        self.generator_exited = threading.Event()

    def stream_turn(self, text, *, tier=None):
        self.turns.append((text, tier))
        try:
            for frame in self.frames:
                yield frame
                if self.hold is not None:
                    # Park between frames so a test can observe a turn that is
                    # genuinely mid-flight. The timeout is short because a
                    # cancelled `to_thread` call waits for the worker to
                    # return — a long park would just make the suite slow.
                    self.hold.wait(timeout=0.2)
        except GeneratorExit:
            self.generator_exited.set()
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
        "citations": [{"chunkId": "c1"}],
        "retrievedChunkIds": ["c1"],
        "usage": {"inputTokens": 10, "outputTokens": 4, "cost": 0.002},
    },
]


def build_app(**kwargs):
    return create_app(provider=StubSearchProvider(), static_dir=None, **kwargs)


def client_for(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def client(**kwargs) -> TestClient:
    return client_for(build_app(**kwargs))


def factory_for(session) -> callable:
    """A session_factory that always hands back `session`."""

    def make(conversation_id, *, corpus, tier, user):
        session.built_with = {"id": conversation_id, "corpus": corpus,
                              "tier": tier, "user": user}
        return session

    return make


def frames_of(response) -> list[dict]:
    """Parse an SSE body into frames, asserting the wire format on the way."""
    text = response.text
    assert text.endswith("\n\n")
    out = []
    for block in text.split("\n\n"):
        if not block:
            continue
        assert block.startswith("data: "), block
        out.append(json.loads(block[len("data: "):]))
    return out


def new_conversation(c: TestClient, corpus: str = "budget") -> str:
    r = c.post("/api/conversations", json={"corpus": corpus})
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


# ---------------------------------------------------------------------------
# POST /api/conversations
# ---------------------------------------------------------------------------


def test_create_returns_id_health_and_default_tier():
    r = client(session_factory=factory_for(FakeSession())).post(
        "/api/conversations", json={"corpus": "budget"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"]
    # No settings.json on this tmp share -> honest, pinned reason string.
    assert body["health"] == {"ok": False, "reason": "no API key configured"}
    assert body["tier_default"] == "standard"


def test_create_health_ok_when_configured():
    configure_ai()
    r = client(session_factory=factory_for(FakeSession())).post(
        "/api/conversations", json={"corpus": "fiscal_notes"}
    )
    assert r.json()["health"] == {"ok": True}


def test_create_rejects_unknown_corpus():
    r = client(session_factory=factory_for(FakeSession())).post(
        "/api/conversations", json={"corpus": "payroll"}
    )
    assert r.status_code == 422


def test_create_passes_corpus_and_user_to_the_session():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    new_conversation(c, "fiscal_notes")
    assert session.built_with["corpus"] == "fiscal_notes"
    assert session.built_with["user"] == USER
    assert session.built_with["tier"] == DEFAULT_TIER


# ---------------------------------------------------------------------------
# POST /api/conversations/{id}/messages
# ---------------------------------------------------------------------------


def test_message_streams_sse_frames_ending_in_done():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "how much for ADC?", "tier": "standard"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"].startswith("no-cache")
    assert r.headers["x-accel-buffering"] == "no"
    frames = frames_of(r)
    assert [f["type"] for f in frames] == [
        "user_message", "assistant_text_delta", "turn_complete", "_done",
    ]
    assert frames[-1]["finalAnswer"] == "The answer."
    assert frames[-1]["usage"]["cost"] == 0.002
    assert session.turns == [("how much for ADC?", "standard")]


def test_tier_is_forwarded_per_message():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    c.post(f"/api/conversations/{cid}/messages",
           json={"text": "sweep", "tier": "deep_research"})
    assert session.turns[-1] == ("sweep", "deep_research")


def test_unknown_tier_is_rejected():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "hi", "tier": "unlimited"})
    assert r.status_code == 422


def test_unknown_conversation_is_404():
    c = client(session_factory=factory_for(FakeSession()))
    r = c.post("/api/conversations/nope/messages", json={"text": "hi"})
    assert r.status_code == 404
    assert "conversation" in r.json()["detail"].lower()


def test_empty_text_is_400():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages", json={"text": "   "})
    assert r.status_code == 400
    assert session.turns == []


def test_error_frame_is_terminal_and_passed_through():
    session = FakeSession(frames=[{"type": "_error", "message": "boom"}])
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    frames = frames_of(
        c.post(f"/api/conversations/{cid}/messages", json={"text": "hi"})
    )
    assert frames == [{"type": "_error", "message": "boom"}]


def test_second_turn_while_one_is_streaming_is_409():
    # HarnessSession would refuse a re-entrant turn with an _error frame, but
    # a second POST is an HTTP-level mistake and deserves an HTTP-level answer
    # the UI can act on without parsing a stream it should not have opened.
    session = FakeSession(hold=threading.Event())
    app = build_app(session_factory=factory_for(session))
    c = client_for(app)
    cid = new_conversation(c)
    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "first"}
    )
    turn.wait_started()
    second = c.post(f"/api/conversations/{cid}/messages",
                    json={"text": "second"})
    assert second.status_code == 409
    assert "still answering" in second.json()["detail"]
    turn.hang_up()


def test_a_finished_turn_releases_the_conversation():
    session = FakeSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    assert c.post(f"/api/conversations/{cid}/messages",
                  json={"text": "one"}).status_code == 200
    # Release happens twice per turn — the generator's `finally` when the body
    # is exhausted, then the background task once the response is over — and
    # both are scoped to their own turn's token (see the registry tests
    # below), so a second question is accepted and cannot be un-busied by the
    # first turn's late cleanup.
    assert c.post(f"/api/conversations/{cid}/messages",
                  json={"text": "two"}).status_code == 200


def test_client_disconnect_closes_the_model_stream():
    """The disconnect path is what keeps an abandoned tab from wedging a
    conversation.

    HarnessSession repairs its dangling tool calls in `except GeneratorExit`,
    and that handler only runs if the route's generator is actually closed
    when the browser goes away. `probe` is checked while the event loop is
    still running, so this proves the close happens on a live server rather
    than at loop teardown.
    """
    session = FakeSession(hold=threading.Event())
    app = build_app(session_factory=factory_for(session))
    cid = new_conversation(client_for(app))
    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "hi"},
        probe=session.generator_exited.is_set,
    )
    turn.wait_started()
    turn.hang_up()
    assert turn.probe_result is True
    # …and the conversation is usable again afterwards, not stuck busy.
    assert client_for(app).post(
        f"/api/conversations/{cid}/messages", json={"text": "again"}
    ).status_code == 200


class FailsToStartOnceSession:
    """A session whose `stream_turn` raises SYNCHRONOUSLY the first time.

    `HarnessSession.stream_turn` is a generator function, so today it cannot
    do this — calling it runs no code. Nothing in the `session_factory` seam
    enforces that, though, and the route must not depend on it: the raise
    lands after ASGI response-start, so Starlette re-raises before it would
    reach the background task, and if the generator's own `finally` is not on
    the stack either, the conversation is wedged `busy` for the life of the
    process — permanently 409ing AND permanently occupying one of the 40 slots
    (a busy conversation is never evicted).
    """

    def __init__(self):
        self.calls = 0
        self.closed = False

    def stream_turn(self, text, *, tier=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("stream_turn blew up before yielding anything")
        return self._frames()

    def _frames(self):
        yield {"type": "_done", "stopReason": "end_turn", "finalAnswer": "ok",
               "citations": [], "retrievedChunkIds": [], "usage": {"cost": None}}

    def close(self):
        self.closed = True


def test_a_stream_that_never_starts_still_releases_the_conversation():
    session = FailsToStartOnceSession()
    app = build_app(session_factory=factory_for(session))
    c = client_for(app)
    cid = new_conversation(c)
    c.post(f"/api/conversations/{cid}/messages", json={"text": "one"})
    # The failure must not leave the conversation claimed: the next question
    # gets through (a 409 here would mean it is wedged forever).
    second = c.post(f"/api/conversations/{cid}/messages", json={"text": "two"})
    assert second.status_code == 200, second.text
    assert app.state.conversations.get(cid).busy is False


def test_over_limit_user_gets_the_ledgers_exact_error_frame():
    # A $0 limit blocks before any provider call, so the REAL HarnessSession
    # runs here with no key, no network and no fake in sight.
    configure_ai(default_monthly_limit_usd=0.0)
    c = client()
    cid = new_conversation(c)
    frames = frames_of(
        c.post(f"/api/conversations/{cid}/messages", json={"text": "hi"})
    )
    assert frames == [
        {
            "type": "_error",
            "message": (
                "You've reached your monthly AI usage limit ($0.00) "
                "— ask dana to raise it."
            ),
        }
    ]


# ---------------------------------------------------------------------------
# POST /api/conversations/{id}/stop
# ---------------------------------------------------------------------------


class InterruptibleSession(FakeSession):
    """A fake that records interrupt() the way HarnessSession would receive
    it — from a different thread than the one running the turn."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.interrupted = threading.Event()

    def interrupt(self):
        self.interrupted.set()
        if self.hold is not None:
            # The real session's retry backoff waits on the interrupt flag;
            # releasing the park here mirrors "the turn ends promptly".
            self.hold.set()


def test_stop_interrupts_a_running_turn():
    session = InterruptibleSession(hold=threading.Event())
    app = build_app(session_factory=factory_for(session))
    c = client_for(app)
    cid = new_conversation(c)
    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "hi"}
    )
    turn.wait_started()
    r = c.post(f"/api/conversations/{cid}/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": True}
    assert session.interrupted.is_set()
    turn.hang_up()


def test_stop_on_an_idle_conversation_is_harmless():
    # HarnessSession clears the flag at the start of every turn, so stopping
    # an idle conversation cannot poison the next question.
    session = InterruptibleSession()
    c = client(session_factory=factory_for(session))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": False}
    assert session.interrupted.is_set()
    assert c.post(f"/api/conversations/{cid}/messages",
                  json={"text": "hi"}).status_code == 200


class RacingSession:
    """Models the ONE thing about HarnessSession that makes stop racy: the
    interrupt flag is cleared inside `stream_turn`, on the first advance —
    which happens after the HTTP round trip that accepted the turn, an ASGI
    response-start, and a threadpool dispatch. `gate` freezes the turn in
    exactly that window so a test can land a stop inside it deterministically
    instead of hoping the scheduler cooperates."""

    def __init__(self):
        self.gate = threading.Event()
        self._interrupted = threading.Event()
        self.saw_interrupt = threading.Event()
        self.closed = False

    def interrupt(self):
        self._interrupted.set()

    def close(self):
        self.closed = True

    def stream_turn(self, text, *, tier=None):
        self.gate.wait(timeout=5)
        # harness/session.py:416 — verbatim in effect.
        self._interrupted.clear()
        yield {"type": "user_message", "text": text}
        for _ in range(20):
            # harness/session.py checks the flag at the top of every step,
            # i.e. after the first frame has already gone out.
            if self._interrupted.is_set():
                self.saw_interrupt.set()
                yield {"type": "user_interrupt", "kind": "plain"}
                break
            yield {"type": "assistant_text_delta", "uuid": "u1", "text": "…"}
            time.sleep(0.02)
        yield {"type": "_done", "stopReason": "user_interrupt",
               "finalAnswer": "", "citations": [], "retrievedChunkIds": [],
               "usage": {"cost": None}}


def test_a_stop_that_races_the_start_of_the_turn_is_not_lost():
    """A stop landing between "turn accepted" and "turn actually started" used
    to be wiped by the session's own `_interrupted.clear()`, and the turn ran
    on as though nobody had pressed anything — no error, no frame, no log. The
    existing stop tests both interrupt an ALREADY-RUNNING turn, so neither
    covers this window."""
    session = RacingSession()
    app = build_app(session_factory=factory_for(session))
    c = client_for(app)
    cid = new_conversation(c)
    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "hi"}
    )
    # Wait for the route to have CLAIMED the turn; the session is still parked
    # at the gate, so its clear() has provably not run yet.
    registry = app.state.conversations
    deadline = time.monotonic() + 5
    while not registry.get(cid).busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert registry.get(cid).busy, "the turn was never accepted"

    assert c.post(f"/api/conversations/{cid}/stop").json() == {"stopped": True}
    session.gate.set()  # the turn starts now — and clears the flag
    # wait_finished, NOT hang_up: a disconnect would truncate the stream after
    # the first frame and the turn would never reach the step where it notices
    # the interrupt, which is the whole thing under test.
    turn.wait_finished()
    assert session.saw_interrupt.is_set(), "the stop was swallowed by the turn"


def test_stop_on_an_unknown_conversation_is_404():
    c = client(session_factory=factory_for(FakeSession()))
    assert c.post("/api/conversations/nope/stop").status_code == 404


# ---------------------------------------------------------------------------
# Registry lifecycle
# ---------------------------------------------------------------------------


def _registry_with_one_conversation():
    from app.routes.conversations import ConversationRegistry, _Conversation

    registry = ConversationRegistry()
    entry = _Conversation(id="c1", session=FakeSession(), corpus="budget")
    registry.add(entry)
    return registry, entry


def test_a_late_release_cannot_un_busy_the_next_turn():
    """Each turn releases TWICE — the generator's `finally` when the body is
    exhausted, then the background task when the response is over — and a
    client that has already received `_done` may legitimately POST its next
    question in between. Without a per-turn token the first turn's second
    release clears the SECOND turn's busy flag, which lets that live turn be
    evicted (and `HarnessSession.close()`d mid-answer) and lets a third POST
    reach a session that is already streaming.
    """
    registry, entry = _registry_with_one_conversation()
    _, first = registry.begin_turn("c1")
    registry.end_turn(entry, first)          # body exhausted; client has _done
    _, second = registry.begin_turn("c1")    # next question accepted
    registry.end_turn(entry, first)          # turn 1's background task, late
    assert entry.busy is True, "turn 2 was un-busied by turn 1's cleanup"
    registry.end_turn(entry, second)
    assert entry.busy is False


def test_releasing_a_turn_twice_is_still_idempotent():
    # The double release within ONE turn must keep working — that is the
    # normal path, not an error case.
    registry, entry = _registry_with_one_conversation()
    _, token = registry.begin_turn("c1")
    registry.end_turn(entry, token)
    registry.end_turn(entry, token)
    assert entry.busy is False
    assert registry.begin_turn("c1")[1] != token


def test_registry_evicts_the_oldest_idle_conversation_and_closes_it(monkeypatch):
    monkeypatch.setattr("app.routes.conversations.MAX_CONVERSATIONS", 2)
    sessions = [FakeSession() for _ in range(3)]
    index = {"n": 0}

    def make(conversation_id, *, corpus, tier, user):
        session = sessions[index["n"]]
        index["n"] += 1
        return session

    c = client(session_factory=make)
    first = new_conversation(c)
    new_conversation(c)
    new_conversation(c)
    # The oldest is gone, and its httpx pool was released rather than leaked.
    assert sessions[0].closed is True
    assert c.post(f"/api/conversations/{first}/messages",
                  json={"text": "hi"}).status_code == 404


def test_a_streaming_conversation_is_never_evicted(monkeypatch):
    # HarnessSession.close() does not take the turn lock, so evicting a live
    # conversation would kill the analyst's answer mid-sentence. Going over
    # the cap is the lesser harm.
    monkeypatch.setattr("app.routes.conversations.MAX_CONVERSATIONS", 1)
    busy = FakeSession(hold=threading.Event())
    sessions = [busy, FakeSession()]
    index = {"n": 0}

    def make(conversation_id, *, corpus, tier, user):
        session = sessions[index["n"]]
        index["n"] += 1
        return session

    app = build_app(session_factory=make)
    c = client_for(app)
    cid = new_conversation(c)
    turn = LiveRequest(
        app, "POST", f"/api/conversations/{cid}/messages", {"text": "hi"}
    )
    turn.wait_started()
    new_conversation(c)  # would evict the only other entry
    assert busy.closed is False
    turn.hang_up()


# ---------------------------------------------------------------------------
# GET /api/ai/status
# ---------------------------------------------------------------------------

# Verbatim from spec S16. Task 12 asserts both example strings render in the
# UI explainer, so a drift here is a cross-task break, not a typo.
STANDARD_COPY = (
    "for quick lookups — e.g. 'how much did we spend on X last year?' or "
    "'did we appropriate money for xyz in FY 2020?'"
)
DEEP_COPY = (
    "for open-ended, historical, broad-scope research — e.g. 'a comprehensive "
    "accounting of appropriated vs actual expenditures for all "
    "border-enforcement programs across the past 10 fiscal years'"
)


def test_ai_status_reports_unavailable_without_a_key():
    body = client().get("/api/ai/status").json()
    assert body["available"] is False
    assert body["reason"] == "no API key configured"
    assert body["tiers"]["standard"]["available"] is False


def test_ai_status_tier_copy_is_the_spec_wording_verbatim():
    body = client().get("/api/ai/status").json()
    assert body["tiers"]["standard"]["description"] == STANDARD_COPY
    assert body["tiers"]["deep_research"]["description"] == DEEP_COPY
    # The two examples are also carried apart from the sentence so the UI can
    # render them as a list without re-typing (and re-typo-ing) them.
    assert body["tiers"]["standard"]["examples"] == [
        "how much did we spend on X last year?",
        "did we appropriate money for xyz in FY 2020?",
    ]
    assert body["tiers"]["deep_research"]["examples"] == [
        "a comprehensive accounting of appropriated vs actual expenditures "
        "for all border-enforcement programs across the past 10 fiscal years"
    ]
    assert body["tiers"]["standard"]["default"] is True
    assert body["tiers"]["deep_research"]["default"] is False
    assert body["tiers"]["standard"]["label"] == "Standard"
    assert body["tiers"]["deep_research"]["label"] == "Deep Research"


def test_tier_copy_still_matches_the_spec_file():
    """The two strings above are quoted from S16. Asserting them against the
    spec DOCUMENT (not just against a copy in this file) is what makes this a
    drift detector: if someone rewords the spec, this fails and the wording is
    re-decided deliberately instead of the app and the spec quietly diverging.
    """
    from pathlib import Path

    spec = (
        Path(__file__).resolve().parent.parent
        / "docs" / "superpowers" / "specs"
        / "2026-07-29-standalone-consolidation-design.md"
    ).read_text(encoding="utf-8")
    assert STANDARD_COPY in spec
    assert DEEP_COPY in spec


def test_ai_status_available_when_configured():
    configure_ai()
    body = client().get("/api/ai/status").json()
    assert body["available"] is True
    assert "reason" not in body or body["reason"] is None
    assert body["tiers"]["deep_research"]["available"] is True


def test_ai_status_reports_a_half_configured_tier_honestly():
    settings = Settings(
        provider=ProviderConfig(api_key="sk-test"),
        tiers={"standard": TierConfig(model="vendor/standard"),
               "deep_research": TierConfig(model="")},
    )
    save_settings(settings)
    reset_settings_cache()
    body = client().get("/api/ai/status").json()
    # One usable tier is enough for the AI Mode toggle; the dead tier says why.
    assert body["available"] is True
    assert body["tiers"]["deep_research"]["available"] is False
    assert body["tiers"]["deep_research"]["reason"] == (
        "no model configured — ask the admin"
    )


def test_ai_status_carries_the_users_usage_snapshot():
    configure_ai(default_monthly_limit_usd=10.0)
    from harness.ledger import record_usage

    record_usage(USER, "standard", "vendor/standard", 100, 50, 9.0)
    body = client().get("/api/ai/status").json()
    assert body["user_usage"] == {
        "month_usd": 9.0, "limit_usd": 10.0, "warned": True,
    }


def test_ai_status_usage_is_null_when_limits_cannot_apply():
    # S15 custom endpoint: no exact costs, so no dollar figures to show.
    save_settings(
        Settings(
            provider=ProviderConfig(api_key="k", provider="custom"),
            tiers={"standard": TierConfig(model="m"),
                   "deep_research": TierConfig(model="m")},
        )
    )
    reset_settings_cache()
    body = client().get("/api/ai/status").json()
    assert body["user_usage"] == {
        "month_usd": None, "limit_usd": None, "warned": False,
    }
