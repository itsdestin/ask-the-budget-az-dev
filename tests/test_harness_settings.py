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

    # Not `==` any more. Saving RESOLVES the on/off sentinels (2026-07-31):
    # an in-memory `enabled=None` means "never explicitly set", but a file
    # on the share is read by people in Notepad, and a `null` there reads
    # as broken. So the write is explicit and the reload comes back with
    # real booleans — equivalent in behaviour, not identical in value.
    assert reloaded.provider == settings.provider
    assert reloaded.admin_username == settings.admin_username
    assert reloaded.default_monthly_limit_usd == settings.default_monthly_limit_usd
    assert reloaded.user_limits == settings.user_limits
    assert reloaded.exempt_users == settings.exempt_users
    assert {n: c.model for n, c in reloaded.tiers.items()} == {
        n: c.model for n, c in settings.tiers.items()
    }
    assert reloaded.ai_is_enabled == settings.ai_is_enabled
    for name, cfg in settings.tiers.items():
        assert reloaded.tiers[name].is_enabled == cfg.is_enabled


def test_the_resolved_switches_are_written_explicitly(tmp_path):
    """What an admin sees if they open settings.json in Notepad.

    The handbook's last-resort recovery step tells them to do exactly
    that, so the file has to be readable — `"enabled": null` is not.
    """
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-or-xyz"),
        tiers={"standard": TierConfig(model="vendor/m")},
    ))
    raw = json.loads(settings_path().read_text(encoding="utf-8"))
    assert raw["ai_enabled"] is True
    assert raw["tiers"]["standard"]["enabled"] is True


def test_an_explicitly_disabled_mode_keeps_its_model(tmp_path):
    """Switching a mode off must not throw away the admin's choice.

    Before the switch existed the only way to disable Deep Research was to
    blank its model, which made re-enabling it a fresh decision.
    """
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-or-xyz"),
        tiers={"deep_research": TierConfig(model="moonshotai/kimi-k3", enabled=False)},
    ))
    reset_settings_cache()
    tier = load_settings().tiers["deep_research"]
    assert tier.model == "moonshotai/kimi-k3"
    assert tier.is_enabled is False
    assert ai_available(load_settings(), "deep_research") == (
        False, "this answer mode is switched off — ask the admin"
    )


def test_an_older_file_with_no_switches_still_works(tmp_path):
    """The upgrade path. A settings.json from before this change has no
    `ai_enabled` and no per-mode `enabled`, and must keep working exactly
    as it did — not silently switch the office's AI Mode off."""
    settings_path().write_text(json.dumps({
        "provider": {"api_key": "sk-or-xyz", "provider": "openrouter"},
        "tiers": {"standard": {"model": "vendor/m"}, "deep_research": {"model": ""}},
    }), encoding="utf-8")
    reset_settings_cache()

    settings = load_settings()
    assert settings.ai_is_enabled is True
    assert ai_available(settings, "standard") == (True, None)
    # And a mode that was never configured still reads as unconfigured,
    # not as "switched off".
    assert ai_available(settings, "deep_research") == (
        False, "no model configured — ask the admin"
    )


def test_the_master_switch_beats_a_configured_mode(tmp_path):
    settings = Settings(
        provider=ProviderConfig(api_key="sk-or-xyz"),
        tiers={"standard": TierConfig(model="vendor/m", enabled=True)},
        ai_enabled=False,
    )
    assert ai_available(settings, "standard") == (
        False, "AI Mode is switched off — ask the admin"
    )


def test_no_key_reads_as_no_key_even_when_switched_off(tmp_path):
    # Telling an admin with no key that "AI Mode is switched off" would
    # send them hunting for a toggle when what they need is a key.
    settings = Settings(ai_enabled=False)
    assert ai_available(settings, "standard") == (False, "no API key configured")


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


@pytest.mark.parametrize("bad_provider", ["oops", 5, True, [1, 2]])
def test_provider_field_wrong_type_falls_back_to_defaults(tmp_path, bad_provider):
    """Valid JSON, wrong shape: `provider` as a truthy non-dict must not
    crash the load — same tolerance _tiers_from_dict already had, applied
    to the provider triple too. Regression for a real defect: only
    falsy non-dicts ("", 0, False) happened to route through the old
    `raw.get("provider") or {}` fallback; a truthy string/int/bool/list
    called .get() on a non-dict and raised.
    """
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"provider": bad_provider}), encoding="utf-8")
    reset_settings_cache()
    settings = load_settings()  # must not raise
    assert settings.provider == ProviderConfig()


def test_provider_field_explicit_null_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"provider": None}), encoding="utf-8")
    reset_settings_cache()
    settings = load_settings()
    assert settings.provider == ProviderConfig()


def test_tiers_entry_wrong_type_falls_back_to_default_for_that_tier(tmp_path):
    """A non-dict value under one tier name must not crash the load and
    must not poison the other, well-formed tier."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"tiers": {"standard": "oops", "deep_research": {"model": "kimi-k3"}}}
        ),
        encoding="utf-8",
    )
    reset_settings_cache()
    settings = load_settings()  # must not raise
    assert settings.tiers["standard"] == TierConfig()  # default, not crashed
    assert settings.tiers["deep_research"] == TierConfig(model="kimi-k3")


def test_explicit_null_on_each_provider_string_field_falls_back_to_default(tmp_path):
    """str(None) == "None" is the bug this guards against: dict.get's
    default only fires when a key is ABSENT, so an explicit JSON null on
    base_url/api_key/provider must still resolve to this module's own
    default, never the literal text "None"."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"provider": {"base_url": None, "api_key": None, "provider": None}}),
        encoding="utf-8",
    )
    reset_settings_cache()
    settings = load_settings()
    assert settings.provider == ProviderConfig()


def test_explicit_null_api_key_does_not_leak_as_the_string_none(tmp_path):
    """The critical case: an admin "clearing" api_key by setting it to
    JSON null must produce an EMPTY key, not the truthy string "None" —
    otherwise ai_available() reports the tier available (its `if not
    settings.provider.api_key` check doesn't fire on a non-empty string)
    and the harness would go on to send the literal text "None" as a
    bearer token instead of refusing honestly.
    """
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "provider": {"api_key": None, "provider": "openrouter"},
                "tiers": {"standard": {"model": "qwen/qwen3-max"}},
            }
        ),
        encoding="utf-8",
    )
    reset_settings_cache()
    settings = load_settings()
    assert settings.provider.api_key == ""
    assert ai_available(settings, tier="standard") == (False, "no API key configured")


def test_explicit_null_on_tier_model_and_admin_username_falls_back_to_default(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "tiers": {"standard": {"model": None}},
                "admin_username": None,
            }
        ),
        encoding="utf-8",
    )
    reset_settings_cache()
    settings = load_settings()
    assert settings.tiers["standard"].model == ""
    assert settings.admin_username == ""


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


# The exact-only pin that lived here was retired with spec U0 (2026-08-25);
# see the folding tests below.


def test_settings_is_frozen():
    settings = Settings()
    with pytest.raises(Exception):
        settings.admin_username = "someone"  # type: ignore[misc]


def test_provider_config_is_frozen():
    provider = ProviderConfig(base_url="x", api_key="y", provider="openrouter")
    with pytest.raises(Exception):
        provider.api_key = "z"  # type: ignore[misc]


# --- spec U0: username matching folds case, exact match wins ------------

def test_limit_for_matches_a_differently_cased_username():
    s = Settings(default_monthly_limit_usd=25.0, user_limits={"dmoss": 100.0})
    assert s.limit_for("DMOSS") == 100.0


def test_limit_for_exact_match_beats_a_folded_one():
    # A legacy hand-typed file can hold both spellings. The exact one wins —
    # silently picking is what the old comment was right to refuse, and the
    # People panel renders the collision (test_admin_users_route.py).
    s = Settings(user_limits={"dmoss": 100.0, "DMOSS": 60.0})
    assert s.limit_for("dmoss") == 100.0
    assert s.limit_for("DMOSS") == 60.0
    assert s.limit_for("Dmoss") == 100.0  # neither exact → first folded match, dict order


def test_exempt_list_folds_too():
    s = Settings(default_monthly_limit_usd=25.0, exempt_users=("director",))
    assert s.limit_for("DIRECTOR") is None
    assert s.is_exempt("Director")
    assert not s.is_exempt("analyst1")


def test_blank_user_never_folds_onto_anyone():
    s = Settings(default_monthly_limit_usd=25.0, user_limits={"": 5.0})
    assert s.limit_for("") == 5.0        # exact match still honoured
    assert s.limit_for("  ") == 25.0     # but whitespace does not fold to ""


def test_hidden_users_round_trip(tmp_path):
    s = Settings(hidden_users=("pchen",))
    save_settings(s, tmp_path / "settings.json")
    reloaded = load_settings(tmp_path / "settings.json")
    assert reloaded.hidden_users == ("pchen",)
    assert reloaded.is_hidden("PCHEN")
    assert not reloaded.is_hidden("dmoss")


def test_hidden_users_absent_from_an_older_file_reads_as_none(tmp_path):
    (tmp_path / "settings.json").write_text('{"admin_username": "x"}', encoding="utf-8")
    assert load_settings(tmp_path / "settings.json").hidden_users == ()


def test_the_settings_fold_is_the_same_expression_as_whoami():
    # Invariant 7 forbids importing users/ here, so this is a COPY — pinned
    # to the exact expression so the two cannot drift (spec U0).
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "harness" / "settings.py").read_text(encoding="utf-8")
    assert "return user.strip().casefold()" in src
