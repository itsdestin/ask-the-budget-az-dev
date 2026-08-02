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
_FIGURE_RE = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?"     # $1,391,157,700 / $8,287.7
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
        value = float(raw.replace("$", "").replace(",", "").strip())
        scale = 1
        tail = answer[m.end():m.end() + 12]
        for pattern, mult in _SUFFIX:
            if pattern.match(tail):
                scale = mult
                break
        else:
            # No explicit suffix: inherit the table's declared unit, but
            # only for decimals — a fully grouped integer like
            # 1,391,157,700 is already absolute.
            if table_scale != 1 and "." in raw:
                scale = table_scale
        figures.append(Figure(raw, m.start(), m.end(), value, scale))
    return figures
