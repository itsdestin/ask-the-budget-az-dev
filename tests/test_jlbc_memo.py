"""The renderer is measured against the committed reference memo, not
against remembered numbers.

`REFERENCE` is `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx`
— the real FY 2027 Appropriations Report Round 1 instructions memo. Where
a value can be read out of it, these tests read it, so a future JLBC style
change is a fixture swap rather than a code rewrite.

Two structural elements of that document are INVISIBLE to
`Document.paragraphs` and were missed on a first pass: the horizontal rule
is a VML `pict`, and the DATE/TO/FROM/SUBJECT block is a borderless table.
Anything that needs to see them must walk `document.body` elements.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

import memo
from memo import style

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "raw-docx"
    / "jlbc-staff-memorandum-style-reference.docx"
)


@pytest.fixture(scope="module")
def reference():
    return Document(str(REFERENCE))


@pytest.fixture
def rendered():
    return memo.render(
        "Body text.",
        subject="FY 2027 AHCCCS Appropriations Summary",
        sender="Destin Jarrett",
        recipient="",
        date="August 12, 2026",
    )


def test_page_margins_match_the_reference_to_the_emu(rendered, reference):
    ours, theirs = rendered.sections[0], reference.sections[0]
    assert ours.top_margin == theirs.top_margin
    assert ours.bottom_margin == theirs.bottom_margin
    assert ours.left_margin == theirs.left_margin
    assert ours.right_margin == theirs.right_margin
    assert ours.header_distance == theirs.header_distance
    assert ours.footer_distance == theirs.footer_distance


def test_the_masthead_carries_the_letterhead_with_the_research_subtitle(rendered):
    texts = [p.text for p in rendered.paragraphs[:4]]
    assert texts[0] == "Joint Legislative Budget Committee"
    assert texts[1] == "Research Memorandum"
    assert texts[2].startswith("1716 West Adams\t")
    assert texts[3].startswith("Phoenix, Arizona 85007\t")


def test_the_masthead_lines_are_14pt_bold_centered(rendered):
    title_style = rendered.styles["Title"]
    assert title_style.font.size == Pt(14)
    assert title_style.font.bold is True
    assert title_style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    subtitle = rendered.paragraphs[1]
    assert subtitle.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert subtitle.runs[0].bold is True
    assert subtitle.runs[0].font.size == Pt(14)


def test_the_title_styles_default_blue_border_and_spacing_are_stripped(rendered):
    """python-docx's default `Title` style ships a blue bottom border
    (sz 8, accent1) and `spacing after 300`. The reference has neither, and
    leaving them draws a stray blue line directly above the real 2.25pt
    rule — two lines where the memo has one. Verified against a stock
    `Document()` during planning."""
    assert "pBdr" not in rendered.styles["Title"].element.xml
    assert rendered.styles["Title"].paragraph_format.space_after == Pt(0)


def test_the_address_lines_use_a_left_tab_stop_at_7020_twips(rendered):
    for index in (2, 3):
        stops = list(rendered.paragraphs[index].paragraph_format.tab_stops)
        assert len(stops) == 1
        assert stops[0].position == style.TAB_STOP_TWIPS
        assert rendered.paragraphs[index].runs[0].font.size == Pt(10)


def test_the_rule_is_a_225pt_paragraph_bottom_border(rendered):
    rule = rendered.paragraphs[4]
    assert "pBdr" in rule._p.xml
    assert 'w:sz="18"' in rule._p.xml  # 18 eighths of a point = 2.25pt


def test_the_footer_note_appears_on_the_first_page_too(rendered):
    section = rendered.sections[0]
    assert section.different_first_page_header_footer is True
    for footer in (section.footer, section.first_page_footer):
        assert footer.paragraphs[0].text == "Generated with JLBC Agentic Search"
        assert footer.paragraphs[0].runs[0].font.size == Pt(9)


def test_later_pages_carry_a_page_number_and_the_first_page_does_not(rendered):
    section = rendered.sections[0]
    assert "PAGE" in section.header.paragraphs[0]._p.xml
    assert section.first_page_header.paragraphs[0].text.strip() == ""


def test_body_text_is_calibri_105pt_on_the_normal_style(rendered):
    """Set on the style, not per-run, so bullets and table cells inherit
    (spec M9). The reference sets 10.5 on each run over a 12pt Normal;
    same rendered result, one place to change."""
    normal = rendered.styles["Normal"]
    assert normal.font.name == "Calibri"
    assert normal.font.size == Pt(10.5)


def test_the_memo_block_is_a_borderless_7x2_table(rendered, reference):
    table = rendered.tables[0]
    theirs = reference.tables[0]
    assert len(table.rows) == len(theirs.rows) == 7
    assert len(table.columns) == 2
    assert [c.width for c in table.columns] == [c.width for c in theirs.columns]
    assert "tblBorders" not in table.style.element.xml


def test_every_memo_block_CELL_carries_its_own_width(rendered, reference):
    """Column widths alone do not protect the thing that actually wraps.

    Measured on python-docx 1.2.0, and it corrects the plan's account of
    this trap. Build the table with its rows already present
    (`add_table(rows=7, cols=2)`) and set only the columns, and every
    CELL round-trips at 2743200 EMU — Word's even split — while
    `columns[].width` still reads the intended 925830 / 4914900. The
    labels wrap and `test_the_memo_block_is_a_borderless_7x2_table`
    stays green throughout. This test is what goes red.

    It asserts the rendered property, not the mechanism: with the shipped
    `rows=0` + `add_row()` construction the cells inherit the gridCol
    widths on their own, so deleting the explicit `cells[…].width` lines
    in `add_memo_block` does NOT fail this — verified by deleting them.
    What fails it is a refactor to rows-up-front.
    """
    ours = rendered.tables[0]
    theirs = reference.tables[0]
    expected = [c.width for c in theirs.rows[0].cells]
    assert expected == [style.LABEL_COL_TWIPS, style.VALUE_COL_TWIPS]
    for index, row in enumerate(ours.rows):
        assert [c.width for c in row.cells] == expected, f"row {index} unsized"


def test_the_memo_block_labels_are_in_order_and_not_bold(rendered):
    """The labels share the `Header` paragraph style with section
    headings, and in the reference they are NOT bold — only the headings
    are, via direct run formatting. A future edit that puts bold on the
    style instead of the run bolds these as a side effect (spec M8)."""
    table = rendered.tables[0]
    labels = [table.rows[i].cells[0].text for i in (0, 2, 4, 6)]
    assert labels == ["DATE:", "TO:", "FROM:", "SUBJECT:"]
    for row in (0, 2, 4, 6):
        paragraph = table.rows[row].cells[0].paragraphs[0]
        assert paragraph.style.name == "Header"
        assert paragraph.runs[0].bold is not True


def test_the_subject_row_carries_the_documents_title(rendered):
    assert (
        rendered.tables[0].rows[6].cells[1].text
        == "FY 2027 AHCCCS Appropriations Summary"
    )


def test_there_is_no_separate_title_line_in_the_body(rendered):
    """The reference has none, and Word's `Title` style is already spent
    on the masthead. The subject IS the title (spec M4)."""
    body_texts = [p.text for p in rendered.paragraphs]
    assert body_texts.count("FY 2027 AHCCCS Appropriations Summary") == 0


def test_an_absent_recipient_renders_a_visible_placeholder(rendered):
    assert rendered.tables[0].rows[2].cells[1].text == "[Recipient(s)]"


def test_a_supplied_recipient_is_used_verbatim():
    doc = memo.render(
        "Body.", subject="S", sender="A. Analyst", recipient="Director Smith"
    )
    assert doc.tables[0].rows[2].cells[1].text == "Director Smith"


def test_the_sender_row_names_the_analyst_and_the_tool(rendered):
    assert (
        rendered.tables[0].rows[4].cells[1].text
        == "Destin Jarrett, via JLBC Agentic Search"
    )


def test_an_unknown_analyst_leaves_the_tool_alone_on_the_from_line():
    """Degrades to the tool's name rather than a dangling comma. An
    unnameable user should lose attribution, not get a malformed memo —
    the same posture `app.identity.current_user` already takes."""
    doc = memo.render("Body.", subject="S", sender="")
    assert doc.tables[0].rows[4].cells[1].text == "JLBC Agentic Search"


def test_the_date_defaults_to_today_in_long_form():
    from memo.style import today_long

    doc = memo.render("Body.", subject="S", sender="A")
    assert doc.tables[0].rows[0].cells[1].text == today_long()
