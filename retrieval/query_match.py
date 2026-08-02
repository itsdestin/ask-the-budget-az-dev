"""Shared shape for anything parsed out of a query (spec Q2).

WHY this is one module rather than a convention repeated in each parser: the
filter-versus-boost decision is the safety-critical part of this feature, and
two copies of it would eventually disagree. A hard filter that fires on a bad
guess empties the page for a question the analyst asked in good faith, so the
rule deciding when that is allowed lives in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


class Confidence(StrEnum):
    EXACT = "exact"  # unambiguous: a hard filter is safe
    WEAK = "weak"  # fuzzy, ambiguous, or a stoplisted word: boost only


@dataclass(frozen=True)
class Match:
    value: str  # e.g. "agency:adc" or "approps-per-agency"
    confidence: Confidence
    matched_text: str  # the span of the query that produced it


def is_filterable(matches: Sequence[Match]) -> bool:
    """True only when EVERY match is exact.

    Deliberately all-or-nothing. A set containing one weak match must not
    hard-filter, because the weak one could be wrong and a wrong hard filter
    returns an empty page for a question the analyst asked in good faith.
    """
    return bool(matches) and all(m.confidence is Confidence.EXACT for m in matches)
