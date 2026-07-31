"""Usage endpoints (Plan 5 Task 7, spec S19).

Two endpoints, deliberately different in who may call them:

  - `/api/admin/usage` is the office-wide breakdown, admin-gated,
  - `/api/me/usage` is the caller's OWN numbers and is NOT gated — an
    analyst has to be able to see what they have spent and why they are
    blocked without asking anyone.

The property this file exists to protect: neither endpoint re-derives
policy. `check_limit()` already encodes all of S19 (custom-endpoint
inactivity, the exempt list, per-user overrides, `<= 0` meaning "block
outright", the 80% warn boundary and the exact wording). These routes
read config and report; a second implementation of the resolution is how
the composer and the admin page end up disagreeing about whether someone
is blocked.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    reset_settings_cache,
    save_settings,
)
from store.config import data_dir

ADMIN = "Destin"
ANALYST = "analyst1"
MONTH = "2026-07"


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    yield
    reset_settings_cache()


def configure(**overrides) -> None:
    settings = Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        tiers={"standard": TierConfig(model="vendor/standard"),
               "deep_research": TierConfig(model="vendor/deep")},
        admin_username=ADMIN,
        **overrides,
    )
    save_settings(settings)
    reset_settings_cache()


def write_rows(rows: list[dict], shard: str = MONTH) -> None:
    path = data_dir() / "usage" / f"usage-{shard}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


ROWS = [
    {"user": ANALYST, "tier": "standard", "model": "m1", "tokens_in": 1000,
     "tokens_out": 100, "cost_usd": 0.10, "cached_tokens": 800},
    {"user": ANALYST, "tier": "standard", "model": "m1", "tokens_in": 1000,
     "tokens_out": 100, "cost_usd": None},          # custom endpoint (S15)
    {"user": ADMIN, "tier": "deep_research", "model": "m2", "tokens_in": 500,
     "tokens_out": 50, "cost_usd": 0.50, "cached_tokens": 0},
]


@pytest.fixture
def admin_client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


@pytest.fixture
def analyst_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("JLBC_USER", ANALYST)
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


# ---------------------------------------------------------------------------
# GET /api/admin/usage
# ---------------------------------------------------------------------------


def test_usage_returns_all_three_breakdowns(admin_client):
    configure()
    write_rows(ROWS)

    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()

    assert body["month"] == MONTH
    assert body["total_usd"] == 0.60
    assert body["rows"] == 3
    assert body["rows_with_unknown_cost"] == 1
    assert body["tokens_in"] == 2500
    assert body["cached_tokens"] == 800

    by_user = {g["key"]: g for g in body["by_user"]}
    assert set(by_user) == {ANALYST, ADMIN}
    assert by_user[ANALYST]["cost_usd"] == 0.10
    assert by_user[ANALYST]["rows_with_unknown_cost"] == 1
    assert {g["key"] for g in body["by_model"]} == {"m1", "m2"}
    assert {g["key"] for g in body["by_tier"]} == {"standard", "deep_research"}


def test_the_office_total_never_lies_by_omission(admin_client):
    """`total_usd` EXCLUDES unknown-cost rows and says how many there were.

    Treating an unrecorded cost as $0 would understate office spend with
    no visible sign it happened — which is exactly the number an admin
    would be budgeting against.
    """
    configure()
    write_rows(ROWS)
    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()
    assert body["total_usd"] == 0.60          # not 0.60-plus-a-guess
    assert body["rows_with_unknown_cost"] == 1


def test_usage_defaults_to_the_current_arizona_month(admin_client):
    from datetime import datetime, timedelta, timezone

    configure()
    now = datetime.now(timezone(timedelta(hours=-7)))
    write_rows(ROWS, shard=f"{now.year:04d}-{now.month:02d}")

    body = admin_client.get("/api/admin/usage").json()

    assert body["month"] == f"{now.year:04d}-{now.month:02d}"
    assert body["rows"] == 3


def test_a_month_with_no_usage_is_zeros_not_an_error(admin_client):
    configure()
    body = admin_client.get("/api/admin/usage?month=2019-01").json()
    assert body["total_usd"] == 0
    assert body["rows"] == 0
    assert body["by_user"] == []


def test_a_malformed_month_is_rejected(admin_client):
    configure()
    r = admin_client.get("/api/admin/usage?month=July")
    assert r.status_code == 400
    assert r.json()["detail"] == "Pick a month in YYYY-MM form, like 2026-07."


def test_limits_are_active_when_a_limit_is_configured(admin_client):
    configure(default_monthly_limit_usd=25.0)
    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()
    assert body["limits_active"] is True
    assert body["limits_inactive_reason"] is None


def test_limits_are_inactive_on_a_custom_endpoint(admin_client):
    """S15/S19: there is nothing numeric to compare against a dollar limit.

    The reason string is `check_limit`'s own `reason` field, NOT a
    sentence re-derived here — the whole point is that one module owns
    the policy.
    """
    configure(default_monthly_limit_usd=25.0)
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-test", provider="custom",
                                base_url="https://example.test/v1"),
        admin_username=ADMIN,
        default_monthly_limit_usd=25.0,
    ))
    reset_settings_cache()

    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()

    assert body["limits_active"] is False
    assert body["limits_inactive_reason"] == "custom endpoint"


def test_limits_stay_active_when_the_admin_exempts_themselves(admin_client):
    """"Are limits doing anything?" is about the office, not the reader.

    An admin who puts themselves on the exempt list — an entirely normal
    thing to do — must not see "limits inactive" and conclude nobody in
    the office is capped.
    """
    configure(default_monthly_limit_usd=25.0, exempt_users=[ADMIN])

    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()

    assert body["limits_active"] is True
    assert body["limits_inactive_reason"] is None


def test_limits_are_inactive_when_none_is_configured(admin_client):
    configure()
    body = admin_client.get(f"/api/admin/usage?month={MONTH}").json()
    assert body["limits_active"] is False
    # "nobody set one" and "they can't work here" are different facts and
    # the admin page says which it is.
    assert body["limits_inactive_reason"] == "no limit"


# ---------------------------------------------------------------------------
# GET /api/me/usage
# ---------------------------------------------------------------------------


def test_me_usage_is_not_admin_gated(analyst_client):
    configure(default_monthly_limit_usd=25.0)
    write_rows(ROWS)

    r = analyst_client.get("/api/me/usage")

    assert r.status_code == 200
    body = r.json()
    # Only their OWN rows — an analyst must not be able to browse a
    # colleague's spend from an ungated endpoint.
    assert body["month_usd"] == 0.10
    assert body["limit_usd"] == 25.0
    assert body["status"] == "allowed"
    assert body["rows_with_unknown_cost"] == 1
    assert "by_user" not in body


def test_me_usage_returns_the_ledgers_exact_blocked_sentence(analyst_client):
    configure(user_limits={ANALYST: 0.05})
    write_rows(ROWS)

    body = analyst_client.get("/api/me/usage").json()

    assert body["status"] == "blocked"
    # The ledger's wording verbatim. A re-typed copy here would give the
    # office two subtly different "you're over your limit" messages, and
    # the one in the composer is the one people would quote back.
    assert body["message"] == (
        "You've reached your monthly AI usage limit ($0.05) — ask Destin "
        "to raise it."
    )


def test_me_usage_warns_at_the_ledgers_boundary(analyst_client):
    configure(user_limits={ANALYST: 0.11})   # $0.10 spent = 90%
    write_rows(ROWS)

    body = analyst_client.get("/api/me/usage").json()

    assert body["status"] == "warn"
    assert body["message"] and "0.10" in body["message"]


def test_me_usage_reports_an_exemption_as_a_reason(analyst_client):
    configure(default_monthly_limit_usd=1.0, exempt_users=[ANALYST])
    write_rows(ROWS)

    body = analyst_client.get("/api/me/usage").json()

    assert body["status"] == "allowed"
    assert body["limit_usd"] is None
    assert body["reason"] == "exempt"


def test_me_usage_on_a_fresh_install_is_zeros(analyst_client):
    body = analyst_client.get("/api/me/usage").json()
    assert body["month_usd"] == 0
    assert body["status"] == "allowed"
    assert body["message"] is None
