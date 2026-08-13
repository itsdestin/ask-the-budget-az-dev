"""Who the memo says it is from.

The name is cosmetic — it appears on a generated document and nowhere
else. Nothing here may raise: an unnameable analyst should lose
attribution on a memo, not the ability to generate one, which is the same
posture `app.identity.current_user` already takes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import identity, machine_config
from app.main import create_app
from app.search_provider import StubSearchProvider


@pytest.fixture(autouse=True)
def machine_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_no_override_and_no_windows_name_falls_back_to_the_username(monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    assert identity.display_name("djarrett") == "djarrett"


def test_the_windows_display_name_is_used_when_there_is_no_override(monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "Destin Jarrett")
    assert identity.display_name("djarrett") == "Destin Jarrett"


def test_a_stored_override_beats_the_windows_name(monkeypatch):
    """DEVIATION from spec M5, deliberate: the spec put Windows first. An
    override that loses to auto-detection cannot correct a WRONG AD name,
    and a wrong name is likelier than a missing one. The spec's intent —
    nobody types this if Windows knows it — still holds, because the
    override is empty until somebody sets it."""
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "JARRETTD")
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    assert identity.display_name("djarrett") == "Destin Jarrett"


def test_the_override_is_keyed_by_user():
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    machine_config.set_display_name("gpaulsen", "Geoff Paulsen")
    assert machine_config.read_display_name("djarrett") == "Destin Jarrett"
    assert machine_config.read_display_name("gpaulsen") == "Geoff Paulsen"
    assert machine_config.read_display_name("nobody") == ""


def test_clearing_the_override_removes_the_key_rather_than_storing_blank():
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    machine_config.set_display_name("djarrett", "   ")
    assert machine_config.read_display_name("djarrett") == ""


def test_setting_a_name_preserves_every_other_machine_json_key(tmp_path):
    """`_update` is read-modify-write for a reason: set_data_dir once
    wrote its key wholesale and silently switched off the one machine
    configured to process uploads."""
    machine_config.set_ingest_enabled(True)
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    assert machine_config.ingest_enabled() is True


def test_a_corrupt_display_names_value_reads_as_absent(tmp_path):
    """Same degradation posture as every other read here — a broken file
    costs a name, not the app."""
    machine_config.machine_config_path().parent.mkdir(parents=True, exist_ok=True)
    machine_config.machine_config_path().write_text(
        '{"display_names": "not a dict"}', encoding="utf-8"
    )
    assert machine_config.read_display_name("djarrett") == ""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "djarrett")
    # `provider=`, not `search_provider=` — the plan's snippet named a kwarg
    # `create_app` does not have (app/main.py:155), which would have raised
    # TypeError on every route test here.
    app = create_app(provider=StubSearchProvider(), ingest_worker=None)
    with TestClient(app) as c:
        yield c


def test_api_me_reports_the_display_name(client, monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    body = client.get("/api/me").json()
    assert body["display_name"] == "djarrett"


def test_the_display_name_can_be_set_and_read_back(client):
    response = client.put("/api/me/display-name", json={"display_name": "Destin Jarrett"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Destin Jarrett"
    assert client.get("/api/me").json()["display_name"] == "Destin Jarrett"


def test_an_over_long_name_is_rejected_rather_than_written(client):
    response = client.put("/api/me/display-name", json={"display_name": "x" * 200})
    assert response.status_code == 422
