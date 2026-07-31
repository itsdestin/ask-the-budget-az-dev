"""Break-glass admin reset (Plan 5 Task 13).

Task 1 makes `admin_username` a one-way claim, which is right — but every
one-way door needs a documented way back through. The realistic lockouts
are mundane and ALL of them are permanent without this:

  * the admin transfers to a mistyped username (`destin` vs `Destin` —
    matching is exact, deliberately),
  * the admin leaves and IT deletes their Windows account,
  * IT changes the username format office-wide,
  * somebody hand-edits `settings.json` and breaks it.

In every case the result is an app nobody can configure, on a share
nobody can fix, with no error explaining what happened. There is no
vendor to call.

TIER 2 — the reset file — is the primary recovery and grants NO new
power: anyone who can create `RESET-ADMIN.txt` in the data folder can
already open `settings.json` in Notepad and edit it. It adds convenience,
not access. Do not "harden" it into uselessness.

The two properties that must not regress:

  * IT FAILS OPEN. A corrupt settings file already degrades to "admin
    claimable"; that stays, because the alternative is a file nobody can
    fix locking out the only person who could fix it.
  * IT PRESERVES THE CORRUPT BYTES. They may hold the only recoverable
    copy of the API key, and the app's own fail-open behaviour would
    otherwise eat the evidence.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.identity import (
    RESET_FILENAME,
    admin_claimable,
    admin_reset_pending,
    claim_admin,
    is_admin,
    reset_file_path,
)
from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.notices import read_notices
from harness.settings import (
    ProviderConfig,
    Settings,
    load_settings,
    reset_settings_cache,
    save_settings,
    settings_path,
)
from store.config import data_dir


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "Jen")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path


def touch_reset() -> None:
    reset_file_path().touch()
    reset_settings_cache()


# ---------------------------------------------------------------------------
# The reset file
# ---------------------------------------------------------------------------


def test_reset_file_unclaims_a_configured_admin(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    assert admin_claimable(load_settings()) is False

    (tmp_data_dir / RESET_FILENAME).touch()

    assert admin_claimable(load_settings()) is True
    assert is_admin(load_settings(), "anyone") is True


def test_the_reset_file_is_named_exactly_what_the_handbook_says():
    # The handbook tells a non-technical reader to create this file by name
    # in File Explorer. A rename here silently invalidates those steps.
    assert RESET_FILENAME == "RESET-ADMIN.txt"
    assert reset_file_path() == data_dir() / "RESET-ADMIN.txt"


def test_admin_reset_pending_reports_the_file(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    assert admin_reset_pending() is False
    touch_reset()
    assert admin_reset_pending() is True


def test_claiming_consumes_the_reset_file_and_leaves_a_record(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    touch_reset()

    claim_admin("Jen")

    # RENAMED, not deleted: the file is the only evidence that an admin
    # takeover happened out-of-band, and silently deleting it would erase
    # the one trace anyone could audit later.
    assert not (tmp_data_dir / RESET_FILENAME).exists()
    assert list(tmp_data_dir.glob("RESET-ADMIN.done-*.txt"))
    reset_settings_cache()
    assert load_settings().admin_username == "Jen"
    assert any(n["kind"] == "admin_claimed" for n in read_notices())


def test_the_notice_names_who_claimed_and_what_they_replaced(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    touch_reset()

    claim_admin("Jen")

    notice = next(n for n in read_notices() if n["kind"] == "admin_claimed")
    assert "Jen" in notice["message"]
    assert "Destin" in notice["message"]


def test_a_second_claim_needs_a_second_reset_file(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    touch_reset()
    claim_admin("Jen")
    reset_settings_cache()

    # The file was used up. Without a new one this is a claimed install
    # again — otherwise one reset would leave admin permanently open.
    assert admin_claimable(load_settings()) is False
    with pytest.raises(PermissionError):
        claim_admin("Someone-Else")


def test_claiming_an_unclaimed_install_needs_no_reset_file(tmp_data_dir):
    # The fresh-install path from Task 1 still works and consumes nothing.
    claim_admin("Jen")
    reset_settings_cache()
    assert load_settings().admin_username == "Jen"
    assert not list(tmp_data_dir.glob("RESET-ADMIN.done-*.txt"))


def test_readonly_share_still_allows_the_claim(tmp_data_dir, monkeypatch, capsys):
    """A share that has gone read-only must not turn a recoverable lockout
    into a permanent one.

    The claim proceeds; the failure to consume the file is logged loudly
    rather than raised.
    """
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    touch_reset()

    real_replace = __import__("os").replace

    def refuse_rename(src, dst, *args, **kwargs):
        if RESET_FILENAME in str(src):
            raise PermissionError("share is read-only")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("os.replace", refuse_rename)

    claim_admin("Jen")

    reset_settings_cache()
    assert load_settings().admin_username == "Jen"
    assert "reset file" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Corrupt settings: fail open, preserve the bytes
# ---------------------------------------------------------------------------


def test_corrupt_settings_fails_open_and_preserves_the_original(tmp_data_dir):
    settings_path().write_text("{ this is not json", encoding="utf-8")
    reset_settings_cache()

    assert admin_claimable(load_settings()) is True  # fail OPEN, not locked

    claim_admin("Jen")

    # The corrupt bytes may still contain a recoverable API key. Overwriting
    # them without a copy would destroy the ONLY path back to it — the app's
    # own fail-open behaviour would eat the evidence.
    preserved = list(tmp_data_dir.glob("settings.json.corrupt-*"))
    assert preserved and "not json" in preserved[0].read_text(encoding="utf-8")


def test_the_preserved_copy_keeps_a_recoverable_key(tmp_data_dir):
    # The realistic shape: valid-ish JSON broken by a hand edit, with the
    # key still sitting in it in plain text.
    settings_path().write_text(
        '{"provider": {"api_key": "sk-or-v1-secret"} ,,,}', encoding="utf-8"
    )
    reset_settings_cache()

    claim_admin("Jen")

    preserved = list(tmp_data_dir.glob("settings.json.corrupt-*"))
    assert "sk-or-v1-secret" in preserved[0].read_text(encoding="utf-8")


def test_a_second_corruption_does_not_overwrite_the_first_copy(tmp_data_dir):
    settings_path().write_text("{ first corruption", encoding="utf-8")
    reset_settings_cache()
    save_settings(Settings(admin_username="A"))

    settings_path().write_text("{ second corruption", encoding="utf-8")
    reset_settings_cache()
    save_settings(Settings(admin_username="B"))

    preserved = sorted(p.read_text(encoding="utf-8") for p in
                       tmp_data_dir.glob("settings.json.corrupt-*"))
    # Two distinct copies. Overwriting the first would destroy the older
    # key — which is the one more likely to still be valid.
    assert len(preserved) == 2
    assert "first corruption" in " ".join(preserved)
    assert "second corruption" in " ".join(preserved)


def test_a_healthy_settings_file_is_never_copied(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    save_settings(Settings(admin_username="Jen"))
    # Otherwise every admin-page save would litter the share with copies.
    assert list(tmp_data_dir.glob("settings.json.corrupt-*")) == []


def test_saving_over_a_missing_file_is_not_a_corruption(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    assert list(tmp_data_dir.glob("settings.json.corrupt-*")) == []


# ---------------------------------------------------------------------------
# Through the HTTP surface
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def test_me_reports_a_pending_reset(client, tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    assert client.get("/api/me").json()["admin_reset_pending"] is False

    touch_reset()

    body = client.get("/api/me").json()
    assert body["admin_reset_pending"] is True
    assert body["admin_claimable"] is True
    # And the app must let them in, or the reset would be a file that does
    # nothing.
    assert body["is_admin"] is True


def test_claiming_through_the_route_consumes_the_file(client, tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    touch_reset()

    r = client.post("/api/admin/claim", json={"confirm": True})

    assert r.status_code == 200
    assert r.json() == {"admin_username": "Jen"}
    assert not (tmp_data_dir / RESET_FILENAME).exists()
    assert list(tmp_data_dir.glob("RESET-ADMIN.done-*.txt"))


def test_the_admin_page_still_loads_with_corrupt_settings(client, tmp_data_dir):
    """The whole point of failing open.

    A broken settings file is exactly when someone needs to reach the page
    that fixes it.
    """
    settings_path().write_text("{ broken", encoding="utf-8")
    reset_settings_cache()

    r = client.get("/api/admin/settings")

    assert r.status_code == 200
    assert r.json()["admin_username"] == ""
