"""The coverage signal (spec T6).

Fixtures are built in-process with PyMuPDF rather than committed, so this
suite opens no corpus and loads no model.
"""
from pathlib import Path

import fitz
import pytest

from ingest.coverage import COVERAGE_FLOOR, coverage_ratio, source_text_chars


def _pdf(tmp_path: Path, pages: list[str], name: str = "f.pdf") -> Path:
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_text((72, 72), body)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_source_text_chars_counts_the_text_layer(tmp_path):
    path = _pdf(tmp_path, ["hello world", "second page"])
    assert source_text_chars(path) >= len("hello world") + len("second page")


def test_ratio_is_produced_over_source(tmp_path):
    path = _pdf(tmp_path, ["abcdefghij"])          # 10 chars of source text
    got = coverage_ratio(["abcde"], path)          # 5 chars produced
    assert got == pytest.approx(5 / source_text_chars(path))


def test_the_fy2024_afr_shape_lands_below_the_floor(tmp_path):
    """20 chunks from a 191-page document scored 2.0% on the real corpus."""
    path = _pdf(tmp_path, ["x" * 1000 for _ in range(10)])
    ratio = coverage_ratio(["x" * 20], path)
    assert ratio < COVERAGE_FLOOR


def test_a_ratio_above_one_is_returned_unchanged(tmp_path):
    """Healthy AFRs score 278-286% because chunk text carries table markup.

    Clamping to 1.0 would erase the single clearest signal that extraction
    is working. Pinned because "normalize it to a percentage" is a natural
    and wrong instinct.
    """
    path = _pdf(tmp_path, ["abc"])
    assert coverage_ratio(["x" * 10_000], path) > 1.0


def test_no_text_layer_returns_None_rather_than_zero(tmp_path):
    """An image-only PDF must route to OCR, not read as a failed extraction.

    0.0 and None are different answers: 0.0 means "we extracted nothing from
    a document that has text", None means "there is nothing here to compare
    against".
    """
    path = _pdf(tmp_path, [""])
    assert coverage_ratio(["anything"], path) is None


def test_the_floor_is_the_calibrated_value():
    """Pinned so a future edit has to go and re-read the calibration."""
    assert COVERAGE_FLOOR == 0.10
