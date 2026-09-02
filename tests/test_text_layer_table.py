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
    MIN_FIGURE_RETENTION,
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
            # 6-pt SUPERSCRIPT, right of the last column — as printed. Raised
            # above the row's baseline so the word boxes reproduce the
            # real geometry measured on `jlbc-approps-fy2010-rad` page 1,
            # where the marker's y0 sits ~1.35 pt ABOVE its own row's. That
            # is inside the half-median-height tolerance, so it groups onto
            # the row; it also means a marker that ever failed to group would
            # arrive BEFORE its row, which is why `_rows` looks down.
            self.page.insert_text((534, self.y - 4.5), marker, fontsize=6)
        self.y += 11.5

    def masthead(self, left: str, right: str) -> None:
        """One printed line carrying both the director and the JLBC analyst —
        the shape that makes MinerU's first cell unmatchable (see
        `test_four_column_edition_rebuilds_its_own_header`)."""
        self.page.insert_text((52, self.y), left, fontsize=9)
        self.page.insert_text((283, self.y), right, fontsize=9)
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
    columns; 156 measured in the live corpus 2026-09-01, all FY2006), read
    off `jlbc-approps-fy2006-agr-0000` and its PDF.

    Two real properties are pinned:

    1. MinerU's own header row is unusable — on the real page it comes out
       as `['Director: Donald Butler', 'JLBC Analyst: Eric Jorgensen']`, and
       on a sibling page MinerU even mis-read the analyst's name (`JLBC
       Anaiyst: Nick Kiingernan`). The reader anchors on cell 0 only and
       rebuilds the header from the printed year tokens, in both the
       `FY 2004` (two words) and `FY2006` (one word) forms the books mix.
    2. MinerU's FIRST anchor cannot be matched at all: it fuses the page
       masthead into cell 0 as `Director: Donald Butler`, while the page
       prints `Director: Donald Butler JLBC Analyst: Eric Jorgensen` as ONE
       line, which is LONGER than the anchor and so fails a containment
       running page → MinerU. `_region` must fall back to the first matched
       line instead of refusing. **705 of the 4,875 in-scope chunks (14.5%)
       are in this state, measured 2026-09-01** — refusing them would throw
       away every four-column page, the ones MinerU reads worst.
    """
    doc = fitz.open()
    b = PageBuilder(doc, centres=CENTRES4, rights=RIGHTS4)
    b.masthead("Director: Donald Butler", "JLBC Analyst: Eric Jorgensen")
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
        # MinerU's four-column header, as it really comes out: the masthead
        # fused into cell 0 and the year labels scrambled.
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


# ---------------------------------------------------------------------------
# Two tables on one page. Anchor labels are generic (`AFIS Replacement`,
# `General Fund`, `TOTAL - ALL SOURCES`), so a region that starts at "the
# first line matching anything" and ends at "the last line matching the last
# anchor" reads the wrong table — and the arithmetic gate cannot see it,
# because the wrong table reconciles perfectly well with itself. Measured on
# the live corpus 2026-09-01: 2 chunks read a neighbouring table outright and
# 31 more swallowed a sibling. All three tests below are that defect.
# ---------------------------------------------------------------------------

def test_the_region_starts_at_minerUs_own_first_row_not_the_first_match():
    """`jlbc-approps-fy2017-doa-apf-0001`, reduced.

    Its 39-row Individual Projects table starts at y=291, but the page also
    carries an 11-row General Fund Transfers table above it that repeats the
    labels `AFIS Replacement` and `TOTAL - ALL SOURCES`. Anchoring on the
    first line matching ANY label put the region on the upper table and
    reported `rebuilt`, losing ~28 rows of per-project dollars.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("GENERAL FUND TRANSFERS")                      # the OTHER table
    b.row("AFIS Replacement", "18,400,000", "2,383,000", "0", x0=65)
    b.row("TOTAL - ALL SOURCES", "18,400,000", "2,383,000", "0")
    b.y += 22
    b.row("INDIVIDUAL PROJECTS")                         # MinerU's own table
    b.row("AFIS Replacement", "16,783,600", "2,500,000", "0", x0=65)
    b.row("e-Procurement System Replacement", "0", "0", "12,000,000", x0=65)
    b.row("TOTAL - ALL PROJECTS", "16,783,600", "2,500,000", "12,000,000")
    b.row("FUND SOURCES")
    b.row("General Fund", "16,783,600", "2,500,000", "12,000,000")
    b.row("SUBTOTAL - Appropriated Funds", "16,783,600", "2,500,000", "12,000,000", x0=61)
    b.row("TOTAL - ALL SOURCES", "16,783,600", "2,500,000", "12,000,000")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>INDIVIDUAL PROJECTS</td><td></td><td></td><td></td></tr>"
        "<tr><td>AFIS Replacement</td><td>16,783,600</td><td>2,500,000</td><td>0</td></tr>"
        "<tr><td>e-Procurement System Replacement</td><td>0</td><td>0</td><td>12,000,000</td></tr>"
        "<tr><td>TOTAL - ALL PROJECTS</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[1][0] == "INDIVIDUAL PROJECTS"
    assert [r[0] for r in cells].count("TOTAL - ALL SOURCES") == 1
    # Not one figure from the table above may appear.
    flat = [c for r in cells for c in r]
    assert "18,400,000" not in flat and "2,383,000" not in flat
    assert cells[2] == ["AFIS Replacement", "16,783,600", "2,500,000", "0"]


def test_the_region_ends_at_the_first_occurrence_of_minerUs_last_row():
    """`…-ata-0002` / `…-judspa-0001` / `…-sdb-0000`, reduced: a page with two
    programmes, each ending `TOTAL - ALL SOURCES`. MinerU's block is the
    FIRST one. Ending the region at the LAST line matching the last anchor
    swallowed the sibling — 5 MinerU rows came back as 22, and the gate
    passed because concatenated ladders each reconcile from their own
    boundary."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("OPERATING BUDGET")
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "100", "200", "300")
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    b.y += 22
    b.row("PROGRAM BUDGET")                              # the sibling table
    b.row("Personal Services", "50", "60", "70")
    b.row("OPERATING SUBTOTAL", "50", "60", "70", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "50", "60", "70")
    b.row("SUBTOTAL - Appropriated Funds", "50", "60", "70", x0=61)
    b.row("TOTAL - ALL SOURCES", "50", "60", "70")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>OPERATING BUDGET</td><td></td><td></td><td></td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert len(cells) == 8, [r[0] for r in cells]      # header + MinerU's 7 rows
    assert cells[-1] == ["TOTAL - ALL SOURCES", "100", "200", "300"]
    flat = [c for r in cells for c in r]
    assert "50" not in flat and "PROGRAM BUDGET" not in flat


def test_a_rebuild_that_drops_minerUs_figures_is_refused():
    """The backstop for the fallback above.

    MinerU's block is the LOWER table, but its first anchor is a fused
    masthead that nothing on the page can match, so the start falls back to
    the first matched line — which is in the UPPER table, whose labels it
    shares. The upper table reconciles with itself, so the arithmetic gate
    passes it. Only the fact that almost none of MinerU's own figures
    survived says the reader read the wrong thing.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("GENERAL FUND TRANSFERS")
    b.row("AFIS Replacement", "18,400,000", "2,383,000", "0", x0=65)
    b.row("e-Procurement System Replacement", "0", "0", "3,000,000", x0=65)
    b.row("FUND SOURCES")
    b.row("General Fund", "18,400,000", "2,383,000", "3,000,000")
    b.row("SUBTOTAL - Appropriated Funds", "18,400,000", "2,383,000", "3,000,000", x0=61)
    b.row("TOTAL - ALL SOURCES", "18,400,000", "2,383,000", "3,000,000")
    b.y += 22
    # The page prints the fund name and the department on ONE line; MinerU
    # kept only the first half in cell 0, so its anchor is SHORTER than what
    # is printed and a containment running page → MinerU cannot match it.
    b.masthead("INDIVIDUAL PROJECTS - Automation Projects Fund", "Department of Administration")
    b.row("AFIS Replacement", "16,783,600", "2,500,000", "0", x0=65)
    b.row("e-Procurement System Replacement", "0", "0", "12,000,000", x0=65)
    b.row("General Fund", "16,783,600", "2,500,000", "12,000,000")
    b.row("SUBTOTAL - Appropriated Funds", "16,783,600", "2,500,000", "12,000,000", x0=61)
    b.row("TOTAL - ALL SOURCES", "16,783,600", "2,500,000", "12,000,000")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>INDIVIDUAL PROJECTS - Automation Projects Fund</td><td></td><td></td><td></td></tr>"
        "<tr><td>AFIS Replacement</td><td>16,783,600</td><td>2,500,000</td><td>0</td></tr>"
        "<tr><td>e-Procurement System Replacement</td><td>0</td><td>0</td><td>12,000,000</td></tr>"
        "<tr><td>General Fund</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>16,783,600</td><td>2,500,000</td><td>12,000,000</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None, _cells(out.table)
    assert out.reason.startswith("figure retention"), out.reason
    assert out.figure_retention < MIN_FIGURE_RETENTION
    assert out.anchor_match >= ANCHOR_MIN_MATCH    # it got past the anchor gate


def test_a_header_printed_inside_the_anchor_region_is_found_and_not_read_as_a_row():
    """`jlbc-approps-fy2011-for-0000`, reduced — one of the 6 chunks in the
    live corpus whose year header falls INSIDE the anchor region (measured
    2026-09-01; the other 4,858 print it above).

    MinerU's first cell is `State Forester: Victoria Christiansen` and the
    page's first line is the bare masthead `State Forester`, which IS
    contained in that anchor — so the region opens above the year header.
    The header must then be found inside the region, and its two lines must
    not become data rows.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.row("State Forester")
    b.masthead("State Forester: Victoria Christiansen", "JLBC Analyst: Jay Chilton")
    b.header(years=("FY 2009", "FY 2010", "FY 2011"))
    b.row("OPERATING BUDGET")
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "100", "200", "300")
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td>State Forester: Victoria Christiansen</td><td></td><td></td><td></td></tr>"
        "<tr><td>OPERATING BUDGET</td><td></td><td></td><td></td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[0] == ["", "FY 2009 ACTUAL", "FY 2010 ESTIMATE", "FY 2011 APPROVED"]
    labels = [r[0] for r in cells[1:]]
    assert not any("FY 2009" in l or "ACTUAL" in l for l in labels), labels
    assert "TOTAL - ALL SOURCES" in labels


def test_a_marker_left_on_its_own_line_attaches_to_the_row_below():
    """JLBC prints markers as superscripts, so a marker's word box sits ABOVE
    its own row (measured on `jlbc-approps-fy2010-rad` p1: `1/` at y0=154.31
    against its row at 155.66) and lines are ordered by `y0`. A marker that
    ever failed to group therefore arrives BEFORE its row, never after it.

    This is a safety net — it fired 0 times across 400 real tables — so the
    marker is raised further here than any real page raises it, purely to
    reach the branch and pin its DIRECTION. Attaching upwards would put the
    footnote on the wrong figure.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    # Ordinary rows sit 11.5 pt apart against a ~6.2 pt tolerance, so no
    # position BETWEEN two of them is isolated; the gap is opened first.
    b.page.insert_text((534, b.y - 3.5), "3/", fontsize=6)
    b.y += 12
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>3003/</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[1] == ["Personal Services", "100", "200", "300"]      # NOT the row above
    assert cells[2] == ["OPERATING SUBTOTAL", "100", "200", "300 [3/]"]


def test_a_fused_last_row_extends_the_region_over_both_printed_lines():
    """`jlbc-approps-fy2009-hla-0000`, reduced. MinerU's LAST cell is two
    printed rows fused into one — `Federal Funds TOTAL - ALL SOURCES` — and
    both printed lines are contained in it. Stopping at the first occurrence
    ends the table one row early, dropping the `TOTAL - ALL SOURCES` row
    itself; the remaining rows still reconcile, so the gate cannot catch it.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "60", "120", "180")
    b.row("Federal Funds", "40", "80", "120")
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>60</td><td>120</td><td>180</td></tr>"
        "<tr><td>Federal Funds TOTAL - ALL SOURCES</td><td>40 100</td><td>80 200</td><td>120 300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[-1] == ["TOTAL - ALL SOURCES", "100", "200", "300"]
    assert ["Federal Funds", "40", "80", "120"] in cells


def test_a_repeated_minerU_label_is_counted_once_in_the_match_rate():
    """17 of 400 sampled tables repeat a cell-0 label (the same fund under
    two headings). `matched` is a SET of labels, so counting the repeat twice
    in the denominator understates the rate — here it is the difference
    between 4/5 = 80% (accepted) and 4/6 = 67% (refused), and it would also
    skew the distribution the dry run uses to set the threshold.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.masthead("Director: Jane Doe", "JLBC Analyst: John Roe")   # never matchable
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "60", "120", "180")
    b.row("Other Appropriated Funds")
    b.row("General Fund", "40", "80", "120")
    b.row("SUBTOTAL - Other Appropriated Funds", "40", "80", "120", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td>Director: Jane Doe</td><td></td><td></td><td></td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>General Fund</td><td>60</td><td>120</td><td>180</td></tr>"
        "<tr><td>General Fund</td><td>40</td><td>80</td><td>120</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    assert out.anchor_match == 0.8, out.anchor_match


def test_a_figureless_group_heading_cannot_end_the_region():
    """`jlbc-baseline-fy2013-axs-0000`, reduced.

    MinerU's last anchor is the fused
    `SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS`. The bare group
    heading `Expenditure Authority Funds`, printed well ABOVE the real
    subtotal, is contained in that label and has two words, so it matched —
    and ended the region ten lines early, dropping the whole
    expenditure-authority block. On the real page the cross-check caught it
    (7,024,518,200 against 1,417,666,800) and the table was refused, costing
    a repair; a truncation that removed the cross-check's own rows would
    have passed in silence.

    A real last row is a subtotal or a total and always prints figures. The
    terminus here is also the wrap shape — `SUBTOTAL - Appropriated/
    Expenditure` carries the figures and `Authority Funds` continues the
    label on the next line with none — so the CONTIGUOUS extension must
    still accept a figure-less line.
    """
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("General Fund", "100", "200", "300")
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("Expenditure Authority Funds")            # the false terminus
    b.row("County Funds", "10", "20", "30")
    b.row("Federal Medicaid Authority", "5", "10", "15")
    b.row("SUBTOTAL - Expenditure Authority Funds", "15", "30", "45", x0=61)
    b.row("SUBTOTAL - Appropriated/Expenditure", "115", "230", "345", x0=61)
    b.row("Authority Funds", x0=69)                 # the label's own wrap
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>Expenditure Authority Funds</td><td></td><td></td><td></td></tr>"
        "<tr><td>County Funds</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>Federal Medicaid Authority</td><td>5</td><td>10</td><td>15</td></tr>"
        "<tr><td>SUBTOTAL - Expenditure Authority Funds</td><td>15</td><td>30</td><td>45</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated/Expenditure Authority Funds</td><td>115</td><td>230</td><td>345</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    # The block between the false terminus and the real one must be present.
    assert ["County Funds", "10", "20", "30"] in cells
    assert ["Federal Medicaid Authority", "5", "10", "15"] in cells
    assert cells[-1] == ["SUBTOTAL - Appropriated/Expenditure Authority Funds", "115", "230", "345"]
