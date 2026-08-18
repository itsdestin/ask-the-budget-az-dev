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
from chunking.agency_catalog import load_agency_catalog
from chunking.entity_stamper import _normalize_for_match
from retrieval.query_agency import CURATED_ALIAS_AGENCIES, _index, parse_query_agencies
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


def test_collision_with_a_catalog_name_phrase_is_rejected(admin_client):
    # "corrections" is agency:adc's own catalog name-head — it lives in
    # phrase_to_ids, NOT alias_to_ids, so the alias-only collision check
    # missed it entirely and let Revenue silently claim Corrections'
    # vocabulary. Verified live against samples/entity-catalog.yaml:
    # phrase_to_ids['corrections'] == {'agency:adc'}.
    r = _put(admin_client, [{"alias": "corrections", "canonical_id": REV}])
    assert r.status_code == 400
    assert "Corrections" in r.json()["detail"]
    assert admin_client.get("/api/admin/aliases").json()["added"] == []


def test_a_name_phrase_pointed_at_its_own_agency_is_allowed(admin_client):
    # "revenue" is a catalog name phrase too — phrase_to_ids['revenue'] ==
    # {'agency:dor', 'agency:rev'}, both "Revenue, Department of" recorded
    # twice (same logical_group). The phrase-collision fix must not turn
    # into a blanket rejection of an agency's own name phrase.
    r = _put(admin_client, [{"alias": "revenue", "canonical_id": REV}])
    assert r.status_code == 200, r.text


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
    # PIN THE CANDIDATE SET: this is the exact table _shipped_aliases()
    # excludes FROM. If a future edit narrows _shipped_aliases() back to
    # catalog-aliases-only, `victim` stops being an alias_to_ids member (or
    # starts looking like a derived slug) and this test must fail loudly —
    # not pass vacuously because the exclusion it's guarding became dead code.
    index = _index(None)
    assert victim in index.alias_to_ids
    slugs = {
        _normalize_for_match(entry.slug)
        for entry in load_agency_catalog().values()
        if entry.slug
    }
    assert victim not in slugs  # excluded for being a name phrase, not a slug
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
    # PIN THE CANDIDATE: `rev` must be a string the slug exclusion actually
    # REMOVED, not one that was never there. Without this the assertion below
    # passes just as happily if the slug exclusion is deleted and `rev` stops
    # being alias vocabulary at all — a vacuous guard. (Measured: 142 of the
    # 156 aliases the resolver knows are derived slugs.)
    assert "rev" in _index(None).alias_to_ids
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
    assert ADE in ids
    assert all(a["name"] for a in agencies)
    # EVERY real agency is still offered — one row per logical group, which
    # is fewer rows than the catalog has ids (see the dedupe test below) and
    # must never be fewer than the number of real agencies.
    index = _index(None)
    groups = {index.logical_group[cid] for cid in load_agency_catalog()}
    assert len(agencies) == len(groups)
    assert len(agencies) > 140


def test_the_picker_never_offers_two_rows_for_one_agency(admin_client):
    # THE DEFECT THIS GUARDS: the picker used to be `id_to_name()` verbatim,
    # so an admin choosing an agency saw "Revenue, Department of" twice with
    # nothing to tell the two apart — the catalog records that agency (and 6
    # other names, 15 ids in all) more than once. Picking the wrong half
    # cannot be seen, only measured later in worse answers.
    agencies = admin_client.get("/api/admin/aliases").json()["agencies"]
    names = [a["name"] for a in agencies]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, duplicates
    index = _index(None)
    groups = [index.logical_group.get(a["canonical_id"]) for a in agencies]
    assert len(groups) == len(set(groups))
    # The id offered is the catalog-order-first member of the group, which
    # is the one EntityStamper's first-wins name index stamps onto chunks
    # carrying that printed name.
    ids = {a["canonical_id"] for a in agencies}
    assert "agency:dor" in ids and "agency:rev" not in ids
    assert "agency:uniasu" in ids and "agency:uniasum" not in ids
    # The dropped id is still a legal thing to POST — the picker narrows what
    # is OFFERED, it does not narrow what the route accepts.
    assert _put(admin_client, [{"alias": "tpt", "canonical_id": REV}]).status_code == 200


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_non_admin_gets_403(analyst_client):
    assert analyst_client.get("/api/admin/aliases").status_code == 403
    assert _put(analyst_client, [{"alias": "tpt", "canonical_id": REV}]).status_code == 403


# ---------------------------------------------------------------------------
# Office guidance (spec E2) — GET/PUT /api/admin/guidance
# ---------------------------------------------------------------------------


def test_guidance_round_trip_and_meta(admin_client):
    r = admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    assert r.status_code == 200
    got = admin_client.get("/api/admin/guidance").json()
    assert got["text"] == "Prefer the AFR."
    assert got["edited_by"] and got["edited_at"]
    assert got["max_bytes"] == 8192


def test_guidance_over_cap_is_a_400_with_the_reason(admin_client):
    r = admin_client.put("/api/admin/guidance", json={"text": "x" * 9000})
    assert r.status_code == 400
    # The save's OWN sentence (harness/office_guidance.py), surfaced as-is —
    # "byte limit", not "limited". Asserting the substring that's actually
    # shipped, not rewriting the message to fit a different word.
    assert "byte limit" in r.json()["detail"]


def test_guidance_routes_are_admin_only(analyst_client):
    assert analyst_client.get("/api/admin/guidance").status_code == 403


def test_guidance_get_on_a_never_edited_install_has_no_none_fields(admin_client):
    # THE TRAP THIS GUARDS: load_guidance_meta() returns {} for a
    # never-edited install, while webapp/src/api.ts's AdminGuidance
    # declares edited_by/edited_at as REQUIRED strings, not optional ones.
    # _guidance_payload() covers the gap with meta.get(..., "") fallbacks —
    # a future "simplification" to meta["edited_by"] would either KeyError
    # or (with .get(key) and no default) ship `None` through JSON, breaking
    # the shipped TS contract silently on the very first admin visit. No
    # prior PUT here on purpose — every other guidance test PUTs before it
    # GETs, so none of them would ever notice this regressing.
    r = admin_client.get("/api/admin/guidance")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "text": "",
        "max_bytes": 8192,
        "edited_by": "",
        "edited_at": "",
    }


# ---------------------------------------------------------------------------
# The assistant's shipped instructions, read-only — GET /api/admin/prompt
# ---------------------------------------------------------------------------
#
# WHY this surface exists: the admin writes office guidance (above) blind.
# They cannot see the ~1,170 lines of instructions the assistant already
# has, so they duplicate them, contradict them, or spend the 8,192-byte cap
# restating something already said at length.
#
# THE TEST THAT MATTERS MOST here is
# `test_every_section_lands_in_a_named_group`. The page groups sections
# under plain-English labels from a hardcoded mapping. A section added to
# or renamed in harness/system-prompt.md would fall into the catch-all
# group — the admin would still see it, but under a label that says
# nothing. That must fail here rather than pass quietly.


def _prompt(client: TestClient, corpus: str = "budget"):
    return client.get(f"/api/admin/prompt?corpus={corpus}")


def _headings(body: dict) -> list[str]:
    return [s["heading"] for g in body["groups"] for s in g["sections"]]


def _rendered_headings(corpus: str) -> list[str]:
    """Every top-level heading the real prompt renders, fence-aware.

    NOTE what this can and cannot prove. It splits with the SAME `_scan`
    the route uses, so the equality it feeds only shows that `_grouped`
    dropped nothing — a SPLITTER that drops content is invisible to it,
    which is how the lead text went missing for a whole review cycle.
    `test_every_rendered_line_reaches_the_page` is the one that would
    catch that; this is the group-mapping check, nothing more.
    """
    from app.routes.tuning import _scan
    from harness.prompt import build_system_prompt

    return [
        h for h, _ in _scan(build_system_prompt(corpus=corpus, tier="standard"), 2)[1]
    ]


def _shown_lines(body: dict) -> set[str]:
    """Every non-blank line of text the page actually puts on screen.

    Headings arrive without their `##` markers, so they are added bare and
    the comparison below strips markers off the rendered side too.
    """
    out: set[str] = set()
    chunks = [body["lead"]]
    for group in body["groups"]:
        for section in group["sections"]:
            out.add(section["heading"])
            chunks.append(section["text"])
            for sub in section["subsections"]:
                out.add(sub["heading"])
                chunks.append(sub["text"])
    for chunk in chunks:
        out.update(line.strip() for line in chunk.splitlines() if line.strip())
    return out


@pytest.mark.parametrize("corpus", ["budget", "fiscal_notes"])
def test_every_section_lands_in_a_named_group(admin_client, corpus):
    """THE guard for this feature.

    Two ways the page can quietly stop being true: a section the mapping
    has never heard of (it lands in the catch-all and the admin reads it
    under a meaningless label), or a section that never reaches the page
    at all. Both are checked, with the admin's own guidance present so
    that section is covered too.
    """
    from app.routes.tuning import OTHER_GROUP

    admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    body = _prompt(admin_client, corpus).json()

    assert OTHER_GROUP not in [g["label"] for g in body["groups"]], [
        s
        for g in body["groups"]
        if g["label"] == OTHER_GROUP
        for s in [x["heading"] for x in g["sections"]]
    ]
    # Nothing dropped by the GROUPING either. See `_rendered_headings` for
    # why this half proves less than it looks like it does.
    assert sorted(_headings(body)) == sorted(_rendered_headings(corpus))


@pytest.mark.parametrize("corpus", ["budget", "fiscal_notes"])
def test_every_rendered_line_reaches_the_page(admin_client, corpus):
    """THE coverage guard: content, not heading names.

    The heading-list assertion above is built with the route's own
    splitter, so a splitter that silently drops text passes it — which is
    exactly what happened: everything above the first `##` (the document's
    own title line) never reached the page, and no test could see it.

    This compares LINES against the rendered prompt instead, so anything
    the page fails to carry — a lead, a section, a subsection body, the
    tail of a section cut short by a fence — shows up here by its own text.
    Order-independent on purpose: the page regroups the prompt.
    """
    from harness.prompt import build_system_prompt

    admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    rendered = build_system_prompt(corpus=corpus, tier="standard")
    shown = _shown_lines(_prompt(admin_client, corpus).json())

    missing = [
        line
        for raw in rendered.splitlines()
        if (line := raw.strip())
        # A heading arrives on the wire without its markers; a "#" line
        # inside a fenced example arrives verbatim. Accept either.
        and line not in shown
        and line.lstrip("#").strip() not in shown
    ]
    assert not missing, missing
    # And the lead specifically, because it is the one that was missing and
    # a set comparison would go quiet again the moment it is folded in.
    assert "# JLBC Search — assistant instructions" in shown


def test_an_unmapped_section_is_still_shown_rather_than_swallowed(admin_client):
    # Runtime posture, deliberately different from the test above: an
    # unknown heading must never VANISH from a read-only page an admin is
    # using to check what the assistant reads. It goes in the catch-all,
    # and the test above is what makes that state loud in CI.
    from app.routes import tuning

    body = tuning._grouped([("Brand new section", "body text")])
    assert [g["label"] for g in body] == [tuning.OTHER_GROUP]
    assert body[0]["sections"][0]["heading"] == "Brand new section"


def test_two_sections_sharing_a_heading_are_both_shown():
    # `_grouped` filters `sections` rather than looking each heading up,
    # precisely so a repeated heading cannot lose its second section. That
    # choice was argued for in a comment and pinned by nothing until the
    # 2026-08-12 review; a lookup-table rewrite would have passed the whole
    # suite while dropping instructions off a page whose only job is
    # showing them.
    from app.routes import tuning

    got = tuning._grouped([("Your role", "a"), ("Your role", "b")])
    rows = [s for g in got for s in g["sections"]]
    assert [s["heading"] for s in rows] == ["Your role", "Your role"]
    assert [s["text"] for s in rows] == ["a", "b"]


def test_no_heading_is_mapped_into_two_groups():
    # The other half of the same hazard: `_grouped` filters, so a heading
    # listed under two labels emits its section TWICE. The module asserts
    # this at import; this fails loudly under `python -O`, where asserts
    # are stripped.
    from app.routes.tuning import _GROUPS

    mapped = [h for _, headings in _GROUPS for h in headings]
    assert sorted(mapped) == sorted(set(mapped))


def test_groups_are_plain_english_and_ordered(admin_client):
    labels = [g["label"] for g in _prompt(admin_client).json()["groups"]]
    # Order is fixed by the mapping, not by render order — an admin looking
    # for the subject matter should not have to know it comes ninth.
    assert labels == [
        "What the assistant is, and how it decides",
        "How it writes an answer",
        "What it can look things up in",
        "Arizona budget background",
    ]


def test_the_middle_section_follows_the_chosen_documents(admin_client):
    budget = _headings(_prompt(admin_client, "budget").json())
    notes = _headings(_prompt(admin_client, "fiscal_notes").json())
    assert "Reading budget documents" in budget
    assert "Reading budget documents" not in notes
    assert "Reading fiscal notes" in notes


def test_subsections_are_carried_because_that_is_where_the_detail_lives(admin_client):
    body = _prompt(admin_client).json()
    sections = {s["heading"]: s for g in body["groups"] for s in g["sections"]}

    primer = sections["Domain primer — Arizona state budget"]
    subs = [s["heading"] for s in primer["subsections"]]
    # The tunable detail — an admin about to write "always prefer the AFR"
    # needs to see that the instructions already rank sources for that.
    assert "6. Why numbers don't reconcile across documents" in subs
    assert "1. Fiscal-year convention" in subs
    assert all(s["text"].strip() for s in primer["subsections"])

    reading = sections["Reading budget documents"]
    assert "Accuracy hierarchy for actuals" in [
        s["heading"] for s in reading["subsections"]
    ]


def test_the_admins_own_guidance_is_shown_and_marked(admin_client):
    before = _prompt(admin_client).json()
    assert before["office_guidance_present"] is False
    assert not any(
        s["is_office_guidance"] for g in before["groups"] for s in g["sections"]
    )

    admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    after = _prompt(admin_client).json()

    assert after["office_guidance_present"] is True
    mine = [s for g in after["groups"] for s in g["sections"] if s["is_office_guidance"]]
    assert len(mine) == 1, _headings(after)
    # Pins the heading this module hardcodes against the one
    # harness/office_guidance.py actually renders — a preamble edit there
    # would otherwise leave the admin's own block unmarked in the list.
    assert mine[0]["heading"] == "Office guidance from the administrator"
    assert "Prefer the AFR." in mine[0]["text"]
    assert [g["label"] for g in after["groups"]][-1] == "Your office's own guidance"


def test_the_office_block_really_does_render_mid_prompt(admin_client):
    """The claim the window's position note makes, checked against reality.

    The group above is shown LAST, which reads as "the assistant's final
    instruction" unless the page says otherwise — and it isn't: the
    `{{OFFICE_GUIDANCE}}` slot sits mid-template, and the refusal rules
    that the block's own preamble says outrank it render BELOW it. The
    window says so in words (SystemGuidance.tsx's GUIDANCE_POSITION_NOTE);
    this pins that those words stay true if the template is reordered.
    """
    from harness.prompt import build_system_prompt

    admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    rendered = build_system_prompt(corpus="budget", tier="standard")
    at = rendered.index("## Office guidance from the administrator")
    for later in (
        "## Refusal — three cases",
        "## Conversation flow",
        "## What goes into your final answer",
        "## Quick reference",
        "## Domain primer — Arizona state budget",
    ):
        assert rendered.index(later) > at, f"{later} no longer renders after the block"


def test_sizes_are_the_real_ones(admin_client):
    from harness.prompt import build_system_prompt

    rendered = build_system_prompt(corpus="budget", tier="standard")
    body = _prompt(admin_client).json()
    # The admin's 8,192-byte cap only reads as "a small addition to
    # something much larger" if these numbers are the real ones.
    assert body["total_lines"] == len(rendered.splitlines())
    # Bytes, not characters: the cap this number is shown beside is a byte
    # cap, and the prompt is full of em dashes at 3 bytes each.
    assert body["total_bytes"] == len(rendered.encode("utf-8"))
    assert body["total_bytes"] > len(rendered)
    # Only the totals ship. Per-section sizes were on the wire and rendered
    # nowhere (review, 2026-08-12); this keeps them from creeping back as
    # dead payload.
    assert "total_chars" not in body
    assert all(
        "chars" not in s and all("chars" not in sub for sub in s["subsections"])
        for g in body["groups"]
        for s in g["sections"]
    )


def test_an_unknown_document_set_is_a_plain_sentence(admin_client):
    r = admin_client.get("/api/admin/prompt?corpus=nonsense")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "nonsense" in detail
    assert detail.endswith(".")


def test_the_default_is_budget_documents(admin_client):
    assert admin_client.get("/api/admin/prompt").json()["corpus"] == "budget"


def test_the_viewer_is_read_only(admin_client):
    # No way to edit the shipped instructions from this surface, ever. The
    # GET is registered, so a PUT handler added here later would flip these
    # from 405 to 200 and fail.
    assert admin_client.put("/api/admin/prompt", json={}).status_code == 405
    assert admin_client.post("/api/admin/prompt", json={}).status_code == 405


def test_prompt_view_is_admin_only(analyst_client):
    assert analyst_client.get("/api/admin/prompt").status_code == 403


def test_reading_the_view_does_not_disturb_the_prompt(admin_client):
    # Spec E2's headline property: with no guidance file the rendered
    # prompt is byte-identical to before that feature existed. This page
    # only READS, so opening it must not perturb caches or the file.
    from harness.prompt import build_system_prompt

    before = build_system_prompt(corpus="budget", tier="standard")
    _prompt(admin_client)
    _prompt(admin_client, "fiscal_notes")
    assert build_system_prompt(corpus="budget", tier="standard") == before


# --- the splitter itself ----------------------------------------------------


def test_split_ignores_headings_inside_a_code_fence():
    # The template documents its own syntax in fenced examples, and a
    # fenced "## like this" must stay TEXT — otherwise the page invents a
    # section the assistant never reads as one.
    from app.routes.tuning import _scan

    text = "## Real\nbody\n```\n## Not a heading\n```\nmore\n## Second\ntail\n"
    assert [h for h, _ in _scan(text, 2)[1]] == ["Real", "Second"]
    assert "## Not a heading" in dict(_scan(text, 2)[1])["Real"]


def test_the_text_above_the_first_heading_is_kept_not_dropped():
    # The defect this pins: `_scan`'s lead was thrown away by the route, so
    # `# JLBC Search — assistant instructions` — which the assistant
    # really does read — never appeared on a page captioned as showing
    # everything it is told.
    from app.routes.tuning import _scan

    lead, parts = _scan("# Title\n\nOpening words.\n## First\nbody\n", 2)
    assert lead == "# Title\n\nOpening words."
    assert [h for h, _ in parts] == ["First"]


def test_a_fenced_example_never_cuts_a_section_short():
    # The bug this guards, found in self-review: taking the section's own
    # prose as `body[: body.index("### ")]` cuts at the first "### "
    # ANYWHERE, including inside a fenced example. The lines after it
    # belong to no part and no lead, so they vanish from a page whose
    # entire job is showing the whole of what the assistant reads.
    from app.routes.tuning import _section_payload

    body = (
        "Lead line.\n```\n### not a real part\n```\nStill lead.\n"
        "### Real part\ntail\n"
    )
    got = _section_payload("X", body)
    assert [s["heading"] for s in got["subsections"]] == ["Real part"]
    assert "Still lead." in got["text"]
    assert "### not a real part" in got["text"]
