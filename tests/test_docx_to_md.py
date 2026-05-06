"""Tests for primer/docx_to_md.py — DOCX run_docx_ingest output → Markdown.

Operates directly on the raw block list emitted by run_docx_ingest (a flat
list of {kind, paragraph_id|table_cell_id, ...} dicts) rather than the
DocxReader's Section model — DocxReader's section detection is bill-
specific (SEC 06-* / ALL-CAPS dept), but the writing draft and other
non-bill DOCX inputs are flat text with optional Word heading styles.
"""
from __future__ import annotations

import pytest

from primer.docx_to_md import render_docx_to_markdown


def _para(text: str, *, style: str = "Normal", cells: list[str] | None = None,
          paragraph_id: str = "p:0001") -> dict:
    block: dict = {
        "kind": "paragraph",
        "paragraph_id": paragraph_id,
        "style": style,
        "text": text,
    }
    if cells is not None:
        block["cells"] = cells
    return block


def _cell(text: str, *, row: int, col: int, table_cell_id: str | None = None) -> dict:
    return {
        "kind": "table_cell",
        "table_cell_id": table_cell_id or f"t1-r{row}-c{col}",
        "row": row,
        "col": col,
        "text": text,
    }


# --- empty / single ---------------------------------------------------------


def test_render_empty_blocks_returns_empty_string():
    assert render_docx_to_markdown([]) == ""


def test_render_single_paragraph():
    md = render_docx_to_markdown([_para("Hello world.")])
    assert md == "Hello world."


def test_render_drops_empty_paragraphs():
    """Empty paragraphs are spacing artifacts — drop them so we don't emit
    a trail of blank lines."""
    md = render_docx_to_markdown([
        _para("Para A"),
        _para(""),
        _para("Para B"),
    ])
    assert md == "Para A\n\nPara B"


def test_render_multiple_paragraphs_separated_by_blank_lines():
    md = render_docx_to_markdown([
        _para("First paragraph."),
        _para("Second paragraph."),
        _para("Third paragraph."),
    ])
    assert md == "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."


# --- heading styles ---------------------------------------------------------


def test_render_word_heading_styles_become_markdown_headings():
    md = render_docx_to_markdown([
        _para("Title", style="Heading 1"),
        _para("Body text under title."),
        _para("Subtitle", style="Heading 2"),
        _para("Body under subtitle."),
        _para("Sub-subtitle", style="Heading 3"),
    ])
    assert "# Title" in md
    assert "## Subtitle" in md
    assert "### Sub-subtitle" in md


def test_render_heading_stripping_leading_hashes_in_user_text():
    """A paragraph whose body already starts with '# ' gets that text used
    verbatim — we don't double-prefix when the style says heading."""
    md = render_docx_to_markdown([
        _para("# Already a hash", style="Heading 1"),
    ])
    # Should be exactly one '# ' prefix.
    assert md.startswith("# ")
    assert md.count("# ") == 1


def test_render_heading_clamps_at_six_levels():
    """Heading 7+ Word styles are rare but exist — clamp to ###### to stay
    valid Markdown (max heading depth is 6)."""
    md = render_docx_to_markdown([_para("Deep", style="Heading 9")])
    assert md == "###### Deep"


def test_render_unknown_style_treated_as_paragraph():
    md = render_docx_to_markdown([
        _para("Body", style="P 06-1"),
    ])
    assert md == "Body"


# --- tab-cell line-item rows -----------------------------------------------


def test_render_tab_cell_paragraph_becomes_markdown_table_row():
    """Plan note: AZ Legislature bills encode line-item rows as tab-split
    paragraphs. Render them inline as Markdown tables."""
    md = render_docx_to_markdown([
        _para("col 1\tcol 2", cells=["col 1", "col 2"]),
        _para("Operating Lump Sum\t11,005,600", cells=["Operating Lump Sum", "11,005,600"]),
        _para("Building Renewal\t500,000", cells=["Building Renewal", "500,000"]),
    ])
    # First tab-cell paragraph supplies the header row; trailing tab-cell
    # paragraphs become body rows. A separator row appears between them.
    assert "| col 1 | col 2 |" in md
    assert "| --- | --- |" in md
    assert "| Operating Lump Sum | 11,005,600 |" in md
    assert "| Building Renewal | 500,000 |" in md


def test_render_tab_cell_block_resets_after_normal_paragraph():
    """A normal paragraph ends a tab-cell block — a later tab-cell paragraph
    starts a fresh table."""
    md = render_docx_to_markdown([
        _para("col 1\tcol 2", cells=["col 1", "col 2"]),
        _para("data 1\tdata 2", cells=["data 1", "data 2"]),
        _para("Some prose paragraph between tables."),
        _para("other 1\tother 2", cells=["other 1", "other 2"]),
        _para("another a\tanother b", cells=["another a", "another b"]),
    ])
    # Two separator rows = two tables
    assert md.count("| --- | --- |") == 2


# --- table_cell blocks ------------------------------------------------------


def test_render_table_cells_form_a_markdown_table():
    """run_docx_ingest emits one table_cell block per <w:tc>. Consecutive
    cells with the same row index form a row; first row is treated as
    the header."""
    md = render_docx_to_markdown([
        _cell("Header A", row=1, col=1),
        _cell("Header B", row=1, col=2),
        _cell("data 1", row=2, col=1),
        _cell("data 2", row=2, col=2),
        _cell("data 3", row=3, col=1),
        _cell("data 4", row=3, col=2),
    ])
    assert "| Header A | Header B |" in md
    assert "| --- | --- |" in md
    assert "| data 1 | data 2 |" in md
    assert "| data 3 | data 4 |" in md


def test_render_table_cells_handle_pipe_in_content():
    """Pipe characters inside cells must escape — pipes break Markdown
    table syntax."""
    md = render_docx_to_markdown([
        _cell("a | b", row=1, col=1),
        _cell("c", row=1, col=2),
    ])
    assert r"a \| b" in md


def test_render_table_cells_block_then_paragraph_resumes_normal_flow():
    """A table_cell sequence ends when a paragraph or different table id
    appears."""
    md = render_docx_to_markdown([
        _cell("h1", row=1, col=1, table_cell_id="t1-r1-c1"),
        _cell("h2", row=1, col=2, table_cell_id="t1-r1-c2"),
        _cell("d1", row=2, col=1, table_cell_id="t1-r2-c1"),
        _cell("d2", row=2, col=2, table_cell_id="t1-r2-c2"),
        _para("After the table."),
    ])
    assert "After the table." in md
    # Markdown table separator present once
    assert md.count("| --- | --- |") == 1


def test_render_two_separate_tables_by_table_id():
    """table_cell_id 't1-*' vs 't2-*' marks distinct tables — they shouldn't
    bleed into each other's row sequences."""
    md = render_docx_to_markdown([
        _cell("a", row=1, col=1, table_cell_id="t1-r1-c1"),
        _cell("b", row=1, col=2, table_cell_id="t1-r1-c2"),
        _cell("x", row=1, col=1, table_cell_id="t2-r1-c1"),
        _cell("y", row=1, col=2, table_cell_id="t2-r1-c2"),
    ])
    # Two header rows (each at row 1 in its own table)
    assert md.count("| --- | --- |") == 2


# --- end-to-end -------------------------------------------------------------


def test_render_produces_valid_markdown_overall_structure():
    """A realistic mini-document with headings + paragraphs + a table."""
    md = render_docx_to_markdown([
        _para("Document Title", style="Heading 1"),
        _para("Introduction", style="Heading 2"),
        _para("This is the introduction body."),
        _para("Tables", style="Heading 2"),
        _cell("Col A", row=1, col=1),
        _cell("Col B", row=1, col=2),
        _cell("1", row=2, col=1),
        _cell("2", row=2, col=2),
    ])
    expected = (
        "# Document Title\n\n"
        "## Introduction\n\n"
        "This is the introduction body.\n\n"
        "## Tables\n\n"
        "| Col A | Col B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |"
    )
    assert md == expected
