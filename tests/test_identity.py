"""Who is this user, and are they the admin? (Plan 5 Task 1, spec S11.)

The gate is SOFT — `current_user()` is the OS username, which anyone can
override with JLBC_USER. These tests pin the bootstrap rule (an empty
`admin_username` is claimable, once) and the exact-match comparison,
because both are decisions a future reader would otherwise be tempted to
"fix" into something friendlier and wronger.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import identity
from app.identity import admin_claimable, current_user, is_admin
from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import Settings, reset_settings_cache, save_settings


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """Every test gets a throwaway share; nothing here touches a real one."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_current_user_prefers_env(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert current_user() == "analyst1"


def test_admin_matches_the_username_under_the_one_identity_rule():
    s = Settings(admin_username="Destin")
    assert is_admin(s, "Destin") is True
    # Folds now (spec U0). `%USERNAME%` reflects how the person typed it at
    # logon, so `destin` vs `Destin` was a real lockout mode with a real
    # break-glass file to recover from. Once the admin seat is set from a
    # dropdown of observed usernames, "two rows an admin typed" cannot happen.
    assert is_admin(s, "destin") is True
    assert is_admin(s, "destin2") is False


def test_unclaimed_admin_is_claimable_and_grants_access():
    s = Settings(admin_username="")
    assert admin_claimable(s) is True
    # WHY anyone is admin while unclaimed: a fresh install has no other path
    # to configuring the app. The claim is one-way and recorded.
    assert is_admin(s, "whoever") is True


def test_claimed_admin_is_not_claimable_by_others():
    s = Settings(admin_username="Destin")
    assert admin_claimable(s) is False
    assert is_admin(s, "someone-else") is False


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def test_me_reports_the_caller_and_their_admin_state(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "Destin")
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()

    body = _client().get("/api/me").json()

    assert body["user"] == "Destin"
    assert body["is_admin"] is True
    assert body["admin_username"] == "Destin"
    assert body["admin_claimable"] is False
    assert body["admin_reset_pending"] is False


def test_me_reports_a_non_admin_honestly(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()

    body = _client().get("/api/me").json()

    assert body["user"] == "analyst1"
    assert body["is_admin"] is False
    # The non-admin still learns WHO the admin is — that is the whole point
    # of surfacing it: "ask Destin to raise your limit" needs a name.
    assert body["admin_username"] == "Destin"
    assert body["admin_claimable"] is False


def test_me_reports_claimable_on_a_fresh_install(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "whoever")
    # No settings.json at all — the fresh-install case.
    body = _client().get("/api/me").json()

    assert body["admin_claimable"] is True
    assert body["is_admin"] is True
    assert body["admin_username"] == ""


def test_me_is_registered_before_the_spa_catch_all(monkeypatch):
    """The SPA fallback must not swallow /api/me.

    Route order in app/main.py is load-bearing (Ground truth 11): a router
    registered after `/{path:path}` never receives a request, and the symptom
    is HTML arriving where JSON was expected — which surfaces as an opaque
    "Unexpected token '<'" in the browser, not as a 404.
    """
    monkeypatch.setenv("JLBC_USER", "whoever")
    r = _client().get("/api/me")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


def test_me_registers_the_caller_in_the_roster(monkeypatch, tmp_path):
    from users import registry
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "dmoss")
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "Danielle Moss")
    registry.reset_roster_cache()
    with TestClient(create_app(provider=StubSearchProvider())) as client:
        body = client.get("/api/me").json()
    assert body["user"] == "dmoss"
    p = registry.read_person("dmoss")
    assert p is not None and p.display_name == "Danielle Moss"


def test_me_is_unaffected_when_the_roster_write_fails(monkeypatch, tmp_path, capsys):
    from users import registry
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "dmoss")

    def boom(*a, **k):
        raise OSError("share is read-only")

    monkeypatch.setattr(registry, "touch", boom)
    with TestClient(create_app(provider=StubSearchProvider())) as client:
        r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["user"] == "dmoss"
    assert "share is read-only" in capsys.readouterr().err
