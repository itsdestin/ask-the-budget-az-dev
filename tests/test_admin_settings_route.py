"""GET/PUT /api/admin/settings (Plan 5 Task 3).

The first two tests are the reason this module exists. Both failure modes
are SILENT:

  - a leaked API key looks completely fine right up until it is in a
    screenshot or a browser devtools tab,
  - a clobbered API key looks like "AI Mode randomly stopped working"
    a week later, with nothing in any log pointing at the settings edit
    that caused it.

Everything after them is validation copy and the soft admin gate.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.catalog import CACHE_FILE
from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    load_settings,
    reset_settings_cache,
    save_settings,
)

ADMIN = "Destin"
ANALYST = "analyst1"
KEY = "sk-or-v1-abcdef"


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    _seed_catalog_cache(tmp_path)
    yield
    reset_settings_cache()


def _seed_catalog_cache(share: Path) -> None:
    """Pre-warm the model-catalog cache so NO test here touches the network.

    Model-id validation consults the catalog when an id fails the shape
    check (see `_model_id_looks_valid`), and a cold cache would make that
    a live HTTPS call — slow, flaky, and dependent on whoever runs the
    suite having outbound access. Seeding a fresh cache from the same
    captured payload tests/test_catalog.py uses keeps the behaviour real
    while keeping the suite hermetic.
    """
    fixture = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    cache = share / CACHE_FILE
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({
            "fetched_at": "2026-07-31T12:00:00-07:00",
            "fetched_at_epoch": time.time(),
            "payload": json.loads(fixture.read_text(encoding="utf-8")),
        }),
        encoding="utf-8",
    )


@pytest.fixture
def settings_with_key() -> Settings:
    settings = Settings(
        provider=ProviderConfig(api_key=KEY, provider="openrouter"),
        tiers={
            "standard": TierConfig(model="vendor/standard"),
            "deep_research": TierConfig(model="vendor/deep"),
        },
        admin_username=ADMIN,
        default_monthly_limit_usd=10.0,
        user_limits={"analyst1": 5.0},
        exempt_users=("director",),
    )
    save_settings(settings)
    reset_settings_cache()
    return settings


@pytest.fixture
def admin_client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


@pytest.fixture
def analyst_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("JLBC_USER", ANALYST)
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def base_body(**overrides) -> dict:
    body = {
        "provider": {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
        "tiers": {"standard": {"model": "vendor/standard"},
                  "deep_research": {"model": "vendor/deep"}},
        "admin_username": ADMIN,
        "default_monthly_limit_usd": 10.0,
        "user_limits": {"analyst1": 5.0},
        "exempt_users": ["director"],
        "api_key": "__unchanged__",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Redaction — the two silent failures
# ---------------------------------------------------------------------------


def test_get_never_returns_the_api_key(admin_client, settings_with_key):
    body = admin_client.get("/api/admin/settings").json()
    assert "api_key" not in body["provider"]
    assert body["provider"]["api_key_set"] is True
    assert body["provider"]["api_key_hint"] == "…cdef"     # last 4 only
    assert "sk-or-v1" not in admin_client.get("/api/admin/settings").text


def test_put_with_sentinel_preserves_the_existing_key(admin_client, settings_with_key):
    # The failure this prevents: an admin edits a spend limit, the form
    # round-trips a blank key, and AI Mode dies office-wide with no error
    # that points at what happened.
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(api_key="__unchanged__", default_monthly_limit_usd=25.0),
    )
    assert r.status_code == 200, r.text
    reset_settings_cache()
    assert load_settings().provider.api_key == KEY
    assert load_settings().default_monthly_limit_usd == 25.0


def test_put_response_is_also_redacted(admin_client, settings_with_key):
    body = admin_client.put("/api/admin/settings", json=base_body()).json()
    assert "api_key" not in body["provider"]
    assert body["provider"]["api_key_set"] is True


def test_put_can_actually_replace_the_key(admin_client, settings_with_key):
    r = admin_client.put("/api/admin/settings", json=base_body(api_key="sk-or-v1-999999"))
    assert r.status_code == 200, r.text
    reset_settings_cache()
    assert load_settings().provider.api_key == "sk-or-v1-999999"
    assert r.json()["provider"]["api_key_hint"] == "…9999"


def test_put_with_an_empty_key_clears_it_deliberately(admin_client, settings_with_key):
    # "" is NOT the sentinel — an admin who empties the field means it.
    # The sentinel exists so a form that never touched the field can say so.
    r = admin_client.put("/api/admin/settings", json=base_body(api_key=""))
    assert r.status_code == 200, r.text
    reset_settings_cache()
    assert load_settings().provider.api_key == ""
    assert r.json()["provider"]["api_key_set"] is False
    assert r.json()["provider"]["api_key_hint"] == ""


def test_hint_never_reveals_a_short_key(admin_client):
    save_settings(Settings(provider=ProviderConfig(api_key="abc"), admin_username=ADMIN))
    reset_settings_cache()
    body = admin_client.get("/api/admin/settings").json()
    # A 3-character key is garbage, but "…abc" would still print all of it.
    assert body["provider"]["api_key_hint"] == "…"
    assert "abc" not in admin_client.get("/api/admin/settings").text


def test_an_omitted_field_is_not_blanked(admin_client, settings_with_key):
    """Ground rule from the plan: start from the loaded settings, replace
    only supplied fields. A client on an older shape must not be able to
    wipe a field it has never heard of."""
    r = admin_client.put(
        "/api/admin/settings", json={"default_monthly_limit_usd": 42.0}
    )
    assert r.status_code == 200, r.text
    reset_settings_cache()
    after = load_settings()
    assert after.default_monthly_limit_usd == 42.0
    assert after.provider.api_key == KEY            # untouched
    assert after.tiers["standard"].model == "vendor/standard"
    assert after.exempt_users == ("director",)
    assert after.admin_username == ADMIN


# ---------------------------------------------------------------------------
# Validation — one plain sentence per failure
# ---------------------------------------------------------------------------


def test_implausible_model_id_is_rejected(admin_client, settings_with_key):
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(tiers={"standard": {"model": "gpt4"},
                              "deep_research": {"model": "vendor/deep"}}),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "That model id doesn't look right — pick one from the list, "
        "or check the spelling."
    )
    reset_settings_cache()
    assert load_settings().tiers["standard"].model == "vendor/standard"


def test_a_blank_tier_model_is_allowed(admin_client, settings_with_key):
    # An admin who hasn't chosen a Deep Research model yet is a normal,
    # supported state — ai_available() reports "no model configured —
    # ask the admin" for that tier and Standard keeps working.
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(tiers={"standard": {"model": "vendor/standard"},
                              "deep_research": {"model": ""}}),
    )
    assert r.status_code == 200, r.text


def test_negative_default_limit_is_rejected(admin_client, settings_with_key):
    r = admin_client.put(
        "/api/admin/settings", json=base_body(default_monthly_limit_usd=-1)
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "A monthly limit can't be negative. Leave it blank for no limit, "
        "or enter 0 to block a user entirely."
    )


def test_negative_per_user_limit_is_rejected(admin_client, settings_with_key):
    r = admin_client.put(
        "/api/admin/settings", json=base_body(user_limits={"analyst1": -5})
    )
    assert r.status_code == 400
    assert "can't be negative" in r.json()["detail"]


def test_zero_limit_is_allowed(admin_client, settings_with_key):
    # 0 means "block this user outright" — check_limit already encodes that.
    r = admin_client.put(
        "/api/admin/settings", json=base_body(user_limits={"analyst1": 0})
    )
    assert r.status_code == 200, r.text
    reset_settings_cache()
    assert load_settings().user_limits["analyst1"] == 0


def test_empty_username_in_user_limits_is_rejected(admin_client, settings_with_key):
    # An empty username silently applies to nobody — it looks like a
    # configured limit on the page and enforces nothing.
    r = admin_client.put(
        "/api/admin/settings", json=base_body(user_limits={"   ": 5.0})
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "A spend limit needs a username. Remove the blank row, or type "
        "the Windows username it applies to."
    )


def test_blank_exempt_user_is_rejected(admin_client, settings_with_key):
    r = admin_client.put("/api/admin/settings", json=base_body(exempt_users=["  "]))
    assert r.status_code == 400
    assert "needs a username" in r.json()["detail"]


def test_unknown_provider_is_rejected(admin_client, settings_with_key):
    # check_limit branches on provider == "custom" to turn spend limits off.
    # A typo'd value would leave limits nominally "on" against costs that
    # are always None — enforcement that silently never fires.
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(provider={"provider": "Custom",
                                 "base_url": "https://example.test/v1"}),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "Provider must be either 'openrouter' or 'custom'."
    )


def test_base_url_must_be_a_url(admin_client, settings_with_key):
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(provider={"provider": "custom", "base_url": "my-server"}),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "The endpoint address needs to start with http:// or https://."
    )


def test_an_odd_shaped_id_the_catalog_vouches_for_is_accepted(
    admin_client, settings_with_key, tmp_path
):
    """The rule is "implausible AND unknown to the catalog" — not "implausible".

    A real model id that doesn't match the vendor/model pattern must still
    be settable, or the shape check becomes an allowlist that ages badly.
    """
    fixture = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["data"][0]["id"] = "weird-but-real"
    (tmp_path / CACHE_FILE).write_text(
        json.dumps({"fetched_at": "2026-07-31T12:00:00-07:00",
                    "fetched_at_epoch": time.time(), "payload": payload}),
        encoding="utf-8",
    )
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(tiers={"standard": {"model": "weird-but-real"},
                              "deep_research": {"model": "vendor/deep"}}),
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# GET /api/admin/models
# ---------------------------------------------------------------------------


def test_models_route_serves_the_cached_catalog(admin_client, settings_with_key):
    body = admin_client.get("/api/admin/models").json()
    assert body["source"] == "cache"
    assert body["note"] is None
    ids = {m["id"] for m in body["catalog"]}
    assert "qwen/qwen3.7-plus" in ids
    # Every card the picker renders must be tool-capable — that is the
    # entry criterion, not a preference.
    assert all(m["supports_tools"] for m in body["catalog"])
    recommended = body["recommended"]
    assert {m["tier_hint"] for m in recommended} == {"standard", "deep_research"}
    assert all(m["blurb"] for m in recommended)


def test_models_route_reports_a_custom_endpoint_honestly(admin_client, settings_with_key):
    admin_client.put(
        "/api/admin/settings",
        json=base_body(provider={"provider": "custom",
                                 "base_url": "https://example.test/v1"}),
    )
    body = admin_client.get("/api/admin/models").json()
    assert body["source"] == "bundled"
    assert body["catalog"] == []
    assert "custom endpoint" in body["note"].lower()


# ---------------------------------------------------------------------------
# GET /api/admin/notices
# ---------------------------------------------------------------------------


def test_notices_route_returns_the_feed(admin_client, settings_with_key):
    from harness.notices import KIND_MODEL_FALLBACK, record_notice

    record_notice(KIND_MODEL_FALLBACK, "the standard model was retired")
    body = admin_client.get("/api/admin/notices").json()
    assert [n["message"] for n in body["notices"]] == [
        "the standard model was retired"
    ]

    newest = body["notices"][-1]["at"]
    assert admin_client.get(f"/api/admin/notices?since={newest}").json()["notices"] == []


def test_notices_route_is_empty_on_a_fresh_install(admin_client, settings_with_key):
    assert admin_client.get("/api/admin/notices").json() == {"notices": []}


# ---------------------------------------------------------------------------
# Admin transfer — the lockout guards
# ---------------------------------------------------------------------------


def test_transfer_requires_explicit_confirmation(admin_client, settings_with_key):
    r = admin_client.put("/api/admin/settings", json=base_body(admin_username="Jen"))
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Jen" in detail
    assert "lose" in detail or "lose access" in detail
    reset_settings_cache()
    assert load_settings().admin_username == ADMIN   # untouched


def test_confirmed_transfer_goes_through(admin_client, settings_with_key):
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(admin_username="Jen", confirm_admin_transfer=True),
    )
    assert r.status_code == 200, r.text
    reset_settings_cache()
    assert load_settings().admin_username == "Jen"


def test_transfer_to_an_empty_username_is_rejected_outright(
    admin_client, settings_with_key
):
    # This would un-claim the install and hand admin to EVERYONE — the
    # confirmation flag must not be able to authorise it.
    r = admin_client.put(
        "/api/admin/settings",
        json=base_body(admin_username="  ", confirm_admin_transfer=True),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "The admin username can't be blank — that would hand admin access "
        "to everyone. To hand over the app, type the new admin's Windows "
        "username; to reset it entirely, see 'If nobody can get into Admin' "
        "in the handbook."
    )
    reset_settings_cache()
    assert load_settings().admin_username == ADMIN


def test_resending_your_own_username_is_not_a_transfer(admin_client, settings_with_key):
    # Saving the form without touching the admin field must not demand a
    # confirmation for a change that isn't happening.
    r = admin_client.put("/api/admin/settings", json=base_body(admin_username=ADMIN))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# The soft admin gate
# ---------------------------------------------------------------------------


# The ONE route under /api/admin that is deliberately ungated, with the
# reason recorded here so a future reader doesn't "fix" it. `claim` would
# work gated — an unclaimed install makes is_admin true for everyone — but
# a non-admin hitting it on a CLAIMED install would get "The Admin page is
# limited to Destin", which answers the wrong question. It answers 409 with
# a sentence naming the recovery path instead, and that behaviour is pinned
# by test_claim_is_refused_when_an_admin_exists below.
UNGATED_BY_DESIGN = {("POST", "/api/admin/claim")}


def _admin_routes() -> list[tuple[str, str]]:
    """Every registered /api/admin/* route, as (method, path) pairs.

    Enumerated from the app rather than hand-listed so a route added in a
    later task WITHOUT a gate fails this test instead of shipping open.
    """
    app = create_app(provider=StubSearchProvider(), ingest_worker=None)
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/admin"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            if (method, path) in UNGATED_BY_DESIGN:
                continue
            pairs.append((method, path))
    return sorted(pairs)


def test_claim_is_refused_when_an_admin_exists(analyst_client, settings_with_key):
    r = analyst_client.post("/api/admin/claim", json={"confirm": True})
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "An admin is already configured. To reset it, see 'If nobody can get "
        "into Admin' in the handbook."
    )
    reset_settings_cache()
    assert load_settings().admin_username == ADMIN


def test_claim_takes_the_seat_on_a_fresh_install(analyst_client):
    r = analyst_client.post("/api/admin/claim", json={"confirm": True})
    assert r.status_code == 200
    assert r.json() == {"admin_username": ANALYST}
    reset_settings_cache()
    assert load_settings().admin_username == ANALYST


def test_claim_requires_confirmation(analyst_client):
    r = analyst_client.post("/api/admin/claim", json={})
    assert r.status_code == 400
    reset_settings_cache()
    assert load_settings().admin_username == ""


def test_the_route_table_is_not_empty():
    # Guards the guard: if _admin_routes() ever returns nothing, the
    # parametrized gate test below would vacuously pass.
    assert _admin_routes()


@pytest.mark.parametrize("method,path", _admin_routes())
def test_every_admin_route_is_gated(analyst_client, settings_with_key, method, path):
    # Path params are filled with a throwaway value — the gate must fire
    # before the handler ever looks at them.
    concrete = path.replace("{name}", "snapshot-1").replace("{month}", "2026-07")
    r = analyst_client.request(method, concrete, json={})
    assert r.status_code == 403, f"{method} {concrete} returned {r.status_code}"
    assert r.json()["detail"] == (
        "The Admin page is limited to Destin. Ask them if you need "
        "something changed."
    )


def test_an_unclaimed_install_lets_anyone_in(analyst_client):
    # Fresh install: no settings.json at all, so admin is claimable and the
    # gate must not lock the first user out of configuring the app.
    r = analyst_client.get("/api/admin/settings")
    assert r.status_code == 200
    assert r.json()["admin_username"] == ""


def test_the_gate_names_the_actual_admin(analyst_client):
    save_settings(Settings(admin_username="Someone-Else"))
    reset_settings_cache()
    r = analyst_client.get("/api/admin/settings")
    assert r.status_code == 403
    assert "Someone-Else" in r.json()["detail"]
