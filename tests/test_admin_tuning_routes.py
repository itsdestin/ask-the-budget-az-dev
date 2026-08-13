"""GET/PUT /api/admin/aliases — the admin's alias overlay (spec E1).

Two behaviours here are the reason the module exists, and both are SILENT
failures if they regress:

  - a validation gap lets a word into the overlay that misdirects every
    search containing it, and nothing in the app ever says so,
  - the disable list offers a checkbox that does nothing, so an admin
    switches a shorthand "off", watches it keep resolving, and stops
    trusting the page.

Fixture pattern copied from tests/test_admin_settings_route.py. The
admin-seat claim in `_isolated_share` is load-bearing: with no
`admin_username` on disk the seat is CLAIMABLE, `is_admin` answers True
for everyone, and the 403 test below would pass for the wrong reason.

No LanceDB, no ONNX: StubSearchProvider + ingest_worker=None. The agency
catalog is the real committed samples/entity-catalog.yaml — there is no
fixture catalog in this repo — so every id and alias used here is one
that really ships.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import Settings, reset_settings_cache, save_settings
from retrieval.query_agency import CURATED_ALIAS_AGENCIES, parse_query_agencies
from store.office_aliases import OfficeAliases, reset_office_aliases_cache

ADMIN = "Destin"
ANALYST = "analyst1"

# Real ids, verified present in samples/entity-catalog.yaml.
REV = "agency:rev"  # Revenue, Department of
ADE = "agency:ade"  # Education, Department of


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    reset_office_aliases_cache()
    # Claim the admin seat, or the gate is open to everyone — see the
    # module docstring.
    save_settings(Settings(admin_username=ADMIN))
    reset_settings_cache()
    yield
    reset_settings_cache()
    reset_office_aliases_cache()


@pytest.fixture
def admin_client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


@pytest.fixture
def analyst_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("JLBC_USER", ANALYST)
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def _put(client: TestClient, added: list[dict], disabled: list[str] | None = None):
    return client.put(
        "/api/admin/aliases", json={"added": added, "disabled": disabled or []}
    )


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_put_and_get_round_trip(admin_client):
    r = _put(admin_client, [{"alias": "tpt", "canonical_id": REV}])
    assert r.status_code == 200, r.text
    added = admin_client.get("/api/admin/aliases").json()["added"]
    assert [a["alias"] for a in added] == ["tpt"]
    assert added[0]["canonical_id"] == REV
    assert added[0]["agency_name"] == "Revenue, Department of"
    assert added[0]["added_by"] == ADMIN  # stamped server-side
    assert added[0]["added_at"]


def test_put_replaces_the_whole_list(admin_client):
    # Wholesale replace, never a per-key merge — a merge makes deleting an
    # alias impossible, which is the `user_limits` lesson.
    _put(admin_client, [{"alias": "tpt", "canonical_id": REV},
                        {"alias": "k12", "canonical_id": ADE}])
    _put(admin_client, [{"alias": "k12", "canonical_id": ADE}])
    added = admin_client.get("/api/admin/aliases").json()["added"]
    assert [a["alias"] for a in added] == ["k12"]


def test_existing_stamp_is_preserved_on_resave(admin_client):
    first = _put(admin_client, [{"alias": "tpt", "canonical_id": REV}]).json()["added"][0]
    again = _put(
        admin_client,
        [{"alias": "tpt", "canonical_id": REV}, {"alias": "k12", "canonical_id": ADE}],
    ).json()["added"]
    kept = next(a for a in again if a["alias"] == "tpt")
    fresh = next(a for a in again if a["alias"] == "k12")
    assert kept["added_at"] == first["added_at"]
    assert kept["added_by"] == first["added_by"]
    assert fresh["added_at"]


# ---------------------------------------------------------------------------
# Rejections — every one a plain sentence
# ---------------------------------------------------------------------------


def test_suppressed_word_is_rejected_with_a_reason(admin_client):
    r = _put(admin_client, [{"alias": "for", "canonical_id": REV}])
    assert r.status_code == 400
    assert "for" in r.json()["detail"]


def test_a_suppressed_word_cannot_be_smuggled_in_by_spelling(admin_client):
    # Validation runs on the SAME normalization the resolver applies, so
    # "For." is the same word as "for" here — otherwise the stoplist is a
    # formality anyone bypasses with a capital letter or a full stop.
    r = _put(admin_client, [{"alias": "For.", "canonical_id": REV}])
    assert r.status_code == 400


def test_ambiguous_word_is_rejected(admin_client):
    r = _put(admin_client, [{"alias": "des", "canonical_id": REV}])
    assert r.status_code == 400
    assert "des" in r.json()["detail"]


def test_unknown_agency_is_rejected_and_nothing_is_saved(admin_client):
    # An unknown id is NOT inert: it makes the match list non-empty so the
    # fuzzy tier never fires, and it reaches ranking as the only preferred
    # agency, penalising every chunk in the corpus.
    r = _put(admin_client, [{"alias": "zz9", "canonical_id": "agency:nope"}])
    assert r.status_code == 400
    assert "agency:nope" in r.json()["detail"]
    assert admin_client.get("/api/admin/aliases").json()["added"] == []


def test_collision_with_another_agencys_vocabulary_is_rejected(admin_client):
    # "adc" is Corrections' shorthand. Pointing it at Revenue would boost
    # two agencies under one word with no ambiguity machinery to notice.
    r = _put(admin_client, [{"alias": "adc", "canonical_id": REV}])
    assert r.status_code == 400
    assert "Corrections" in r.json()["detail"]


def test_the_same_agency_recorded_twice_is_not_a_collision(admin_client):
    # "dor" is agency:dor's slug, and agency:dor and agency:rev are ONE
    # agency the catalog recorded twice (both "Revenue, Department of").
    # Refusing this would print "'dor' already means Revenue, Department
    # of" to an admin who just asked for Revenue, Department of.
    r = _put(admin_client, [{"alias": "dor", "canonical_id": REV}])
    assert r.status_code == 200, r.text


def test_a_duplicate_row_is_rejected(admin_client):
    r = _put(admin_client, [{"alias": "tpt", "canonical_id": REV},
                            {"alias": "tpt", "canonical_id": ADE}])
    assert r.status_code == 400
    assert "tpt" in r.json()["detail"]


def test_a_blank_alias_is_rejected(admin_client):
    assert _put(admin_client, [{"alias": "   ", "canonical_id": REV}]).status_code == 400
    assert _put(admin_client, [{"alias": "!!!", "canonical_id": REV}]).status_code == 400


def test_a_pasted_paragraph_is_rejected(admin_client):
    r = _put(admin_client, [{"alias": "x" * 60, "canonical_id": REV}])
    assert r.status_code == 400
    assert "too long" in r.json()["detail"]


def test_the_saved_alias_is_the_string_search_will_look_for(admin_client):
    # Stored normalized, so what the admin typed and what the resolver
    # matches are the same string.
    r = _put(admin_client, [{"alias": "  TPT  ", "canonical_id": REV}])
    assert r.json()["added"][0]["alias"] == "tpt"


def test_two_char_alias_is_allowed_with_a_warning(admin_client):
    r = _put(admin_client, [{"alias": "xr", "canonical_id": REV}])
    assert r.status_code == 200, r.text
    assert r.json()["warnings"]
    assert "xr" in r.json()["warnings"][0]


# ---------------------------------------------------------------------------
# The shipped list — what an admin may switch off
# ---------------------------------------------------------------------------


def test_shipped_omits_aliases_that_a_disable_cannot_reach(admin_client):
    # THE DEFECT THIS GUARDS: disabling suppresses the ALIAS tier only. A
    # shipped alias that is also a name phrase is claimed one tier higher,
    # so the checkbox would silently do nothing. Proven live, not asserted
    # from a list.
    victim = "financial institutions"
    assert victim in CURATED_ALIAS_AGENCIES  # it really is shipped vocabulary
    still_resolves = parse_query_agencies(
        f"{victim} budget",
        office_aliases=OfficeAliases(disabled=frozenset({victim})),
    )
    assert still_resolves, "the premise changed — this alias is now disable-able"

    shipped = {row["alias"] for row in admin_client.get("/api/admin/aliases").json()["shipped"]}
    assert victim not in shipped
    # ...while a shorthand a disable DOES reach is still offered.
    assert not parse_query_agencies(
        "difi budget", office_aliases=OfficeAliases(disabled=frozenset({"difi"}))
    )
    assert "difi" in shipped


def test_shipped_omits_derived_slugs(admin_client):
    shipped = {row["alias"] for row in admin_client.get("/api/admin/aliases").json()["shipped"]}
    assert "rev" not in shipped  # a JLBC URL slug, not a reviewed shorthand
    assert "adc" not in shipped
    assert "doc" in shipped  # a reviewed acronym for the same agency


def test_shipped_rows_name_their_agency(admin_client):
    rows = admin_client.get("/api/admin/aliases").json()["shipped"]
    doc = next(r for r in rows if r["alias"] == "doc")
    assert doc["canonical_id"] == "agency:adc"
    assert doc["agency_name"] == "Corrections, State Department of"


def test_a_shipped_alias_can_be_disabled_and_comes_back(admin_client):
    r = _put(admin_client, [], ["DIFI"])  # normalized on the way in
    assert r.status_code == 200, r.text
    assert r.json()["disabled"] == ["difi"]
    assert admin_client.get("/api/admin/aliases").json()["disabled"] == ["difi"]


def test_disabling_something_that_is_not_offered_is_rejected(admin_client):
    r = _put(admin_client, [], ["financial institutions"])
    assert r.status_code == 400
    r = _put(admin_client, [], ["not-a-real-alias"])
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# The agency list the form needs
# ---------------------------------------------------------------------------


def test_get_lists_every_agency_for_the_picker(admin_client):
    agencies = admin_client.get("/api/admin/aliases").json()["agencies"]
    ids = {a["canonical_id"] for a in agencies}
    assert REV in ids and ADE in ids
    assert len(agencies) > 150
    assert all(a["name"] for a in agencies)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_non_admin_gets_403(analyst_client):
    assert analyst_client.get("/api/admin/aliases").status_code == 403
    assert _put(analyst_client, [{"alias": "tpt", "canonical_id": REV}]).status_code == 403
