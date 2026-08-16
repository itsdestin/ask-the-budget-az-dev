"""The office's own agency list, and the picker that merges it with the
shipped catalog.

WHAT THIS PROTECTS. `samples/entity-catalog.yaml` holds 157 agencies and
ships read-only inside the office bundle, so an agency created, merged or
renamed after Phase 0 has nowhere to be named. The upload page's agency
picker is the one place a document's title is not fully determined by its
type and year (~78 agency budget requests a year, all otherwise called
"FY 2027 Budget Request"), so a missing agency is a document that cannot
be named correctly.
"""
from __future__ import annotations

import json

import pytest

from store import office_agencies as oa


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """Point the module at a scratch data dir and clear its cache.

    Both halves matter: the module caches on (path, mtime, size), so a test
    that writes a file the previous test also wrote — same size, same
    coarse mtime — would read the previous test's parse.
    """
    monkeypatch.setattr(oa, "data_dir", lambda: tmp_path)
    oa.reset_office_agencies_cache()
    yield tmp_path / oa.OFFICE_AGENCIES_FILE
    oa.reset_office_agencies_cache()


def test_no_overlay_is_the_normal_silent_case(overlay, capsys):
    # Most offices never create one. It must not print, because a line on
    # stderr for the ordinary case trains everyone to ignore stderr.
    assert oa.load_office_agencies() == ()
    assert capsys.readouterr().err == ""


def test_the_shipped_catalog_is_offered_with_no_overlay_at_all(overlay):
    names = [a.name for a in oa.all_agencies()]
    assert len(names) > 100, "the 157-agency catalog should be the bulk of the list"
    assert all(a.source == "catalog" for a in oa.all_agencies())


def test_an_added_agency_joins_the_list_and_is_marked_as_the_office_s(overlay):
    oa.save_office_agencies(
        (oa.OfficeAgency(canonical_id="agency:office-x", name="Office of X"),)
    )
    rows = oa.all_agencies()
    mine = [a for a in rows if a.source == "office"]
    assert [a.name for a in mine] == ["Office of X"]
    # And it sorts AFTER the whole catalog, not into the middle of it.
    assert rows[-1].name == "Office of X"


def test_a_corrupt_overlay_costs_the_additions_and_not_the_catalog(overlay, capsys):
    # 🔴 The failure this degradation exists for: a torn file on the shared
    # drive must not empty the picker, because an empty picker makes the one
    # document type that needs it unsubmittable.
    overlay.write_text("{not json", encoding="utf-8")
    assert oa.load_office_agencies() == ()
    assert len(oa.all_agencies()) > 100
    assert "office_agencies" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["null", "[]", "5", '"a string"'])
def test_json_that_parses_but_is_not_an_object_degrades_too(overlay, body, capsys):
    # The store/documents.py lesson: `null` and `[]` parse fine and then
    # raise AttributeError on `.get`, which is not a JSONDecodeError and
    # escapes the obvious except clause.
    overlay.write_text(body, encoding="utf-8")
    assert oa.load_office_agencies() == ()
    assert capsys.readouterr().err != ""


def test_a_torn_row_costs_itself_and_not_the_file(overlay):
    overlay.write_text(
        json.dumps(
            {
                "added": [
                    None,
                    "a bare string",
                    {"name": "", "canonical_id": "agency:office-blank"},
                    {"name": "No id"},
                    {"canonical_id": "agency:office-ok", "name": "Office of OK"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert [a.name for a in oa.load_office_agencies()] == ["Office of OK"]


def test_a_duplicate_id_in_the_file_is_kept_once(overlay):
    overlay.write_text(
        json.dumps(
            {
                "added": [
                    {"canonical_id": "agency:office-x", "name": "First"},
                    {"canonical_id": "agency:office-x", "name": "Second"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert [a.name for a in oa.load_office_agencies()] == ["First"]


def test_agency_name_resolves_from_either_source(overlay):
    oa.save_office_agencies(
        (oa.OfficeAgency(canonical_id="agency:office-x", name="Office of X"),)
    )
    assert oa.agency_name("agency:office-x") == "Office of X"
    # A shipped one, taken from the catalog rather than hardcoded here.
    shipped = next(a for a in oa.all_agencies() if a.source == "catalog")
    assert oa.agency_name(shipped.canonical_id) == shipped.name
    assert oa.agency_name("agency:nope") is None
    assert oa.agency_name("") is None


def test_a_rewrite_by_another_machine_is_picked_up(overlay):
    # ~20 machines read this corpus off a shared drive; an admin adding an
    # agency on their PC must not require every other app to restart. The
    # cache is stamped on (path, mtime, size) for exactly this.
    oa.save_office_agencies(
        (oa.OfficeAgency(canonical_id="agency:office-a", name="Office of A"),)
    )
    assert [a.name for a in oa.load_office_agencies()] == ["Office of A"]

    overlay.write_text(
        json.dumps(
            {"added": [{"canonical_id": "agency:office-b", "name": "Office of Bee"}]}
        ),
        encoding="utf-8",
    )
    assert [a.name for a in oa.load_office_agencies()] == ["Office of Bee"]


def test_a_save_failure_raises_rather_than_vanishing(overlay, monkeypatch):
    # The admin route turns this into a visible error. A silent no-op save is
    # the worst outcome: the admin believes the agency is there and finds out
    # when somebody cannot file a document under it.
    def boom(*_a, **_k):
        raise OSError("share is read-only")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(OSError):
        oa.save_office_agencies(
            (oa.OfficeAgency(canonical_id="agency:office-x", name="X"),)
        )
