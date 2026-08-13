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
