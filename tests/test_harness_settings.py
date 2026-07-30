"""harness/settings.py — the one shared settings.json (Plan 4 Task 1).

Covers: typed defaults on a missing file, atomic round-trip, the
provider triple (OpenRouter default / S15 custom escape hatch), the
S16 tier map + ai_available() reason strings, and S19 per-user spend
limit resolution. All tests point JLBC_DATA_DIR at tmp_path via
monkeypatch (store/config.py convention — see tests/test_store_config.py)
so nothing here ever touches a real share.
"""
from __future__ import annotations

import json

import pytest

from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    ai_available,
    load_settings,
    reset_settings_cache,
    save_settings,
    settings_path,
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """Point every test at a throwaway data dir and clear the mtime cache.

    The cache is keyed on (path, mtime, size); across tests the path
    itself changes (fresh tmp_path each time) so stale entries would
    never collide in practice, but resetting explicitly keeps this test
    module from depending on that coincidence.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_settings_path_lives_under_data_dir(tmp_path):
    assert settings_path() == tmp_path / "settings.json"


def test_missing_file_returns_typed_defaults():
    settings = load_settings()
    assert isinstance(settings, Settings)
    assert settings.provider == ProviderConfig(
        base_url="https://openrouter.ai/api/v1", api_key="", provider="openrouter"
    )
    assert settings.tiers == {
        "standard": TierConfig(model=""),
        "deep_research": TierConfig(model=""),
    }
    assert settings.admin_username == ""
    assert settings.default_monthly_limit_usd is None
    assert settings.user_limits == {}
    assert settings.exempt_users == ()


def test_missing_file_means_no_api_key_configured():
    settings = load_settings()
    assert ai_available(settings, tier="standard") == (False, "no API key configured")


def test_key_present_but_tier_model_empty():
    settings = Settings(
        provider=ProviderConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-abc123",
            provider="openrouter",
        ),
    )
    assert ai_available(settings, tier="standard") == (
        False,
        "no model configured — ask the admin",
    )


def test_key_and_model_present_is_available():
    settings = Settings(
        provider=ProviderConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-abc123",
            provider="openrouter",
        ),
        tiers={
            "standard": TierConfig(model="qwen/qwen3-max"),
            "deep_research": TierConfig(model=""),
        },
    )
    # Standard is configured; deep_research is not — ai_available is
    # asked per-tier because later tasks (session.py) gate a specific
    # conversation's tier, not "AI Mode" as an undifferentiated whole.
    assert ai_available(settings, tier="standard") == (True, None)
    assert ai_available(settings, tier="deep_research") == (
        False,
        "no model configured — ask the admin",
    )


def test_save_and_load_round_trip(tmp_path):
    settings = Settings(
        provider=ProviderConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-xyz",
            provider="openrouter",
        ),
        tiers={
            "standard": TierConfig(model="qwen/qwen3-max"),
            "deep_research": TierConfig(model="moonshotai/kimi-k3"),
        },
        admin_username="destin",
        default_monthly_limit_usd=25.0,
        user_limits={"analyst1": 50.0},
        exempt_users=("destin",),
    )
    save_settings(settings)
    reset_settings_cache()
    reloaded = load_settings()
    assert reloaded == settings


def test_save_is_atomic_no_leftover_tmp_file(tmp_path):
    save_settings(load_settings())
    names = {p.name for p in tmp_path.iterdir()}
    assert "settings.json" in names
    assert not any(n.endswith(".tmp") for n in names)


def test_custom_provider_with_explicit_per_tier_model(tmp_path):
    """S15: custom endpoint, any OpenAI-compatible chat-completions API."""
    settings = Settings(
        provider=ProviderConfig(
            base_url="https://my-gateway.example.gov/v1",
            api_key="internal-key",
            provider="custom",
        ),
        tiers={
            "standard": TierConfig(model="llama-3.1-70b-instruct"),
            "deep_research": TierConfig(model="llama-3.1-405b-instruct"),
        },
    )
    save_settings(settings)
    reset_settings_cache()
    reloaded = load_settings()
    assert reloaded.provider.provider == "custom"
    assert reloaded.provider.base_url == "https://my-gateway.example.gov/v1"
    assert ai_available(reloaded, tier="standard") == (True, None)


def test_unknown_keys_in_json_do_not_crash_load(tmp_path):
    """Hand-edited / future-admin-page-written files may carry extra keys."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "provider": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-abc",
                    "provider": "openrouter",
                    "future_field": "ignored",
                },
                "tiers": {
                    "standard": {"model": "qwen/qwen3-max"},
                    "deep_research": {"model": ""},
                },
                "admin_username": "destin",
                "default_monthly_limit_usd": None,
                "user_limits": {},
                "exempt_users": [],
                "some_totally_new_top_level_key": {"nested": True},
            }
        ),
        encoding="utf-8",
    )
    reset_settings_cache()
    settings = load_settings()
    assert settings.provider.api_key == "sk-or-abc"
    assert settings.tiers["standard"].model == "qwen/qwen3-max"


def test_corrupt_json_surfaces_reason_via_ai_available(tmp_path):
    """A half-written or hand-broken file must not crash AI checks.

    load_settings() falls back to defaults (empty key) so ai_available()
    reports the same honest "no API key configured" reason it would for
    a missing file — never a stack trace mid-chat-turn.
    """
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    reset_settings_cache()
    settings = load_settings()
    assert settings == Settings()
    assert ai_available(settings, tier="standard") == (False, "no API key configured")


def test_mtime_cache_picks_up_a_rewritten_file(tmp_path):
    first = load_settings()
    assert first.provider.api_key == ""

    updated = Settings(
        provider=ProviderConfig(
            base_url="https://openrouter.ai/api/v1", api_key="sk-or-new", provider="openrouter"
        )
    )
    save_settings(updated)
    # No explicit reset_settings_cache() call here — load_settings() must
    # notice the file changed on disk on its own (mtime+size stamp, same
    # pattern as retrieval/api.py's _document_metadata()).
    second = load_settings()
    assert second.provider.api_key == "sk-or-new"


def test_cache_avoids_rereading_when_file_unchanged(tmp_path, monkeypatch):
    save_settings(load_settings())
    reset_settings_cache()
    load_settings()  # primes the cache

    calls = []
    real_read_text = type(settings_path()).read_text

    def _tracking_read_text(self, *args, **kwargs):
        calls.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.read_text", _tracking_read_text)
    load_settings()
    load_settings()
    assert calls == []


# --- S19 per-user spend limits -------------------------------------------


def test_limit_for_no_default_no_override_is_unlimited():
    settings = Settings()
    assert settings.limit_for("anyone") is None


def test_limit_for_uses_default_when_no_override():
    settings = Settings(default_monthly_limit_usd=25.0)
    assert settings.limit_for("analyst1") == 25.0


def test_limit_for_override_wins_over_default():
    settings = Settings(
        default_monthly_limit_usd=25.0,
        user_limits={"analyst1": 100.0},
    )
    assert settings.limit_for("analyst1") == 100.0
    assert settings.limit_for("analyst2") == 25.0


def test_limit_for_exempt_user_is_unlimited_even_with_default_and_override():
    settings = Settings(
        default_monthly_limit_usd=25.0,
        user_limits={"director": 10.0},
        exempt_users=("director",),
    )
    assert settings.limit_for("director") is None


def test_limit_for_username_case_sensitivity_is_exact_match():
    """Windows usernames: we store/compare exactly as configured.

    No case-folding here — the admin page (Plan 5) is the place to
    normalize input if that turns out to matter; silently folding case
    here would let "Analyst1" and "analyst1" collide in ways an admin
    reading their own config wouldn't expect.
    """
    settings = Settings(user_limits={"Analyst1": 50.0})
    assert settings.limit_for("analyst1") == settings.default_monthly_limit_usd
    assert settings.limit_for("Analyst1") == 50.0


def test_settings_is_frozen():
    settings = Settings()
    with pytest.raises(Exception):
        settings.admin_username = "someone"  # type: ignore[misc]


def test_provider_config_is_frozen():
    provider = ProviderConfig(base_url="x", api_key="y", provider="openrouter")
    with pytest.raises(Exception):
        provider.api_key = "z"  # type: ignore[misc]
