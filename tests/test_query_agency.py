from retrieval.query_agency import AMBIGUOUS_ALIASES, parse_query_agencies
from retrieval.query_match import Confidence


def _ids(query):
    return [m.value for m in parse_query_agencies(query)]


def test_the_full_canonical_name_is_an_exact_match():
    ms = parse_query_agencies("corrections, state department of budget")
    assert ms[0].value == "agency:adc"
    assert ms[0].confidence is Confidence.EXACT


def test_a_partial_but_distinctive_name_resolves():
    assert "agency:adc" in _ids("corrections baseline")


def test_the_jlbc_slug_resolves_exactly():
    """JLBC's own URL shorthand: /26AR/adc.pdf"""
    ms = parse_query_agencies("adc baseline")
    assert ms[0].value == "agency:adc"
    assert ms[0].confidence is Confidence.EXACT


def test_a_stoplisted_alias_matches_but_only_weakly():
    """'doc' is both the Corrections acronym and an ordinary English word.
    It must still MATCH -- it just must not hard-filter."""
    assert "doc" in AMBIGUOUS_ALIASES
    ms = parse_query_agencies("doc baseline")
    assert [m.value for m in ms] == ["agency:adc"]
    assert ms[0].confidence is Confidence.WEAK


def test_an_alias_shared_by_two_agencies_is_weak():
    """Ambiguity is decided by the catalog, not by a hand-written list."""
    ms = parse_query_agencies("juvenile corrections")
    assert all(m.confidence is Confidence.WEAK for m in ms) or len(ms) == 1


def test_a_query_naming_no_agency_returns_nothing():
    assert parse_query_agencies("what changed since last year") == []


def test_an_empty_query_returns_nothing():
    assert parse_query_agencies("") == []
    assert parse_query_agencies("   ") == []


def test_matching_is_case_insensitive():
    assert _ids("AHCCCS baseline") == _ids("ahcccs baseline")


def test_a_short_token_does_not_fuzzy_match_everything():
    """rapidfuzz on 2-3 character tokens matches far too much. The floor
    exists so 'ar' does not resolve to 'Agriculture, Arizona Department of'.

    The plan wrote this agency's id as `agency:ada`; the real catalog id is
    `agency:agr` (verified against samples/entity-catalog.yaml), and asserting
    on an id no agency has would have passed vacuously forever.

    The bare-"ar" case is asserted as well because it is the one that actually
    exercises the floor: in "dema ar" the alias `dema` already resolves at a
    higher tier, so fuzzy matching never runs and the first assertion alone
    would prove nothing.
    """
    assert "agency:agr" not in _ids("dema ar")
    assert "agency:agr" not in _ids("ar")


def test_dema_resolves_to_emergency_and_military_affairs():
    """The motivating query: 'dema ar' returned mostly Attorney General."""
    assert "agency:ema" in _ids("dema ar")


def test_ahcccs_resolves():
    assert "agency:axs" in _ids("ahcccs baseline")


def test_a_slug_that_is_an_ordinary_english_word_cannot_hard_filter():
    """`for` is the JLBC slug for Forestry and Fire Management. It is also the
    commonest preposition in English, and Task 1 puts every slug into `aliases`
    unconditionally -- so without a stoplist entry the query "What deposit to
    the Hyperbaric Oxygen Therapy for Military Veterans Fund..." resolved to
    Forestry with EXACT confidence, which Task 6 turns into a HARD FILTER.

    Measured on the 47-query eval set before this guard: `for` hard-filtered 13
    of them onto Forestry. This is the plan's Risk #1 -- a confidently wrong
    agency -- reached through a slug rather than through a reviewed alias.
    """
    assert "for" in AMBIGUOUS_ALIASES
    ms = parse_query_agencies("funding for military veterans")
    assert all(m.confidence is Confidence.WEAK for m in ms)
    assert "agency:for" not in [
        m.value for m in ms if m.confidence is Confidence.EXACT
    ]


def test_the_real_forestry_name_still_resolves_exactly():
    """Stoplisting the slug must not cost the agency its real name -- the head
    phrase is a separate tier and is still unambiguous."""
    ms = parse_query_agencies("forestry and fire management wildfire funding")
    assert ms[0].value == "agency:for"
    assert ms[0].confidence is Confidence.EXACT


def test_a_four_letter_name_fragment_does_not_hard_filter():
    """'Fire' is the head of 'Fire, Building and Life Safety, Department of'.
    At a 4-character floor it hard-filtered a question about the Prison
    Construction and Operations Fund -- which happens to mention "Fire and Life
    Safety Upgrades" -- onto that department, deleting every other agency from
    an answer that was not about it.

    The floor is the same one chunking/entity_stamper.py uses corpus-side.
    """
    ms = parse_query_agencies(
        "appropriations from the Prison Construction and Operations Fund and "
        "continuing authority for Fire and Life Safety Upgrades"
    )
    assert "agency:bfs" not in [
        m.value for m in ms if m.confidence is Confidence.EXACT
    ]


def test_the_full_fire_department_name_still_resolves():
    """The floor costs the fragment, never the real name.

    Spelled the way the catalog and the JLBC agency index spell it. The
    "Department of Fire, Building and Life Safety" form does NOT resolve
    exactly, because `_invert_comma_form` splits on the first comma only and
    a two-comma name inverts to the garbled "Building and Life Safety,
    Department of Fire" -- a chunking/entity_stamper.py limitation this module
    inherits rather than papers over.
    """
    ms = parse_query_agencies(
        "fire, building and life safety, department of inspections"
    )
    assert ms[0].value == "agency:bfs"
    assert ms[0].confidence is Confidence.EXACT


def test_a_stripped_possessive_does_not_fuzzy_match_an_agency():
    """Normalization turns "Tucson's General Fund" into "tucson s general fund",
    and the orphaned "s" then formed the window "s general", which
    `token_set_ratio` scored above the floor against the Auditor General.

    A one-character token is punctuation debris, never agency evidence.
    """
    assert "agency:legaud" not in _ids(
        "What was the City of Tucson's General Fund ending balance in FY 2026?"
    )


def test_the_full_official_name_beats_a_fuzzy_neighbour():
    """'emergency and military affairs appropriations report' returned
    Agriculture at ranks 1, 2, 3 and 5 before this work."""
    assert _ids("emergency and military affairs appropriations report")[0] == "agency:ema"


# ---------------------------------------------------------------------------
# Duplicate catalog entries for ONE agency (found in review, 2026-08-02)
# ---------------------------------------------------------------------------


def test_one_agency_recorded_twice_still_hard_filters():
    """A duplicate catalog entry is a DEFECT, not ambiguity.

    Resolving to two ids used to downgrade the match to WEAK, so
    "revenue, department of" — an unmistakable agency name — lost its hard
    filter to a catalog bookkeeping problem.
    """
    ms = parse_query_agencies("revenue, department of")
    assert {m.value for m in ms} == {"agency:dor", "agency:rev"}
    assert all(m.confidence is Confidence.EXACT for m in ms)


def test_a_duplicate_group_is_filtered_as_one_agency():
    """Both ids are returned, not just the one whose name matched, because the
    duplicate ALSO splits the stamped chunks — Child Safety is spread across
    1,510 / 505 / 18 chunks on three live ids."""
    ids = set(_ids("child safety department"))
    assert {"agency:cs", "agency:dcs"} <= ids


def test_the_comma_inverted_form_joins_the_same_group():
    """The catalog writes this agency both ways round — "Child Safety,
    Department of" AND "Department of Child Safety" — so plain string equality
    would leave two groups where there is one agency."""
    from retrieval.query_agency import _logical_key

    assert _logical_key("Child Safety, Department of") == _logical_key(
        "Department of Child Safety"
    )


def test_asu_reaches_the_years_recorded_under_the_other_id():
    """agency:uniasu is FY2021-2027 and agency:uniasum is FY2015-2020 — one
    university either side of a JLBC naming change. An `asu` filter that
    returned only the first would silently hide six years of documents."""
    ms = parse_query_agencies("asu budget")
    assert {m.value for m in ms} == {"agency:uniasu", "agency:uniasum"}
    assert all(m.confidence is Confidence.EXACT for m in ms)


def test_genuinely_different_agencies_are_still_ambiguous():
    """The merge must not swallow real ambiguity: the Department of Education
    and the State Board of Education are two agencies, and a hard filter would
    pick a side and be wrong half the time."""
    ms = parse_query_agencies("education funding")
    assert {m.value for m in ms} == {"agency:ade", "agency:boe"}
    assert all(m.confidence is Confidence.WEAK for m in ms)


def test_the_aliases_approved_during_review_resolve():
    """Named by Destin during the 2026-08-02 catalog review. `adoa` in
    particular was DROPPED by the generator as colliding with Agriculture,
    which is a rule too blunt for a real-world acronym."""
    for alias, expected in [
        ("adoa budget", "agency:doa"),
        ("difi rates", "agency:dif"),
        ("dohs funding", "agency:hla"),
    ]:
        ms = parse_query_agencies(alias)
        assert [m.value for m in ms] == [expected], alias
        assert ms[0].confidence is Confidence.EXACT, alias
