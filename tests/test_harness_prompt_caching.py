"""S22 — prompt caching.

The system prompt renders at ~40 KB (~13.5K tokens) and is resent on
EVERY step of a turn, up to 50 steps in a Deep Research turn. Every
candidate model prices cache reads roughly 10x below fresh input, so
this is the single largest cost lever in the app — but a provider can
only serve a cache hit when the request PREFIX is byte-identical to the
previous request's.

That makes prefix stability a property, not a coincidence, and this file
is what stops a future edit from silently destroying it. A regression
here has no symptom a human would notice: answers stay correct, tests
stay green, the bill quietly goes back up ~10x. So the tests below pin
the property directly rather than testing a function that happens to
produce it today.

Everything runs against `httpx.MockTransport`. No network, no key.
"""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from harness.session import ANTHROPIC_STYLE_MODEL_MARKERS, HarnessSession
from harness.settings import ProviderConfig, Settings, TierConfig

from tests.test_harness_session import (
    FakeExecutor,
    FakeLedger,
    Provider,
    finish_chunk,
    make_settings,
    sse,
    text_chunk,
    tool_chunk,
    usage_chunk,
)

SYSTEM_PROMPT = "SYSTEM PROMPT — pretend this is 40 KB of instructions."


def _settings(model: str = "vendor/standard-model", provider: str = "openrouter") -> Settings:
    return Settings(
        provider=ProviderConfig(
            base_url="https://provider.test/api/v1", api_key="sk-test", provider=provider
        ),
        tiers={
            "standard": TierConfig(model=model),
            "deep_research": TierConfig(model=model),
        },
        admin_username="admin",
    )


def _session(
    provider_stub: Provider,
    *,
    model: str = "vendor/standard-model",
    provider: str = "openrouter",
    conversation_id: str = "conv-1",
    user: str = "analyst1",
    **over,
) -> HarnessSession:
    return HarnessSession(
        conversation_id,
        user=user,
        settings=_settings(model, provider),
        executor=FakeExecutor(),
        transport=provider_stub.transport(),
        system_prompt=SYSTEM_PROMPT,
        tools=[{"type": "function", "function": {"name": "retrieve", "parameters": {}}}],
        check_limit=FakeLedger().check_limit,
        record_usage=FakeLedger().record_usage,
        **over,
    )


def _two_tool_steps_then_answer() -> Provider:
    """A three-step turn: search, search, answer."""
    return Provider(
        lambda: sse(
            tool_chunk(0, "call-1", "retrieve", '{"query": "a"}'),
            finish_chunk("tool_calls"),
            usage_chunk(),
        ),
        lambda: sse(
            tool_chunk(0, "call-2", "retrieve", '{"query": "b"}'),
            finish_chunk("tool_calls"),
            usage_chunk(),
        ),
        lambda: sse(text_chunk("Done."), finish_chunk("stop"), usage_chunk()),
    )


def _prefix(body: dict) -> str:
    """The part of a request a provider can serve from cache: the system
    message plus the tool schemas, serialized exactly as sent."""
    return json.dumps(
        {"system": body["messages"][0], "tools": body.get("tools")},
        ensure_ascii=False,
        sort_keys=False,
    )


# ---------------------------------------------------------------------------
# The property: a byte-identical prefix
# ---------------------------------------------------------------------------


def test_prefix_is_byte_identical_across_every_step_of_a_turn():
    provider = _two_tool_steps_then_answer()
    session = _session(provider)

    session.send_turn("How much did AHCCCS get in FY 2027?")

    assert provider.call_count == 3
    prefixes = {_prefix(body) for body in provider.bodies}
    assert len(prefixes) == 1, (
        "The system prompt + tool schemas differ between steps of one turn. "
        "Every step after the first is now a cache MISS, at roughly 10x the "
        "price of a hit. Whatever was just made dynamic belongs in a user or "
        "tool message, not ahead of the conversation."
    )


def test_prefix_is_byte_identical_across_turns():
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    session = _session(provider)

    session.send_turn("first question")
    session.send_turn("second question")

    assert provider.call_count == 2
    assert _prefix(provider.bodies[0]) == _prefix(provider.bodies[1])


def test_prefix_is_byte_identical_across_conversations_and_users():
    """Two analysts asking two different questions share the cache.

    One process serves the whole office, so anything per-user or
    per-conversation in the prefix would mean each analyst pays full
    price for their own copy."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))

    _session(provider, conversation_id="conv-a", user="analyst1").send_turn("q1")
    _session(provider, conversation_id="conv-b", user="analyst2").send_turn("q2")

    assert _prefix(provider.bodies[0]) == _prefix(provider.bodies[1])


def test_the_prefix_is_where_the_bytes_are_and_the_question_is_not_in_it():
    """Guards the test above from passing vacuously: if the question ever
    leaked into the prefix, the equality assertions would be comparing
    the wrong thing."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    _session(provider).send_turn("a very distinctive question about AHCCCS")

    assert "distinctive question" not in _prefix(provider.bodies[0])
    assert "distinctive question" in json.dumps(provider.bodies[0]["messages"][1:])


def test_prefix_carries_no_dates():
    """The most likely way a future edit breaks caching is by telling the
    model what day it is. That is one line to write and invisible to
    every other test."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    session = HarnessSession(
        "conv-1",
        settings=_settings(),
        executor=FakeExecutor(),
        transport=provider.transport(),
        tools=[],
        check_limit=FakeLedger().check_limit,
        record_usage=FakeLedger().record_usage,
    )
    session.send_turn("q")

    prefix = _prefix(provider.bodies[0])
    today = date.today()
    for stamp in (today.isoformat(), today.strftime("%B %d, %Y"), today.strftime("%m/%d/%Y")):
        assert stamp not in prefix, (
            f"Today's date ({stamp}) is in the cacheable prefix. Every "
            "request will miss the cache from tomorrow onward, and the "
            "office will never see a symptom other than the bill."
        )


def test_the_real_system_prompt_renders_identically_every_time():
    """The builder itself, not just the session's cache of it — a session
    that rebuilds the prompt for any reason must get the same bytes."""
    from harness.prompt import build_system_prompt, reset_template_cache

    first = build_system_prompt(corpus="budget", tier="standard")
    reset_template_cache()
    second = build_system_prompt(corpus="budget", tier="standard")

    assert first == second
    assert "{{" not in first  # an unsubstituted placeholder is dynamic-looking noise


# ---------------------------------------------------------------------------
# cache_control breakpoints (models that need explicit marking)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["anthropic/claude-opus-5", "anthropic/claude-haiku-4.5"])
def test_anthropic_style_models_get_an_explicit_cache_breakpoint(model):
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    _session(provider, model=model).send_turn("q")

    system = provider.bodies[0]["messages"][0]
    assert system["role"] == "system"
    assert isinstance(system["content"], list)
    assert system["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # The prompt text itself must survive the wrapping intact.
    assert system["content"][-1]["text"] == SYSTEM_PROMPT


def test_the_breakpoint_does_not_make_the_prefix_unstable():
    provider = _two_tool_steps_then_answer()
    _session(provider, model="anthropic/claude-opus-5").send_turn("q")

    assert len({_prefix(body) for body in provider.bodies}) == 1


@pytest.mark.parametrize(
    "model", ["openai/gpt-5", "deepseek/deepseek-v4", "moonshotai/kimi-k3", "qwen/qwen3.7-plus"]
)
def test_implicit_caching_models_get_a_plain_string_system_message(model):
    """OpenAI/DeepSeek/Moonshot-style providers cache prefixes
    automatically. Marking them would add bytes for nothing and risks a
    strict endpoint rejecting an unknown field."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    _session(provider, model=model).send_turn("q")

    assert provider.bodies[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_custom_endpoints_never_get_cache_control():
    """S15's custom endpoint may be a strictly OpenAI-compatible server
    that 400s on an unknown field — the same reason `usage: {include}` is
    gated on the provider being OpenRouter."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    _session(provider, model="anthropic/claude-opus-5", provider="custom").send_turn("q")

    assert provider.bodies[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_the_marker_table_is_what_decides():
    assert any(marker in "anthropic/claude-opus-5" for marker in ANTHROPIC_STYLE_MODEL_MARKERS)
    assert not any(marker in "openai/gpt-5" for marker in ANTHROPIC_STYLE_MODEL_MARKERS)


# ---------------------------------------------------------------------------
# The context budget must still see the prompt's real size
# ---------------------------------------------------------------------------


def test_context_budget_measures_the_prompt_text_not_the_wrapper():
    """`_context_window` gets the system prompt's size as `reserved`. When
    the prompt is wrapped in content parts for cache_control, a naive
    `len(content)` reads 1 instead of ~40,000 and the history window
    silently grows by the whole prompt's budget — which is how a request
    ends up over the model's context limit with no local error."""
    long_prompt = "x" * 5_000
    provider_a = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    provider_b = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    history = [
        {"role": "user", "content": "y" * 400},
        {"role": "assistant", "content": "z" * 400},
    ] * 6

    def run(provider: Provider, model: str) -> list[dict]:
        session = HarnessSession(
            "conv-1",
            settings=_settings(model),
            executor=FakeExecutor(),
            transport=provider.transport(),
            system_prompt=long_prompt,
            tools=[],
            history=list(history),
            context_chars=6_000,
            check_limit=FakeLedger().check_limit,
            record_usage=FakeLedger().record_usage,
        )
        session.send_turn("q")
        return provider.bodies[0]["messages"]

    marked = run(provider_a, "anthropic/claude-opus-5")
    plain = run(provider_b, "openai/gpt-5")

    assert len(marked) == len(plain)
    assert marked[1:] == plain[1:]
    # And the budget genuinely bit — otherwise this proves nothing.
    assert len(plain) < len(history) + 1


# ---------------------------------------------------------------------------
# cached_tokens reaches the ledger
# ---------------------------------------------------------------------------


def test_each_step_records_its_own_cached_token_count():
    ledger = FakeLedger()
    provider = Provider(
        lambda: sse(
            tool_chunk(0, "call-1", "retrieve", "{}"),
            finish_chunk("tool_calls"),
            usage_chunk(prompt=14_000, cached=0),
        ),
        lambda: sse(text_chunk("done"), finish_chunk("stop"), usage_chunk(prompt=14_400, cached=13_500)),
    )
    session = HarnessSession(
        "conv-1",
        user="analyst1",
        settings=_settings(),
        executor=FakeExecutor(),
        transport=provider.transport(),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        check_limit=ledger.check_limit,
        record_usage=ledger.record_usage,
    )

    session.send_turn("q")

    assert [row["cached_tokens"] for row in ledger.recorded] == [0, 13_500]


def test_missing_cache_details_record_zero_not_none():
    """A provider that reports no cache details means "we know of none",
    which is 0 — not unknown. `cost_usd` is the only field where None
    carries meaning."""
    ledger = FakeLedger()
    usage = usage_chunk()
    del usage["usage"]["prompt_tokens_details"]
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage))
    HarnessSession(
        "conv-1",
        settings=_settings(),
        executor=FakeExecutor(),
        transport=provider.transport(),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        check_limit=ledger.check_limit,
        record_usage=ledger.record_usage,
    ).send_turn("q")

    assert ledger.recorded[0]["cached_tokens"] == 0
