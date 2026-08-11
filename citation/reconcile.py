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


def _close(a: float, goal: float, tol: float) -> bool:
    # An ABSOLUTE tolerance, not a relative one: the question is whether
    # the arithmetic lands inside the interval the target's own rendering
    # certifies, and that interval is fixed by how the target was written.
    # This also removes the old goal == 0 special case — a zero target
    # just gets the ±0.5 floor like any other exact integer.
    return abs(a - goal) <= tol


def reconcile(target: Figure, linked: list[Figure]) -> Derivation | None:
    goal = target.absolute
    # The result's WRITTEN precision is what an arithmetic claim must hit
    # (spec A5). The old flat 1% accepted 16.77 as "explaining" a stated
    # 16.83 billion — different numbers (memo §5.3). A rounded
    # restatement still reconciles, because a rounded target carries a
    # correspondingly wide interval: "$1.06 billion" certifies ±5M, which
    # is exactly the slack 1,058,400,000 needs.
    tol = max(target.halfwidth, 0.5)
    values = [x.absolute for x in linked]

    # A restatement of a single figure is a one-input "sum".
    for i, v in enumerate(values):
        if _close(v, goal, tol):
            return Derivation("sum", [i])

    for n in (2, 3):
        if n > _MAX_INPUTS:
            break
        for combo in combinations(range(len(values)), n):
            if _close(sum(values[i] for i in combo), goal, tol):
                return Derivation("sum", list(combo))

    for a, b in combinations(range(len(values)), 2):
        # Magnitude on BOTH sides: an answer may write the same gap as
        # "$3.59B" or as accounting-negative "$(3.59)B" depending on
        # which way its column subtracts. Comparing a positive
        # difference against a signed goal never matched the latter.
        if _close(abs(values[a] - values[b]), abs(goal), tol):
            return Derivation("difference", [a, b])
        # percent change in either direction, against the same absolute
        # tolerance. A percent target's own halfwidth is tiny ("12.4%"
        # certifies ±0.05), so in practice the ±0.5 floor is what applies
        # — half a percentage point, which is the right slack for a
        # figure the model rounded.
        for x, y in ((a, b), (b, a)):
            if values[x] and _close((values[y] - values[x]) / values[x] * 100,
                                    goal, tol):
                return Derivation("percent_change", [x, y])
    return None
