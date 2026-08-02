"""Figure extraction tests.

Why offsets matter: the chip is placed at the figure's position in the
answer, so a wrong offset puts a citation on the wrong number. Why scale
matters: an answer renders "$8,287.7" under a "$ Millions" header while
the source document says "8,287,700,000" — measured at 67% of figures in
the 2026-08-01 baseline. Without scale the match fails.
"""
from __future__ import annotations

from citation.figures import Figure, extract_figures


def test_finds_plain_currency_with_offsets():
    ans = "ADC received $1,391,157,700 in FY 2025."
    figs = extract_figures(ans)
    assert len(figs) == 1
    f = figs[0]
    assert f.text == "$1,391,157,700"
    assert ans[f.start:f.end] == "$1,391,157,700"
    assert f.value == 1391157700.0
    assert f.scale == 1


def test_suffix_sets_scale():
    figs = extract_figures("the program cost $1.06 billion last year")
    assert figs[0].value == 1.06
    assert figs[0].scale == 1_000_000_000


def test_million_suffix():
    figs = extract_figures("a $376.2 million increase")
    assert figs[0].scale == 1_000_000


def test_table_header_sets_scale_for_the_whole_table():
    # The header declares the unit once; every cell inherits it.
    ans = (
        "| Agency | FY 2026 GF Appropriation ($ Millions) |\n"
        "|---|---|\n"
        "| ADE | $8,287.7 |\n"
        "| AHCCCS | $2,613.7 |\n"
    )
    figs = extract_figures(ans)
    cells = [f for f in figs if f.text in ("$8,287.7", "$2,613.7")]
    assert len(cells) == 2
    assert all(f.scale == 1_000_000 for f in cells)


def test_bare_grouped_integers_count_as_figures():
    figs = extract_figures("enrollment reached 101,602 students")
    assert [f.text for f in figs] == ["101,602"]
    assert figs[0].value == 101602.0


def test_years_and_percentages_are_not_figures():
    # "FY 2026" is a label and "3.8%" is almost always derived; neither
    # should demand a source chip.
    figs = extract_figures("In FY 2026 spending rose 3.8% over FY 2025.")
    assert figs == []


def test_offsets_are_correct_for_every_figure_in_order():
    ans = "First $1,000,000 then $2,500,000 and finally $3,750,000."
    figs = extract_figures(ans)
    assert [ans[f.start:f.end] for f in figs] == [
        "$1,000,000", "$2,500,000", "$3,750,000"]
    assert [f.start for f in figs] == sorted(f.start for f in figs)


def test_a_word_ending_in_in_does_not_swallow_the_figure():
    # The year guard looks for "FY"/"in" before a figure. Without a word
    # boundary, "within" and "margin" end in "in" and would silently drop
    # a real figure — a citation missing with no visible cause.
    assert [f.text for f in extract_figures("kept within $1,000,000 of plan")] == [
        "$1,000,000"]
    assert [f.text for f in extract_figures("a margin 1,234,567 wide")] == [
        "1,234,567"]
