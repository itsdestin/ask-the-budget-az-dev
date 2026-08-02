"""Scale-aware matching tests.

Two properties carry this module. First, the answer's rendering and the
source's rendering differ for two thirds of figures, so matching must
compare VALUES across scale. Second, the returned string must be the
SOURCE's rendering, because that is what exists in the PDF text layer.
"""
from __future__ import annotations

from citation.figures import Figure
from citation.matching import SourceHit, find_in_chunks


def fig(text, value, scale=1):
    return Figure(text=text, start=0, end=len(text), value=value, scale=scale)


def test_exact_match_returns_source_rendering():
    chunks = {"c-1": "ADC General Fund 1,391,157,700 in FY 2025"}
    hits = find_in_chunks(fig("$1,391,157,700", 1391157700.0), chunks)
    assert len(hits) == 1
    assert hits[0].chunk_id == "c-1"
    assert hits[0].source_text == "1,391,157,700"
    assert chunks["c-1"][hits[0].start:hits[0].end] == "1,391,157,700"


def test_scale_shifted_match():
    # The answer says "$8,287.7" under a "$ Millions" header; the document
    # prints the absolute figure.
    chunks = {"c-1": "Department of Education 8,287,700,000 total"}
    hits = find_in_chunks(fig("$8,287.7", 8287.7, scale=1_000_000), chunks)
    assert len(hits) == 1
    assert hits[0].source_text == "8,287,700,000"
    assert hits[0].scale_used == 1_000_000


def test_rounding_tolerance():
    # "$1,391.2 million" is a faithful rounding of 1,391,157,700.
    chunks = {"c-1": "appropriation of 1,391,157,700"}
    hits = find_in_chunks(fig("$1,391.2", 1391.2, scale=1_000_000), chunks)
    assert len(hits) == 1


def test_multiple_chunks_all_returned():
    chunks = {"c-1": "total 2,613,700,000", "c-2": "AHCCCS 2,613,700,000 GF"}
    hits = find_in_chunks(fig("$2,613,700,000", 2613700000.0), chunks)
    assert {h.chunk_id for h in hits} == {"c-1", "c-2"}


def test_short_figures_are_refused_by_the_specificity_floor():
    # "$37" collides incidentally everywhere. Refusing to link is correct;
    # guessing is not.
    chunks = {"c-1": "line 37 of the report shows 37 positions"}
    assert find_in_chunks(fig("$37", 37.0), chunks) == []


def test_fused_table_numbers_still_locate_correctly():
    # Extraction fuses adjacent cells: DCS 1,320,598,100 runs straight into
    # Chiropractic's 643,700. The offsets for the first figure are still
    # correct, which is what the highlighter needs.
    chunks = {"c-1": "Child Safety, Department of\t1,320,598,100643,700\tnext"}
    hits = find_in_chunks(fig("$1,320,598,100", 1320598100.0), chunks)
    assert len(hits) == 1
    assert chunks["c-1"][hits[0].start:hits[0].end] == "1,320,598,100"


def test_no_match_returns_empty():
    assert find_in_chunks(fig("$999,999,999", 999999999.0), {"c-1": "nothing"}) == []
