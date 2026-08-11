"""Interval matching anchored on the figure's absolute value (spec A4)."""
from __future__ import annotations

from citation.figures import extract_figures
from citation.matching import find_in_chunks, nearest_value


def _fig(text):
    (fig,) = extract_figures(text)
    return fig


def test_scale_shifted_match_returns_the_sources_rendering():
    fig = _fig("| $ Millions |\n| $8,287.7 |")
    hits = find_in_chunks(fig, {"k1": "General Fund total 8,287,700,000 for"})
    assert hits[0].source_text == "8,287,700,000"
    assert hits[0].scale_used == 1  # source printed the absolute value


def test_source_tabulating_in_thousands_matches_via_multiplier():
    fig = _fig("spent $10,297,300 on it")
    hits = find_in_chunks(fig, {"k1": "amount 10,297.3 (in thousands)"})
    assert hits[0].scale_used == 1_000


def test_written_precision_bounds_the_match():
    # "$10.3M" certifies [10.25M, 10.35M].
    # The floor is lowered here because "$10.3" is only THREE written
    # digits, so the default floor of 4 would refuse it before the
    # interval was ever consulted — and the interval is what this test
    # is about. The floor itself is pinned below.
    fig = _fig("about $10.3M budgeted")
    assert find_in_chunks(fig, {"k": "total 10,297,300 net"},
                          min_significant_digits=3)          # inside
    assert not find_in_chunks(fig, {"k": "total 10,352,000 net"},
                              min_significant_digits=3)      # outside


def test_exact_integer_does_not_match_a_nearby_value():
    # the §5.3 shape: 16,830,000,000 stated, 16,770,000,000 in source
    fig = _fig("total $16,830,000,000 combined")
    assert not find_in_chunks(fig, {"k": "sum 16,770,000,000 was"})


def test_specificity_floor_uses_written_digits():
    # "$12.49B" is 4 written digits -> at floor 5 it must be refused even
    # though its magnitude is 11 digits (the §5.4 bypass).
    fig = _fig("about $12.49B overall")
    assert not find_in_chunks(fig, {"k": "12,490,000,000"},
                              min_significant_digits=5)
    assert find_in_chunks(fig, {"k": "12,490,000,000"},
                          min_significant_digits=4)


def test_restrict_to_searches_only_the_named_chunks():
    fig = _fig("was $1,391,157,700 total")
    chunks = {"a": "x 1,391,157,700 y", "b": "x 1,391,157,700 y"}
    hits = find_in_chunks(fig, chunks, restrict_to=["b"])
    assert [h.chunk_id for h in hits] == ["b"]


def test_fused_table_numbers_still_locate_correctly():
    # Ported from the pre-attestation suite: extraction fuses adjacent
    # cells, so DCS's 1,320,598,100 runs straight into Chiropractic's
    # 643,700. The offsets for the first figure must still be exact —
    # they are what the PDF highlighter searches with.
    fig = _fig("Child Safety got $1,320,598,100 total")
    chunks = {"c-1": "Child Safety, Department of\t1,320,598,100643,700\tnext"}
    hits = find_in_chunks(fig, chunks)
    assert len(hits) == 1
    assert chunks["c-1"][hits[0].start:hits[0].end] == "1,320,598,100"


def test_nearest_value_reports_the_closest_source_number():
    # the §5.5 case: $12.49B stated, 12,515.4 (millions) in source
    fig = _fig("dipped to $12.49B in")
    nm = nearest_value(fig, {"k": "revenues of 12,515.4 were"})
    assert nm is not None
    assert nm.source_text == "12,515.4"
    assert 0.001 < nm.distance < 0.01  # ~0.2%


def test_nearest_value_beyond_five_percent_is_none():
    fig = _fig("cost $10,000,000.00 total")
    assert nearest_value(fig, {"k": "value 123,456 only"}) is None


def test_a_source_value_under_a_thousand_is_not_invisible():
    """A table printed "in millions" writes every agency under $1B with no
    comma — "Universities 974.6". Requiring a comma group made those source
    values unmatchable while the answer side extracted "$974.6" happily, so
    the system refused to cite a figure whose source was in a retrieved
    chunk. On a nine-row General Fund table that is most of the rows."""
    fig = _fig("| $ Millions |\n| $974.6 |")
    hits = find_in_chunks(fig, {"k": "Universities 974.6 Child Safety 488.8"})
    assert [h.source_text for h in hits] == ["974.6"]


def test_a_bare_integer_in_a_source_is_still_not_a_candidate():
    """The other half of the same decision. A decimal signals an amount; a
    bare integer is as likely to be a year, a page number or a rank, and
    admitting those multiplies candidate density for no coverage this
    corpus needs."""
    fig = _fig("about $2,026.0 thousand")
    assert not find_in_chunks(fig, {"k": "see FY 2026 on page 14"})
