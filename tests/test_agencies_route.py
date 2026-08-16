"""The agency picker's list route and the admin's add/remove.

The read route is UNGATED on purpose — it feeds a picker on the upload page
that any analyst reaches, and the contents are a committed catalog plus
names an admin typed. Gating it would break the page for the people it is
for. The two write routes carry the same soft admin gate as every other
admin surface.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from store import office_agencies as oa


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(oa, "data_dir", lambda: tmp_path)
    oa.reset_office_agencies_cache()
    yield TestClient(create_app(ingest_worker=None))
    oa.reset_office_agencies_cache()


@pytest.fixture
def admin(client):
    """The same client, named for what it is doing.

    No gate is stubbed, deliberately. `require_admin` is bound into the
    route at import, so patching the admin module's attribute would do
    nothing and only LOOK like it had — and it is not needed: these run
    against a fresh tmp data dir with no settings.json, where the admin slot
    is unclaimed and the first caller is let in (see
    tests/test_admin_settings_route.py::test_an_unclaimed_install_lets_anyone_in).

    That the routes ARE gated on a claimed install is proved elsewhere and
    automatically: `_admin_routes()` in that same file enumerates every
    `/api/admin/*` path off the live app, so both routes below are already
    covered by its parametrized gate test without anything being added
    there.
    """
    return client


def test_the_list_is_readable_without_being_the_admin(client):
    r = client.get("/api/agencies")
    assert r.status_code == 200
    rows = r.json()["agencies"]
    assert len(rows) > 100
    assert {"canonical_id", "name", "source"} <= set(rows[0])
    assert all(row["source"] == "catalog" for row in rows)


def test_the_list_is_sorted_by_name_so_a_person_can_find_one(client):
    names = [r["name"].lower() for r in client.get("/api/agencies").json()["agencies"]]
    assert names == sorted(names)


def test_an_added_agency_appears_in_the_list_marked_as_the_office_s(admin):
    r = admin.post("/api/admin/agencies", json={"name": "Office of Made-Up Things"})
    assert r.status_code == 200, r.text
    added = r.json()["agency"]
    assert added["source"] == "office"
    assert added["canonical_id"] == "agency:office-office-of-made-up-things"

    rows = admin.get("/api/agencies").json()["agencies"]
    office = [row for row in rows if row["source"] == "office"]
    assert [row["name"] for row in office] == ["Office of Made-Up Things"]


def test_an_empty_name_is_refused(admin):
    assert admin.post("/api/admin/agencies", json={"name": "   "}).status_code == 422


def test_a_pasted_paragraph_is_refused_rather_than_becoming_a_title(admin):
    # Whatever is typed here ends up in a document's title, so the cap is
    # about what a title can be, not about storage.
    r = admin.post("/api/admin/agencies", json={"name": "x" * 200})
    assert r.status_code == 422
    assert "limit" in r.json()["detail"]


def test_an_agency_the_app_already_ships_is_refused_and_says_so(admin):
    shipped = next(
        row for row in admin.get("/api/agencies").json()["agencies"]
        if row["source"] == "catalog"
    )
    r = admin.post("/api/admin/agencies", json={"name": shipped["name"]})
    assert r.status_code == 409
    assert "ships with the app" in r.json()["detail"]


def test_a_duplicate_differing_only_in_case_or_spacing_is_refused(admin):
    # 🔴 The failure this prevents: two rows in the picker that LOOK
    # identical, and no way for the person uploading to tell which one the
    # last person used — which is exactly the free-text-Title problem the
    # picker replaces, re-created inside the picker.
    assert admin.post("/api/admin/agencies", json={"name": "Office of X"}).status_code == 200
    r = admin.post("/api/admin/agencies", json={"name": "  office   of  x "})
    assert r.status_code == 409


def test_an_added_agency_can_be_removed(admin):
    added = admin.post("/api/admin/agencies", json={"name": "Office of X"}).json()["agency"]
    assert admin.delete(f"/api/admin/agencies/{added['canonical_id']}").status_code == 200
    rows = admin.get("/api/agencies").json()["agencies"]
    assert all(row["source"] == "catalog" for row in rows)


def test_a_shipped_agency_cannot_be_removed(admin):
    shipped = next(
        row for row in admin.get("/api/agencies").json()["agencies"]
        if row["source"] == "catalog"
    )
    r = admin.delete(f"/api/admin/agencies/{shipped['canonical_id']}")
    assert r.status_code == 422
    # And it is still there.
    assert any(
        row["canonical_id"] == shipped["canonical_id"]
        for row in admin.get("/api/agencies").json()["agencies"]
    )


def test_removing_one_that_is_not_there_is_a_404_not_a_silent_success(admin):
    r = admin.delete("/api/admin/agencies/agency:office-never-existed")
    assert r.status_code == 404
