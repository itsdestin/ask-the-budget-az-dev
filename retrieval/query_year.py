"""Parse fiscal years out of a natural-language query (spec S21, layer 1).

An explicit year in the query becomes a HARD fiscal-year filter in
`retrieve()` (unless the caller already passed one). That is the whole
reason this module is stricter than the mockup search engine
(`webapp/reference/assets/search/search.js`) it was ported from: there, a
misread number only added a +0.15 score bump to documents whose
fiscal_year matched, so a wrong guess lifted nothing and cost nothing.
Here a wrong guess DELETES every other fiscal year from the result set.

Ported forms (mockup line refs are to that file's `qYears` block):
  - four-digit, bare or FY-prefixed:  "2013", "FY 2019", "fy2019"
  - two-digit with an FY prefix:      "fy26", "FY 19"
  - two-digit with an apostrophe:     "'19", "’19"   (added here)

Deliberately NOT ported: the mockup's bare two-digit form ("26" → 2026).
It reads "26 caseworkers" and "chapter 19" as years, which was harmless
as a soft bump and is destructive as a filter.

Known limitation: ranges are not expanded. "FY2019 through FY2021" yields
[2019, 2021], not [2019, 2020, 2021] — no range word is parsed.
"""
from __future__ import annotations

import re

# Plausible fiscal-year window. The floor is the oldest edition in
# data/jlbc-book-catalog.json (approps-fy1984), NOT a round number: the
# S20 backfill ingests those editions, and a floor of 1990 would silently
# refuse to filter on FY1984-1989 — the exact years this feature exists
# to make reachable. The ceiling leaves headroom for Executive Budgets
# published a few cycles ahead of the current one.
MIN_PLAUSIBLE_YEAR = 1984
MAX_PLAUSIBLE_YEAR = 2035

# Four digits, optionally FY-prefixed, standing alone as a token.
# `(?<![\w$])` is doing two jobs: the \w half rejects digits embedded in a
# larger token ("HB2019", "account 42026"), and the $ half rejects money
# ("a $2026 grant"). Plain \b would accept both.
_FOUR_DIGIT = re.compile(r"(?<![\w$])(?:fy[\s-]?)?(\d{4})(?![\w])", re.IGNORECASE)

# Two digits that are explicitly marked as a fiscal year — either by an
# "fy" prefix ("fy26", "FY 19") or by the elided-century apostrophe
# ("'19"). Both straight and curly apostrophes appear in pasted text.
_TWO_DIGIT = re.compile(r"(?<![\w$])(?:fy[\s-]?|['‘’])(\d{2})(?![\w])", re.IGNORECASE)


def _expand_two_digit(n: int) -> int | None:
    """Expand a two-digit shorthand to whichever century lands inside the
    plausible window, or None if neither does.

    The two candidate windows are disjoint by construction (20xx covers
    n <= 35, 19xx covers n >= 84 given MIN/MAX above), so there is never
    an ambiguous case to break a tie on.
    """
    for candidate in (2000 + n, 1900 + n):
        if MIN_PLAUSIBLE_YEAR <= candidate <= MAX_PLAUSIBLE_YEAR:
            return candidate
    return None


def parse_query_years(query: str) -> list[int]:
    """Fiscal years named in `query`, sorted ascending and de-duplicated.

    Returns `[]` when the query names none — which is the signal callers
    use to mean "no hard filter, this query is year-agnostic".
    """
    if not query or not query.strip():
        return []

    years: set[int] = set()

    for match in _FOUR_DIGIT.finditer(query):
        year = int(match.group(1))
        if MIN_PLAUSIBLE_YEAR <= year <= MAX_PLAUSIBLE_YEAR:
            years.add(year)

    for match in _TWO_DIGIT.finditer(query):
        expanded = _expand_two_digit(int(match.group(1)))
        if expanded is not None:
            years.add(expanded)

    return sorted(years)
