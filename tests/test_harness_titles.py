"""Auto-naming for a chat (Plan: chat history, H3).

One short non-streaming LLM call after the first exchange. Every failure
falls back to truncating the question — naming is a convenience, and history
must keep working with no OpenRouter key at all.
"""
import json

import httpx
import pytest

from harness import titles
from harness.ledger import LimitStatus
from harness.settings import Settings


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Keep these tests off the office ledger.

    `check_limit` reads `data_dir()/usage/` — on a dev box that is the real
    shared corpus directory. Any test here that does not stub check_limit
    would read it for real.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "data"))


def _allowed(*_a, **_kw):
    return LimitStatus(status="allowed", message=None, reason=None,
                       limit_usd=None, month_usd=0.0)


def _ok_transport(text="ADC vacancy savings", record=None):
    def handler(request):
        if record is not None:
            record["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 6,
                      "cost": 0.00004},
        })
    return httpx.MockTransport(handler)


def _settings_with_key(provider: str = "openrouter") -> Settings:
    """Build a Settings with a key and a Standard tier model.

    On "custom" it also carries both per-million prices, or check_limit's
    has_pricing branch changes what is being tested.
    """
    from harness.settings import ProviderConfig, TierConfig
    kwargs: dict = {}
    if provider == "custom":
        kwargs = {"prompt_usd_per_m": 1.0, "completion_usd_per_m": 2.0}
    return Settings(
        provider=ProviderConfig(
            api_key="sk-test", provider=provider, **kwargs,
        ),
        tiers={
            "standard": TierConfig(model="vendor/standard"),
            "deep_research": TierConfig(model="vendor/deep"),
        },
        admin_username="dana",
    )


def test_fallback_is_the_truncated_question():
    assert titles.fallback_title("What did ADC save from vacancies in FY2025?").startswith("What did ADC save")


def test_fallback_never_exceeds_sixty_characters():
    assert len(titles.fallback_title("x" * 500)) <= 60


def test_a_successful_call_returns_the_model_title(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    got = titles.generate_title("q", "a", user="destin",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_no_api_key_falls_back_without_calling_anything():
    def explode(request):
        raise AssertionError("must not call the provider without a key")
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=Settings(), transport=httpx.MockTransport(explode))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_provider_error_falls_back(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    def boom(request):
        return httpx.Response(500, json={"error": "nope"})
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(boom))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_blocked_user_falls_back_and_never_calls(monkeypatch):
    """Over the spend limit must not mean a failed chat title.

    NOTE the stub shape: check_limit takes (user, settings) POSITIONALLY and
    returns a LimitStatus. A `lambda **k: (False, "…")` stub raises TypeError
    at the call — outside generate_title's try — which would defeat the very
    property this test asserts.
    """
    blocked = LimitStatus(status="blocked", message="over limit", reason=None,
                          limit_usd=10.0, month_usd=10.0)
    monkeypatch.setattr(titles, "check_limit", lambda *_a, **_kw: blocked)
    def explode(request):
        raise AssertionError("must not call while blocked")
    got = titles.generate_title("What did ADC save?", "a", user="d",
                                settings=_settings_with_key(), transport=httpx.MockTransport(explode))
    assert got == titles.fallback_title("What did ADC save?")


def test_a_warned_user_is_still_titled(monkeypatch):
    """"warn" is not "blocked" — only blocked stops the call."""
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    warned = LimitStatus(status="warn", message="80%", reason=None,
                         limit_usd=10.0, month_usd=8.5)
    monkeypatch.setattr(titles, "check_limit", lambda *_a, **_kw: warned)
    got = titles.generate_title("q", "a", user="d",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_the_call_is_ledgered_under_its_own_tier(monkeypatch):
    """S19: title spend must never read as analyst spend in the admin panel."""
    seen = {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage",
                        lambda **kw: seen.update(kw))
    titles.generate_title("q", "a", user="destin",
                          settings=_settings_with_key(), transport=_ok_transport())
    assert seen["tier"] == "title"
    assert seen["user"] == "destin"


def test_openrouter_is_asked_for_the_dollar_cost(monkeypatch):
    """Without `usage: {include: true}` OpenRouter returns no `cost`.

    The row would then be written with cost_usd=None, which (a) sums as zero
    in month_total, so title spend is invisible to the S19 limit it is
    supposed to be counted against, and (b) increments
    rows_with_unknown_cost, which the admin page explains to the analyst as
    "older requests … made before prices were set up" — an explanation that
    would be false and unfixable.
    """
    seen, record = {}, {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", lambda **kw: seen.update(kw))
    titles.generate_title("q", "a", user="d", settings=_settings_with_key(),
                          transport=_ok_transport(record=record))
    assert record["body"]["usage"] == {"include": True}
    assert seen["cost_usd"] == 0.00004


def test_a_custom_endpoint_is_not_sent_the_openrouter_extension(monkeypatch):
    """S15: a strict OpenAI-compatible server rejects unknown top-level
    fields outright. Same gate harness/session.py:955 applies."""
    record = {}
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", lambda **kw: None)
    titles.generate_title("q", "a", user="d",
                          settings=_settings_with_key(provider="custom"),
                          transport=_ok_transport(record=record))
    assert "usage" not in record["body"]


def test_a_ledger_failure_does_not_throw_away_a_paid_for_title(monkeypatch):
    """record_usage RAISES by contract (harness/ledger.py) — the money is
    already spent by then, so losing the title too is the worst outcome."""
    def boom(**_kw):
        raise OSError("share full")
    monkeypatch.setattr(titles, "check_limit", _allowed)
    monkeypatch.setattr(titles, "record_usage", boom)
    got = titles.generate_title("q", "a", user="d",
                                settings=_settings_with_key(), transport=_ok_transport())
    assert got == "ADC vacancy savings"


def test_a_rambling_reply_is_truncated_not_used_raw(monkeypatch):
    monkeypatch.setattr(titles, "record_usage", lambda *a, **k: None)
    monkeypatch.setattr(titles, "check_limit", _allowed)
    got = titles.generate_title("q", "a", user="d", settings=_settings_with_key(),
                                transport=_ok_transport("Sure! Here is a title: " + "x" * 300))
    assert len(got) <= 60
