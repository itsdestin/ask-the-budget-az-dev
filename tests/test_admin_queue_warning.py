""""Nobody is processing uploads" (Session B's app-requirement #1, half two).

The per-machine `ingest_enabled` flag defaults to OFF because one bundle
goes on all ~20 office PCs. That default re-creates the exact silent
failure the one-bundle decision was made to avoid: uploads queue on the
share and nothing ever drains them, with no error anywhere.

So the flag is only half the fix. The admin page has to SAY SO — out
loud, in the plain-English register the rest of that page uses, and only
when it is actually true.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import (
    ProviderConfig,
    Settings,
    reset_settings_cache,
    save_settings,
)
from ingest.jobs import advance, new_job, save

ADMIN = "Destin"


@pytest.fixture(autouse=True)
def _share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    monkeypatch.delenv("JLBC_INGEST_ENABLED", raising=False)
    reset_settings_cache()
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        admin_username=ADMIN,
    ))
    reset_settings_cache()
    yield tmp_path
    reset_settings_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def _queue_one(state: str = "queued"):
    job = new_job(
        doc_id="d1", title="A book", corpus="budget",
        source_path="x.pdf", source_sha256="a" * 64, publisher="jlbc",
        doc_type="baseline-per-agency", fiscal_year=2027,
    )
    save(job)
    if state == "failed":
        # The queue refuses to fail a job without a reason — "a failed
        # upload with no reason gives the user nothing to act on".
        advance(job, "failed", error="MinerU gave up on page 3")
    elif state != "queued":
        advance(job, state)
    return job


def _corpus(client) -> dict:
    return client.get("/api/admin/corpus").json()


# ---------------------------------------------------------------------------
# When it fires
# ---------------------------------------------------------------------------


def test_warns_when_jobs_are_queued_and_no_machine_is_draining(client):
    body = _corpus(client)

    assert body["ingest_enabled_here"] is False

    _queue_one()
    body = _corpus(client)

    assert body["queue_stalled"] is True
    assert body["queue_stalled_message"]


def test_the_message_names_the_fix_not_the_symptom(client):
    """A non-technical admin has to be able to ACT on it. "No worker
    running" is a symptom; "open the app on the computer that should do
    this and turn it on" is an instruction."""
    _queue_one()
    message = _corpus(client)["queue_stalled_message"]

    assert "no computer is set to process them" in message.lower()
    assert "Process uploads on this computer" in message
    assert "Admin" in message


# ---------------------------------------------------------------------------
# When it must NOT fire — a warning that cries wolf gets ignored
# ---------------------------------------------------------------------------


def test_silent_when_the_queue_is_empty(client):
    """No uploads waiting is not a problem, even with ingest off here.
    Nineteen of the twenty office PCs are in exactly this state all day."""
    body = _corpus(client)

    assert body["queue_stalled"] is False
    assert body["queue_stalled_message"] is None


def test_silent_on_the_machine_that_IS_the_ingest_machine(client, monkeypatch):
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "1")
    _queue_one()

    body = _corpus(client)

    assert body["ingest_enabled_here"] is True
    assert body["queue_stalled"] is False


def test_silent_when_something_is_already_running(client):
    """A job in flight proves SOME machine is draining the queue, even
    though it isn't this one. Warning here would send an admin to fix a
    thing that is working."""
    _queue_one("extracting")

    body = _corpus(client)

    assert body["queue_stalled"] is False


def test_a_failed_job_alone_does_not_trigger_it(client):
    """Failures are their own signal with their own UI. This warning is
    specifically about work nobody will ever pick up."""
    _queue_one("failed")

    body = _corpus(client)

    assert body["queue_stalled"] is False


# ---------------------------------------------------------------------------
# Turning it on from the admin page
# ---------------------------------------------------------------------------


def test_the_admin_can_turn_this_machine_on(client):
    r = client.post("/api/admin/machine/ingest", json={"enabled": True})

    assert r.status_code == 200
    assert r.json()["ingest_enabled_here"] is True
    assert _corpus(client)["ingest_enabled_here"] is True


def test_the_admin_can_turn_it_off_again(client):
    client.post("/api/admin/machine/ingest", json={"enabled": True})
    client.post("/api/admin/machine/ingest", json={"enabled": False})

    assert _corpus(client)["ingest_enabled_here"] is False


def test_the_response_says_a_restart_is_needed(client):
    """The worker starts in the lifespan hook, so flipping this at runtime
    cannot start one in the process already running. Saying so beats an
    admin watching a queue that never moves and concluding it is broken."""
    body = client.post("/api/admin/machine/ingest", json={"enabled": True}).json()

    assert "restart" in body["message"].lower()


def test_the_switch_is_admin_gated(client, monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    fresh = TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))

    r = fresh.post("/api/admin/machine/ingest", json={"enabled": True})

    assert r.status_code == 403


def test_turning_ingest_on_does_not_wipe_the_data_dir_pointer(client, tmp_path):
    """Both live in machine.json. A wholesale write here would strand the
    machine on the repo default and look like a lost corpus."""
    from app.machine_config import read_data_dir, set_data_dir

    set_data_dir(str(tmp_path / "share"))
    client.post("/api/admin/machine/ingest", json={"enabled": True})

    assert str(read_data_dir()) == str(tmp_path / "share")
