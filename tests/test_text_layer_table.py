"""chunking/readers/text_layer_table.py — spec §3.1. Every page here is
built in the test with PyMuPDF at real coordinates (the AHCCCS FY2026
page: label at x=52, three columns centred at x=305/404/503, figures
right-aligned to x=334/433/532, 9-pt text, markers 6-pt at x=534).

WHY synthetic pages rather than a committed PDF fixture: spec §8 — the
suite may not reach the network and may not open the real store, and a
coordinate we place ourselves is a coordinate we can reason about when a
test fails. The numbers above were measured off the real AHCCCS FY2026
baseline page, not invented.
"""
from __future__ import annotations

import fitz

from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.text_layer_table import (
    ANCHOR_MIN_MATCH,
    refine_operating_table,
    render_html,
)

# Three-column edition (the common shape).
CENTRES = (305.0, 404.0, 503.0)
RIGHTS = (334.0, 433.0, 532.0)
# Four-column edition — the biennial books. Spec §2 says 152 tables;
# measured 2026-09-01 against the live corpus it is 156 in-scope table
# chunks with four or more year tokens in MinerU's header, and every one
# of them is FY2006 (not FY2010 as the task brief had it). These are the
# pages MinerU reads worst: its header row comes back scrambled, so the
# rebuilt header cannot be taken from it. The label zone is narrower
# because four columns have to fit the same page width.
CENTRES4 = (255.0, 335.0, 415.0, 495.0)
RIGHTS4 = (284.0, 364.0, 444.0, 524.0)


class PageBuilder:
    """Places text at coordinates on a US-letter page.

    `centres`/`rights` are constructor arguments rather than module
    constants so a four-column edition can be built with the same helper
    (the plan's sketch hardcoded the three-column geometry).
    """

    def __init__(self, doc: fitz.Document, centres=CENTRES, rights=RIGHTS):
        self.page = doc.new_page(width=612, height=792)
        self.y = 60.0
        self.centres = centres
        self.rights = rights

    def centred(self, y: float, text: str, cx: float, size: float = 9) -> None:
        w = fitz.get_text_length(text, fontsize=size)
        self.page.insert_text((cx - w / 2, y), text, fontsize=size)

    def right(self, y: float, text: str, rx: float, size: float = 9) -> None:
        w = fitz.get_text_length(text, fontsize=size)
        self.page.insert_text((rx - w, y), text, fontsize=size)

    def header(
        self,
        years=("FY 2024", "FY 2025", "FY 2026"),
        kinds=("ACTUAL", "ESTIMATE", "APPROVED"),
    ) -> None:
        for cx, yr in zip(self.centres, years):
            self.centred(self.y, yr, cx)
        self.y += 12
        for cx, k in zip(self.centres, kinds):
            self.centred(self.y, k, cx)
        self.y += 24

    def row(self, label: str, *figures: str, x0: float = 52, marker: str | None = None) -> None:
        if label:
            self.page.insert_text((x0, self.y), label, fontsize=9)
        for rx, fig in zip(self.rights, figures):
            if fig:
                self.right(self.y, fig, rx)
        if marker:
            # 6-pt, one point below the baseline, right of the last column — as
            # printed. Measured: the marker's y0 sits 4.2 pt below the row's,
            # inside the half-median-height tolerance (6.2 pt), so it groups
            # onto the row rather than becoming a line of its own.
            self.page.insert_text((534, self.y + 1), marker, fontsize=6)
        self.y += 11.5

    def prose(self, text: str) -> None:
        self.page.insert_text((52, self.y), text, fontsize=9)
        self.y += 12


def _minerU(html: str, page: int = 1):
    return MinerUReader._parse_html_table(html, page=page, bbox=None)


def _cells(table) -> list[list[str]]:
    return [[c.text for c in r.cells] for r in table.rows]


CLEAN_HTML = (
    "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
    "<tr><td>OPERATING BUDGET</td><td></td><td></td><td></td></tr>"
    "<tr><td>Full Time Equivalent Positions</td><td>10.0</td><td>10.0</td><td>12.0</td></tr>"
    "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
    "<tr><td>Equipment</td><td>50</td><td>50</td><td>50</td></tr>"
    "<tr><td>OPERATING SUBTOTAL</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>AGENCY TOTAL</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
    "<tr><td>General Fund</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>SUBTOTAL - Appropriated Funds</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>TOTAL - ALL SOURCES</td><td>150</td><td>250</td><td>350</td></tr></table>"
)


def _clean_page(b: PageBuilder) -> None:
    b.header()
    b.row("OPERATING BUDGET")
    b.row("Full Time Equivalent Positions", "10.0", "10.0", "12.0")
    b.row("Personal Services", "100", "200", "300")
    b.row("Equipment", "50", "50", "50")
    b.row("OPERATING SUBTOTAL", "150", "250", "350", x0=61)
    b.row("AGENCY TOTAL", "150", "250", "350")
    b.row("FUND SOURCES")
    b.row("General Fund", "150", "250", "350")
    b.row("SUBTOTAL - Appropriated Funds", "150", "250", "350", x0=61)
    b.row("TOTAL - ALL SOURCES", "150", "250", "350")


def test_clean_table_round_trips_with_header_row_first():
    doc = fitz.open()
    _clean_page(PageBuilder(doc))
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[0] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]
    assert cells[3] == ["Personal Services", "100", "200", "300"]
    assert cells[1] == ["OPERATING BUDGET", "", "", ""]
    assert out.table.page == 1 and out.table.html.startswith("<table><tr><td></td><td>FY 2024 ACTUAL")


def test_two_merged_rows_come_back_as_two_rows():
    """The defect itself: MinerU fused two printed rows into one cell."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "60", "120", "180")
    b.row("Other Appropriated Funds")
    b.row("Some Fund", "40", "80", "120")
    b.row("SUBTOTAL - Other Appropriated Funds", "40", "80", "120", x0=61)
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>60</td><td>120</td><td>180</td></tr>"
        "<tr><td>Other Appropriated Funds</td><td></td><td></td><td></td></tr>"
        "<tr><td>Some Fund</td><td>40</td><td>80</td><td>120</td></tr>"
        "<tr><td>SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds</td><td>40 100</td><td>80 200</td><td>120 300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "SUBTOTAL - Other Appropriated Funds" in labels and "SUBTOTAL - Appropriated Funds" in labels
    from chunking.table_gate import has_merged_cell
    assert not has_merged_cell(_cells(out.table)[1:])


def test_wrapped_label_is_appended_to_its_row():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Tobacco Products Tax Fund - Proposition 204 Protection", "10", "20", "30")
    b.row("Account", x0=61)
    b.row("SUBTOTAL - Other Appropriated Funds", "10", "20", "30", x0=61)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Tobacco Products Tax Fund - Proposition 204 Protection</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>Account SUBTOTAL - Other Appropriated Funds</td><td>10</td><td>20</td><td>30</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "Tobacco Products Tax Fund - Proposition 204 Protection Account" in labels


def test_footnote_markers_separate_word_and_fused_word():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("DES Eligibility", "116,083,200", "98,906,500", "99,294,500", marker="3/")
    b.row("Personal Services", "100", "100", "100")
    b.page.insert_text((52, b.y), "OPERATING SUBTOTAL", fontsize=9)
    b.right(b.y, "116,083,300", 334.0)
    b.right(b.y, "98,906,600", 433.0)
    b.right(b.y, "99,294,6001/", 532.0)   # the FY2006 shape: marker fused in the text layer
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>DES Eligibility</td><td>116,083,200</td><td>98,906,500</td><td>99,294,5003/</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>100</td><td>100</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>116,083,300</td><td>98,906,600</td><td>99,294,6001/</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[1][3] == "99,294,500 [3/]"
    assert cells[3][3] == "99,294,600 [1/]"


def test_minerU_table_whose_rows_span_two_pages_is_followed_forward():
    """MinerU merged both pages into its page-1 block (the AHCCCS shape)."""
    doc = fitz.open()
    b1 = PageBuilder(doc)
    b1.header()
    b1.row("Personal Services", "100", "200", "300")
    b1.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b1.row("AGENCY TOTAL", "100", "200", "300")
    b2 = PageBuilder(doc)
    b2.header()
    b2.row("FUND SOURCES")
    b2.row("General Fund", "100", "200", "300")
    b2.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b2.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>AGENCY TOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html, page=1), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert labels[-1] == "TOTAL - ALL SOURCES" and "AGENCY TOTAL" in labels
    assert out.table.page == 1 and out.table.pages == [1]   # D4: provenance untouched


def test_continuation_without_its_own_header_borrows_the_previous_page():
    doc = fitz.open()
    b1 = PageBuilder(doc)
    b1.header()
    b1.row("Personal Services", "100", "200", "300")
    b2 = PageBuilder(doc)          # no header printed on page 2
    b2.row("FUND SOURCES")
    b2.row("General Fund", "100", "200", "300")
    b2.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b2.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html, page=2), doc)
    assert out.table is not None, out.reason
    assert _cells(out.table)[0] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]


def test_four_column_edition_rebuilds_its_own_header():
    """The FY2006 biennial shape (spec §2: 152 tables carry FOUR year
    columns; 156 measured in the live corpus 2026-09-01, all FY2006).

    Two real properties are pinned here, both read off
    `jlbc-approps-fy2006-agr-0000` and its PDF:

    1. MinerU's own header row is unusable — on the real page it comes out
       as `['Director: Donald Butler', 'JLBC Analyst: Eric Jorgensen']`,
       and on a sibling page MinerU even mis-read the analyst's name
       (`JLBC Anaiyst: Nick Kiingernan`). The reader anchors on cell 0
       only and rebuilds the header from the printed year tokens.
    2. Because MinerU's row 0 cell 0 is that director line, the anchor
       region STARTS ABOVE the year header — so the header line and its
       kind line fall INSIDE the region and must be skipped when the rows
       are built, and the header itself has to be found inside the region
       rather than above it.

    Both year forms are exercised: `FY 2004` (two words) and `FY2006`
    (one word), which the books mix.
    """
    doc = fitz.open()
    b = PageBuilder(doc, centres=CENTRES4, rights=RIGHTS4)
    b.row("Director: Donald Butler")          # printed above the year header
    b.header(
        years=("FY 2004", "FY 2005", "FY2006", "FY2007"),
        kinds=("ACTUAL", "ESTIMATE", "APPROVED", "APPROVED"),
    )
    b.row("Personal Services", "100", "200", "300", "400")
    b.row("Employee Related Expenditures", "10", "20", "30", "40")
    b.row("OPERATING SUBTOTAL", "110", "220", "330", "440", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "110", "220", "330", "440")
    b.row("SUBTOTAL - Appropriated Funds", "110", "220", "330", "440", x0=61)
    b.row("TOTAL - ALL SOURCES", "110", "220", "330", "440")
    html = (
        # MinerU's four-column header, as it really comes out: the director
        # line in cell 0 and the year labels scrambled.
        "<table><tr><td>Director: Donald Butler</td><td>FY 2005</td><td>JLBC Anaiyst</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td><td>400</td></tr>"
        "<tr><td>Employee Related Expenditures</td><td>10</td><td>20</td><td>30</td><td>40</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>110</td><td>220</td><td>330</td><td>440</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>110</td><td>220</td><td>330</td><td>440</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>110</td><td>220</td><td>330</td><td>440</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>110</td><td>220</td><td>330</td><td>440</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[0] == [
        "", "FY 2004 ACTUAL", "FY 2005 ESTIMATE", "FY 2006 APPROVED", "FY 2007 APPROVED",
    ]
    assert cells[-1] == ["TOTAL - ALL SOURCES", "110", "220", "330", "440"]
    assert all(len(r) == 5 for r in cells)
    # The header and kind lines are inside the region; neither may become a row.
    labels = [r[0] for r in cells[1:]]
    assert not any("FY 2004" in l or "ACTUAL" in l for l in labels), labels


def test_four_columns_printed_under_a_three_column_header_is_refused():
    """Spec §3.1 step 7: two figure words landing in one column on one line
    is a column-assignment failure → None.

    The trigger here is spec §3.3's own case — a text layer that disagrees
    with what is printed. This four-column FY2006 page has its fourth year
    corrupted to `FY 200I` (a letter, the classic old-scan OCR slip), so
    the header yields three columns while every row prints four figures.
    Two of the four then land in the same column. The table is refused
    rather than written with a figure under the wrong year, which is the
    one outcome Invariant 1 cannot tolerate.
    """
    doc = fitz.open()
    b = PageBuilder(doc, centres=CENTRES4, rights=RIGHTS4)
    b.header(
        years=("FY 2004", "FY 2005", "FY2006", "FY 200I"),
        kinds=("ACTUAL", "ESTIMATE", "APPROVED", "APPROVED"),
    )
    b.row("Personal Services", "100", "200", "300", "400")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", "400", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300", "400")
    html = (
        "<table><tr><td></td><td>FY 2004</td><td>FY 2005</td><td>FY2006</td><td>FY 200I</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td><td>400</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td><td>400</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td><td>400</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None and out.reason == "two figures in one column"


def test_sub_table_and_prose_outside_the_anchor_region_are_ignored():
    doc = fitz.open()
    b = PageBuilder(doc)
    _clean_page(b)
    b.prose("AGENCY DESCRIPTION — The agency operates on a health maintenance model.")
    b.y += 10
    b.header(years=("FY 2023", "FY 2024", "FY 2026"), kinds=("Actual", "Actual", "Approved"))
    b.row("PERFORMANCE MEASURES")
    b.row("Fair attendance", "1,067,500", "1,060,086", "1,100,000")
    # Spec §3.1 step 3, verbatim: a prose heading further down the page
    # matches the anchor `OPERATING BUDGET`. The region must still end at
    # MinerU's LAST row, or this line drags the whole block above in.
    b.prose("Operating Budget")
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "Fair attendance" not in labels and not any("AGENCY DESCRIPTION" in l for l in labels)


def test_accounting_negative_and_empty_column():
    """Figures at real AHCCCS magnitude, deliberately.

    `23,010,071,300` is AHCCCS's own FY2026 TOTAL - ALL SOURCES. Printed at
    9 pt and right-aligned to x=334 it is 62.5 pt wide, so its CENTRE sits
    at x=302.7 — LEFT of the first column centre (305). A label zone that
    ran all the way to the first centre would read the agency's largest
    figures as label text; it stops half a column spacing short (x=255.5)
    for exactly this reason. Short fixture figures never reach that far and
    cannot see the difference.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("A", "(546,838,600)", "", "23,010,071,300")
    b.row("B", "18,981,713,300", "", "0")
    b.row("OPERATING SUBTOTAL", "18,434,874,700", "", "23,010,071,300", x0=61)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>A</td><td>(546,838,600)</td><td></td><td>23,010,071,300</td></tr>"
        "<tr><td>B</td><td>18,981,713,300</td><td></td><td>0</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>18,434,874,700</td><td></td><td>23,010,071,300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    assert _cells(out.table)[1] == ["A", "(546,838,600)", "", "23,010,071,300"]
    assert _cells(out.table)[3] == ["OPERATING SUBTOTAL", "18,434,874,700", "", "23,010,071,300"]


def test_scanned_page_and_weak_anchor_return_none_with_a_reason():
    doc = fitz.open()
    doc.new_page()                                  # no words at all
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is None and out.reason == "no text layer"

    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Something Else Entirely", "1", "2", "3")
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is None and out.reason.startswith("anchor match")
    assert out.anchor_match < ANCHOR_MIN_MATCH


def test_gate_failure_returns_none():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "101", "200", "300", x0=61)   # printed page that does not add up
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>101</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None and out.reason == "arithmetic"


def test_label_that_wrapped_before_its_figures_is_one_row():
    """FY2006 DHS: `SUBTOTAL - Appropriated/Expenditure` on one line, the
    figures on the indented `Authority Funds` line under it."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("General Fund", "100", "200", "300")
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("Expenditure Authority Funds")
    b.row("Federal Title XIX Funds", "10", "20", "30")
    b.row("SUBTOTAL - Expenditure Authority Funds", "10", "20", "30", x0=61)
    b.row("SUBTOTAL - Appropriated/Expenditure", x0=61)
    b.row("Authority Funds", "110", "220", "330", x0=69)
    b.row("TOTAL - ALL SOURCES", "110", "220", "330")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>Expenditure Authority Funds</td><td></td><td></td><td></td></tr>"
        "<tr><td>Federal Title XIX Funds</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>SUBTOTAL - Expenditure Authority Funds</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated/Expenditure Authority Funds</td><td>110</td><td>220</td><td>330</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>110</td><td>220</td><td>330</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert ["SUBTOTAL - Appropriated/Expenditure Authority Funds", "110", "220", "330"] in cells


def test_last_minerU_row_must_be_found_on_the_page():
    """A summary table's lone `Total` further down the page must not stand
    in for `TOTAL - ALL SOURCES`; with the real last row missing the end of
    the region is a guess and the table is refused."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("Equipment", "10", "20", "30")
    b.row("Travel - In State", "1", "2", "3")
    b.row("Other Operating Expenditures", "1", "2", "3")
    b.row("OPERATING SUBTOTAL", "112", "224", "336", x0=61)
    b.prose("AGENCY DESCRIPTION — prose.")
    b.row("Total", "112", "224", "336", x0=91)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>Equipment</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>Travel - In State</td><td>1</td><td>2</td><td>3</td></tr>"
        "<tr><td>Other Operating Expenditures</td><td>1</td><td>2</td><td>3</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>112</td><td>224</td><td>336</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>112</td><td>224</td><td>336</td></tr></table>"
    )   # five of six MinerU rows are on the page (83%), but not the last one
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None and out.reason == "last row unmatched"


def test_render_html_escapes_and_shapes():
    assert render_html([["", "FY 2024"], ["A & B", "1"]]) == "<table><tr><td></td><td>FY 2024</td></tr><tr><td>A &amp; B</td><td>1</td></tr></table>"
