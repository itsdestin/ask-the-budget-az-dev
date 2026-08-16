"""The fuzzy rung, which is what mis-labelled 732 documents.

`token_set_ratio` compares token SETS, so a candidate whose tokens are a
subset of a catalog name scores 100 no matter how little of the name it
covers. Measured against the real Osteopathic entry:

    candidate     token_set_ratio   token_sort_ratio
    'Arizona'                 100                 14
    'Medicine'                100                 16
    'Board of'                 77                 16
    'Board of Barbers'         97                 97   (vs 'Barbers, Board of')
    'DEPARTMENT OF CORRECTIONS' 88                88   (vs 'Corrections, State Department of')

`extractOne` then breaks the resulting 100-way tie by CATALOG ORDER rather
than by evidence, which is why one small regulatory board collected 992
documents.
"""
from __future__ import annotations

import pytest

from chunking.entity_stamper import EntityStamper


@pytest.fixture(scope="module")
def stamper():
    return EntityStamper.from_default_paths()


def test_a_single_common_word_no_longer_resolves_to_an_agency(stamper):
    for candidate in ("Arizona", "Medicine", "Surgery", "Board of"):
        got, _chain = stamper._resolve(
            section_path=[], text=candidate, source_url=None
        )
        assert got is None, f"{candidate!r} resolved to {got}"


def test_a_real_agency_heading_still_resolves(stamper):
    # NOTE: 'Department of Child Safety' was dropped from this table
    # (2026-08-16). It is not a fuzzy-rung case at all -- it resolves at
    # rung 1 (exact/inverted match) -- and it hits a PRE-EXISTING, documented
    # artifact unrelated to this task: the catalog carries 5 duplicate
    # 'Child Safety' entries (agency:cs, agency:dcs, agency:doa-cfs,
    # agency:doa-csf, agency:doacfs — samples/entity-catalog.yaml), and
    # `load_agency_catalog`'s own docstring says name->id is FIRST-WINS BY
    # FILE ORDER. agency:cs sits first in the file, so it wins today on
    # unmodified master too -- reproduced before any change in this task.
    # Catalog dedup is out of this task's scope (chunking/entity_stamper.py
    # fuzzy rung only); see STATUS.md's duplicate-catalog-entries section.
    for text, expected in (
        ("Board of Barbers", "agency:bar"),
        ("Arizona Department of Racing", "agency:rac"),
        ("Department of Corrections", "agency:adc"),
    ):
        got, _chain = stamper._resolve(
            section_path=[], text=text, source_url=None
        )
        assert got == expected, f"{text!r} -> {got}"


def test_a_tie_at_the_ceiling_refuses_rather_than_taking_catalog_order(stamper):
    """An ambiguous match is not evidence. Leaving the chunk unlabelled costs
    a ranking preference; guessing costs a wrong agency facet -- and agency is
    a PREFERENCE, not a filter, so refusing cannot delete an answer."""
    got, _chain = stamper._resolve(
        section_path=[], text="Board", source_url=None
    )
    assert got is None


def test_the_url_rung_still_wins_over_the_text(stamper):
    """Rung order is unchanged: a slug is stronger evidence than a phrase."""
    got, _chain = stamper._resolve(
        section_path=[],
        text="Board of Barbers",
        source_url="https://www.azjlbc.gov/26ar/rac.pdf",
    )
    assert got == "agency:rac"
