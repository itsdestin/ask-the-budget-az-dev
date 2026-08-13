"""The admin alias overlay in query resolution (spec E1).

THE ONE RULE THAT MAY NEVER WEAKEN: an overlay alias resolves WEAK, no
matter how unique, long, or plausible it is. EXACT becomes a hard filter,
a hard filter deletes every other agency from the page, and 'for' ->
Forestry already shipped that defect once. The guard here is structural —
it constructs the most EXACT-deserving aliases possible and asserts WEAK.

These tests use the REAL committed catalog (samples/entity-catalog.yaml),
because that is what `tests/test_query_agency.py` does — it never passes
`catalog_path=`, and there is no fixture catalog to reuse.
"""
import pytest

from retrieval.query_agency import parse_query_agencies
from retrieval.query_match import Confidence, is_filterable
from store.office_aliases import (
    OfficeAlias,
    OfficeAliases,
    reset_office_aliases_cache,
)


@pytest.fixture(autouse=True)
def _no_overlay_on_disk(monkeypatch, tmp_path):
    """Point the overlay's data dir at an empty tmp dir for every test here.

    WHY: `parse_query_agencies` now reads the overlay from the shared data
    dir when no overlay is passed. Without this, a dev box that happens to
    have an office-aliases.json would silently change the baseline calls
    below — the assertions would be measuring that machine, not the code.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_office_aliases_cache()
    yield
    reset_office_aliases_cache()


def _overlay(*pairs: tuple[str, str], disabled: frozenset[str] = frozenset()):
    return OfficeAliases(
        added=tuple(OfficeAlias(a, cid, "t", "now") for a, cid in pairs),
        disabled=disabled,
    )


# Every shape that earns EXACT somewhere in tiers 1-3: long and unique, a
# curated-alias spelling, a plain three-letter acronym at the length floor.
# All of them are still WEAK here, because the confidence is hardcoded
# rather than computed.
@pytest.mark.parametrize(
    "alias, query",
    [
        ("revenuedept", "revenuedept baseline"),
        # Long, multi-word, unmistakable — and deliberately built from words
        # no catalog name uses, so nothing but the overlay can claim it.
        ("the money collectors office", "the money collectors office fy2026"),
        ("rvq", "rvq baseline"),
    ],
)
def test_overlay_alias_resolves_weak_never_exact(alias, query):
    overlay = _overlay((alias, "agency:rev"))
    matches = parse_query_agencies(query, office_aliases=overlay)
    ours = [m for m in matches if m.value == "agency:rev"]
    assert ours and all(m.confidence is Confidence.WEAK for m in ours)
    # The consequence that actually matters: never a hard filter.
    assert not is_filterable(matches)


def test_overlay_never_downgrades_a_catalog_match():
    # A catalog name resolving EXACT must stay EXACT when an overlay alias
    # for the same agency also appears — first tier to name an agency owns it.
    overlay = _overlay(("revx", "agency:rev"))
    matches = parse_query_agencies(
        "revenue, department of revx", office_aliases=overlay
    )
    exact = [m for m in matches if m.confidence is Confidence.EXACT]
    assert any(m.value == "agency:rev" for m in exact)


def test_disabled_shipped_alias_stops_resolving():
    # `difi` resolves agency:dif EXACT through tier 3 today (verified by the
    # baseline assertion). Disabling it must remove it from the alias tier.
    baseline = parse_query_agencies("difi baseline")
    assert any(m.value == "agency:dif" for m in baseline)

    matches = parse_query_agencies(
        "difi baseline", office_aliases=_overlay(disabled=frozenset({"difi"}))
    )
    assert not any(
        m.value == "agency:dif" and m.matched_text == "difi" for m in matches
    )


def test_disabling_an_alias_does_not_hide_the_agency_by_name():
    # The escape hatch kills a SHORTHAND, never an agency: the NAME tier is
    # higher than the alias tier and is untouched by `disabled`.
    matches = parse_query_agencies(
        "insurance and financial institutions, department of",
        office_aliases=_overlay(disabled=frozenset({"difi", "dif"})),
    )
    assert any(
        m.value == "agency:dif" and m.confidence is Confidence.EXACT for m in matches
    )


def test_overlay_match_suppresses_fuzzy_tier():
    # An overlay hit counts as a match, so tier 4 (fuzzy) must not ALSO run
    # and drag in a guess — same rule as every other tier.
    # Baseline: this query reaches the fuzzy tier and guesses agency:wat.
    assert [m.value for m in parse_query_agencies("dorx water resorces department")] == [
        "agency:wat"
    ]

    overlay = _overlay(("dorx", "agency:rev"))
    matches = parse_query_agencies(
        "dorx water resorces department", office_aliases=overlay
    )
    assert [m.value for m in matches] == ["agency:rev"]


def test_none_means_load_from_disk_and_missing_file_changes_nothing(
    monkeypatch, tmp_path
):
    # Production callers pass nothing. With no overlay file on disk the
    # result is byte-identical to before this feature existed.
    import store.office_aliases as oa

    monkeypatch.setattr(oa, "office_aliases_path", lambda: tmp_path / "none.json")
    oa.reset_office_aliases_cache()
    with_none = parse_query_agencies("revenue, department of")
    explicit_empty = parse_query_agencies(
        "revenue, department of", office_aliases=OfficeAliases()
    )
    assert with_none == explicit_empty
    # A set, not a list: `_expand_group` returns a set, so the ORDER of a
    # duplicate group is not a promise this module makes (the existing suite
    # compares the same query as a set for the same reason).
    assert {m.value for m in with_none} == {"agency:dor", "agency:rev"}


def test_an_overlay_on_disk_is_picked_up_without_an_explicit_argument(tmp_path):
    # The admin saves under a running server: the overlay is read per call,
    # not baked into the lru-cached agency index.
    from store.office_aliases import save_office_aliases

    save_office_aliases(
        _overlay(("revenuedept", "agency:rev")),
        path=tmp_path / "office-aliases.json",
    )
    matches = parse_query_agencies("revenuedept baseline")
    assert [(m.value, m.confidence) for m in matches] == [
        ("agency:rev", Confidence.WEAK)
    ]


def test_overlay_alias_with_two_agencies_yields_both_sorted():
    # One overlay alias naming two agencies must resolve to BOTH ids, WEAK,
    # in sorted() order — pins `overlay_to_ids[alias]` multi-id handling and
    # the determinism comment on `sorted(overlay_to_ids[alias])` (same
    # rationale as the tiebreak comment in `_fuzzy_match`: a name two
    # agencies share must resolve the same way on every run, not on
    # set-iteration order).
    overlay = _overlay(("rvq", "agency:ema"), ("rvq", "agency:acc"))
    matches = parse_query_agencies("rvq baseline", office_aliases=overlay)
    assert [(m.value, m.confidence) for m in matches] == [
        ("agency:acc", Confidence.WEAK),
        ("agency:ema", Confidence.WEAK),
    ]


def test_overlay_alias_colliding_with_catalog_alias_does_not_downgrade_or_duplicate():
    # An overlay alias spelled exactly like a shipped catalog alias must not
    # downgrade the catalog's EXACT match to WEAK, nor add a second entry for
    # the same agency. Tier 3 runs before the overlay tier, and `_add`'s
    # "first tier to name an agency owns it" dedupe does the rest — the
    # overlay's own scan still finds "difi" (both tiers scan the same query),
    # but `agency:dif` is already `seen` by the time it gets there.
    overlay = _overlay(("difi", "agency:dif"))
    matches = parse_query_agencies("difi baseline", office_aliases=overlay)
    dif_matches = [m for m in matches if m.value == "agency:dif"]
    assert len(dif_matches) == 1
    assert dif_matches[0].confidence is Confidence.EXACT


def test_alias_in_both_added_and_disabled_does_not_resolve():
    # The admin's own addition, switched off, must not resolve. `disabled`
    # is checked while building `overlay_to_ids`, before the overlay's scan
    # even runs, so an alias in both lists behaves as "off", not as a race
    # between the two.
    overlay = _overlay(("zqx", "agency:ema"), disabled=frozenset({"zqx"}))
    matches = parse_query_agencies("zqx baseline", office_aliases=overlay)
    assert not any(m.value == "agency:ema" for m in matches)


def test_two_agency_outcome_one_exact_one_overlay_weak():
    # A query that already resolves one agency EXACT through the catalog,
    # plus an overlay alias for a SECOND, unrelated agency, must yield BOTH:
    # the catalog agency keeping EXACT, the overlay agency at WEAK. This
    # test exists to make a future change to that outcome — e.g. widening
    # ever suppressing the catalog match, or the overlay ever inheriting
    # EXACT — a DELIBERATE edit to this test rather than a silent behavior
    # change nothing else here would catch.
    overlay = _overlay(("zqy", "agency:acc"))
    matches = parse_query_agencies(
        "insurance and financial institutions, department of zqy",
        office_aliases=overlay,
    )
    assert {(m.value, m.confidence) for m in matches} == {
        ("agency:dif", Confidence.EXACT),
        ("agency:acc", Confidence.WEAK),
    }
