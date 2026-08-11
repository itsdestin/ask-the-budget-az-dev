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

Two functions, deliberately separate: `parse_query_years` reports the
years the ANALYST named (that is what gets echoed back to them), and
`fiscal_year_filter` turns those into the year set actually filtered on,
which is wider. See ADJACENT_YEAR_WINDOW for why.
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

# How many adjacent fiscal years ride along with each year the analyst
# named, when the parsed years become a filter.
#
# WHY this is not 0: `chunks.fiscal_year` is the DOCUMENT's fiscal year,
# not the year the passage is ABOUT, and Arizona's document lifecycle
# routinely puts them one apart. A FY 2025 supplemental appropriation is
# enacted in the 2025 session's bill, which is the FY 2026 budget bill;
# the JLBC Appropriations Report for an enacted FY is published in the
# following cycle. Measured on the 34-query eval set (2026-07-31, real
# corpus), an exact-year filter dropped recall@20 from 100% to 93.1% —
# below gate G1's 95% bar — on exactly that shape: two queries saying
# "FY 2025" whose ground truth is a chunk of the FY 2026 budget bill.
#
# WHY not 2: measured at ±2 the filter is too loose to sharpen ranking at
# all — recall@5 falls back to the unfiltered baseline's 72.41%. ±1 keeps
# recall@5 at 82.76% AND restores recall@15/@20 to 96.55%/100%, so it
# strictly beats filtering nothing. It also still cuts a post-backfill
# 20-edition corpus to 3, which is what S21 needs it to do.
#
# The ±0 and ±2 numbers came from throwaway sweep runs (the pipeline
# monkeypatched to widen the window), so there is no committed artifact
# for them — the full four-row table is in the commit message of the
# change that introduced this constant. The ±1 run IS committed under
# eval/results/.
ADJACENT_YEAR_WINDOW = 1

# Four digits, optionally FY-prefixed, standing alone as a token.
# `(?<![\w$])` is doing two jobs: the \w half rejects digits embedded in a
# larger token ("HB2019", "account 42026"), and the $ half rejects money
# ("a $2026 grant"). Plain \b would accept both.
_FOUR_DIGIT = re.compile(r"(?<![\w$])(?:fy[\s-]?)?(\d{4})(?![\w])", re.IGNORECASE)

# Text that, when it sits immediately in front of a four-digit number,
# means the number is NOT a fiscal year.
#
# WHY this exists: Arizona House bills are numbered from 2001 up, so
# HB 2001 through HB 2035 land squarely inside the plausible-year window.
# `(?<![\w$])` on _FOUR_DIGIT catches the unspaced "HB2019" but not the
# spaced "HB 2019", and bill-number lookup is the fiscal-note corpus's
# primary access path — a coordinator searching "HB 2019" would have been
# silently filtered to session years 2018-2020 and shown the wrong notes,
# or none. Statute cites ("A.R.S. 41-1994") and phone numbers fail the
# same way through the trailing digit-hyphen.
_YEAR_LOOKALIKE_PREFIX = re.compile(
    r"(?:"
    # Bill / resolution designators: HB, S.B., HCR, SJR, HM, SR …
    r"\b[hs]\.?\s?(?:b|c\.?\s?r|j\.?\s?r|m|r)\.?\s*"
    # Citation words that number things in the same range as fiscal years
    r"|\b(?:chapter|ch|title|section|sec|article|art|laws|prop|proposition)\.?\s*"
    r"|§\s*"
    # A hyphenated run: statute sections (41-1994), phone numbers
    r"|\d-\s*"
    r")$",
    re.IGNORECASE,
)

# Two digits that are explicitly marked as a fiscal year — either by an
# "fy" prefix ("fy26", "FY 19") or by the elided-century apostrophe
# ("'19"). Both straight and curly apostrophes appear in pasted text.
_TWO_DIGIT = re.compile(r"(?<![\w$])(?:fy[\s-]?|['‘’])(\d{2})(?![\w])", re.IGNORECASE)

# JLBC's own URL convention: azjlbc.gov/26AR/508.pdf, /21baseline/adc.pdf.
# The type suffix is REQUIRED — it is what makes the two digits a fiscal
# year rather than an ordinary number.
#
# `ar` and `baseline` are JLBC's, read off the website's directory names.
# `br`, `afr` and `exec` are OURS (Destin, 2026-08-11): the published
# convention covers only two of the corpus's report types, so an analyst who
# learned the pattern hit a wall on Annual Financial Reports and Executive
# Budgets. The budget bill deliberately gets none — there is one per year and
# shorthand earns nothing.
#
# Alternation is ordered LONGEST FIRST. The trailing `(?![\w])` already
# prevents "26afr" from being read as "26ar" + stray "f", but relying on a
# lookahead to undo a wrong alternative is a subtlety the next reader
# shouldn't have to re-derive.
_JLBC_SHORTHAND = re.compile(
    r"(?<![\w$])(\d{2})\s?(baseline|exec|afr|br|ar)(?![\w])", re.IGNORECASE
)

# PUBLIC (2026-08-11): `app/search_terms.py` inverts this to label documents
# with their own shorthand, so the filter box and the query parser cannot
# disagree about what "26afr" means. It was private while retrieval was its
# only consumer.
SHORTHAND_DOC_TYPE = {
    "ar": "approps-per-agency",
    "baseline": "baseline-per-agency",
    "br": "baseline-per-agency",
    "afr": "afr",
    "exec": "governors-budget",
}

# The shorthand is a 20xx-only convention, so this form never expands into
# the 1900s even though `_expand_two_digit` would happily read "99" as 1999.
#
# WHY: the convention IS the website's directory naming, and JLBC only ever
# used it from FY2002 on (02recbk, 03app, … 13AR, 21baseline, 27baseline —
# see data/jlbc-book-catalog.json). Pre-2000 editions are single files with
# the year spelled out, FY1984AppropRpt.pdf. So "99ar" is not a reference to
# anything that exists, and reading it as FY1999 would hard-filter a query
# onto a year with no such document in it.
_SHORTHAND_MIN_YEAR = 2000


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


def iter_jlbc_shorthand(query: str) -> list[tuple[int, str, str]]:
    """`(fiscal_year, doc_type, matched_text)` for every JLBC shorthand token.

    The third element exists for `query_doc_type.parse_query_doc_types`,
    which reports the span of the query each match came from. Everything
    else wants `parse_jlbc_shorthand`, which drops it.
    """
    out: list[tuple[int, str, str]] = []
    for match in _JLBC_SHORTHAND.finditer(query or ""):
        year = _expand_two_digit(int(match.group(1)))
        if year is None or year < _SHORTHAND_MIN_YEAR:
            continue
        # Same designator guard the four-digit rule uses, for the same reason
        # — and it matters MORE here. The optional space in the pattern lets
        # "chapter 21 baseline" look like shorthand, and unlike a nonsense
        # year that guess would SUCCEED: FY2021 baselines exist, so the
        # pipeline's empty-result fallback never fires and the analyst
        # silently gets one year's documents for a query about something
        # else. Checked against what precedes the DIGITS, not the whole
        # match, mirroring parse_query_years.
        if _YEAR_LOOKALIKE_PREFIX.search(query[: match.start(1)]):
            continue
        out.append((year, SHORTHAND_DOC_TYPE[match.group(2).lower()], match.group(0)))
    return out


def parse_jlbc_shorthand(query: str) -> list[tuple[int, str]]:
    """`(fiscal_year, doc_type)` pairs from JLBC's own URL convention.

    WHY this exists: the corpus's source URLs are literally
    azjlbc.gov/26AR/508.pdf and /21baseline/adc.pdf, so an analyst who works
    from those files types "27ar" without thinking about it. Reusing the
    publisher's own shorthand costs one regex and removes a whole class of
    zero-result query.

    Requires the type suffix. A bare "27" stays with the ordinary two-digit
    rule, which needs an "FY" or apostrophe prefix — otherwise every
    "27 positions" in a budget table becomes a fiscal year.
    """
    return [(year, doc_type) for year, doc_type, _text in iter_jlbc_shorthand(query)]


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
        if not (MIN_PLAUSIBLE_YEAR <= year <= MAX_PLAUSIBLE_YEAR):
            continue
        # The digits are checked against what precedes THEM, not what
        # precedes the whole match, so an "FY " prefix inside the match
        # can't shield a designator sitting in front of it.
        if _YEAR_LOOKALIKE_PREFIX.search(query[: match.start(1)]):
            continue
        years.add(year)

    for match in _TWO_DIGIT.finditer(query):
        expanded = _expand_two_digit(int(match.group(1)))
        if expanded is not None:
            years.add(expanded)

    # "27ar" / "26baseline" carry a year the two rules above cannot see: the
    # digits have no FY prefix and no apostrophe, and are glued to a word.
    years.update(year for year, _doc_type in parse_jlbc_shorthand(query))

    return sorted(years)


def fiscal_year_filter(years: list[int]) -> list[int]:
    """Widen named years into the fiscal years to actually filter on.

    Each named year brings its ADJACENT_YEAR_WINDOW neighbours along,
    because a passage about FY N frequently lives in a document stamped
    FY N±1. Returns `[]` for `[]` so "no years named" stays "no filter".

    The window is NOT clamped to MIN/MAX_PLAUSIBLE_YEAR: those bound what
    a human could plausibly have MEANT, and a filter value no document
    carries simply matches nothing.
    """
    if not years:
        return []
    widened: set[int] = set()
    for year in years:
        for offset in range(-ADJACENT_YEAR_WINDOW, ADJACENT_YEAR_WINDOW + 1):
            widened.add(year + offset)
    return sorted(widened)
