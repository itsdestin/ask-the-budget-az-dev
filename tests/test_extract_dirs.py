"""ingest.extract_dirs.resolve_extract_dir — the READ side of the layout
`ingest/worker.py::_extract_dir` / `_legacy_extract_dir` write.

The sidecar's `extraction.method` decides the folder. It has to: on the live
share `agao-afr-fy2024` holds both `mineru/` and `mineru-ocr/` (the
2026-08-13 forced-fallback experiment wrote the OCR one) and the corpus
holds the MinerU reading. A rule that picks by folder name reads the wrong
document and the repair's body gate then skips it -- the exact document
spec G-T4's prediction is about.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest.extract_dirs import resolve_extract_dir


def _pages(directory: Path, extractor: str, *pages: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for p in pages:
        (directory / f"page-{p}.json").write_text(
            json.dumps({"extractor": extractor, "page": p, "blocks": []}), encoding="utf-8"
        )


def test_legacy_root_layout_when_no_method_is_recorded(tmp_path: Path):
    _pages(tmp_path / "extractor-output" / "doc-a", "opendataloader-2.4.1", 1, 2)
    assert resolve_extract_dir("doc-a", tmp_path) == (
        tmp_path / "extractor-output" / "doc-a", "opendataloader-2.4.1"
    )


def test_the_sidecar_method_picks_the_folder_even_when_the_root_has_pages(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base, "opendataloader-2.4.1", 1)            # an older reading
    _pages(base / "mineru", "mineru-3.1.6", 1)
    _pages(base / "mineru-ocr", "mineru-3.1.6", 1)     # a rung that lost
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru") == (base / "mineru", "mineru-3.1.6")


def test_a_recorded_method_with_no_output_on_disk_is_none_not_a_guess(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base / "mineru-ocr", "mineru-3.1.6", 1)
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru") is None


def test_missing_document_is_none(tmp_path: Path):
    assert resolve_extract_dir("nope", tmp_path) is None


def test_the_extractor_comes_from_the_page_file_not_the_folder_name(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base / "mineru", "mineru-3.4.4", 1)
    (base / "manifest.json").write_text(json.dumps({"extractor": "opendataloader"}), encoding="utf-8")
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru")[1] == "mineru-3.4.4"
