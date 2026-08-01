"""Mechanical scoring for Layer 2 agent transcripts.

This module is deliberately free of model calls: everything here can be
re-run over historical transcripts at zero cost, which is what makes
metric improvements retroactive (spec: 'Mechanical scorer — free,
decoupled').
"""
from __future__ import annotations

import math
import re

from eval.agent_schema import KeyFact

# A currency mention: optional $, digits with optional thousands commas
# and decimals, optional scale word/suffix. The $-or-scale requirement in
# currency_values() below keeps bare years ('FY 2025') out of the pool.
_CURRENCY_RE = re.compile(
    # The comma-grouped alternative MUST allow a decimal tail: without it
    # '$1,391.2 million' backtracks into '$1' + '391.2 million' — two wrong
    # numbers instead of one right one.
    #
    # The trailing lookahead used to be '(?![\w.])', which rejects a match
    # immediately followed by ANY '.' — including a bare sentence-ending
    # period with no digit after it. '$1,214,000,000.' has no legal way to
    # satisfy that lookahead at its true length, so the engine backtracks
    # the '(?:,\d{3})+' repetition, shedding trailing 3-digit groups one at
    # a time until it finds a stopping point followed by something other
    # than '.' — here, the very next comma — and silently returns
    # '1,214,000' instead of '1,214,000,000' (1000x too small). Since
    # "...totaled $X." is one of the most common sentence shapes in budget
    # prose, this was a routine input, not an edge case. The replacement,
    # '(?!\w)(?!\.\d)', splits the two backtracking hazards apart: '(?!\w)'
    # still blocks stopping mid-word/mid-digit-run, while '(?!\.\d)' only
    # blocks a '.' that is itself followed by a digit (a genuine decimal
    # continuation, e.g. the '.2' in '1,391.2'). A bare '.' with no digit
    # after it — sentence-final — no longer forces backtracking.
    r"(\$)?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(billion|million|thousand|[bmk])?(?!\w)(?!\.\d)",
    re.IGNORECASE,
)
_SCALE = {"b": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}

# 0.5% relative tolerance: accepts faithful roundings ('$1,391.2 million'
# for $1,391,157,700, ~0.003% off) while still rejecting a neighboring
# budget line. Authors needing exactness use kind=regex instead.
_REL_TOL = 0.005


def currency_values(text: str) -> set[float]:
    """Every dollar amount mentioned in text, normalized to plain floats."""
    values: set[float] = set()
    for dollar, num, scale in _CURRENCY_RE.findall(text):
        # Require a $ sign or a scale word — a bare number like '2025'
        # is a year or a count, not a currency mention.
        if not dollar and not scale:
            continue
        values.add(float(num.replace(",", "")) * _SCALE.get(scale.lower(), 1.0))
    return values


def fact_matches(fact: KeyFact, text: str) -> bool:
    """Does text contain the fact, within currency-formatting tolerance?"""
    if fact.kind == "string":
        return fact.value.lower() in text.lower()
    if fact.kind == "regex":
        return re.search(fact.value, text, re.IGNORECASE) is not None
    wanted = currency_values(fact.value)
    if not wanted:
        # An unparseable currency fact is an authoring error; failing
        # closed here would hide it as a permanent query failure.
        raise ValueError(f"key fact is not a parseable currency amount: {fact.value!r}")
    found = currency_values(text)
    return any(
        any(math.isclose(w, f, rel_tol=_REL_TOL) for f in found) for w in wanted
    )
