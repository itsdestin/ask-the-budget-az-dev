"""The agent loop must cap `max_tokens`.

WHY this file exists (observed live 2026-08-03, mid eval run): the loop sent
no `max_tokens` at all, so every request implicitly asked for the model's
maximum — 65,536 tokens. OpenRouter reserves credit for that worst case
BEFORE it will start a request, so a key with $2.73 of headroom was refused
with HTTP 402: "You requested up to 65536 tokens, but can only afford 7473."
Twelve of thirty-one eval queries died that way after $0.84 had been spent.

The office consequence is worse than the eval one: every analyst request
reserves 65k tokens of credit, so when the shared key runs low every user
gets a hard failure while the balance still looks healthy.

The cap is sized from measurement, not taste — see MAX_COMPLETION_TOKENS.
"""
from __future__ import annotations

from harness.session import MAX_COMPLETION_TOKENS
from tests.test_harness_session import (
    FakeExecutor, Provider, finish_chunk, make_settings, sse, text_chunk,
    usage_chunk,
)
from harness.session import HarnessSession


def _run_and_capture() -> dict:
    provider = Provider(
        lambda: sse(text_chunk("An answer."), finish_chunk("stop"), usage_chunk()),
    )
    session = HarnessSession(
        "conv-max-tokens", "budget", "standard", "analyst",
        make_settings(), executor=FakeExecutor(),
        transport=provider.transport(), tools=[],
        system_prompt="test prompt",
    )
    session.send_turn("How much for ADC?")
    session.close()
    return provider.bodies[0]


def test_the_request_caps_max_tokens():
    body = _run_and_capture()
    assert body["max_tokens"] == MAX_COMPLETION_TOKENS


def test_the_cap_clears_every_step_ever_observed():
    """319 billed steps across every recorded eval run: median 207, p95
    4,220, max 7,426, and not one over 8,000. The cap must sit clear of
    that ceiling so it never truncates a real answer — while staying far
    below the 65,536 that caused the outage."""
    assert MAX_COMPLETION_TOKENS >= 16_000
    assert MAX_COMPLETION_TOKENS <= 32_000
