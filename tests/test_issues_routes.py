"""Issue report routes (spec E3).

Fixtures are defined locally, following the pattern in
tests/test_admin_settings_route.py — tests/test_admin_tuning_routes.py
(named in the task brief as the fixture source) does not exist in this
worktree; it is being built on a parallel track.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import Settings, reset_settings_cache, save_settings

ADMIN = "Destin"
ANALYST = "analyst1"


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    # Claim the admin seat explicitly. The bare _isolated_share pattern in
    # test_admin_settings_route.py leaves admin_username empty, which makes
    # is_admin() true for EVERYONE (an unclaimed install lets the first
    # person in) — fine for that file's gate-parity sweep, but it would make
    # test_patch_is_admin_only below vacuously pass (a non-admin who reads
    # as "admin" only because nobody has claimed the seat yet).
    save_settings(Settings(admin_username=ADMIN))
    reset_settings_cache()
    yield
    reset_settings_cache()


class _UserClient:
    """A TestClient pinned to one JLBC_USER, re-applied around every call.

    app.identity.current_user() reads JLBC_USER from the environment at
    REQUEST time, not at app-construction time. Several tests below build
    both admin_client and analyst_client and interleave calls through them
    in one test — with a plain monkeypatch.setenv per fixture (the pattern
    in tests/test_admin_settings_route.py) the two fixtures would fight
    over one process-wide env var, and whichever fixture's setup ran last
    would silently win identity for the rest of the test, for BOTH
    clients. Pinning the var immediately around each individual request is
    what lets the two clients coexist.
    """

    def __init__(self, client: TestClient, user: str) -> None:
        self._client = client
        self._user = user

    def _call(self, method: str, *args, **kwargs):
        previous = os.environ.get("JLBC_USER")
        os.environ["JLBC_USER"] = self._user
        try:
            return getattr(self._client, method)(*args, **kwargs)
        finally:
            if previous is None:
                os.environ.pop("JLBC_USER", None)
            else:
                os.environ["JLBC_USER"] = previous

    def get(self, *args, **kwargs):
        return self._call("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._call("post", *args, **kwargs)

    def patch(self, *args, **kwargs):
        return self._call("patch", *args, **kwargs)


@pytest.fixture
def admin_client() -> _UserClient:
    app = create_app(provider=StubSearchProvider(), ingest_worker=None)
    return _UserClient(TestClient(app), ADMIN)


@pytest.fixture
def analyst_client() -> _UserClient:
    app = create_app(provider=StubSearchProvider(), ingest_worker=None)
    return _UserClient(TestClient(app), ANALYST)


def _minimal_transcript_kwargs() -> dict:
    """Minimal valid harness.history.Transcript kwargs (harness/history.py:38-51).

    Only the five fields with no default: id, title, corpus, created_at,
    updated_at. The rest (version, title_is_manual, messages, message_count)
    all default.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "placeholder",
        "title": "a conversation",
        "corpus": "budget",
        "created_at": now,
        "updated_at": now,
    }


def test_analyst_can_submit_and_see_their_own(analyst_client):
    r = analyst_client.post("/api/issues", json={"description": "search broke"})
    assert r.status_code == 200
    listed = analyst_client.get("/api/issues").json()
    assert listed["reports"][0]["description"] == "search broke"
    assert listed["reports"][0]["status"] == "unresolved"


def test_empty_description_is_a_400(analyst_client):
    assert analyst_client.post("/api/issues", json={"description": "  "}).status_code == 400


def test_analyst_sees_only_their_own(analyst_client, admin_client):
    analyst_client.post("/api/issues", json={"description": "mine"})
    admin_client.post("/api/issues", json={"description": "admins own report"})
    mine = analyst_client.get("/api/issues").json()["reports"]
    assert [r["description"] for r in mine] == ["mine"]
    everyone = admin_client.get("/api/issues").json()["reports"]
    assert len(everyone) == 2


def test_an_analyst_sees_their_own_torn_report_as_a_visible_row(analyst_client):
    # THE DEFECT THIS GUARDS: an unreadable stub has no `submitted_by` to
    # match on, so the non-admin filter dropped it — the admin saw the row
    # and the person who FILED it did not, which is backwards for the one
    # person who needs to know their report never landed.
    from app.issue_reports import reports_dir

    analyst_client.post("/api/issues", json={"description": "fine"})
    (reports_dir() / "20260101T000000000000-deadbeef.json").write_text(
        "{torn", encoding="utf-8"
    )
    rows = analyst_client.get("/api/issues").json()["reports"]
    assert any(r.get("unreadable") for r in rows)
    assert any(r.get("description") == "fine" for r in rows)


def test_an_unreadable_share_says_so_instead_of_no_reports(analyst_client, monkeypatch):
    # The screens print "No reports yet" off an empty list. When the folder
    # can't be read, nobody knows whether it is empty — so the route says
    # "unreachable" and the list stays empty rather than being narrated.
    import app.routes.issues as issues_routes
    from app.issue_reports import ReportsUnavailable

    def boom() -> list[dict]:
        raise ReportsUnavailable("Permission denied")

    monkeypatch.setattr(issues_routes, "list_reports", boom)
    body = analyst_client.get("/api/issues").json()
    assert body["reports"] == [] and body["unreachable"] is True


def test_a_readable_share_is_not_flagged_unreachable(analyst_client):
    analyst_client.post("/api/issues", json={"description": "x"})
    assert analyst_client.get("/api/issues").json().get("unreachable") is None


def test_admin_resolves_with_a_note(analyst_client, admin_client):
    rid = analyst_client.post("/api/issues", json={"description": "x"}).json()["report"]["id"]
    r = admin_client.patch(f"/api/issues/{rid}",
                           json={"status": "resolved", "admin_note": "restarted it"})
    assert r.status_code == 200
    mine = analyst_client.get("/api/issues").json()["reports"][0]
    assert mine["status"] == "resolved" and mine["admin_note"] == "restarted it"


def test_patch_is_admin_only(analyst_client):
    assert analyst_client.patch("/api/issues/whatever", json={"status": "resolved"}).status_code == 403


def test_transcript_embeds_when_a_conversation_is_named(analyst_client, monkeypatch):
    # The history module is per-device local storage; fake its load.
    import app.routes.issues as issues_routes
    import harness.history as hh

    def fake_load(cid):
        assert cid == "conv-1"
        # Build the real dataclass so asdict() exercises the real shape.
        return hh.Transcript(**{**_minimal_transcript_kwargs(), "id": "conv-1"})

    monkeypatch.setattr(issues_routes, "_load_transcript", fake_load)
    r = analyst_client.post(
        "/api/issues", json={"description": "bad answer", "conversation_id": "conv-1"}
    )
    assert r.status_code == 200
    # Non-admin GET replaces the transcript body with a flag.
    mine = analyst_client.get("/api/issues").json()["reports"][0]
    assert mine.get("transcript_attached") is True and "transcript" not in mine


def test_unknown_conversation_is_a_400(analyst_client, monkeypatch):
    import app.routes.issues as issues_routes
    monkeypatch.setattr(issues_routes, "_load_transcript", lambda cid: None)
    r = analyst_client.post(
        "/api/issues", json={"description": "x", "conversation_id": "gone"}
    )
    assert r.status_code == 400
