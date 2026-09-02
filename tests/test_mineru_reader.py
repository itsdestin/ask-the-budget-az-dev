"""Tests for chunking/readers/mineru_reader.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.types import ExtractedDocument, Heading, Image, Paragraph, Table

FIXTURE_APPROPS_P513 = Path(__file__).parent / "fixtures" / "mineru-jlbc-approps-p513.json"


def test_mineru_reader_returns_extracted_document():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    assert isinstance(doc, ExtractedDocument)
    assert doc.extractor == "mineru"


def test_mineru_reader_block_kinds():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    blocks = doc.pages[0].blocks
    # 2 headings (text_level=1, text_level=2), 1 paragraph, 1 table, 1 image
    assert sum(1 for b in blocks if isinstance(b, Heading)) == 2
    assert sum(1 for b in blocks if isinstance(b, Paragraph)) == 1
    assert sum(1 for b in blocks if isinstance(b, Table)) == 1
    assert sum(1 for b in blocks if isinstance(b, Image)) == 1


def test_mineru_reader_text_level_is_heading_signal():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    headings = [b for b in doc.pages[0].blocks if isinstance(b, Heading)]
    levels = [(h.level, h.text) for h in headings]
    assert levels == [
        (1, "Department of Administration"),
        (2, "Capital Outlay"),
    ]


def test_mineru_reader_html_table_parsed_to_rows_and_cells():
    """Plan §3.2.b: HTML tables → row/col cells."""
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    # 1 header row + 2 body rows = 3
    assert len(table.rows) == 3
    # Header row
    assert [c.text for c in table.rows[0].cells] == ["Project", "FY2026"]
    # Parks line item — the test from the plan, verbatim
    assert any(
        "Parks" in cell.text for row in table.rows for cell in row.cells
    )
    # Original HTML preserved on the Table
    assert table.html and "<table>" in table.html


def test_mineru_reader_table_cell_indices():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    assert table.rows[0].cells[0].row == 0
    assert table.rows[0].cells[0].col == 0
    assert table.rows[2].cells[1].row == 2
    assert table.rows[2].cells[1].col == 1


def test_mineru_reader_blocks_carry_page_from_outer_field():
    """Plan note in run_mineru.py: per-page JSON's outer `page` is authoritative;
    block-internal `page_idx` may carry the CLI's local re-indexing."""
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    paragraph = next(b for b in doc.pages[0].blocks if isinstance(b, Paragraph))
    assert paragraph.page == 513
    table = doc.tables[0]
    assert table.page == 513


def test_mineru_reader_outline_built_from_text_levels():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    assert len(doc.outline) == 1
    root = doc.outline[0]
    assert root.text == "Department of Administration"
    assert len(root.children) == 1
    assert root.children[0].text == "Capital Outlay"


# --- Multi-page table reassembly --------------------------------------------


def test_mineru_reader_reassembles_multi_page_table(tmp_path):
    """Plan §3.2.b step 4: tables on consecutive pages with the same column
    headers reassemble into one logical table.
    """
    target_dir = tmp_path / "multi"
    target_dir.mkdir()

    def _write_page(n: int, table_html: str, *, has_heading_above: bool = False) -> None:
        blocks: list[dict] = []
        if has_heading_above:
            blocks.append({
                "type": "text",
                "text": f"Section on page {n}",
                "text_level": 1,
                "bbox": [72, 700, 540, 720],
                "page_idx": n - 1,
            })
        blocks.append({
            "type": "table",
            "table_body": table_html,
            "bbox": [72, 400, 540, 600],
            "page_idx": n - 1,
        })
        (target_dir / f"page-{n}.json").write_text(
            json.dumps({
                "extractor": "mineru-3.1.6",
                "source_pdf": "fake.pdf",
                "page": n,
                "blocks": blocks,
            })
        )

    # Same column headers on both pages — these should reassemble.
    _write_page(
        10,
        "<table><tr><th>Agency</th><th>FY2026</th></tr><tr><td>AHCCCS</td><td>$14.5B</td></tr></table>",
        has_heading_above=True,
    )
    _write_page(
        11,
        "<table><tr><th>Agency</th><th>FY2026</th></tr><tr><td>ADC</td><td>$1.6B</td></tr></table>",
    )

    doc = MinerUReader().read(target_dir)
    # Tables reassembled: one logical table, header row + 2 body rows
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert len(table.rows) == 3
    assert [c.text for c in table.rows[0].cells] == ["Agency", "FY2026"]
    body_text = " ".join(c.text for r in table.rows[1:] for c in r.cells)
    assert "AHCCCS" in body_text
    assert "ADC" in body_text
    # Pages are tracked
    assert table.pages == [10, 11]


def test_mineru_reader_does_not_merge_tables_with_different_headers(tmp_path):
    target_dir = tmp_path / "diff-headers"
    target_dir.mkdir()

    (target_dir / "page-10.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6",
        "source_pdf": "fake.pdf",
        "page": 10,
        "blocks": [{
            "type": "table",
            "table_body": "<table><tr><th>Agency</th><th>FY2026</th></tr><tr><td>AHCCCS</td><td>$14.5B</td></tr></table>",
            "bbox": [72, 400, 540, 600],
            "page_idx": 9,
        }],
    }))
    (target_dir / "page-11.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6",
        "source_pdf": "fake.pdf",
        "page": 11,
        "blocks": [{
            "type": "table",
            "table_body": "<table><tr><th>Project</th><th>Cost</th></tr><tr><td>Parks</td><td>$1.2M</td></tr></table>",
            "bbox": [72, 400, 540, 600],
            "page_idx": 10,
        }],
    }))

    doc = MinerUReader().read(target_dir)
    assert len(doc.tables) == 2  # different headers — kept separate


def test_mineru_reader_does_not_merge_tables_separated_by_heading(tmp_path):
    """Heading between tables = new section = don't merge even if headers match."""
    target_dir = tmp_path / "separated"
    target_dir.mkdir()

    (target_dir / "page-10.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6",
        "source_pdf": "fake.pdf",
        "page": 10,
        "blocks": [{
            "type": "table",
            "table_body": "<table><tr><th>Agency</th><th>FY2026</th></tr><tr><td>AHCCCS</td><td>$14.5B</td></tr></table>",
            "bbox": [72, 400, 540, 600],
            "page_idx": 9,
        }],
    }))
    (target_dir / "page-11.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6",
        "source_pdf": "fake.pdf",
        "page": 11,
        "blocks": [
            {
                "type": "text",
                "text": "Department of Health Services",
                "text_level": 1,
                "bbox": [72, 700, 540, 720],
                "page_idx": 10,
            },
            {
                "type": "table",
                "table_body": "<table><tr><th>Agency</th><th>FY2026</th></tr><tr><td>ADHS</td><td>$1.1B</td></tr></table>",
                "bbox": [72, 400, 540, 600],
                "page_idx": 10,
            },
        ],
    }))

    doc = MinerUReader().read(target_dir)
    assert len(doc.tables) == 2


def test_mineru_reader_handles_table_with_no_explicit_thead(tmp_path):
    """Many MinerU tables don't use <thead> — first <tr> is the header."""
    target_dir = tmp_path / "no-thead"
    target_dir.mkdir()
    (target_dir / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6",
        "source_pdf": "fake.pdf",
        "page": 1,
        "blocks": [{
            "type": "table",
            "table_body": "<table><tr><td>Fund</td><td>FY2026</td></tr><tr><td>General Fund</td><td>$13B</td></tr></table>",
            "bbox": [72, 400, 540, 600],
            "page_idx": 0,
        }],
    }))
    doc = MinerUReader().read(target_dir)
    table = doc.tables[0]
    assert len(table.rows) == 2
    assert [c.text for c in table.rows[0].cells] == ["Fund", "FY2026"]


def test_reader_refines_operating_tables_when_given_the_pdf(tmp_path):
    """Spec D5: the refinement is inside the reader, so ingest and repair share it."""
    import fitz
    from tests.test_text_layer_table import CLEAN_HTML, PageBuilder, _clean_page

    pdf = fitz.open()
    _clean_page(PageBuilder(pdf))
    pdf_path = tmp_path / "axs.pdf"
    pdf.save(str(pdf_path))
    page_json = tmp_path / "page-1.json"
    page_json.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")

    plain = MinerUReader().read(page_json).tables[0]
    refined = MinerUReader(source_pdf=pdf_path).read(page_json).tables[0]
    assert [c.text for c in plain.rows[0].cells] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]
    assert [c.text for c in refined.rows[3].cells] == ["Personal Services", "100", "200", "300"]
    assert refined.page == plain.page and refined.bbox == plain.bbox


def test_refine_falls_back_to_mineru_when_the_pdf_cannot_be_opened(tmp_path):
    """Spec D3 + the shared-rung finding: both in-scope doc types run
    [mineru, mineru-ocr] (ingest/ladder.py), every rung the SAME
    source_pdf -- so a PDF MinerU extracted fine but PyMuPDF refuses must
    not raise out of read(), or it exhausts the ladder and the whole
    document is held out of search where it used to reach `live`."""
    from tests.test_text_layer_table import CLEAN_HTML

    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\nnot a real pdf\n")
    page_json = tmp_path / "page-1.json"
    page_json.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")

    doc = MinerUReader(source_pdf=bad_pdf).read(page_json)  # must not raise
    table = doc.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]


def test_refine_falls_back_to_mineru_when_refine_operating_table_raises(tmp_path, monkeypatch):
    """One bad table must not cost its siblings: a table that raises inside
    the refinement keeps its MinerU text; a qualifying table on another
    page still refines normally."""
    import fitz

    from chunking.readers import mineru_reader as mod
    from tests.test_text_layer_table import CLEAN_HTML, PageBuilder, _clean_page

    pdf = fitz.open()
    _clean_page(PageBuilder(pdf))  # page 1 — will raise
    _clean_page(PageBuilder(pdf))  # page 2 — refines normally
    pdf_path = tmp_path / "axs.pdf"
    pdf.save(str(pdf_path))

    block = {"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}
    # WHY a heading sits between the two tables: both in-scope doc types'
    # tables share an identical column header, and _reassemble_multi_page_tables
    # (which runs BEFORE refinement) merges two same-header tables on
    # consecutive pages with no intervening heading into ONE logical
    # table -- which would leave only one qualifying block to test
    # against, not two. A heading breaks that chain (as it does for a
    # real agency-to-agency page boundary), keeping them distinct.
    heading = {"type": "text", "text_level": 1, "text": "Next Agency"}
    (tmp_path / "page-1.json").write_text(json.dumps(
        {"extractor": "mineru-3.1.6", "page": 1, "blocks": [block]}), encoding="utf-8")
    (tmp_path / "page-2.json").write_text(json.dumps(
        {"extractor": "mineru-3.1.6", "page": 2, "blocks": [heading, block]}), encoding="utf-8")

    real_refine = mod.refine_operating_table
    calls = {"n": 0}

    def flaky(table, pdf_doc):
        calls["n"] += 1
        if table.page == 1:
            raise RuntimeError("boom")
        return real_refine(table, pdf_doc)

    monkeypatch.setattr(mod, "refine_operating_table", flaky)

    doc = MinerUReader(source_pdf=pdf_path).read(tmp_path)  # must not raise
    page1_table = next(t for t in doc.tables if t.page == 1)
    page2_table = next(t for t in doc.tables if t.page == 2)
    # page 1 kept MinerU's plain header row (never refined)
    assert [c.text for c in page1_table.rows[0].cells] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]
    # page 2 refined normally despite page 1's failure
    assert [c.text for c in page2_table.rows[3].cells] == ["Personal Services", "100", "200", "300"]
    assert calls["n"] == 2
