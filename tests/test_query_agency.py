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

    Asserts the BEHAVIOUR rather than which list holds the slug. `for` began
    in AMBIGUOUS_ALIASES and was later escalated to SUPPRESSED_ALIASES; the
    property that matters -- it cannot hard-filter -- never changed, and a test
    pinned to the mechanism would have failed on an improvement.
    """
    from retrieval.query_agency import SUPPRESSED_ALIASES

    assert "for" in AMBIGUOUS_ALIASES | SUPPRESSED_ALIASES
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


# ---------------------------------------------------------------------------
# The aliases Destin approved by name, 2026-08-02. This is the WHOLE approved
# set — the 158 machine-drafted proposals are deliberately NOT applied.
# ---------------------------------------------------------------------------


def test_the_approved_alias_set_resolves_exactly():
    for query, expected in [
        ("nau budget", {"agency:uninau"}),
        ("asu budget", {"agency:uniasu", "agency:uniasum"}),
        ("adoa budget", {"agency:doa"}),
        ("dohs funding", {"agency:hla"}),
        ("dhs budget", {"agency:dhs"}),          # Health Services, via its slug
        ("difi rates", {"agency:dif"}),
        ("pio budget", {"agency:pio"}),
        ("aph budget", {"agency:pio"}),
    ]:
        ms = parse_query_agencies(query)
        assert {m.value for m in ms} == expected, query
        assert all(m.confidence is Confidence.EXACT for m in ms), query


def test_dhs_is_health_services_and_dohs_is_homeland_security():
    """One letter apart and easy to swap. The generator's own proposal for
    Homeland Security was `adhs`, which is one letter from Health Services'
    slug — which is exactly why `dohs` was approved instead."""
    assert _ids("dhs budget") == ["agency:dhs"]
    assert _ids("dohs funding") == ["agency:hla"]


def test_ua_names_both_university_of_arizona_lines():
    """No catalog entry is named plainly "University of Arizona": there is a
    Main Campus (959 chunks) and a Health Sciences Center (564), and unlike
    the ASU pair they run in PARALLEL every year FY2015-2027 — neither
    supersedes the other, so picking one would silently hide the other."""
    for query in ("ua budget", "university of arizona"):
        ms = parse_query_agencies(query)
        assert {m.value for m in ms} == {"agency:uniumain", "agency:uniuhsc"}, query
        assert all(m.confidence is Confidence.EXACT for m in ms), query


def test_a_two_letter_curated_alias_clears_the_length_floor():
    """`ua` is shorter than _MIN_EXACT_ALIAS_LEN. That floor exists to stop a
    MACHINE-derived alias filtering on a guess; a human approved this one."""
    from retrieval.query_agency import CURATED_ALIAS_AGENCIES, _MIN_EXACT_ALIAS_LEN

    assert len("ua") < _MIN_EXACT_ALIAS_LEN
    assert "ua" in CURATED_ALIAS_AGENCIES
    assert parse_query_agencies("ua budget")[0].confidence is Confidence.EXACT


def test_a_specific_name_beats_the_curated_umbrella():
    """Asking for one UA line by its full catalog name must not drag in the
    other. The umbrella phrase is a prefix of both lines' own names."""
    assert _ids("university of arizona - health sciences center budget") == [
        "agency:uniuhsc"
    ]
    assert _ids("university of arizona - main campus budget") == ["agency:uniumain"]


def test_no_unreviewed_alias_was_applied():
    """The 158 machine-drafted proposals stay in the review document until
    Destin approves them. A wrong alias under a hard filter sends a query
    confidently to the wrong agency — the reason the gate exists."""
    from chunking.agency_catalog import load_agency_catalog

    approved = {
        "doc", "dema", "adoa", "difi", "dohs", "asu", "nau", "aph",
        "dffm", "colleges",  # round 2 of the review, same day
    }
    for entry in load_agency_catalog().values():
        for alias in entry.aliases:
            # Every agency gets its own slug for free; anything else must be
            # on the approved list.
            assert alias == entry.slug or alias in approved, (
                f"{entry.canonical_id} carries unreviewed alias {alias!r}"
            )


# ---------------------------------------------------------------------------
# Alias review round 2 (Destin, 2026-08-02): suppressions and corrections
# ---------------------------------------------------------------------------


def test_a_subject_matter_word_does_not_reach_its_namesake_agency():
    """The reason `tax` was rejected, in Destin's own words: it "might
    interrupt searches for other things like '2024 income tax rate'". It did —
    weakly matching the State Board of Tax Appeals, which pulls a regulator
    into a question about rates."""
    assert parse_query_agencies("2024 income tax rate") == []
    assert parse_query_agencies("what is the corporate tax base") == []


def test_the_tax_appeals_board_is_still_reachable_by_name():
    """Suppressing a slug must not cost the agency itself."""
    assert _ids("tax appeals board") == ["agency:tax"]


def test_the_preposition_slug_is_gone_and_the_real_acronym_works():
    """`for` was Forestry's slug AND an English preposition. `dffm` is what
    the department is actually called."""
    from retrieval.query_agency import SUPPRESSED_ALIASES

    assert "for" in SUPPRESSED_ALIASES
    assert parse_query_agencies("for the department") == []
    assert _ids("dffm budget") == ["agency:for"]
    assert _ids("forestry and fire management") == ["agency:for"]


def test_the_defunct_financial_institutions_slug_is_gone():
    """`ban` is an ordinary word AND names an agency that no longer exists:
    it and agency:ins both end FY2021, merged into DIFI."""
    assert parse_query_agencies("ban") == []
    assert _ids("difi rates") == ["agency:dif"]


def test_financial_institutions_reaches_the_agency_that_does_the_job_now():
    """Left alone this resolved to the DEFUNCT agency alone — 362 chunks
    ending in 2021 — and returned nothing from DIFI, which has done the job
    since. A merger cannot be detected the way a rename can, so it is
    curated."""
    ms = parse_query_agencies("financial institutions")
    assert {m.value for m in ms} == {"agency:ban", "agency:dif"}
    assert all(m.confidence is Confidence.EXACT for m in ms)


def test_insurance_alone_does_not_hard_filter_onto_the_regulator():
    """Same defect as `tax`, one tier up: "Insurance, Department of" has the
    single-word head "Insurance", so questions about employee benefits landed
    on the insurance REGULATOR. Reached through the NAME, so a suppressed
    slug could not have fixed it."""
    for query in (
        "health insurance premiums for state employees",
        "unemployment insurance trust fund",
    ):
        ms = parse_query_agencies(query)
        assert all(m.confidence is Confidence.WEAK for m in ms), query


def test_the_insurance_department_is_still_reachable_by_full_name():
    assert _ids("insurance, department of") == ["agency:ins"]


def test_community_colleges_resolve_but_bare_colleges_only_boosts():
    """"colleges" is approved but DEMOTED: "universities and colleges funding"
    is a real question, and a hard filter would answer it with the community
    colleges alone."""
    assert _ids("comm colleges") == ["agency:acc"]
    assert _ids("community colleges") == ["agency:acc"]

    ms = parse_query_agencies("universities and colleges funding")
    assert [m.value for m in ms] == ["agency:acc"]
    assert ms[0].confidence is Confidence.WEAK


def test_dcs_and_adc_still_resolve():
    """Explicitly kept at Destin's request."""
    assert "agency:dcs" in _ids("dcs caseload")
    assert _ids("adc baseline") == ["agency:adc"]


def test_extraction_debris_no_longer_forms_a_hard_filtering_phrase():
    """"ministration" is a truncated "Administration" left by a PDF text
    layer, and it registered as a single-word phrase that HARD-FILTERED."""
    from retrieval.query_agency import _index

    assert "ministration" not in _index(None).phrase_to_ids
