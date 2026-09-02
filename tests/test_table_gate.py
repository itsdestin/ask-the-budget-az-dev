"""chunking/table_gate.py — spec §4. A rebuilt table is accepted only when
its published subtotals equal the sum of their rows in every column."""
from __future__ import annotations

from chunking.table_gate import count_figure_rows, has_fused_marker, has_merged_cell, reconcile


def _t(*lines: str) -> list[list[str]]:
    return [line.split("\t") for line in lines]


AHCCCS = _t(
    "OPERATING BUDGET\t\t",
    "Full Time Equivalent Positions\t2,358.3\t2,459.3",
    "Personal Services\t100\t200",
    "Equipment\t50\t50",
    "OPERATING SUBTOTAL\t150\t250 1/2/",
    "SPECIAL LINE ITEMS\t\t",
    "Administration\t\t",
    "DES Eligibility\t10\t20 3/",
    "Medicaid Services 5/6/7/\t\t",
    "Traditional Medicaid Services\t40\t30",
    "AGENCY TOTAL\t200\t300",
    "FUND SOURCES\t\t",
    "General Fund\t120\t180",
    "Other Appropriated Funds\t\t",
    "Budget Neutrality Compliance Fund\t30\t20",
    "SUBTOTAL - Other Appropriated Funds\t30\t20",
    "SUBTOTAL - Appropriated Funds\t150\t200",
    "Expenditure Authority Funds\t\t",
    "AHCCCS Fund\t50\t100",
    "SUBTOTAL - Expenditure Authority Funds\t50\t100",
    "SUBTOTAL - Appropriated/Expenditure Authority Funds\t200\t300",
    "Other Non-Appropriated Funds\t5\t5",
    "Federal Funds\t(5)\t10",
    "TOTAL - ALL SOURCES\t200\t315",
)


def test_reconciling_three_section_ladder_passes():
    result = reconcile(AHCCCS)
    assert result.passed, [c for c in result.checks if not c.ok]
    rules = {c.label for c in result.checks}
    assert "TOTAL - ALL SOURCES" in rules and "AGENCY TOTAL = SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS" in rules


def test_one_wrong_digit_fails_and_names_the_row_and_column():
    bad = [list(r) for r in AHCCCS]
    bad[3][2] = "51"  # Equipment, column 2
    result = reconcile(bad)
    assert not result.passed
    failed = [c for c in result.checks if not c.ok]
    assert failed[0].label == "OPERATING SUBTOTAL" and failed[0].column == 1
    assert failed[0].expected == 251 and failed[0].actual == 250   # the nearest span, named


def test_fy2006_four_columns_no_operating_subtotal_variant_labels():
    table = _t(
        "OPERATING BUDGET\t\t\t\t",
        "Full Time Equivalent Positions\t186.0\t186.0\t186.0\t186.0",
        "Personal Services\t3,537,100\t4,865,100\t4,947,800\t4,865,100",
        "Employee Related Expenditures\t740,400\t1,131,200\t1,291,900\t1,153,500",
        "AGENCY TOTAL\t4,277,500\t5,996,300\t6,239,7001/\t6,018,600 1/",
        "FUND SOURCES\t\t\t\t",
        "Other Funds\t\t\t\t",
        "Arizona Exposition and State Fair Fund\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "SUBTOTAL - Other Funds\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "SUBTOTAL - Appropriated Funds\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "TOTAL - ALL SOURCES\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
    )
    result = reconcile(table)
    assert result.passed, [c for c in result.checks if not c.ok]


def test_fte_row_is_excluded_from_every_sum():
    table = _t("Full Time Equivalent Positions\t10.0", "Personal Services\t5", "OPERATING SUBTOTAL\t5")
    assert reconcile(table).passed


def test_accounting_negative_sums():
    table = _t("A\t(100)", "B\t300", "OPERATING SUBTOTAL\t200")
    assert reconcile(table).passed


def test_empty_body_cell_is_zero_and_blank_check_cell_is_skipped():
    table = _t("A\t100\t", "B\t\t50", "OPERATING SUBTOTAL\t100\t50", "Federal Funds\t1\t", "TOTAL - ALL SOURCES\t101\t")
    result = reconcile(table)
    assert result.passed
    assert all(c.column == 0 or c.label != "TOTAL - ALL SOURCES" for c in result.checks)


def test_no_check_row_cannot_be_verified():
    result = reconcile(_t("A\t1", "B\t2"))
    assert not result.passed and result.reason == "no check row"


def test_unrecognised_check_label_uses_the_generic_rule():
    assert reconcile(_t("A\t1", "B\t2", "SUBTOTAL - Widgets\t3")).passed
    assert not reconcile(_t("A\t1", "B\t2", "SUBTOTAL - Widgets\t4")).passed


def test_adc_nested_subtotals_inside_the_operating_block():
    """FY2023 ADC: `Personal Services Subtotal` and `Other Operating
    Expenditures Subtotal` sit INSIDE the operating block, and
    `OPERATING SUBTOTAL` is the sum of those two plus the loose rows."""
    table = _t(
        "OPERATING BUDGET\t",
        "Correctional Officer Personal Services\t100",
        "All Other Personal Services\t50",
        "Personal Services Subtotal\t150",
        "Employee Related Expenditures\t30",
        "Other Operating Expenditures\t",
        "Food\t10",
        "Equipment\t5",
        "Other Operating Expenditures Subtotal\t15",
        "OPERATING SUBTOTAL\t195",
        "AGENCY TOTAL\t195",
    )
    result = reconcile(table)
    assert result.passed, [c for c in result.checks if not c.ok]


def test_row_counting_helpers():
    minerU = _t("\tFY 2024\tFY 2025", "A\t1\t2", "SUBTOTAL - X SUBTOTAL - Y\t1 2\t2 4", "G\t\t")
    assert count_figure_rows(minerU) == 2          # the header row's years are not figures
    assert has_merged_cell(minerU)
    assert not has_merged_cell(_t("A\t1\t2"))
    assert has_fused_marker(_t("A\t99,294,5003/"))
    assert not has_fused_marker(_t("A\t99,294,500 3/"))


def test_accounting_dash_is_zero_even_alongside_other_tokens():
    """`-` is JLBC's printed zero. `figure_tokens` treats a lone `-` as a
    figure token even when it is not the WHOLE cell (a footnote marker on
    its own token, extra whitespace) -- found on the live corpus (G-OT0
    calibration): `parse_figure("-")` used to crash `Decimal("-")` because
    the whole-cell shortcut in the old code only fired when the cell
    stripped to exactly `-`, and a non-empty `tokens` list skipped it."""
    table = _t("A\t-", "B\t300", "OPERATING SUBTOTAL\t300")
    assert reconcile(table).passed
