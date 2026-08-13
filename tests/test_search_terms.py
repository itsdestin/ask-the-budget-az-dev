"""Per-document search terms for the Budget Documents filter box.

Typing "dema" or "ema" returns 0 documents without these; both are already
reviewed vocabulary (a curated alias in samples/entity-catalog.yaml, and the
agency's own JLBC URL slug). See
docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md.
"""
from __future__ import annotations

import pytest

from app.search_terms import (
    load_agency_catalog_by_slug,
    _catalog_by_slug_cached,
    _doc_type_forms,
    search_terms,
)
from store.office_aliases import OfficeAlias, OfficeAliases


def test_a_per_agency_document_carries_its_slug_and_reviewed_aliases():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert "ema" in terms      # the JLBC URL slug
    assert "dema" in terms     # the reviewed alias — what an analyst says


def test_a_document_carries_its_type_shorthand_bare_and_year_prefixed():
    terms = search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)
    # Bare forms filter too (Destin, 2026-08-11): "pick 2026 in the rail,
    # type br".
    assert {"br", "baseline", "26br", "26baseline"} <= set(terms)


def test_the_budget_bill_gets_no_type_shorthand():
    assert search_terms("jlbc-budget-bill-fy2026", "budget-bill", 2026) == []


def test_a_raw_slug_doc_type_gets_no_type_shorthand():
    # s-pdf/bd-pdf/topic-pdf have no curated family and no shorthand.
    assert search_terms("jlbc-s-fy2027-01", "s-pdf", 2027) == []


def test_suppressed_and_ambiguous_aliases_never_become_terms():
    # "for" is Forestry's slug and SUPPRESSED; "bar" is the Board of Barbers'
    # and AMBIGUOUS. Both are ordinary English before they are agencies, and
    # both were measured against 247,607 tokens of real budget prose.
    assert "for" not in search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "bar" not in search_terms("jlbc-baseline-fy2026-bar", "baseline-per-agency", 2026)


def test_the_carve_out_survives_suppression():
    # D7: the lists were measured against document PROSE. In a box labelled
    # "Agency or keyword", "dot" is as unambiguous as "dema".
    #
    # The two arrive by different routes, verified against the catalog
    # 2026-08-11: "dot" IS Transportation's slug, while "doc" is a reviewed
    # ALIAS on Corrections, whose slug is "adc". Hence the two doc_ids.
    assert "dot" in search_terms("jlbc-baseline-fy2026-dot", "baseline-per-agency", 2026)
    assert "doc" in search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)


def test_an_alias_survives_its_agencys_slug_being_suppressed():
    # Forestry's slug "for" is SUPPRESSED, but its reviewed alias "dffm" is on
    # no list. The agency stays findable by the acronym an analyst actually
    # types — suppression removes a STRING, not an agency.
    terms = search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "for" not in terms
    assert "dffm" in terms


def test_an_ambiguous_agency_contributes_nothing():
    # agency:gov is demoted across every tier in retrieval — in a budget
    # question "the Governor" names a document or an actor far more often
    # than the Office of the Governor's own budget.
    assert "gov" not in search_terms("jlbc-baseline-fy2026-gov", "baseline-per-agency", 2026)


def test_an_unknown_trailing_segment_yields_no_agency_terms():
    # The FY2005-2012 sub-unit pages (adeassis, axsacute) have no catalog
    # entry. They must still list, and still match by title — their titles
    # ARE the slug uppercased.
    terms = search_terms("jlbc-approps-fy2005-adeassis", "approps-per-agency", 2005)
    assert "adeassis" not in terms
    assert "05ar" in terms  # the type shorthand still applies


def test_the_year_prefixed_form_stops_below_the_conventions_floor():
    # The shorthand is a 20xx-only convention (see _SHORTHAND_MIN_YEAR).
    terms = search_terms("jlbc-baseline-fy1998-adc", "baseline-per-agency", 1998)
    assert "98br" not in terms
    assert "br" in terms  # the bare form is ours and has no such floor


def test_a_missing_fiscal_year_still_yields_the_bare_form():
    terms = search_terms("jlbc-baseline-adc", "baseline-per-agency", None)
    assert "br" in terms
    assert not any(t[0].isdigit() for t in terms)


def test_terms_are_lowercase_sorted_and_unique():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert terms == sorted(set(terms))
    assert all(t == t.lower() for t in terms)


def test_an_unreadable_catalog_degrades_to_no_agency_terms(monkeypatch):
    # Same failure posture as budget_doc_ids: never take the page down.
    #
    # Adapted 2026-08-11 (review fix): the guard used to wrap the whole of
    # `load_agency_catalog_by_slug`, so patching that function to raise exercised it.
    # It now wraps only the catalog READ, which happens inside
    # `_catalog_by_slug_cached` (`load_agency_catalog`) — patching
    # `load_agency_catalog_by_slug` itself would bypass the guard entirely and just
    # assert monkeypatch works. Patch the loader it calls instead.
    #
    # `_catalog_by_slug_cached` is `lru_cache(maxsize=1)` — process-wide, not
    # per test — so a successful call from an earlier test would otherwise
    # short-circuit ours (never reaching the patched loader), and a
    # successful call from THIS test would otherwise leave every later test
    # reading an empty catalog. Clear before (force a fresh call through the
    # patch) and after (don't leak that to whatever runs next), in a
    # finally so a failed assertion still cleans up.
    def boom(*_a, **_kw):
        raise OSError("catalog unreadable")

    monkeypatch.setattr("chunking.agency_catalog.load_agency_catalog", boom)
    _catalog_by_slug_cached.cache_clear()
    try:
        terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    finally:
        _catalog_by_slug_cached.cache_clear()
    assert "ema" not in terms
    assert "26ar" in terms  # the type shorthand needs no catalog


def test_a_renamed_agency_entry_field_raises_instead_of_degrading(monkeypatch):
    # The whole point of the narrowed guard (app/search_terms.py, 2026-08-11
    # review fix): a field renamed on `AgencyEntry` is a programming bug, not
    # an unreadable catalog, and must raise loudly rather than silently
    # degrade to "no agency terms" for the entire corpus. Simulate the rename
    # with an object that has no `.slug` — same failure `entry.slug` would
    # hit if the real dataclass lost that field.
    class _RenamedEntry:
        pass

    def bad_catalog(*_a, **_kw):
        return {"whatever": _RenamedEntry()}

    monkeypatch.setattr("chunking.agency_catalog.load_agency_catalog", bad_catalog)
    _catalog_by_slug_cached.cache_clear()  # see the cache note above
    try:
        with pytest.raises(AttributeError):
            search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    finally:
        _catalog_by_slug_cached.cache_clear()


def test_a_mis_encoded_catalog_file_degrades_same_as_an_unreadable_one(monkeypatch):
    # 2026-08-11 review finding 4: `Path.read_text` raises `UnicodeDecodeError`
    # on a mis-encoded file, which is a `ValueError` subclass, NOT an
    # `OSError` — the pre-fix guard (`except (OSError, yaml.YAMLError)`)
    # missed this and would have 500'd the whole listing on bad bytes rather
    # than degrading like every other bad-catalog-FILE case.
    def boom(*_a, **_kw):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr("chunking.agency_catalog.load_agency_catalog", boom)
    _catalog_by_slug_cached.cache_clear()
    try:
        terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    finally:
        _catalog_by_slug_cached.cache_clear()
    assert "ema" not in terms
    assert "26ar" in terms  # the type shorthand needs no catalog


def test_a_failed_catalog_read_is_retried_not_permanently_cached(monkeypatch, capsys):
    # 2026-08-11 review finding 1: `_catalog_by_slug_cached` is
    # `lru_cache(maxsize=1)` and only reaches its `return` on a SUCCESSFUL
    # read (see that function's docstring) — a failed read raises out of it
    # instead, so lru_cache never memoizes the failure. Simulate a read that
    # fails once (a file lock, an AV scan) and then succeeds, and confirm the
    # SECOND call sees real agency terms again rather than replaying a
    # cached "catalog unreadable" forever.
    from chunking.agency_catalog import load_agency_catalog as real_load_agency_catalog

    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated transient lock")
        return real_load_agency_catalog(*a, **kw)

    monkeypatch.setattr("chunking.agency_catalog.load_agency_catalog", flaky)
    _catalog_by_slug_cached.cache_clear()
    try:
        # RED: the first call hits the simulated failure and degrades —
        # and says why on stderr, per the module's own convention.
        terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
        assert "ema" not in terms
        assert "app.search_terms: ignoring the agency catalog" in capsys.readouterr().err

        # GREEN: the second call is NOT served from a cached failure — it
        # retries `load_agency_catalog`, which now succeeds, so agency terms
        # are back to normal.
        terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
        assert "ema" in terms
        assert "dema" in terms
    finally:
        _catalog_by_slug_cached.cache_clear()


def test_every_emitted_term_is_lowercase_nonempty_and_whitespace_free():
    # 2026-08-11 review finding 5a: this is the ONLY test that runs real
    # `search_terms` output against the invariant the client actually
    # depends on. `webapp/src/pages/Search.tsx`'s `queryHit` lowercases the
    # QUERY but never `d.terms` — it matches by exact token equality — so an
    # uppercase or space-containing term would be one that can NEVER match,
    # and nothing before this test would fail when that happens. Iterates
    # every doc_type form and every real catalog entry, not a hand-picked
    # sample, per the review finding's own instruction.
    def _check(term: str) -> None:
        assert term == term.lower(), f"{term!r} is not already lowercase"
        assert term, "search_terms must never emit an empty string"
        assert not any(ch.isspace() for ch in term), f"{term!r} contains whitespace"

    for doc_type in _doc_type_forms():
        for term in search_terms("some-doc-id", doc_type, 2026):
            _check(term)

    # 2026-08-11 review finding 3 (second pass): the loop below builds each
    # doc_id as f"jlbc-baseline-fy2026-{slug}", but `_agency_terms` (same as
    # production) derives the agency from `doc_id.rsplit("-", 1)[-1]` — so a
    # HYPHENATED slug like "doa-apf" doesn't round-trip: the loop silently
    # exercises the wrong tail ("apf") for those. That is NOT a production
    # gap — `_agency_terms` uses the identical rsplit, so those aliases are
    # equally unreachable in real doc_ids — but the loop's per-term checks
    # below pass regardless, because every doc_type ALSO contributes type
    # shorthand ("26baseline", "26br", ...) independent of the agency
    # portion, so `terms` is non-empty even when the agency-specific portion
    # silently resolved nothing (or resolved the WRONG entry). A bare
    # `assert terms` per slug would therefore never catch a coverage
    # regression; asserting a known count is what makes the coverage
    # visible.
    #
    # Measured against this catalog (2026-08-11): of 145 slugs, the slug's
    # OWN string appears among its emitted terms for exactly 128. The other
    # 17 are the 4 hyphenated non-round-trippers ("doa-apf" and friends)
    # plus 13 deliberately suppressed/ambiguous slugs ("gov", "bar", "for",
    # ...) whose own slug is never meant to become a term. Pinning 128 is
    # what makes a FUTURE regression visible: if a currently-reachable slug
    # ever gains a hyphen (or the suppression lists grow), this count moves
    # and this assertion fails, where the un-pinned loop below would keep
    # silently passing on whatever it happens to reach.
    all_slugs = list(load_agency_catalog_by_slug())
    reachable = [
        slug
        for slug in all_slugs
        if slug
        in search_terms(f"jlbc-baseline-fy2026-{slug}", "baseline-per-agency", 2026)
    ]
    assert len(reachable) == 128, (
        f"{len(reachable)} of {len(all_slugs)} catalog slugs' own strings "
        "round-tripped through this loop (expected 128) — a slug's "
        "reachability changed; re-verify against the catalog before "
        "updating this number."
    )

    for slug in all_slugs:
        terms = search_terms(f"jlbc-baseline-fy2026-{slug}", "baseline-per-agency", 2026)
        for term in terms:
            _check(term)


def test_exec_terms_for_a_governors_budget_document():
    # 2026-08-11 review finding 5b: `exec` is the one new shorthand form
    # carrying an accepted risk (spec D9, "exec fires on ordinary prose") —
    # it had no terms-side test at all before this.
    terms = search_terms("ospb-exec-fy2027", "governors-budget", 2027)
    assert "exec" in terms
    assert "27exec" in terms


# --- admin alias overlay (spec E1) ------------------------------------------
#
# The filter box is the third consumer of store.office_aliases, after
# retrieval/query_agency.py. `agency:rev` is a real, verified catalog id
# (samples/entity-catalog.yaml:8345) but these tests pass a hand-built
# `catalog` dict directly, so the overlay logic under test never touches the
# real file.


def test_overlay_added_alias_becomes_a_search_term():
    catalog = {"rev": ("agency:rev", ("rev",))}
    overlay = OfficeAliases(added=(OfficeAlias("dor", "agency:rev", "", ""),))
    terms = search_terms(
        "jlbc-approps-fy2026-rev", "approps-per-agency", 2026, catalog=catalog, overlay=overlay
    )
    assert "dor" in terms


def test_overlay_disabled_alias_is_removed_from_terms():
    catalog = {"rev": ("agency:rev", ("rev", "dor"))}
    overlay = OfficeAliases(disabled=frozenset({"dor"}))
    terms = search_terms(
        "jlbc-approps-fy2026-rev", "approps-per-agency", 2026, catalog=catalog, overlay=overlay
    )
    assert "dor" not in terms and "rev" in terms


def test_overlay_alias_on_one_split_id_reaches_a_document_under_the_other():
    # IMPORTANT 1 (review): agency:dor and agency:rev are a real, grep-
    # verified split family — both "Revenue, Department of"
    # (samples/entity-catalog.yaml:8325 and :8345) — with distinct doc_id
    # slugs. The picker offers only agency:dor (app/routes/tuning.py's
    # _picker_agencies), so an admin saving "dor" as a shorthand is really
    # saving it against agency:dor. Before the group-expansion fix, a
    # document whose doc_id carries the OTHER member's slug ("-rev") never
    # picked that alias up at all — `added.get(canonical_id)` looked up
    # exactly the id on the overlay entry, with no group widening. This
    # uses the REAL catalog (no `catalog=` override) so the group lookup
    # exercises the genuine agency:dor/agency:rev split, not a hand-built one.
    overlay = OfficeAliases(added=(OfficeAlias("dor", "agency:dor", "", ""),))
    terms = search_terms(
        "jlbc-approps-fy2026-rev", "approps-per-agency", 2026, overlay=overlay
    )
    assert "dor" in terms


def test_overlay_cannot_resurrect_a_blocked_word():
    # The suppress/ambiguous lists still win: an admin alias spelled "for"
    # must not become a filter-box term even if the save-side validation is
    # somehow bypassed (hand-edited JSON on the share).
    catalog = {"rev": ("agency:rev", ("rev",))}
    overlay = OfficeAliases(added=(OfficeAlias("for", "agency:rev", "", ""),))
    terms = search_terms(
        "jlbc-approps-fy2026-rev", "approps-per-agency", 2026, catalog=catalog, overlay=overlay
    )
    assert "for" not in terms
