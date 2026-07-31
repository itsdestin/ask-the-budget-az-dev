"""The fiscal-year bounds exist in two places on purpose; pin them.

`harness/constants.py` is deliberately import-free beyond the stdlib —
building a prompt or a tool schema must not drag retrieval, LanceDB or
the ONNX models into the process. So it carries its own copy of the
plausible-fiscal-year window instead of importing
`retrieval/query_year.py`, and this test is what keeps the copy honest.

Why it matters: `FISCAL_YEAR_MIN/MAX` bound what the MODEL may pass in a
`fiscal_year` filter, while `MIN/MAX_PLAUSIBLE_YEAR` bound what the
PARSER will read out of a query. If the schema's floor drifted above the
parser's, there would be historical years the model could reach only by
accident — by wording its query so the parser caught the year — and no
way to ask for them deliberately.
"""
from __future__ import annotations

from harness.constants import FISCAL_YEAR_MAX, FISCAL_YEAR_MIN
from retrieval.query_year import MAX_PLAUSIBLE_YEAR, MIN_PLAUSIBLE_YEAR


def test_the_schema_bounds_match_the_parser_bounds():
    assert (FISCAL_YEAR_MIN, FISCAL_YEAR_MAX) == (
        MIN_PLAUSIBLE_YEAR,
        MAX_PLAUSIBLE_YEAR,
    )


def test_the_bounds_cover_the_oldest_edition_the_backfill_ingests():
    """data/jlbc-book-catalog.json's oldest edition is approps-fy1984.
    A floor above it would make the S20 backfill's whole point
    unreachable through the filter."""
    assert FISCAL_YEAR_MIN <= 1984
