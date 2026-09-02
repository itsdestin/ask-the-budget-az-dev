"""retrieval/table_view.py — spec §5. Pure text in, labelled text out."""
from __future__ import annotations

from retrieval.table_view import LABELLED_MAX_CHARS, MERGED_NOTE, render_labelled

AHCCCS = "\n".join([
    "FY 2026 Budget",
    "\tFY 2024 ACTUAL\tFY 2025 ESTIMATE\tFY 2026 APPROVED",
    "OPERATING BUDGET\t\t\t",
    "Full Time Equivalent Positions\t2,358.3\t2,459.3\t2,459.3",
    "OPERATING SUBTOTAL\t155,570,300\t156,637,800\t197,263,200 1/2/",
    "DES Eligibility\t116,083,200\t98,906,500\t99,294,5003/",
    "SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds\t377,583,700 2,778,602,700\t455,300,200 3,032,812,300\t621,178,500 3,234,831,100",
    "Case Management Provider Wage Increases\t0\t1,000,000\t0",
])


def test_preamble_survives_and_header_rows_are_consumed():
    out = render_labelled(AHCCCS)
    assert out is not None
    lines = out.split("\n")
    assert lines[0] == "FY 2026 Budget"
    assert "FY 2024 ACTUAL\tFY 2025" not in out          # the header row itself is gone
    assert lines[1] == "OPERATING BUDGET"                 # group heading = label alone


def test_every_value_carries_its_column_label():
    out = render_labelled(AHCCCS)
    assert "Full Time Equivalent Positions | FY 2024 ACTUAL: 2,358.3 | FY 2025 ESTIMATE: 2,459.3 | FY 2026 APPROVED: 2,459.3" in out


def test_footnote_markers_are_peeled():
    out = render_labelled(AHCCCS)
    assert "FY 2026 APPROVED: 197,263,200 [1/2/]" in out
    assert "FY 2026 APPROVED: 99,294,500 [3/]" in out
    assert "99,294,5003/" not in out


def test_merged_cell_is_named_not_hidden():
    out = render_labelled(AHCCCS)
    assert f"FY 2026 APPROVED: 621,178,500 and 3,234,831,100 {MERGED_NOTE}" in out


def test_zero_is_a_value_and_empty_cells_are_omitted():
    out = render_labelled(AHCCCS)
    assert "Case Management Provider Wage Increases | FY 2024 ACTUAL: 0 | FY 2025 ESTIMATE: 1,000,000 | FY 2026 APPROVED: 0" in out
    text = "x\n\tFY 2024\tFY 2025\tFY 2026\nGeneral Fund\t1,000\t\t3,000"
    assert "General Fund | FY 2024: 1,000 | FY 2026: 3,000" in render_labelled(text)


def test_extra_column_beyond_the_header_gets_a_positional_label():
    text = "x\n\tFY 2024\tFY 2025\tFY 2026\nGeneral Fund\t1,000\t2,000\t\t4,000"
    assert "General Fund | FY 2024: 1,000 | FY 2025: 2,000 | column 5: 4,000" in render_labelled(text)


def test_no_header_or_no_table_rows_returns_none():
    assert render_labelled("FUND SOURCES\nGeneral Fund\t1\t2\t3") is None
    assert render_labelled("A prose passage with no tabs at all.") is None
    assert render_labelled("") is None


def test_size_cap():
    big = AHCCCS + "\n" + ("Row\t1\t2\t3\n" * 3000)
    assert len(big) > LABELLED_MAX_CHARS
    assert render_labelled(big) is None
