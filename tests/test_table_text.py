"""chunking/table_text.py — the vocabulary both phases of the operating-table
work share. Spec §3.1 step 6 and §5 rules 1 and 3."""
from __future__ import annotations

import pytest

from chunking.table_text import (
    find_header,
    figure_tokens,
    has_ladder_marker,
    normalise_label,
    peel_markers,
    split_figure_marker,
)


@pytest.mark.parametrize("word, figure, marker", [
    ("99,294,5003/", "99,294,500", "3/"),
    ("10,124,311,2008/-13/", "10,124,311,200", "8/-13/"),
    ("15,352,3001/", "15,352,300", "1/"),
    ("212.312/", "212.3", "12/"),
    ("2,358.34/", "2,358.3", "4/"),
    ("(1,234,500)3/", "(1,234,500)", "3/"),
    ("99,294,500", "99,294,500", None),
    ("5003/", "5003/", None),          # under 1,000 is ambiguous — left alone
    ("General", "General", None),
])
def test_split_figure_marker(word, figure, marker):
    assert split_figure_marker(word) == (figure, marker)


@pytest.mark.parametrize("cell, rendered", [
    ("99,294,5003/", "99,294,500 [3/]"),
    ("15,916,000 4/", "15,916,000 [4/]"),
    ("197,263,200 1/2/", "197,263,200 [1/2/]"),
    ("212.312/", "212.3 [12/]"),
    ("205,641,700 13/22", "205,641,700 13/22"),   # no trailing slash: not a marker
    ("377,583,700 2,778,602,700", "377,583,700 2,778,602,700"),
    ("", ""),
])
def test_peel_markers(cell, rendered):
    assert peel_markers(cell) == rendered


def test_figure_tokens_ignores_peeled_markers():
    assert figure_tokens("197,263,200 1/2/") == ["197,263,200"]
    assert figure_tokens("377,583,700 2,778,602,700") == ["377,583,700", "2,778,602,700"]
    assert figure_tokens("0") == ["0"]
    assert figure_tokens("SPECIAL LINE ITEMS") == []


def test_normalise_label_strips_markers_case_and_dashes():
    assert normalise_label("Medicaid Services 5/6/7/") == "MEDICAID SERVICES"
    assert normalise_label("SUBTOTAL – Other  Appropriated Funds") == "SUBTOTAL - OTHER APPROPRIATED FUNDS"
    assert normalise_label("  ") == ""


def test_has_ladder_marker():
    assert has_ladder_marker("x\nOPERATING SUBTOTAL\t1\t2")
    assert has_ladder_marker("TOTAL - ALL SOURCES\t1")
    assert not has_ladder_marker("Table 1\nBasic State Aid")


def test_find_header_two_rows_three_columns():
    rows = [
        ["", "FY 2024", "FY 2025", "FY 2026"],
        ["", "ACTUAL", "ESTIMATE", "APPROVED"],
        ["OPERATING BUDGET", "", "", ""],
    ]
    h = find_header(rows)
    assert h is not None
    assert h.rows == (0, 1)
    assert h.first_col == 1
    assert h.labels == {1: "FY 2024 ACTUAL", 2: "FY 2025 ESTIMATE", 3: "FY 2026 APPROVED"}


def test_find_header_one_row_merged_cells():
    rows = [["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"], ["General Fund", "1", "2", "3"]]
    h = find_header(rows)
    assert h.rows == (0,)
    assert h.labels[3] == "FY 2026 APPROVED"


def test_find_header_four_columns_fy2006_shape():
    """The FY2006 chunk: a one-year noise row above, a kind-only cell inside."""
    rows = [
        ["", "", "FY 2005", "JLBC Analyst: Nick Klingerman"],
        ["", "FY 2004 Actual", "Estimate", "FY 2006 Approved", "FY 2007 Approved"],
        ["", "", "", "", ""],
        ["OPERATING BUDGET", "", "", "", ""],
    ]
    h = find_header(rows)
    assert h.rows == (1,)
    assert h.labels == {1: "FY 2004 Actual", 2: "Estimate", 3: "FY 2006 Approved", 4: "FY 2007 Approved"}


def test_find_header_accepts_fy_without_space_and_none_when_absent():
    assert find_header([["", "FY2024", "FY2025"]]) is not None
    assert find_header([["FUND SOURCES", "", ""], ["General Fund", "1", "2"]]) is None
    assert find_header([]) is None
