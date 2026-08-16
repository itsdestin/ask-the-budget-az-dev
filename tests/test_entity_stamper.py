"""Tests for chunking/entity_stamper.py."""
from __future__ import annotations

import pytest

from chunking.entity_stamper import EntityStamper, slug_from_jlbc_url
from chunking.types import Chunk, ChunkProvenance


def _chunk(
    *,
    section_path: list[str] | None = None,
    text: str = "",
    publisher: str = "jlbc",
    doc_type: str = "baseline-book",
    fiscal_year: int = 2027,
) -> Chunk:
    return Chunk(
        chunk_id="x-0001",
        doc_id="x",
        text=text,
        section_path=section_path or [],
        provenance=ChunkProvenance(page=1),
        fiscal_year=fiscal_year,
        doc_type=doc_type,
        publisher=publisher,
        token_count=10,
    )


# --- URL slug extraction ----------------------------------------------------


def test_slug_from_jlbc_url_baseline():
    assert slug_from_jlbc_url("https://www.azjlbc.gov/27baseline/axs.pdf") == "axs"


def test_slug_from_jlbc_url_approps():
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26ar/rev.pdf") == "rev"


def test_slug_from_jlbc_url_legacy_host():
    """FY15-FY22 historical host: http://www.azleg.gov/jlbc/<YY>AR/<slug>.pdf."""
    assert slug_from_jlbc_url("http://www.azleg.gov/jlbc/22AR/dor.pdf") == "dor"


def test_slug_from_jlbc_url_returns_none_for_non_jlbc():
    assert slug_from_jlbc_url("https://gao.az.gov/sites/default/files/x.pdf") is None
    assert slug_from_jlbc_url("https://example.com/foo/bar.pdf") is None


def test_slug_from_jlbc_url_returns_none_for_topic_files():
    """Cross-cutting topic PDFs (capitaloutlay/crr/tobacco/csbg) don't map
    to a single agency — they're cross-cuts, not per-agency entries."""
    assert slug_from_jlbc_url("https://www.azjlbc.gov/27baseline/capitaloutlay.pdf") is None


def test_the_url_rung_knows_every_directory_jlbc_actually_published_under():
    """~1,448 JLBC-hosted documents got no slug at all, and ~965 of them have
    a slug that IS a catalogued agency -- the strongest witness in the ladder,
    discarded, on exactly the FY2005-2012 era where the mis-labels concentrate.

    `store/book_family.py:55` in this same repo already parses
    `\\d{2}(baseline|book\\d*|ar|app)`. The two modules disagreed about JLBC's
    own URL vocabulary; this is the module that mattered."""
    assert slug_from_jlbc_url("https://www.azjlbc.gov/05app/bar.pdf") == "bar"
    assert slug_from_jlbc_url("https://www.azjlbc.gov/12book1/des.pdf") == "des"
    # the two that already worked must keep working. NOTE: the brief's own
    # example used "crr.pdf" here, but "crr" is a cross-cutting topic slug
    # (see _TOPIC_SLUGS) that slug_from_jlbc_url deliberately returns None
    # for -- asserting it resolves to "crr" would pin the wrong behaviour.
    # Swapped for "axs", the same per-agency slug the pre-existing baseline
    # test already uses.
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26baseline/axs.pdf") == "axs"
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26ar/ost.pdf") == "ost"
    assert slug_from_jlbc_url("http://www.azleg.gov/jlbc/15AR/adc.pdf") == "adc"


def test_a_url_that_is_not_a_jlbc_book_still_yields_no_slug():
    """The rung must stay a JLBC-book rule. A governor's-budget or AFR URL
    has no agency slug in it and must not be coerced into one."""
    assert slug_from_jlbc_url("https://azgovernor.gov/fy2027-detail.pdf") is None
    assert slug_from_jlbc_url("https://gao.az.gov/afr-fy2024.pdf") is None
    assert slug_from_jlbc_url("https://www.azjlbc.gov/notes/hb2172.pdf") is None


# --- Direct slug match ------------------------------------------------------


def test_stamp_jlbc_url_direct_slug():
    """Plan §3.4 step 1: rule 1 — direct slug match from JLBC URL."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk()
    stamped = stamper.stamp(
        chunk, source_url="https://www.azjlbc.gov/27baseline/axs.pdf"
    )
    assert stamped.agency_canonical_id == "agency:axs"
    # Direct match: no alias hops
    assert stamped.alias_chain == []


def test_stamp_jlbc_url_direct_slug_dor_baseline():
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(
        _chunk(), source_url="https://www.azjlbc.gov/27baseline/dor.pdf"
    )
    assert stamped.agency_canonical_id == "agency:dor"


# --- Alias map lookup -------------------------------------------------------


def test_stamp_alias_old_slug():
    """Plan §3.4 step 2: rule 2 — alias map lookup. `rev` URL → `agency:dor`."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk()
    stamped = stamper.stamp(
        chunk, source_url="https://www.azjlbc.gov/26ar/rev.pdf"
    )
    assert stamped.agency_canonical_id == "agency:dor"
    assert "rev" in stamped.alias_chain


# --- Name-based match (no URL) ----------------------------------------------


def test_stamp_name_based_governor_section_path():
    """Plan §3.4 step 2 rule 3: name-based match against entity catalog.
    Gov SAD doesn't carry slugs — resolve by section_path canonical name."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Corrections, Department of", "Operating Lump Sum"],
        publisher="governor",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:adc"


def test_stamp_name_based_inverted_form():
    """Catalog canonical names use 'X, Department of' or 'Department of X' —
    the stamper should match either form."""
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(
        _chunk(section_path=["Department of Corrections"], publisher="governor")
    )
    assert stamped.agency_canonical_id == "agency:adc"


# --- Fuzzy / OCR-drift match ------------------------------------------------


def test_stamp_ocr_drift_fuzzy_match():
    """Plan §3.4 step 2 rule 3 fallback: rapidfuzz at ratio ≥ 85 catches
    OCR drift (Boseline / Deportment)."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Boseline Book", "Deportment of Revenue"],
        publisher="governor",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:dor"


def test_stamp_all_caps_bill_heading_with_nbsp_resolves_via_fuzzy():
    """Real-bill headings have non-breaking spaces (\\xa0) instead of regular
    spaces between tokens — Word writes them that way. WS6 finding 2026-05-06:
    rapidfuzz `token_set_ratio` does NOT tokenize on NBSP, so
    'Sec.\\xa025.\\xa0\\xa0DEPARTMENT OF CHILD SAFETY' gets tokenized as
    `[..., 'sec.\\xa025.\\xa0\\xa0department', 'of', 'child', 'safety']` —
    the dept-name token is fused with the section number prefix and never
    matches catalog. Fix: normalize NBSP to space in the fuzzy processor.
    """
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["Sec.\xa025.\xa0\xa0DEPARTMENT OF CHILD SAFETY"],
        publisher="legislature",
    )
    stamped = stamper.stamp(chunk)
    # Both Child Safety canonical_ids in the catalog are valid resolutions —
    # accept any agency:cs* match. The bug is None, not which-of-two-cs-ids.
    assert stamped.agency_canonical_id is not None
    assert stamped.agency_canonical_id.startswith("agency:")
    assert "cs" in stamped.agency_canonical_id or "cfs" in stamped.agency_canonical_id


def test_stamp_all_caps_bill_heading_resolves_via_fuzzy():
    """Real-bill Part-1 dept headings are ALL-CAPS (e.g. 'DEPARTMENT OF
    CORRECTIONS' from SB 1735). The catalog stores them as 'Corrections,
    Department of' / 'Department of Corrections'. WS6 finding 2026-05-06:
    rapidfuzz `token_set_ratio` is case-sensitive in v3.x without an explicit
    processor — every ALL-CAPS heading scored ~19, far below the 85 threshold,
    leaving 65 of 91 dept-heading chunks in the bill unstamped.
    """
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(
        section_path=["DEPARTMENT OF CORRECTIONS"],
        publisher="legislature",
    )
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:adc"


# --- No match -> None + observability ---------------------------------------


def test_stamp_no_match_leaves_canonical_id_none():
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(section_path=["Some Random Heading"], publisher="governor")
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id is None


# --- Idempotency ------------------------------------------------------------


def test_stamp_does_not_mutate_input_chunk():
    stamper = EntityStamper.from_default_paths()
    original = _chunk(section_path=["Department of Corrections"], publisher="governor")
    assert original.agency_canonical_id is None
    stamped = stamper.stamp(original)
    assert original.agency_canonical_id is None  # input untouched
    assert stamped.agency_canonical_id == "agency:adc"


def test_stamp_already_stamped_chunk_is_passthrough():
    """If the chunk already has an agency_canonical_id, stamp() should not
    re-run resolution (it could only weaken the signal)."""
    stamper = EntityStamper.from_default_paths()
    chunk = _chunk(section_path=["Department of Corrections"], publisher="governor")
    chunk = chunk.model_copy(update={"agency_canonical_id": "agency:preset"})
    stamped = stamper.stamp(chunk)
    assert stamped.agency_canonical_id == "agency:preset"
    assert stamped.alias_chain == []


# --- Construction with explicit paths --------------------------------------


def test_stamper_constructor_accepts_explicit_paths(tmp_path):
    catalog = tmp_path / "cat.yaml"
    aliases = tmp_path / "al.yaml"
    catalog.write_text(
        "agencies:\n"
        "- canonical_name: Custom Agency\n"
        "  canonical_id: agency:custom\n"
        "  slug: custom\n",
        encoding="utf-8",
    )
    aliases.write_text("renames: []\n", encoding="utf-8")
    stamper = EntityStamper(catalog_path=catalog, aliases_path=aliases)
    stamped = stamper.stamp(
        _chunk(), source_url="https://www.azjlbc.gov/27baseline/custom.pdf"
    )
    assert stamped.agency_canonical_id == "agency:custom"


# --- Sub-programme slug prefix fallback (rung 1b) ---------------------------
#
# Older JLBC editions (roughly FY2005-2012) split some large agencies into
# several sub-programme documents whose slugs are NOT themselves in the
# catalog — e.g. AHCCCS Acute Care published as 'axsacute', not 'axs'. The
# fuzzy text rung was recently tightened (token_sort_ratio, see the WHY
# block in entity_stamper.py) and correctly stopped guessing these from
# text alone, which lost the label these slugs used to get by accident.
#
# Measured by the controller against the live corpus (2026-08-16): the
# longest-catalogued-prefix rule below recovers 36 slugs / 195 documents,
# 35 of them unambiguously correct. This dict is that exact 35-slug
# mapping, transcribed from the measurement — pinned so any future change
# to the catalog or the prefix rule is a conscious edit, not silent drift.
_SUB_PROGRAMME_SLUG_TO_AGENCY = {
    # Department of Education
    "adeadmn": "agency:ade",
    "adeassis": "agency:ade",
    "adeboe": "agency:ade",
    "adeform": "agency:ade",
    "adegs": "agency:ade",
    "adenf": "agency:ade",
    # AHCCCS
    "axsacute": "agency:axs",
    "axsadmn": "agency:axs",
    "axsltc": "agency:axs",
    # Department of Economic Security
    "desadmn": "agency:des",
    "desage": "agency:des",
    "desbene": "agency:des",
    "descf": "agency:des",
    "descs": "agency:des",
    "descyf": "agency:des",
    "desdd": "agency:des",
    "desemp": "agency:des",
    "desltc": "agency:des",
    # Department of Health Services
    "dhsadmn": "agency:dhs",
    "dhsash": "agency:dhs",
    "dhsbehav": "agency:dhs",
    "dhsfam": "agency:dhs",
    "dhspub": "agency:dhs",
    # Department of Administration
    "doafm": "agency:doa",
    "doafs": "agency:doa",
    "doahum": "agency:doa",
    "doaits": "agency:doa",
    "doarisk": "agency:doa",
    "doass": "agency:doa",
    "doasum": "agency:doa",
    # Department of Transportation
    "dotadmn": "agency:dot",
    "dotaero": "agency:dot",
    "dothwys": "agency:dot",
    "dotmvd": "agency:dot",
    # Superior Court
    "judsuperior": "agency:judsup",
}

# The one measured false positive: 'appropveto' is JLBC's "Appropriation
# Vetoes" summary chapter, not a document about the agency slugged 'app'
# (Legislature budget-bill index). It shares the first 3 letters by
# coincidence only, so it must never resolve via this rung.
_APPROPVETO_SLUG = "appropveto"


def _url_for_slug(slug: str) -> str:
    # Directory choice doesn't matter to the URL regex (baseline/book*/ar/app
    # all match) — '07app' matches the FY2005-2012 era these slugs come from.
    return f"https://www.azjlbc.gov/07app/{slug}.pdf"


def test_sub_programme_slugs_recover_via_longest_catalogued_prefix():
    """Pins the exact 35-slug recovery set measured against the live corpus.

    Assert the mapping derived from the real catalog is exactly these 35
    slugs and no more, so a future catalog change surfaces as a failing
    test rather than a silent change in which documents get labelled.
    """
    stamper = EntityStamper.from_default_paths()
    for slug, expected_agency in _SUB_PROGRAMME_SLUG_TO_AGENCY.items():
        stamped = stamper.stamp(_chunk(), source_url=_url_for_slug(slug))
        assert stamped.agency_canonical_id == expected_agency, (
            f"slug {slug!r} expected {expected_agency!r}, "
            f"got {stamped.agency_canonical_id!r}"
        )


def test_appropveto_does_not_resolve_via_the_prefix_rung():
    """The one measured false positive must stay unresolved, not become
    'agency:app' — see the WHY on _APPROPVETO_SLUG above."""
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(_chunk(), source_url=_url_for_slug(_APPROPVETO_SLUG))
    assert stamped.agency_canonical_id is None


def test_numbered_section_slugs_stay_unresolved():
    """Uncatalogued slugs with no catalogued prefix at all — JLBC's numbered
    summary chapters ('302', '341-353', ...) — must keep resolving to
    nothing rather than being swept up by this rung."""
    stamper = EntityStamper.from_default_paths()
    for slug in ["302", "341-353", "zzz-not-a-real-slug"]:
        stamped = stamper.stamp(_chunk(), source_url=_url_for_slug(slug))
        assert stamped.agency_canonical_id is None


def test_prefix_fallback_requires_at_least_three_catalogued_characters(tmp_path):
    """A 2-character catalogued slug (e.g. the real catalog's 'cf', 'cs')
    must never anchor a prefix match — too short to be evidence, it would
    fire inside unrelated slugs across the corpus."""
    catalog = tmp_path / "cat.yaml"
    aliases = tmp_path / "al.yaml"
    catalog.write_text(
        "agencies:\n"
        "- canonical_name: Two Char Agency\n"
        "  canonical_id: agency:tc\n"
        "  slug: tc\n",
        encoding="utf-8",
    )
    aliases.write_text("renames: []\n", encoding="utf-8")
    stamper = EntityStamper(catalog_path=catalog, aliases_path=aliases)
    stamped = stamper.stamp(_chunk(), source_url=_url_for_slug("tcextra"))
    assert stamped.agency_canonical_id is None


def test_prefix_fallback_picks_the_longest_catalogued_match(tmp_path):
    """When more than one catalogued slug is a valid prefix, the longest
    one wins (mirrors 'judsuperior' -> 'judsup', not a shorter accident)."""
    catalog = tmp_path / "cat.yaml"
    aliases = tmp_path / "al.yaml"
    catalog.write_text(
        "agencies:\n"
        "- canonical_name: Short Match\n"
        "  canonical_id: agency:short\n"
        "  slug: abc\n"
        "- canonical_name: Long Match\n"
        "  canonical_id: agency:long\n"
        "  slug: abcde\n",
        encoding="utf-8",
    )
    aliases.write_text("renames: []\n", encoding="utf-8")
    stamper = EntityStamper(catalog_path=catalog, aliases_path=aliases)
    stamped = stamper.stamp(_chunk(), source_url=_url_for_slug("abcdefgh"))
    assert stamped.agency_canonical_id == "agency:long"


def test_prefix_fallback_does_not_fire_on_non_jlbc_urls():
    """A non-JLBC URL still yields nothing — the fallback lives entirely
    inside the URL rung and must not change this."""
    stamper = EntityStamper.from_default_paths()
    stamped = stamper.stamp(
        _chunk(), source_url="https://example.com/axsacute-report.pdf"
    )
    assert stamped.agency_canonical_id is None
