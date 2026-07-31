"""Plan 4 Task 6 — the OpenRouter tool loop (`harness/session.py`).

Every test here runs against a FAKE OpenAI-compatible transport
(`httpx.MockTransport` replaying canned SSE bytes). No network, no API
key, no corpus, no ONNX models: the tool executor, the ledger and the
system prompt are all injected. That is deliberate — this suite has to
stay runnable on a fresh clone, and a tool loop whose tests need the
real stack is a tool loop nobody re-runs after a change.

The load-bearing assertions, in the order the plan lists them:
  * `assistant_text_delta.text` is the FULL accumulated text per uuid
    (the renderer REPLACES on matching uuid; true deltas would render
    garbage with no error anywhere).
  * `tool_result.output` is a JSON-encoded STRING, not an object.
  * history never ends on an assistant `tool_calls` message with no
    matching `{"role": "tool"}` replies — the next request would 400.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

import httpx
import pytest

from harness.constants import TIER_BUDGETS
from harness.ledger import LimitStatus
from harness.session import HarnessSession
from harness.settings import ProviderConfig, Settings, TierConfig

SYSTEM_PROMPT = "SYSTEM PROMPT (Task 7 stub)."


# ---------------------------------------------------------------------------
# Canned SSE plumbing
# ---------------------------------------------------------------------------


class _CannedStream(httpx.SyncByteStream):
    """Replays pre-baked byte parts, optionally running a callback before
    each one.

    A real SSE body arrives in pieces over seconds; the `on_part` hook is
    how the interrupt test fires `session.interrupt()` genuinely
    MID-stream rather than before or after it.
    """

    def __init__(self, parts: Iterable[bytes], on_part: Callable[[int], None] | None = None):
        self._parts = list(parts)
        self._on_part = on_part

    def __iter__(self):
        for index, part in enumerate(self._parts):
            if self._on_part is not None:
                self._on_part(index)
            yield part


def sse(*chunks: dict, done: bool = True, on_part: Callable[[int], None] | None = None) -> httpx.Response:
    """One canned `chat.completions` streaming response.

    Each chunk becomes its own `data: {...}\\n\\n` part so the parser is
    exercised across part boundaries the way a real stream would.
    """
    parts = [f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks]
    if done:
        parts.append(b"data: [DONE]\n\n")
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=_CannedStream(parts, on_part),
    )


def text_chunk(text: str, model: str = "test/model") -> dict:
    return {"model": model, "choices": [{"index": 0, "delta": {"content": text}}]}


def tool_chunk(
    slot: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> dict:
    """One `delta.tool_calls` fragment. `id`/`name` normally appear only on
    the first fragment for a slot; `arguments` arrives in pieces."""
    function: dict[str, Any] = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    fragment: dict[str, Any] = {"index": slot, "function": function}
    if call_id is not None:
        fragment["id"] = call_id
        fragment["type"] = "function"
    return {"choices": [{"index": 0, "delta": {"tool_calls": [fragment]}}]}


def finish_chunk(reason: str = "stop") -> dict:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def usage_chunk(
    prompt: int = 100, completion: int = 20, cost: float | None = 0.0031, cached: int = 7
) -> dict:
    usage: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
    }
    if cost is not None:
        usage["cost"] = cost
    return {"choices": [], "usage": usage}


class Provider:
    """Scripted OpenAI-compatible endpoint.

    Hands back `responses[i]` for the i-th request; once the script is
    exhausted the LAST entry repeats, which is what lets the step-cap
    tests describe "a model that calls tools forever" in two lines.
    Each entry is either an `httpx.Response` or a zero-arg factory (a
    Response's stream can only be consumed once, so anything replayed
    must be a factory).
    """

    def __init__(self, *responses: Any):
        self._responses = list(responses)
        self.bodies: list[dict] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content.decode("utf-8")))
        self.requests.append(request)
        entry = self._responses[min(len(self.bodies) - 1, len(self._responses) - 1)]
        return entry() if callable(entry) else entry

    @property
    def call_count(self) -> int:
        return len(self.bodies)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


# ---------------------------------------------------------------------------
# Fakes for the injected collaborators
# ---------------------------------------------------------------------------


class FakeExecutor:
    """Stands in for `harness.tools.ToolExecutor` — same contract: never
    raises, always returns a JSON string."""

    def __init__(self, results: dict[str, Any] | None = None, default: Any = None):
        self.results = results or {}
        self.default = default if default is not None else {"ok": True}
        self.calls: list[tuple[str, Any]] = []

    def execute(self, name: str, args: Any) -> str:
        self.calls.append((name, args))
        return json.dumps(self.results.get(name, self.default))


class FakeLedger:
    def __init__(self, status: str = "allowed", message: str | None = None, fail: bool = False):
        self.status = LimitStatus(
            status=status, message=message, reason=None, limit_usd=None, month_usd=0.0
        )
        self.fail = fail
        self.recorded: list[dict] = []
        self.checked: list[str] = []

    def check_limit(self, user: str, settings: Settings, **_: Any) -> LimitStatus:
        self.checked.append(user)
        return self.status

    def record_usage(
        self,
        user: str,
        tier: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float | None = None,
        **_: Any,
    ) -> None:
        if self.fail:
            raise OSError("the share went away")
        self.recorded.append(
            {
                "user": user,
                "tier": tier,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
            }
        )


def make_settings(provider: str = "openrouter", api_key: str = "sk-test") -> Settings:
    return Settings(
        provider=ProviderConfig(
            base_url="https://provider.test/api/v1", api_key=api_key, provider=provider
        ),
        tiers={
            "standard": TierConfig(model="vendor/standard-model"),
            "deep_research": TierConfig(model="vendor/deep-model"),
        },
        admin_username="admin",
    )


def make_session(
    provider: Provider,
    *,
    tier: str = "standard",
    settings: Settings | None = None,
    executor: Any = None,
    ledger: FakeLedger | None = None,
    **kwargs: Any,
) -> tuple[HarnessSession, FakeLedger]:
    led = ledger or FakeLedger()
    kwargs.setdefault("sleep", lambda _seconds: None)
    session = HarnessSession(
        "conv-1",
        "budget",
        tier,
        "analyst1",
        settings or make_settings(),
        executor=executor or FakeExecutor(),
        transport=provider.transport(),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        check_limit=led.check_limit,
        record_usage=led.record_usage,
        **kwargs,
    )
    return session, led


def run(session: HarnessSession, text: str = "How much for ADC?") -> tuple[list[dict], dict]:
    """Drive one turn; return (streamed events, terminal frame)."""
    events: list[dict] = []
    terminal = session.send_turn(text, events.append)
    return events, terminal


def of_type(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e["type"] == event_type]


# ---------------------------------------------------------------------------
# Text-only turn
# ---------------------------------------------------------------------------


def test_text_only_turn_streams_full_accumulated_text_per_uuid():
    provider = Provider(
        lambda: sse(
            text_chunk("The Department "),
            text_chunk("of Corrections "),
            text_chunk("received $1.4 B."),
            finish_chunk("stop"),
            usage_chunk(),
        )
    )
    session, _ = make_session(provider)
    events, done = run(session)

    deltas = of_type(events, "assistant_text_delta")
    assert [d["text"] for d in deltas] == [
        "The Department ",
        "The Department of Corrections ",
        "The Department of Corrections received $1.4 B.",
    ]
    # THE contract: every delta is the full text so far, so each is a
    # prefix of the next. A true-delta regression breaks this and nothing
    # else in the stack would notice.
    for earlier, later in zip(deltas, deltas[1:]):
        assert later["text"].startswith(earlier["text"])
    # One assistant message == one uuid, so the reducer replaces in place.
    assert len({d["uuid"] for d in deltas}) == 1
    assert all(isinstance(d["timestamp"], int) for d in deltas)

    complete = of_type(events, "turn_complete")
    assert len(complete) == 1
    assert complete[0]["stopReason"] == "end_turn"
    assert complete[0]["usage"] == {
        "inputTokens": 100,
        "outputTokens": 20,
        "cacheReadTokens": 7,
        "cacheCreationTokens": 0,
    }
    assert done["type"] == "_done"
    assert done["stopReason"] == "end_turn"
    assert done["finalAnswer"] == "The Department of Corrections received $1.4 B."
    assert done["usage"]["cost"] == 0.0031


def test_turn_starts_with_user_message_and_a_thinking_heartbeat():
    provider = Provider(lambda: sse(text_chunk("Hi."), finish_chunk("stop")))
    session, _ = make_session(provider)
    events, _ = run(session, "hello")

    assert events[0]["type"] == "user_message"
    assert events[0]["text"] == "hello"
    # The heartbeat has to precede the first token — that gap is multiple
    # seconds in production and the UI shows nothing without it.
    thinking = of_type(events, "assistant_thinking")
    assert thinking, "no assistant_thinking heartbeat emitted"
    assert events.index(thinking[0]) < events.index(of_type(events, "assistant_text_delta")[0])


def test_request_body_carries_model_tools_stream_and_usage_accounting():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider)
    run(session)

    body = provider.bodies[0]
    assert body["model"] == "vendor/standard-model"
    assert body["stream"] is True
    assert body["usage"] == {"include": True}
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"][-1] == {"role": "user", "content": "How much for ADC?"}
    assert provider.requests[0].headers["authorization"] == "Bearer sk-test"


def test_custom_endpoint_omits_openrouter_usage_block_and_records_no_cost():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk(cost=0.5)))
    session, ledger = make_session(provider, settings=make_settings(provider="custom"))
    run(session)

    # S15: a custom endpoint is not OpenRouter — the vendor extension
    # would be rejected outright by a strict OpenAI-compatible server,
    # and its `cost` field is not trustworthy money.
    assert "usage" not in provider.bodies[0]
    assert ledger.recorded[0]["cost_usd"] is None


# ---------------------------------------------------------------------------
# Tool turn
# ---------------------------------------------------------------------------


RETRIEVE_RESULT = {
    "chunks": [
        {"chunk_id": "jlbc-fy2027-adc:12", "text": "…"},
        {"chunk_id": "jlbc-fy2027-adc:13", "text": "…"},
    ],
    "top_score": 4.2,
}


def _tool_then_text(arguments: str = '{"query": "ADC budget"}') -> Provider:
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_1", name="retrieve", arguments=arguments),
            finish_chunk("tool_calls"),
        ),
        lambda: sse(text_chunk("ADC got $1.4 B."), finish_chunk("stop")),
    )


def test_tool_turn_runs_executor_then_continues_to_a_final_answer():
    provider = _tool_then_text()
    executor = FakeExecutor({"retrieve": RETRIEVE_RESULT})
    session, _ = make_session(provider, executor=executor)
    events, done = run(session)

    use = of_type(events, "tool_use")[0]
    assert use["toolName"] == "retrieve"
    assert use["toolUseId"] == "call_1"
    assert use["input"] == {"query": "ADC budget"}  # parsed object for the UI

    result = of_type(events, "tool_result")[0]
    assert result["toolUseId"] == "call_1"
    # A STRING, not an object — the renderer parses it itself.
    assert isinstance(result["output"], str)
    assert json.loads(result["output"])["top_score"] == 4.2

    assert executor.calls == [("retrieve", '{"query": "ADC budget"}')]
    assert done["stopReason"] == "end_turn"
    assert done["finalAnswer"] == "ADC got $1.4 B."
    assert done["retrievedChunkIds"] == ["jlbc-fy2027-adc:12", "jlbc-fy2027-adc:13"]
    assert done["toolCalls"][0]["toolName"] == "retrieve"
    assert json.loads(done["toolCalls"][0]["output"])["top_score"] == 4.2


def test_tool_results_are_appended_to_history_as_tool_role_messages():
    provider = _tool_then_text()
    session, _ = make_session(provider, executor=FakeExecutor({"retrieve": RETRIEVE_RESULT}))
    run(session)

    second = provider.bodies[1]["messages"]
    assistant = [m for m in second if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["tool_calls"][0]["function"]["name"] == "retrieve"
    tool_msg = [m for m in second if m["role"] == "tool"][0]
    assert tool_msg["tool_call_id"] == "call_1"
    assert json.loads(tool_msg["content"])["top_score"] == 4.2


def test_tool_call_argument_fragments_are_assembled_per_index():
    provider = Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_a", name="retrieve", arguments='{"que'),
            tool_chunk(1, call_id="call_b", name="list_filter_values", arguments='{"fie'),
            tool_chunk(0, arguments='ry": "ADC"}'),
            tool_chunk(1, arguments='ld": "agency"}'),
            finish_chunk("tool_calls"),
        ),
        lambda: sse(text_chunk("done"), finish_chunk("stop")),
    )
    executor = FakeExecutor()
    session, _ = make_session(provider, executor=executor)
    events, _ = run(session)

    assert executor.calls == [
        ("retrieve", '{"query": "ADC"}'),
        ("list_filter_values", '{"field": "agency"}'),
    ]
    assert [u["input"] for u in of_type(events, "tool_use")] == [
        {"query": "ADC"},
        {"field": "agency"},
    ]


def test_unparseable_tool_arguments_still_reach_the_executor_verbatim():
    # The executor owns the "your JSON was truncated" error message; the
    # loop must not swallow the call or invent one.
    provider = Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_1", name="retrieve", arguments='{"query": '),
            finish_chunk("tool_calls"),
        ),
        lambda: sse(text_chunk("recovered"), finish_chunk("stop")),
    )
    executor = FakeExecutor(default={"ok": False, "error": "arguments were not valid JSON"})
    session, _ = make_session(provider, executor=executor)
    events, _ = run(session)

    assert executor.calls == [("retrieve", '{"query": ')]
    assert of_type(events, "tool_result")[0]["isError"] is True


# ---------------------------------------------------------------------------
# Tier budgets
# ---------------------------------------------------------------------------


def _forever_tool_caller() -> Provider:
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_x", name="retrieve", arguments="{}"),
            finish_chunk("tool_calls"),
        )
    )


def test_standard_tier_stops_at_its_step_cap():
    provider = _forever_tool_caller()
    session, _ = make_session(provider, tier="standard")
    events, done = run(session)

    assert provider.call_count == TIER_BUDGETS["standard"]["max_steps"] == 15
    assert done["stopReason"] == "max_steps"
    assert of_type(events, "turn_complete")[0]["stopReason"] == "max_steps"


def test_deep_research_tier_gets_the_larger_cap():
    provider = _forever_tool_caller()
    session, _ = make_session(provider, tier="deep_research")
    _, done = run(session)

    assert provider.call_count == TIER_BUDGETS["deep_research"]["max_steps"] == 50
    assert done["stopReason"] == "max_steps"


def test_step_cap_tells_the_analyst_the_answer_is_incomplete():
    # An answer that just stops is indistinguishable from a finished one.
    provider = _forever_tool_caller()
    session, _ = make_session(provider, tier="standard")
    events, done = run(session)

    note = of_type(events, "assistant_text_delta")[-1]
    assert "incomplete" in note["text"].lower()
    assert note["text"] in done["finalAnswer"]


def test_unknown_tier_falls_back_to_the_cheap_budget():
    # settings.json accepts arbitrary tier names, so an admin can create
    # one this module has never heard of. It must get the CHEAP budget.
    provider = _forever_tool_caller()
    settings = make_settings()
    settings.tiers["platinum"] = TierConfig(model="vendor/expensive-model")
    session, _ = make_session(provider, tier="platinum", settings=settings)
    _, done = run(session)

    assert provider.call_count == TIER_BUDGETS["standard"]["max_steps"]
    assert done["stopReason"] == "max_steps"


# ---------------------------------------------------------------------------
# Retry / provider errors
# ---------------------------------------------------------------------------


def error_response(status: int, body: dict | str, headers: dict | None = None) -> httpx.Response:
    payload = body if isinstance(body, str) else json.dumps(body)
    return httpx.Response(status, content=payload.encode(), headers=headers or {})


def test_429_is_retried_and_honors_retry_after():
    slept: list[float] = []
    provider = Provider(
        lambda: error_response(429, {"error": {"message": "slow down"}}, {"retry-after": "0"}),
        lambda: sse(text_chunk("recovered"), finish_chunk("stop")),
    )
    session, _ = make_session(provider, sleep=slept.append)
    _, done = run(session)

    assert provider.call_count == 2
    assert slept == [0.0]  # the header wins over the [1, 2, 4] schedule
    assert done["finalAnswer"] == "recovered"


def test_5xx_is_retried_on_the_backoff_schedule():
    slept: list[float] = []
    provider = Provider(
        lambda: error_response(503, {"error": {"message": "upstream down"}}),
        lambda: error_response(503, {"error": {"message": "upstream down"}}),
        lambda: sse(text_chunk("recovered"), finish_chunk("stop")),
    )
    session, _ = make_session(provider, sleep=slept.append)
    _, done = run(session)

    assert provider.call_count == 3
    assert slept == [1.0, 2.0]
    assert done["finalAnswer"] == "recovered"


def test_retries_give_up_after_the_schedule_is_exhausted():
    slept: list[float] = []
    provider = Provider(lambda: error_response(500, {"error": {"message": "still broken"}}))
    session, _ = make_session(provider, sleep=slept.append)
    _, terminal = run(session)

    assert slept == [1.0, 2.0, 4.0]
    assert provider.call_count == 4
    assert terminal["type"] == "_error"
    assert "still broken" in terminal["message"]


def test_400_is_not_retried():
    provider = Provider(
        lambda: error_response(400, {"error": {"message": "model not found: vendor/typo"}})
    )
    session, _ = make_session(provider)
    _, terminal = run(session)

    assert provider.call_count == 1
    assert terminal["type"] == "_error"
    assert "model not found: vendor/typo" in terminal["message"]


def test_a_failed_turn_is_closed_before_the_error_frame():
    # The renderer keeps an assistant turn open until turn_complete, and
    # an open turn adopts the NEXT turn's text. One provider hiccup would
    # otherwise fold every later answer into the failed bubble.
    provider = Provider(lambda: error_response(400, {"error": {"message": "bad model"}}))
    session, _ = make_session(provider)
    events, terminal = run(session)

    assert of_type(events, "turn_complete")[0]["stopReason"] == "error"
    assert terminal["type"] == "_error"


def test_openrouter_nested_raw_upstream_error_reaches_the_analyst():
    # OpenRouter's own `error.message` is a generic "Provider returned
    # error"; the actionable text is buried in metadata.raw.
    provider = Provider(
        lambda: error_response(
            400,
            {
                "error": {
                    "message": "Provider returned error",
                    "code": 400,
                    "metadata": {
                        "provider_name": "Anthropic",
                        "raw": json.dumps(
                            {
                                "type": "error",
                                "error": {
                                    "type": "invalid_request_error",
                                    "message": "max_tokens: 200000 > 64000, which is the maximum",
                                },
                            }
                        ),
                    },
                }
            },
        )
    )
    session, _ = make_session(provider)
    _, terminal = run(session)

    assert terminal["type"] == "_error"
    assert "max_tokens: 200000 > 64000" in terminal["message"]


def test_transport_failure_is_retried_then_surfaced():
    slept: list[float] = []

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = Provider()
    transport = httpx.MockTransport(boom)
    ledger = FakeLedger()
    session = HarnessSession(
        "conv-net",
        "budget",
        "standard",
        "analyst1",
        make_settings(),
        executor=FakeExecutor(),
        transport=transport,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        sleep=slept.append,
        check_limit=ledger.check_limit,
        record_usage=ledger.record_usage,
    )
    _, terminal = run(session)

    assert slept == [1.0, 2.0, 4.0]
    assert terminal["type"] == "_error"
    assert "connection refused" in terminal["message"]
    assert provider.call_count == 0


def test_a_connection_dropped_mid_answer_is_reported_not_raised():
    def cut_the_line(_index: int) -> None:
        if _index == 1:
            raise httpx.ReadError("connection reset")

    provider = Provider(
        lambda: sse(text_chunk("Partial…"), finish_chunk("stop"), on_part=cut_the_line)
    )
    session, _ = make_session(provider)
    events, terminal = run(session)

    # Not an exception escaping into Task 8's SSE route.
    assert terminal["type"] == "_error"
    assert "dropped mid-answer" in terminal["message"]
    assert of_type(events, "assistant_text_delta")[0]["text"] == "Partial…"


def test_error_frame_mid_stream_is_surfaced_not_swallowed():
    provider = Provider(
        lambda: sse(
            text_chunk("Partial…"),
            {"error": {"message": "upstream cut the connection"}},
            done=False,
        )
    )
    session, _ = make_session(provider)
    _, terminal = run(session)

    assert terminal["type"] == "_error"
    assert "upstream cut the connection" in terminal["message"]


# ---------------------------------------------------------------------------
# Abort
# ---------------------------------------------------------------------------


def assert_no_dangling_tool_calls(messages: list[dict]) -> None:
    """Every assistant `tool_calls` id has a matching `{"role": "tool"}`
    reply somewhere after it. A single dangling id makes the NEXT
    request malformed and the provider 400s the whole conversation."""
    replied = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    for message in messages:
        for call in message.get("tool_calls") or []:
            assert call["id"] in replied, f"dangling tool_call {call['id']}"


def test_interrupt_mid_stream_ends_the_turn_and_backfills_cancelled_tools():
    session_box: dict[str, HarnessSession] = {}

    def interrupt_before_finish(part_index: int) -> None:
        # Part 0 carries the complete tool_call; interrupting before part
        # 1 (finish_reason) is a genuine mid-stream abort.
        if part_index == 1:
            session_box["s"].interrupt()

    provider = Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_1", name="retrieve", arguments='{"query": "ADC"}'),
            finish_chunk("tool_calls"),
            on_part=interrupt_before_finish,
        )
    )
    executor = FakeExecutor()
    session, _ = make_session(provider, executor=executor)
    session_box["s"] = session
    events, done = run(session)

    assert done["stopReason"] == "user_interrupt"
    assert of_type(events, "user_interrupt")[0]["kind"] == "tool-use"
    assert of_type(events, "turn_complete")[0]["stopReason"] == "user_interrupt"
    # The cancelled call never ran…
    assert executor.calls == []
    # …but history is still a legal next request.
    assert_no_dangling_tool_calls(session.history)
    assert session.history[-1]["role"] == "tool"
    cancelled = json.loads(session.history[-1]["content"])
    assert cancelled["cancelled"] is True


def test_interrupt_between_tool_calls_cancels_only_the_unrun_ones():
    session_box: dict[str, HarnessSession] = {}

    class InterruptingExecutor(FakeExecutor):
        def execute(self, name: str, args: Any) -> str:
            out = super().execute(name, args)
            session_box["s"].interrupt()
            return out

    provider = Provider(
        lambda: sse(
            tool_chunk(0, call_id="call_1", name="retrieve", arguments="{}"),
            tool_chunk(1, call_id="call_2", name="retrieve", arguments="{}"),
            finish_chunk("tool_calls"),
        )
    )
    executor = InterruptingExecutor({"retrieve": RETRIEVE_RESULT})
    session, _ = make_session(provider, executor=executor)
    session_box["s"] = session
    events, done = run(session)

    assert len(executor.calls) == 1  # the second was cancelled
    assert done["stopReason"] == "user_interrupt"
    assert_no_dangling_tool_calls(session.history)
    # The analyst sees the cancelled call resolve rather than spin forever.
    results = of_type(events, "tool_result")
    assert [r["toolUseId"] for r in results] == ["call_1", "call_2"]
    assert results[1]["isError"] is True


def test_interrupt_on_a_text_only_turn_is_a_plain_interrupt():
    session_box: dict[str, HarnessSession] = {}

    provider = Provider(
        lambda: sse(
            text_chunk("The Department "),
            text_chunk("of Corrections…"),
            finish_chunk("stop"),
            on_part=lambda i: session_box["s"].interrupt() if i == 1 else None,
        )
    )
    session, _ = make_session(provider)
    session_box["s"] = session
    events, done = run(session)

    assert of_type(events, "user_interrupt")[0]["kind"] == "plain"
    assert done["stopReason"] == "user_interrupt"
    # Partial text is kept — it is what the analyst already read.
    assert session.history[-1] == {"role": "assistant", "content": "The Department "}


def test_a_new_turn_clears_a_previous_interrupt():
    session_box: dict[str, HarnessSession] = {}
    provider = Provider(
        lambda: sse(
            text_chunk("cut short"),
            finish_chunk("stop"),
            on_part=lambda i: session_box["s"].interrupt() if i == 1 else None,
        ),
        lambda: sse(text_chunk("second turn ran fine"), finish_chunk("stop")),
    )
    session, _ = make_session(provider)
    session_box["s"] = session
    run(session, "first")
    _, done = run(session, "second")

    assert done["stopReason"] == "end_turn"
    assert done["finalAnswer"] == "second turn ran fine"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def _bulky_history() -> list[dict]:
    """Four turns' worth of history, each tool result deliberately fat."""
    history: list[dict] = []
    for n in range(4):
        history.append({"role": "user", "content": f"question {n}"})
        history.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"old_{n}",
                        "type": "function",
                        "function": {"name": "retrieve", "arguments": "{}"},
                    }
                ],
            }
        )
        history.append(
            {"role": "tool", "tool_call_id": f"old_{n}", "name": "retrieve", "content": "x" * 4000}
        )
        history.append({"role": "assistant", "content": f"answer {n}"})
    return history


def test_history_over_budget_drops_oldest_first_and_keeps_the_system_prompt():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider, context_chars=6000)
    session.history.extend(_bulky_history())
    run(session, "the newest question")

    sent = provider.bodies[0]["messages"]
    assert sent[0]["role"] == "system"  # never a drop candidate
    assert sent[-1] == {"role": "user", "content": "the newest question"}
    assert "question 0" not in json.dumps(sent)
    assert "answer 3" in json.dumps(sent)


# Swept rather than pinned to one number: the interesting budgets are the
# ones that land the cut BETWEEN an assistant tool_calls message and its
# tool reply, and exactly where that is depends on message sizes nobody
# should have to recompute when this fixture changes. The invariant has
# to hold at every budget, so assert it at every budget.
@pytest.mark.parametrize(
    "budget", [200, 1000, 2000, 4000, 4100, 4200, 4300, 5000, 8000, 12_000]
)
def test_truncation_never_starts_the_window_on_an_orphaned_tool_message(budget):
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider, context_chars=budget)
    session.history.extend(_bulky_history())
    run(session, "newest")

    sent = provider.bodies[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] != "tool", "window opens on an orphaned tool reply"
    assert sent[-1] == {"role": "user", "content": "newest"}
    assert_no_dangling_tool_calls(sent)
    # Every surviving tool reply still has its originating assistant call.
    calls = {c["id"] for m in sent for c in (m.get("tool_calls") or [])}
    for message in sent:
        if message["role"] == "tool":
            assert message["tool_call_id"] in calls


def test_the_newest_message_survives_even_when_it_alone_exceeds_the_budget():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider, context_chars=100)
    session.history.extend(_bulky_history())
    run(session, "y" * 5000)

    sent = provider.bodies[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[-1]["content"] == "y" * 5000


def test_history_under_budget_is_sent_untouched():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider)
    session.history.extend(_bulky_history())
    before = list(session.history)
    run(session, "newest")

    sent = provider.bodies[0]["messages"]
    assert sent[1:-1] == before
    # Truncation is a VIEW for one request — it must never mutate the
    # conversation's own record.
    assert session.history[: len(before)] == before


# ---------------------------------------------------------------------------
# Usage accounting + limits
# ---------------------------------------------------------------------------


def test_usage_flows_to_the_ledger_with_the_sessions_user_and_tier():
    provider = Provider(
        lambda: sse(
            text_chunk("ok", model="vendor/deep-model"),
            finish_chunk("stop"),
            usage_chunk(300, 40, cost=0.012),
        )
    )
    session, ledger = make_session(provider, tier="deep_research")
    run(session)

    assert ledger.recorded == [
        {
            "user": "analyst1",
            "tier": "deep_research",
            "model": "vendor/deep-model",
            "tokens_in": 300,
            "tokens_out": 40,
            "cost_usd": 0.012,
        }
    ]


def test_every_step_of_a_tool_turn_is_billed():
    provider = Provider(
        lambda: sse(
            tool_chunk(0, call_id="c1", name="retrieve", arguments="{}"),
            finish_chunk("tool_calls"),
            usage_chunk(100, 10, cost=0.001),
        ),
        lambda: sse(text_chunk("done"), finish_chunk("stop"), usage_chunk(400, 30, cost=0.004)),
    )
    session, ledger = make_session(provider)
    _, done = run(session)

    assert len(ledger.recorded) == 2
    assert done["usage"]["inputTokens"] == 500
    assert done["usage"]["outputTokens"] == 40
    assert done["usage"]["cost"] == pytest.approx(0.005)


def test_blocked_user_never_reaches_the_provider():
    provider = Provider(lambda: sse(text_chunk("should never run"), finish_chunk("stop")))
    blocked = FakeLedger(
        status="blocked",
        message="You've reached your monthly AI usage limit ($25.00) — ask admin to raise it.",
    )
    session, _ = make_session(provider, ledger=blocked)
    events, terminal = run(session)

    assert provider.call_count == 0
    assert terminal["type"] == "_error"
    # S19's wording, verbatim — not re-derived here.
    assert terminal["message"] == blocked.status.message
    assert of_type(events, "assistant_text_delta") == []


def test_a_ledger_write_failure_does_not_destroy_a_paid_for_answer():
    provider = Provider(lambda: sse(text_chunk("a real answer"), finish_chunk("stop"), usage_chunk()))
    session, _ = make_session(provider, ledger=FakeLedger(fail=True))
    _, done = run(session)

    assert done["type"] == "_done"
    assert done["finalAnswer"] == "a real answer"


def test_unconfigured_tier_refuses_before_any_call():
    provider = Provider(lambda: sse(text_chunk("nope"), finish_chunk("stop")))
    settings = Settings(
        provider=ProviderConfig(base_url="https://provider.test/api/v1", api_key="sk-test"),
        tiers={"standard": TierConfig(model="")},
    )
    session, _ = make_session(provider, settings=settings)
    _, terminal = run(session)

    assert provider.call_count == 0
    assert terminal["type"] == "_error"
    assert "no model configured" in terminal["message"]


# ---------------------------------------------------------------------------
# Accumulator — citations
# ---------------------------------------------------------------------------


QUOTE_ONLY_CITE = {
    "chunk_id": "jlbc-fy2027-adc:12",
    "quote": "$1,412,300 from the General Fund",
    "confidence": "verbatim",
    "claim_span": "ADC received $1.4 B from the General Fund.",
}


def _cite_turn(tool_name: str, arguments: dict) -> Provider:
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="cite_1", name=tool_name, arguments=json.dumps(arguments)),
            finish_chunk("tool_calls"),
        ),
        lambda: sse(text_chunk("ADC received $1.4 B."), finish_chunk("stop")),
    )


def test_quote_only_cite_reaches_the_audit_accumulator():
    # THE BUG THIS TASK FIXES: the old TypeScript accumulator required
    # numeric offsets, so every quote-only cite — the PREFERRED shape
    # since 2026-05-20 — vanished from the audit record.
    provider = _cite_turn("cite", QUOTE_ONLY_CITE)
    executor = FakeExecutor(
        {
            "cite": {
                "ok": True,
                "citation_id": "cid-1",
                "resolved_span_start": 40,
                "resolved_span_end": 72,
            }
        }
    )
    session, _ = make_session(provider, executor=executor)
    _, done = run(session)

    assert len(done["citations"]) == 1
    citation = done["citations"][0]
    assert citation["chunkId"] == "jlbc-fy2027-adc:12"
    assert citation["quote"] == "$1,412,300 from the General Fund"
    assert citation["claimSpan"] == "ADC received $1.4 B from the General Fund."
    assert citation["confidence"] == "verbatim"
    assert citation["citationId"] == "cid-1"
    assert citation["ok"] is True
    # The server-derived offsets are what the PDF highlight needs.
    assert (citation["spanStart"], citation["spanEnd"]) == (40, 72)


def test_legacy_offset_cites_still_accumulate():
    args = {
        "chunk_id": "c:1",
        "span_start": 5,
        "span_end": 25,
        "confidence": "paraphrase",
        "claim_span": "a claim",
    }
    provider = _cite_turn("cite", args)
    session, _ = make_session(
        provider, executor=FakeExecutor({"cite": {"ok": True, "citation_id": "cid-2"}})
    )
    _, done = run(session)

    citation = done["citations"][0]
    assert (citation["spanStart"], citation["spanEnd"]) == (5, 25)
    assert citation["quote"] is None


def test_cite_batch_citations_are_accumulated_too():
    args = {"citations": [QUOTE_ONLY_CITE, {**QUOTE_ONLY_CITE, "claim_span": "second claim"}]}
    result = {
        "citations": [
            {"ok": True, "citation_id": "cid-a", "resolved_span_start": 1, "resolved_span_end": 9},
            {"ok": False, "error": "quote not found in chunk text"},
        ]
    }
    provider = _cite_turn("cite_batch", args)
    session, _ = make_session(provider, executor=FakeExecutor({"cite_batch": result}))
    _, done = run(session)

    assert [c["claimSpan"] for c in done["citations"]] == [
        "ADC received $1.4 B from the General Fund.",
        "second claim",
    ]
    assert done["citations"][0]["ok"] is True
    assert done["citations"][1]["ok"] is False
    assert "quote not found" in done["citations"][1]["error"]


def test_malformed_cite_input_is_dropped_not_crashed(capsys):
    provider = _cite_turn("cite", {"confidence": "verbatim"})
    session, _ = make_session(
        provider, executor=FakeExecutor({"cite": {"ok": False, "error": "bad"}})
    )
    _, done = run(session)

    assert done["citations"] == []
    assert "dropping malformed cite" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Multi-turn state
# ---------------------------------------------------------------------------


def test_history_carries_across_turns_and_two_sessions_do_not_share_it():
    provider_a = Provider(lambda: sse(text_chunk("first"), finish_chunk("stop")))
    session_a, _ = make_session(provider_a)
    run(session_a, "turn one")
    run(session_a, "turn two")

    sent = provider_a.bodies[1]["messages"]
    assert [m["content"] for m in sent if m["role"] == "user"] == ["turn one", "turn two"]

    provider_b = Provider(lambda: sse(text_chunk("fresh"), finish_chunk("stop")))
    session_b, _ = make_session(provider_b)
    run(session_b, "unrelated")
    assert len(provider_b.bodies[0]["messages"]) == 2  # system + this user message only


def test_two_turns_cannot_run_concurrently_on_one_session():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop")))
    session, _ = make_session(provider)
    outer = session.stream_turn("first")
    next(outer)  # start it; the turn lock is now held

    _, terminal = run(session, "second")
    assert terminal["type"] == "_error"
    assert "already" in terminal["message"].lower()
    outer.close()
