"""Tests for chunking/builders/table_chunk.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.builders.table_chunk import DocMeta, build_table_chunk
from chunking.readers.mineru_reader import MinerUReader
from chunking.types import Chunk

FIXTURE_APPROPS_P513 = Path(__file__).parent / "fixtures" / "mineru-jlbc-approps-p513.json"


def _approps_meta() -> DocMeta:
    return DocMeta(
        doc_id="jlbc-approps-fy2026",
        publisher="jlbc",
        doc_type="bh-pdf",
        fiscal_year=2026,
    )


def test_build_table_chunk_returns_chunk():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    assert isinstance(chunk, Chunk)
    assert chunk.is_table is True


def test_build_table_chunk_preserves_html_for_ui():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    assert chunk.table_html is not None
    assert "<table>" in chunk.table_html
    assert "Parks" in chunk.table_html


def test_build_table_chunk_section_path_from_doc_outline():
    """Plan §3.3.a: chunk-shape D6 header propagation — section path stamped
    on the chunk so retrieval can recover the enclosing section context."""
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    # The Capital Outlay table is under the "Department of Administration" /
    # "Capital Outlay" outline path; the chunk's section_path should reflect that.
    assert chunk.section_path == ["Department of Administration", "Capital Outlay"]


def test_build_table_chunk_text_contains_section_caption_header_and_cells():
    """Embedded text format per the plan: section path → header row → flattened cells."""
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    # Section path appears
    assert "Department of Administration" in chunk.text
    assert "Capital Outlay" in chunk.text
    # Header row column labels appear (chunk-shape D6 — denormalized headers
    # ride with the text so retrieval surfaces them on header-keyword queries)
    assert "FY2026" in chunk.text
    assert "Project" in chunk.text
    # Body row content appears
    assert "Parks Statewide Solar Shade Structures" in chunk.text
    assert "1,200,000" in chunk.text


def test_build_table_chunk_doc_meta_propagated():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    assert chunk.doc_id == "jlbc-approps-fy2026"
    assert chunk.publisher == "jlbc"
    assert chunk.doc_type == "bh-pdf"
    assert chunk.fiscal_year == 2026


def test_build_table_chunk_id_is_doc_id_plus_index():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=7)
    # Zero-padded 4-digit sequence, allowing up to 9999 chunks per doc
    assert chunk.chunk_id == "jlbc-approps-fy2026-0007"


def test_build_table_chunk_provenance_carries_page_and_bbox():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    # PDF chunk → page+bbox provenance (chunk-shape D3)
    assert chunk.provenance.page == 513
    assert chunk.provenance.bbox is not None
    assert len(chunk.provenance.bbox) == 4


def test_build_table_chunk_token_count_set():
    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]
    chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    assert chunk.token_count > 0


def test_build_table_chunk_warns_when_table_exceeds_3k_tokens(monkeypatch):
    """Plan §3.3.a step 3 (chunk-shape D-defer-2): tables > 3K tokens should
    log a warning but still emit the chunk for now (manual review flag)."""
    import logging

    doc = MinerUReader().read(FIXTURE_APPROPS_P513)
    table = doc.tables[0]

    # Force the token-count helper to report a huge value
    import chunking.builders.table_chunk as mod
    monkeypatch.setattr(mod, "count_tokens", lambda _text: 5000)

    with pytest.warns() if False else _capture_logs("chunking.builders.table_chunk", logging.WARNING) as caplog:
        chunk = build_table_chunk(table, doc, _approps_meta(), chunk_index=0)
    assert chunk.token_count == 5000
    assert any("3000" in msg or "review" in msg.lower() for msg in caplog)


# --- helpers ----------------------------------------------------------------


from contextlib import contextmanager
import logging


@contextmanager
def _capture_logs(logger_name: str, level: int):
    """Capture log messages from a named logger as a list of strings."""
    captured: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    h = _Handler(level=level)
    logger = logging.getLogger(logger_name)
    prior_level = logger.level
    logger.setLevel(level)
    logger.addHandler(h)
    try:
        yield captured
    finally:
        logger.removeHandler(h)
        logger.setLevel(prior_level)
