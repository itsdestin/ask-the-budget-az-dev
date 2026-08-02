"""Explain a figure that appears in no source as arithmetic over figures
that do.

Roughly 6% of stated figures are computed — year-over-year deltas, totals,
percent changes, restatements. Without this they would all read
"unverified", which is both noisy and wrong: they ARE supported, just
indirectly. With it, a derived figure can show exactly what it came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from citation.figures import Figure

# Restatements round hard ("$1.06 billion" for 1,058,400,000), so this is
# looser than the matcher's tolerance. A false derivation is cheap: it
# still tells the analyst the figure is computed, not sourced.
_REL_TOL = 0.01
# Beyond three inputs a "sum" stops being an explanation a reader can
# check at a glance, and the combinatorics stop being free.
_MAX_INPUTS = 3


@dataclass(frozen=True)
class Derivation:
    operation: str
    inputs: list[int]
    # No hand-written __eq__: @dataclass generates one and would silently
    # overwrite it. The generated version compares the list by value,
    # which is exactly what the tests expect.


def _close(a: float, b: float) -> bool:
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) <= abs(b) * _REL_TOL


def reconcile(target: Figure, linked: list[Figure]) -> Derivation | None:
    goal = target.absolute
    values = [x.absolute for x in linked]

    # A restatement of a single figure is a one-input "sum".
    for i, v in enumerate(values):
        if _close(goal, v):
            return Derivation("sum", [i])

    for n in (2, 3):
        if n > _MAX_INPUTS:
            break
        for combo in combinations(range(len(values)), n):
            if _close(goal, sum(values[i] for i in combo)):
                return Derivation("sum", list(combo))

    for a, b in combinations(range(len(values)), 2):
        if _close(goal, abs(values[a] - values[b])):
            return Derivation("difference", [a, b])
        # percent change in either direction
        for x, y in ((a, b), (b, a)):
            if values[x] and _close(goal,
                                    (values[y] - values[x]) / values[x] * 100):
                return Derivation("percent_change", [x, y])
    return None
