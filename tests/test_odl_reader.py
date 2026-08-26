"""Tests for chunking/readers/odl_reader.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.readers.odl_reader import ODLReader
from chunking.readers.types import ExtractedDocument, Heading, Image, Paragraph, Table

FIXTURE_AFR_P163 = Path(__file__).parent / "fixtures" / "odl-afr-p163.json"


def test_odl_reader_returns_extracted_document():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    assert isinstance(doc, ExtractedDocument)
    assert doc.extractor == "opendataloader"


def test_odl_reader_one_page_one_page_record():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    assert len(doc.pages) == 1
    assert doc.pages[0].page_number == 163


def test_odl_reader_block_types():
    """The fixture has 3 headings + 1 paragraph + 1 table + 1 image = 6 blocks."""
    doc = ODLReader().read(FIXTURE_AFR_P163)
    blocks = doc.pages[0].blocks
    assert len(blocks) == 6
    assert sum(1 for b in blocks if isinstance(b, Heading)) == 3
    assert sum(1 for b in blocks if isinstance(b, Paragraph)) == 1
    assert sum(1 for b in blocks if isinstance(b, Table)) == 1
    assert sum(1 for b in blocks if isinstance(b, Image)) == 1


def test_odl_reader_has_tables_property():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    assert doc.has_tables is True
    assert len(doc.tables) == 1


def test_odl_reader_table_cells_carry_text():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    table = doc.tables[0]
    assert len(table.rows) == 2
    assert len(table.rows[0].cells) == 2
    # Header row
    assert table.rows[0].cells[0].text == "Fund"
    assert table.rows[0].cells[1].text == "Balance"
    # Data row
    assert table.rows[1].cells[0].text == "General Fund"
    assert "1,234,567,000" in table.rows[1].cells[1].text


def test_odl_reader_table_cells_have_row_col_indices():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    table = doc.tables[0]
    # Plan §3.2.a: cells expose row/col indices
    assert table.rows[0].cells[0].row == 0
    assert table.rows[0].cells[0].col == 0
    assert table.rows[1].cells[1].row == 1
    assert table.rows[1].cells[1].col == 1


def test_odl_reader_heading_levels():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    headings = [b for b in doc.pages[0].blocks if isinstance(b, Heading)]
    levels = [(h.level, h.structure_tag) for h in headings]
    # Doctitle/H1/H2 from the fixture map to numeric levels 1/2/3
    assert levels == [(1, "Doctitle"), (2, "H1"), (3, "H2")]


def test_odl_reader_outline_tree_built_from_structure_tags():
    """Plan §3.2.a step 3: structure-tree info builds a section tree."""
    doc = ODLReader().read(FIXTURE_AFR_P163)
    # Top-level is the Doctitle
    assert len(doc.outline) == 1
    root = doc.outline[0]
    assert root.text == "Arizona Annual Financial Report FY 2025"
    # H1 child
    assert len(root.children) == 1
    assert root.children[0].text == "Notes to the Financial Statements"
    # H2 grandchild
    assert len(root.children[0].children) == 1
    assert (
        root.children[0].children[0].text
        == "Statement of Revenues, Expenditures and Changes in Fund Balance"
    )


def test_odl_reader_paragraph_carries_page_and_bbox():
    doc = ODLReader().read(FIXTURE_AFR_P163)
    paragraph = next(b for b in doc.pages[0].blocks if isinstance(b, Paragraph))
    assert paragraph.page == 163
    assert paragraph.bbox is not None
    assert paragraph.bbox.x0 == 72.0


def test_odl_reader_accepts_directory_path(tmp_path):
    """Plan: ODLReader should also accept a directory of page-N.json files."""
    import shutil

    # Copy fixture into a fake "out dir" with the expected page-N.json naming
    target_dir = tmp_path / "afr-fy25"
    target_dir.mkdir()
    shutil.copy(FIXTURE_AFR_P163, target_dir / "page-163.json")

    doc = ODLReader().read(target_dir)
    assert len(doc.pages) == 1
    assert doc.pages[0].page_number == 163


def test_odl_reader_directory_orders_pages_numerically(tmp_path):
    """page-2.json must come before page-10.json in the resulting page list."""
    import json

    target_dir = tmp_path / "multi"
    target_dir.mkdir()

    def _write_page(n: int, body: str) -> None:
        (target_dir / f"page-{n}.json").write_text(
            json.dumps(
                {
                    "extractor": "opendataloader-2.4.1",
                    "source_pdf": "fake.pdf",
                    "page": n,
                    "blocks": [
                        {
                            "type": "heading",
                            "id": f"h-{n}",
                            "page number": n,
                            "bounding box": [0, 0, 10, 10],
                            "content": body,
                            "heading level": 1,
                            "level": "Doctitle",
                        }
                    ],
                }
            )
        )

    _write_page(10, "later")
    _write_page(2, "early")
    doc = ODLReader().read(target_dir)
    assert [p.page_number for p in doc.pages] == [2, 10]


def test_odl_reader_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        ODLReader().read(Path("/nope/does-not-exist.json"))
