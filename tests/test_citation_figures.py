"""Figure extraction tests.

Why offsets matter: the chip is placed at the figure's position in the
answer, so a wrong offset puts a citation on the wrong number. Why scale
matters: an answer renders "$8,287.7" under a "$ Millions" header while
the source document says "8,287,700,000" — measured at 67% of figures in
the 2026-08-01 baseline. Without scale the match fails.
"""
from __future__ import annotations

from citation.figures import Figure, extract_figures, written_significant_digits


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


def test_abbreviated_suffixes_set_scale():
    # Real answers in the 2026-08-02 baseline write "+$243.5M", not
    # "$243.5 million". Reading that as scale 1 both breaks the match and
    # makes the specificity floor treat $243 million as a 3-digit figure.
    assert extract_figures("growth of +$243.5M over baseline")[0].scale == 1_000_000
    assert extract_figures("a $1.5B fund")[0].scale == 1_000_000_000
    assert extract_figures("$104.8M in savings")[0].absolute == 104_800_000


def test_a_capital_m_that_starts_a_word_is_not_a_suffix():
    # "$1.5 Mesa" must not read as $1.5 million.
    assert extract_figures("$1.5 Mesa district")[0].scale == 1
    assert extract_figures("$1.5 Basic aid")[0].scale == 1


def test_a_word_ending_in_in_does_not_swallow_the_figure():
    # The year guard looks for "FY"/"in" before a figure. Without a word
    # boundary, "within" and "margin" end in "in" and would silently drop
    # a real figure — a citation missing with no visible cause.
    assert [f.text for f in extract_figures("kept within $1,000,000 of plan")] == [
        "$1,000,000"]
    assert [f.text for f in extract_figures("a margin 1,234,567 wide")] == [
        "1,234,567"]


def test_a_figure_after_the_word_in_is_still_a_figure():
    # Seen in a real answer 2026-08-02: "took in $27,362,036.72 in revenues"
    # lost its chip entirely, because the year guard read the bare word "in"
    # as a year cue. "in", "resulted in", "took in" are ordinary English
    # before a dollar amount, so this was a silent hole in coverage.
    assert [f.text for f in extract_figures("took in $27,362,036.72 in revenues")] == [
        "$27,362,036.72"]
    assert [f.text for f in extract_figures("resulted in 1,320,598,100 of costs")] == [
        "1,320,598,100"]


def test_no_year_can_reach_the_extractor_in_the_first_place():
    # This is WHY the year guard was deleted rather than narrowed. A figure
    # must be comma-grouped or carry a currency marker with a decimal, and a
    # bare four-digit year is neither — so the guard had no true positives
    # available to it and could only ever cost real figures.
    for text in ("FY 2026", "in 2026", "fiscal year 2025", "2026", "FY2026"):
        assert extract_figures(text) == [], text


def test_halfwidth_is_half_the_last_written_decimal_place():
    # "$10.3M" certifies [10.25M, 10.35M] — half-width 0.05 * 1e6.
    (fig,) = extract_figures("total $10.3M this year")
    assert fig.scale == 1_000_000
    assert fig.halfwidth == 0.05 * 1_000_000


def test_halfwidth_of_a_grouped_integer_is_half_a_dollar():
    (fig,) = extract_figures("total 10,297,300 exactly")
    assert fig.halfwidth == 0.5


def test_halfwidth_of_cents_is_half_a_cent():
    (fig,) = extract_figures("took in $27,362,036.72 that month")
    assert fig.halfwidth == 0.005


def test_written_significant_digits_ignores_trailing_zeros():
    assert written_significant_digits("$12.49") == 4      # the §5.4 case
    assert written_significant_digits("37") == 2
    assert written_significant_digits("1,320,598,100") == 8
    assert written_significant_digits("10.30") == 3
    assert written_significant_digits("0.05") == 1


def test_the_scale_word_is_part_of_the_figures_span():
    """A chip renders at `end`. Stopping at the digits put the chip INSIDE
    the amount — an analyst read "$13.98[1]B" on every billions figure in a
    live answer."""
    answer = "grew to $13.98B this year"
    (fig,) = extract_figures(answer)
    assert fig.text == "$13.98B"
    assert answer[fig.start:fig.end] == fig.text
    (spelled,) = extract_figures("grew to $8,287.7 million this year")
    assert spelled.text == "$8,287.7 million"
    # ...and the interval the form certifies is unchanged by carrying the
    # suffix: splitting "13.98B" on "." would read three decimal places.
    assert fig.halfwidth == 0.005 * 1_000_000_000


def test_accounting_parentheses_are_a_negative_figure():
    """A variance column writes "$(0.07)B", not "-$0.07B". Without this the
    cell yielded NO figure at all — not an uncited one, an invisible one —
    so a whole actual-vs-forecast column could be neither cited nor
    derived."""
    (fig,) = extract_figures("variance of $(0.07)B against forecast")
    assert fig.text == "$(0.07)B"
    assert fig.value == -0.07
    assert fig.absolute == -70_000_000
