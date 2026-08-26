"""GET /api/admin/users — the People panel's one payload (spec U8, U12, U14).

The route JOINS three sources — roster files, the month's ledger rows,
and settings.json — under the ONE identity rule (U0). The join is what the
tests here are about: a limit stored as DMOSS must land on the dmoss row,
spend ledgered under two spellings must sum onto one row, and a stored key
that matches nobody must appear NOWHERE (Destin: the orphan notice was
"wasteful and confusing").
"""
from __future__ import annotations

import json
import stat

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import ProviderConfig, Settings, TierConfig, reset_settings_cache, save_settings
from store.config import data_dir
from users import registry

ADMIN = "Destin"
MONTH = "2026-08"


@pytest.fixture(autouse=True)
def share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    registry.reset_roster_cache()
    yield tmp_path
    reset_settings_cache()
    registry.reset_roster_cache()


def configure(**over) -> None:
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        tiers={"standard": TierConfig(model="vendor/standard")},
        admin_username=ADMIN, default_monthly_limit_usd=40.0, **over,
    ))
    reset_settings_cache()


def ledger(rows: list[dict]) -> None:
    path = data_dir() / "usage" / f"usage-{MONTH}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def row(user: str, cost: float) -> dict:
    return {"user": user, "tier": "standard", "model": "m", "tokens_in": 1, "tokens_out": 1, "cost_usd": cost}


@pytest.fixture
def client():
    return TestClient(create_app(provider=StubSearchProvider()))


def test_non_admins_get_403(client, monkeypatch):
    configure()
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert client.get(f"/api/admin/users?month={MONTH}").status_code == 403


def test_the_join_lands_a_differently_cased_limit_and_spend_on_one_row(client):
    """G-U2's server half."""
    configure(user_limits={"DMOSS": 25.0})
    registry.touch("dmoss", windows_name="Danielle Moss")
    ledger([row("dmoss", 10.0), row("DMOSS", 4.2)])
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body["unreachable"] is False
    [p] = body["people"]
    assert p["username"] == "dmoss"
    assert p["display_name"] == "Danielle Moss"
    assert p["spent_usd"] == 14.2
    assert p["limit"] == {"kind": "custom", "amount": 25.0, "collision": []}


def test_a_stored_key_matching_nobody_appears_nowhere(client):
    """Spec U14 as Destin settled it: not a row, not a warning, not a count."""
    configure(user_limits={"tmartin": 50.0}, exempt_users=("ghost",), hidden_users=("nobody",))
    registry.touch("dmoss")
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert [p["username"] for p in body["people"]] == ["dmoss"]
    assert "tmartin" not in json.dumps(body)
    assert "ghost" not in json.dumps(body)


def test_two_stored_spellings_are_reported_as_a_collision(client):
    configure(user_limits={"dmoss": 25.0, "DMOSS": 60.0})
    registry.touch("dmoss")
    [p] = client.get(f"/api/admin/users?month={MONTH}").json()["people"]
    assert p["limit"]["kind"] == "custom"
    assert p["limit"]["amount"] == 25.0  # exact match wins (U0)
    assert sorted(p["limit"]["collision"]) == ["DMOSS", "dmoss"]


def test_exempt_and_hidden_fold(client):
    configure(exempt_users=("DIRECTOR",), hidden_users=("PCHEN",))
    registry.touch("director")
    registry.touch("pchen")
    people = {p["username"]: p for p in client.get(f"/api/admin/users?month={MONTH}").json()["people"]}
    assert people["director"]["limit"] == {"kind": "exempt", "amount": None, "collision": []}
    assert people["pchen"]["hidden"] is True
    assert people["director"]["hidden"] is False


def test_default_limit_has_no_amount(client):
    configure()
    registry.touch("dmoss")
    [p] = client.get(f"/api/admin/users?month={MONTH}").json()["people"]
    assert p["limit"] == {"kind": "default", "amount": None, "collision": []}


def test_sorted_by_spend_descending(client):
    configure()
    for u in ("a", "b", "c"):
        registry.touch(u)
    ledger([row("b", 9.0), row("c", 1.0)])
    names = [p["username"] for p in client.get(f"/api/admin/users?month={MONTH}").json()["people"]]
    assert names == ["b", "c", "a"]


def test_a_torn_row_is_counted_not_dropped_silently(client):
    configure()
    registry.touch("dmoss")
    (registry.users_dir() / "torn.json").write_text("{", encoding="utf-8")
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body["unreadable"] == 1
    assert len(body["people"]) == 1


def test_an_unreadable_folder_is_unreachable_not_empty(client, share):
    """G-U3's server half: a prober-shaped failure production can produce."""
    configure()
    d = registry.users_dir()
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        body = client.get(f"/api/admin/users?month={MONTH}").json()
    finally:
        d.chmod(stat.S_IRWXU)
    assert body["unreachable"] is True
    assert body["people"] == []


def test_a_fresh_install_is_empty_and_reachable(client):
    configure()
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body == {"month": MONTH, "unreachable": False, "unreadable": 0, "people": []}


def test_a_bad_month_is_a_400(client):
    configure()
    assert client.get("/api/admin/users?month=nope").status_code == 400
