"""Tests for EntityStamper.resolve_all — decision D2 multi-agency stamping.

A statewide table (e.g. the Baseline's summary schedules) lists dozens of
agencies in one chunk. Scalar resolution picks one — in practice whichever
matched first — so filtering by any of the OTHER agencies silently misses
the row. D2 says the row carries every agency it names.
"""
from __future__ import annotations

from chunking.entity_stamper import EntityStamper
from chunking.types import Chunk, ChunkProvenance


def _stamper() -> EntityStamper:
    return EntityStamper.from_default_paths(fund_catalog_path=None)


def _chunk(text: str, *, is_table: bool, section_path=None, **over) -> Chunk:
    base = dict(
        chunk_id="c1", doc_id="d1", text=text,
        section_path=section_path or [], is_table=is_table, table_html=None,
        provenance=ChunkProvenance(page=1, bbox=[0.0, 0.0, 1.0, 1.0]),
        fiscal_year=2027, doc_type="baseline-per-agency", publisher="jlbc",
        token_count=10,
    )
    base.update(over)
    return Chunk(**base)


TABLE_TEXT = (
    "Agency\tFY 2026\tFY 2027\n"
    "AHCCCS\t1,000,000\t1,100,000\n"
    "Child Safety, Department of\t900,000\t950,000\n"
    "Public Safety, Department of\t800,000\t825,000\n"
)


def test_table_chunk_collects_every_named_agency():
    ids = _stamper().resolve_all(_chunk(TABLE_TEXT, is_table=True))
    # agency:cs, not agency:dcs — the catalog carries both under the identical
    # printed name and the name index is first-wins, so this matches what
    # scalar resolution already returns for the same text.
    assert set(ids) == {"agency:axs", "agency:cs", "agency:dps"}


def test_primary_comes_first():
    """Order matters downstream: the first id is what a single-agency UI
    label shows, and it must stay the scalar resolution's answer."""
    chunk = _chunk(TABLE_TEXT, is_table=True, section_path=["AHCCCS"])
    ids = _stamper().resolve_all(chunk)
    assert ids[0] == "agency:axs"


def test_narrative_chunks_keep_single_resolution():
    """Only tables get the wide scan — a narrative page mentioning another
    agency in passing is not 'about' that agency.

    The FIXTURE changed on 2026-08-16; the property it pins did not. It used
    to put the heading and the prose on ONE line:

        "AHCCCS provider rates increase in FY 2027. The Department of Child
         Safety is unaffected."

    and relied on `token_set_ratio` scoring that whole sentence **100**
    against the bare name `AHCCCS`, because the name's tokens are a subset of
    the sentence's. That is the identical defect that labelled 732 documents
    as the Board of Osteopathic Examiners — the single word `Arizona` scored
    100 against its catalog entry the same way. Under `token_sort_ratio` the
    sentence scores 12.8 and correctly does not resolve.

    Real documents carry the agency as its OWN heading line, which is what
    the candidate-phrase splitter exists to read, so the fixture now has the
    shape the corpus actually has. Measured over a 4,000-chunk sample of the
    live corpus, the scorer change moves label coverage 80.9% → 80.5%: the
    URL rung supplies most labels, and this rung was never carrying the load
    its old score suggested."""
    text = ("AHCCCS\n"
            "Provider rates increase in FY 2027. The Department of "
            "Child Safety is unaffected.")
    ids = _stamper().resolve_all(_chunk(text, is_table=False))
    assert ids == ["agency:axs"]


def test_an_already_stamped_chunk_keeps_its_primary():
    chunk = _chunk(TABLE_TEXT, is_table=True, agency_canonical_id="agency:dps")
    ids = _stamper().resolve_all(chunk)
    assert ids[0] == "agency:dps"
    # agency:cs, not agency:dcs — the catalog carries both under the identical
    # printed name and the name index is first-wins, so this matches what
    # scalar resolution already returns for the same text.
    assert set(ids) == {"agency:axs", "agency:cs", "agency:dps"}


def test_unresolvable_chunk_returns_empty():
    ids = _stamper().resolve_all(_chunk("1\t2\t3\n4\t5\t6", is_table=True))
    assert ids == []


def test_no_duplicate_ids_when_an_agency_repeats():
    text = "AHCCCS\t1\nAHCCCS\t2\nAHCCCS\t3\n"
    assert _stamper().resolve_all(_chunk(text, is_table=True)) == ["agency:axs"]


def test_resolve_all_uses_the_url_slug_for_the_primary():
    ids = _stamper().resolve_all(
        _chunk(TABLE_TEXT, is_table=True),
        source_url="https://www.azjlbc.gov/27baseline/dps.pdf",
    )
    assert ids[0] == "agency:dps"
