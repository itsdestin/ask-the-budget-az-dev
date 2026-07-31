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


class LiveTurn:
    """One SSE request driven through the real ASGI stack, on its own thread.

    Starlette's TestClient CANNOT do this: its transport collects the whole
    response into a BytesIO before handing it back, so by the time a test sees
    a "streamed" response the turn is long over. Anything about a turn WHILE
    it is in flight — the 409 guard, eviction safety, and above all whether a
    browser hanging up actually closes the model stream — has to be driven at
    this level or it is not being tested at all.

    `spec_version: 2.3` is not decoration: Starlette picks its disconnect
    handling from it, and 2.3 is what uvicorn reports, so this exercises the
    same branch production does.
    """

    def __init__(self, app, path: str, payload: dict, probe=None):
        self.app = app
        self.path = path
        self.body = json.dumps(payload).encode()
        self.probe = probe
        self.probe_result = None
        self.status: int | None = None
        self.chunks: list[bytes] = []
        self._first_chunk = threading.Event()
        self._hang_up = threading.Event()
        self._finished = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        import anyio

        try:
            anyio.run(self._main)
        finally:
            self._finished.set()

    async def _main(self):
        import anyio

        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": self.body,
                        "more_body": False}
            while not self._hang_up.is_set():
                await anyio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                self.status = message["status"]
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    self.chunks.append(chunk)
                    self._first_chunk.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(self.body)).encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        await self.app(scope, receive, send)
        # The response's body iterator is finalized by the event loop AFTER
        # the request ends. Staying alive here is what makes the probe below
        # measure the live-server behavior rather than loop teardown.
        await anyio.sleep(0.5)
        if self.probe is not None:
            self.probe_result = self.probe()

    def wait_started(self, timeout: float = 5) -> None:
        assert self._first_chunk.wait(timeout), "no SSE frame arrived"

    def hang_up(self, timeout: float = 10) -> None:
        self._hang_up.set()
        assert self._finished.wait(timeout), "the request never finished"


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
    turn = LiveTurn(app, f"/api/conversations/{cid}/messages", {"text": "first"})
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
    # The busy flag is cleared by the stream's `finally`, so a second question
    # in the same thread must not 409.
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
    turn = LiveTurn(
        app, f"/api/conversations/{cid}/messages", {"text": "hi"},
        probe=session.generator_exited.is_set,
    )
    turn.wait_started()
    turn.hang_up()
    assert turn.probe_result is True
    # …and the conversation is usable again afterwards, not stuck busy.
    assert client_for(app).post(
        f"/api/conversations/{cid}/messages", json={"text": "again"}
    ).status_code == 200


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
# Registry lifecycle
# ---------------------------------------------------------------------------


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
    turn = LiveTurn(app, f"/api/conversations/{cid}/messages", {"text": "hi"})
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
