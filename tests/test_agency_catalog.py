"""Tests for chunking/agency_catalog.py."""
from __future__ import annotations

from chunking.agency_catalog import id_to_name, load_agency_catalog
from identity.validator import validate_name


def test_loads_157_agencies_with_ids():
    cat = load_agency_catalog()
    assert len(cat) >= 150
    # AHCCCS's canonical_id is `agency:axs` — the JLBC slug, not the acronym.
    # (The plan's draft test guessed `agency:ahcccs`; the real catalog keys on
    # the publisher's own slug, which is what every stored chunk carries.)
    entry = cat["agency:axs"]
    assert "AHCCCS" in entry.canonical_name or "Health Care" in entry.canonical_name
    assert entry.slug == "axs"


def test_id_to_name_map():
    names = id_to_name()
    assert names["agency:axs"]
    assert all(k.startswith("agency:") for k in names)


def test_slug_is_none_for_gov_only_entries():
    """Gov-outline entries have no JLBC slug — consumers must not assume one."""
    cat = load_agency_catalog()
    entry = cat["agency:gov:arizona-health-care-cost-containment-system"]
    assert entry.slug is None


def test_catalog_is_cached_across_calls():
    """The YAML is ~10k lines; repeated id→name lookups must not re-parse it."""
    assert load_agency_catalog() is load_agency_catalog()


def test_name_variants_come_from_names_observed_jlbc():
    """`names_observed_jlbc` maps printed-name → docs-seen-in; the KEYS are the
    alternate names the stamper matches against."""
    entry = load_agency_catalog()["agency:sba"]
    assert "Accountancy, Arizona State Board of" in entry.name_variants


def test_every_agency_exposes_its_slug_as_an_alias():
    """JLBC's own URL slug IS an acronym: 26AR/adc.pdf. Derived, not invented."""
    cat = load_agency_catalog()
    adc = cat["agency:adc"]
    assert "adc" in [a.lower() for a in adc.aliases]


def test_aliases_are_separate_from_publisher_observed_names():
    """name_variants is PROVENANCE — names really printed by JLBC. An analyst
    acronym is not one, and must not contaminate it."""
    cat = load_agency_catalog()
    adc = cat["agency:adc"]
    assert adc.name_variants == ["Corrections, State Department of"]
    assert "adc" not in [v.lower() for v in adc.name_variants]
    assert "doc" not in [v.lower() for v in adc.name_variants]


def test_the_des_extraction_garbage_variant_is_gone():
    """'pp y, Economic Security, Department of' is PDF-extraction debris that
    reached the catalog. It would fuzzy-match noise."""
    cat = load_agency_catalog()
    for v in cat["agency:des"].name_variants:
        assert "pp y" not in v


def test_no_variant_or_alias_is_extraction_debris():
    """Guard the whole catalog, not just the one we happened to find."""
    cat = load_agency_catalog()
    for entry in cat.values():
        for text in list(entry.name_variants) + list(entry.aliases):
            assert len(text) >= 2, f"{entry.canonical_id}: {text!r}"
            assert not text.startswith(("pp y", "y, ")), f"{entry.canonical_id}: {text!r}"


def test_the_slug_is_not_duplicated_when_the_reviewed_list_repeats_it():
    """A reviewed list may spell the slug "ADC" where the slug field says
    "adc"; two spellings of one alias would double-count in ambiguity checks."""
    from chunking.agency_catalog import _aliases

    assert _aliases({"slug": "adc", "aliases": ["ADC", "doc"]}) == ["adc", "doc"]


def test_no_variant_is_a_bare_organisational_fragment():
    """A page break split "…, Arizona / Board of" across two lines and the
    harvester recorded BOTH halves, leaving a literal "Board of" variant on
    agency:ost. That fragment matches "board of regents", "board of
    education" and a dozen more, so it would hard-filter unrelated queries
    onto Osteopathic Examiners.

    Guarded as a class rather than as the one instance, because the same
    page-break shape can recur on any future harvest.
    """
    generic = {
        "board of", "department of", "office of", "commission of",
        "commission on", "council of", "division of", "authority of",
        "bd of", "dept of", "board", "department", "office", "commission",
        "state", "arizona", "of", "the",
    }
    cat = load_agency_catalog()
    offenders = [
        (entry.canonical_id, text)
        for entry in cat.values()
        for text in list(entry.name_variants) + list(entry.aliases)
        if text.strip().lower().rstrip(":").strip() in generic
    ]
    assert offenders == [], f"generic fragments would match anything: {offenders}"


def test_no_catalogued_name_fails_the_identity_validator():
    """`list_filter_values` hands `canonical_name` straight to the model in
    production (see `harness/tools.py`) — the catalog's own display name IS
    what the LLM reads. `identity.validator.validate_name` is the one place
    this codebase already knows how to recognise a corrupted TOC-scrape name
    (dot leaders, an embedded page number, a doubled space where two printed
    columns got glued together) — see that module's docstring for the
    dot-leader / embedded-page-number cases it was built to catch.

    Found by running the validator over the file rather than eyeballing it
    (2026-08-16): 3 canonical_name values and 30 names_observed_jlbc keys
    failed. All 33 are repaired in samples/entity-catalog.yaml — each
    offender had a clean sibling entry already recorded for the same
    agency, so every repair is a MERGE of a corrupted key's years onto the
    clean key, never an invented string. This test is what stops a future
    harvest re-introducing the same shape and it going unnoticed, the way
    the original 33 did.

    Deliberately checks BOTH canonical_name and every name_variants string —
    a variant is not directly on the `list_filter_values` response today,
    but `identity.repair`'s title composer reads name_variants too (see
    `chunking/agency_catalog.py::_name_variants`), so a corrupted variant is
    one code path away from reappearing in a document title, not just in the
    filter-values answer.
    """
    cat = load_agency_catalog()
    offenders = []
    for entry in cat.values():
        verdict = validate_name(entry.canonical_name)
        if not verdict.ok:
            offenders.append((entry.canonical_id, "canonical_name", entry.canonical_name, verdict.reason))
        for variant in entry.name_variants:
            verdict = validate_name(variant)
            if not verdict.ok:
                offenders.append((entry.canonical_id, "name_variant", variant, verdict.reason))
    assert offenders == [], f"catalog names the identity validator rejects: {offenders}"
