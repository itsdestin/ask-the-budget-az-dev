from pathlib import Path

import fitz

from ingest.inspection import inspect_source


def _pdf(tmp_path: Path, *, pages: int, text: bool) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), "The Baseline includes $1,000,000 for X.")
    path = tmp_path / "f.pdf"
    doc.save(path)
    doc.close()
    return path


def test_reports_format_and_page_count(tmp_path):
    got = inspect_source(_pdf(tmp_path, pages=3, text=True))
    assert got.source_format == "pdf"
    assert got.pages == 3


def test_detects_a_text_layer(tmp_path):
    assert inspect_source(_pdf(tmp_path, pages=1, text=True)).has_text_layer is True


def test_detects_the_absence_of_a_text_layer(tmp_path):
    assert inspect_source(_pdf(tmp_path, pages=1, text=False)).has_text_layer is False


def test_inspection_reports_nothing_about_tagging(tmp_path):
    """A regression guard, not a capability test.

    Tagging was measured across every OpenDataLoader-first document and does
    not predict extraction success: an UNTAGGED 639-page Executive Budget
    scores 92.2% through OpenDataLoader, while the one document that fails IS
    tagged. A future edit that re-adds this field will re-add the rule that
    consumes it, which diverts a healthy document to a slower extractor.
    """
    got = inspect_source(_pdf(tmp_path, pages=1, text=True))
    assert not hasattr(got, "has_structure_tree")


def test_docx_has_no_page_count(tmp_path):
    """DOCX has no pages at rest. None, not 0 -- 0 would read as "empty"."""
    import docx

    d = docx.Document()
    d.add_paragraph("Section 1. Appropriations.")
    path = tmp_path / "bill.docx"
    d.save(path)

    got = inspect_source(path)
    assert got.source_format == "docx"
    assert got.pages is None
    assert got.has_text_layer is True


def test_an_unreadable_file_does_not_raise(tmp_path):
    """A truncated download must not take the worker thread down.

    pdfium rejects shapes PyMuPDF tolerates and vice versa; whatever the
    reason, an inspection failure means "we learned nothing", which is a
    valid answer that starts the ladder at rung 1.
    """
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nnot really a pdf")

    got = inspect_source(path)
    assert got.pages is None
    assert got.has_text_layer is False
