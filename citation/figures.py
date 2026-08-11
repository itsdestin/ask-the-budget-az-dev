"""Find every figure an answer states, with its exact offsets and the
scale its context implies.

Offsets are the whole point: the chip is placed at the figure's position
in the answer, so chips land on the number they support and number
themselves in reading order. Scale is the other half — the answer renders
"$8,287.7" beneath a "$ Millions" header while the source says
"8,287,700,000", which was 67% of figures in the 2026-08-01 baseline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A figure is a grouped integer (1,234,567) or a decimal with a currency
# marker ($8,287.7). A bare ungrouped integer is NOT a figure — it is far
# more often a count, a year, or a page number than a budget amount.
#
# The parenthesised alternatives are accounting notation for a NEGATIVE:
# a variance column writes "$(0.07)B", not "-$0.07B". Without them such a
# cell yields no figure at all — not an uncited figure, an invisible one —
# so a whole "actual vs forecast" column could be neither cited nor
# derived. Seen live 2026-08-11.
_FIGURE_RE = re.compile(
    r"\$\s?\(\d{1,3}(?:,\d{3})+(?:\.\d+)?\)"  # $(1,234.5)
    r"|\$\s?\(\d+\.\d+\)"                     # $(0.07)
    r"|\(\d{1,3}(?:,\d{3})+(?:\.\d+)?\)"      # (1,234)
    r"|\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?"     # $1,391,157,700 / $8,287.7
    r"|\$\s?\d+\.\d+"                         # $1.06
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"          # 101,602
)
# NO YEAR GUARD, deliberately. An earlier version skipped a match preceded by
# "FY" / "fiscal year" / "in", to keep "FY 2026" from reading as an amount.
# It had no true positives available to it: _FIGURE_RE requires comma-grouping
# or a currency marker with a decimal, so a bare four-digit year can never
# match it in the first place (pinned by
# test_no_year_can_reach_the_extractor_in_the_first_place). All it did was
# cost real money — "took in $27,362,036.72" lost its chip in a live answer on
# 2026-08-02, because "in" before a dollar amount is ordinary English.
_SUFFIX = (
    (re.compile(r"^\s*billion", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"^\s*million", re.IGNORECASE), 1_000_000),
    (re.compile(r"^\s*thousand", re.IGNORECASE), 1_000),
    # Abbreviated forms. Measured on the 2026-08-02 baseline: answers
    # write "+$243.5M" far more often than "$243.5 million", and without
    # these the scale reads as 1 — which both breaks the match and makes
    # the specificity floor judge a $243 million figure as three digits.
    # The \b keeps "M" from firing on "$104.8 Mesa" or "$1.5 Basic".
    (re.compile(r"^\s?B\b"), 1_000_000_000),
    (re.compile(r"^\s?M\b"), 1_000_000),
    (re.compile(r"^\s?K\b", re.IGNORECASE), 1_000),
)
# A markdown table header may declare the unit once for every cell below.
_HEADER_SCALE = (
    (re.compile(r"\$?\s*billions?\b", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"\$?\s*millions?\b", re.IGNORECASE), 1_000_000),
    (re.compile(r"\$?\s*thousands?\b", re.IGNORECASE), 1_000),
)


@dataclass(frozen=True)
class Figure:
    text: str
    start: int
    end: int
    value: float
    scale: int

    @property
    def absolute(self) -> float:
        """The figure in plain dollars, scale applied."""
        return self.value * self.scale

    @property
    def halfwidth(self) -> float:
        """Absolute half-width of the interval this rendering certifies
        (spec A4). "$10.3M" certifies [10.25M, 10.35M]; a grouped integer
        certifies ±0.5. One rule replaces the flat ±0.1% window and
        reconcile's flat 1% — both of which accepted values the written
        form does not actually support."""
        # Strip everything that is not a digit or a decimal point: the text
        # may carry a currency marker, accounting parentheses, and now its
        # scale suffix ("$13.98B", "$(0.07)B"). Splitting the raw string on
        # "." would count "98B" as three decimal places and certify an
        # interval a thousand times too narrow.
        numeral = re.sub(r"[^0-9.]", "", self.text)
        decimals = len(numeral.split(".")[1]) if "." in numeral else 0
        return 0.5 * (10 ** -decimals) * self.scale


def written_significant_digits(raw: str) -> int:
    """Distinctiveness of a figure AS WRITTEN — digits with leading and
    trailing zeros stripped. "$12.49 billion" scores 4, not 11: its
    magnitude is huge but only four digits fingerprint it, which is why
    rounded billions false-link ~10x more often than exact integers
    (review memo §5.2/§5.4)."""
    digits = re.sub(r"[^0-9]", "", raw)
    digits = digits.lstrip("0").rstrip("0")
    return len(digits)


def _table_scale(answer: str) -> int:
    """The unit a markdown table header declares, if any. A header states
    the unit once and every cell inherits it, so a per-figure suffix scan
    alone would read every cell as unscaled."""
    for line in answer.splitlines():
        if line.lstrip().startswith("|"):
            for pattern, scale in _HEADER_SCALE:
                if pattern.search(line):
                    return scale
    return 1


def extract_figures(answer: str) -> list[Figure]:
    table_scale = _table_scale(answer)
    figures: list[Figure] = []
    for m in _FIGURE_RE.finditer(answer):
        raw = m.group(0)
        # A percentage is virtually always computed, not quoted.
        if answer[m.end():m.end() + 1] == "%":
            continue
        negative = "(" in raw
        value = float(re.sub(r"[^0-9.]", "", raw))
        if negative:
            value = -value
        scale = 1
        suffix_len = 0
        tail = answer[m.end():m.end() + 12]
        for pattern, mult in _SUFFIX:
            hit = pattern.match(tail)
            if hit:
                scale = mult
                # The suffix is PART OF THE FIGURE. Ending the span at the
                # digits put the citation chip inside the amount — the
                # analyst read "$13.98[1]B" — because the chip is rendered
                # at `end`. It also makes the tag gap start with a stray
                # "B" for no reason.
                suffix_len = hit.end()
                break
        else:
            # No explicit suffix: inherit the table's declared unit, but
            # only for decimals — a fully grouped integer like
            # 1,391,157,700 is already absolute.
            if table_scale != 1 and "." in raw:
                scale = table_scale
        end = m.end() + suffix_len
        figures.append(Figure(answer[m.start():end], m.start(), end,
                              value, scale))
    return figures
