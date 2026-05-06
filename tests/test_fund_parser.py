"""Tests for funds/parser.py.

s18-style cross-cut tables follow the documented shape (plan §4.1 step 2):
agency name (full row span) → one row per fund the agency uses → agency total.

The parser walks rows once, tracking the "current agency" as boundaries cross,
and emits one FundAgencyRow per fund row. Total rows are skipped; header rows
drive auto-detection of FY → column mapping.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.readers.mineru_reader import MinerUReader
from funds.parser import FundAgencyRow, parse_s18_table

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_S18 = FIXTURES / "mineru-jlbc-baseline-s18.json"


def _load_s18():
    return MinerUReader().read(FIXTURE_S18)


# --- happy path ------------------------------------------------------------


def test_parse_returns_list_of_fund_agency_rows():
    doc = _load_s18()
    rows = parse_s18_table(doc)
    assert rows
    for r in rows:
        assert isinstance(r, FundAgencyRow)


def test_parse_emits_one_row_per_fund_per_agency():
    """Fixture: 3 agencies × (3 + 2 + 2) funds = 7 fund rows. No total rows."""
    rows = parse_s18_table(_load_s18())
    assert len(rows) == 7


def test_parse_agencies_are_three():
    rows = parse_s18_table(_load_s18())
    agencies = sorted(set(r.agency_name for r in rows))
    assert agencies == [
        "Department of Administration",
        "Department of Corrections",
        "Department of Health Services",
    ]


def test_parse_extracts_fund_names_for_administration():
    rows = parse_s18_table(_load_s18())
    adm = [r for r in rows if r.agency_name == "Department of Administration"]
    fund_names = sorted(r.fund_name for r in adm)
    assert fund_names == ["Aviation Fund", "General Fund", "State Highway Fund"]


def test_parse_amounts_keyed_by_fiscal_year():
    """Auto-detect: header is `Fund | FY2026 | FY2027`. Amount columns map
    to FY 2026 / 2027 by index, not by string parsing of each row."""
    rows = parse_s18_table(_load_s18())
    aviation = next(
        r for r in rows
        if r.agency_name == "Department of Administration"
        and r.fund_name == "Aviation Fund"
    )
    assert aviation.amounts == {2026: "$5,000,000", 2027: "$5,200,000"}


def test_parse_skips_department_total_rows():
    """The 'Department Total' rows are not funds and shouldn't appear in output."""
    rows = parse_s18_table(_load_s18())
    assert all("Total" not in r.fund_name for r in rows)


def test_parse_skips_header_row():
    rows = parse_s18_table(_load_s18())
    assert all(r.fund_name not in ("Fund", "FY2026", "FY2027") for r in rows)


# --- header detection ------------------------------------------------------


def test_parse_handles_alternative_fy_header_styles(tmp_path):
    """Header may be `FY 2026` (space) or `FY26` or bare `2026`. All should
    parse to the integer fiscal year."""
    import json

    target = tmp_path / "alt-headers.json"
    target.write_text(
        json.dumps({
            "extractor": "mineru-3.1.6",
            "source_pdf": "fake.pdf",
            "page": 1,
            "blocks": [{
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><th>Fund</th><th>FY 2026</th><th>FY27</th></tr>"
                    '<tr><td colspan="3">Department of X</td></tr>'
                    "<tr><td>General Fund</td><td>$1,000</td><td>$1,100</td></tr>"
                    "</table>"
                ),
                "bbox": [0, 0, 100, 100],
                "page_idx": 0,
            }],
        })
    )
    rows = parse_s18_table(MinerUReader().read(target))
    assert rows
    assert rows[0].amounts == {2026: "$1,000", 2027: "$1,100"}


# --- agency-boundary detection ---------------------------------------------


def test_parse_handles_agency_row_without_colspan(tmp_path):
    """Some MinerU outputs lose the colspan attribute — first cell holds the
    name, remaining cells empty. Parser must still detect the boundary."""
    import json

    target = tmp_path / "no-colspan.json"
    target.write_text(
        json.dumps({
            "extractor": "mineru-3.1.6",
            "source_pdf": "fake.pdf",
            "page": 1,
            "blocks": [{
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><th>Fund</th><th>FY2026</th><th>FY2027</th></tr>"
                    "<tr><td>Department of X</td><td></td><td></td></tr>"
                    "<tr><td>General Fund</td><td>$1</td><td>$2</td></tr>"
                    "</table>"
                ),
                "bbox": [0, 0, 100, 100],
                "page_idx": 0,
            }],
        })
    )
    rows = parse_s18_table(MinerUReader().read(target))
    assert len(rows) == 1
    assert rows[0].agency_name == "Department of X"
    assert rows[0].fund_name == "General Fund"


# --- empty / degenerate inputs ---------------------------------------------


def test_parse_empty_doc_returns_empty_list():
    """No tables → no rows."""
    from chunking.readers.types import ExtractedDocument

    doc = ExtractedDocument(source_path=Path("x"), extractor="mineru")
    assert parse_s18_table(doc) == []


def test_parse_table_without_recognizable_header_returns_empty(tmp_path):
    """No FY columns identifiable in header → can't safely emit rows."""
    import json

    target = tmp_path / "no-fy.json"
    target.write_text(
        json.dumps({
            "extractor": "mineru-3.1.6",
            "source_pdf": "fake.pdf",
            "page": 1,
            "blocks": [{
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><th>A</th><th>B</th><th>C</th></tr>"
                    '<tr><td colspan="3">Department of X</td></tr>'
                    "<tr><td>General Fund</td><td>$1</td><td>$2</td></tr>"
                    "</table>"
                ),
                "bbox": [0, 0, 100, 100],
                "page_idx": 0,
            }],
        })
    )
    assert parse_s18_table(MinerUReader().read(target)) == []


def test_parse_fund_row_before_any_agency_is_skipped(tmp_path):
    """A fund-shaped row appearing before the first agency boundary has no
    agency to bind to — drop it (with the alternative being to bind it to
    a synthetic 'unknown' agency, which silently corrupts output)."""
    import json

    target = tmp_path / "orphan-fund.json"
    target.write_text(
        json.dumps({
            "extractor": "mineru-3.1.6",
            "source_pdf": "fake.pdf",
            "page": 1,
            "blocks": [{
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><th>Fund</th><th>FY2026</th><th>FY2027</th></tr>"
                    "<tr><td>Orphan Fund</td><td>$1</td><td>$2</td></tr>"
                    '<tr><td colspan="3">Department of X</td></tr>'
                    "<tr><td>General Fund</td><td>$3</td><td>$4</td></tr>"
                    "</table>"
                ),
                "bbox": [0, 0, 100, 100],
                "page_idx": 0,
            }],
        })
    )
    rows = parse_s18_table(MinerUReader().read(target))
    assert [r.fund_name for r in rows] == ["General Fund"]
