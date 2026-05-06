"""Tests for primer/notes_chunker.py — AFR Notes ingestion as chunks.

Per plan §5.3: each Note 1..12 becomes one narrative chunk under doc_id
'agao-afr-fy25-notes' with section_path = ['Notes to Financial Statements',
'Note N — <title>']. Most Notes are short (< 500 tokens) so they fit
under the narrative chunk size limit comfortably.

Step 3 capture: defined-table-name → chunk-id mapping. Note 6 cites the
'Statement of Revenues, Expenditures and Changes in Fund Balance' — this
is captured separately for Phase 1b retrieval to join against table chunks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.builders.table_chunk import DocMeta
from chunking.readers.odl_reader import ODLReader
from chunking.types import Chunk
from primer.notes_chunker import chunk_afr_notes

FIXTURE = Path(__file__).parent / "fixtures" / "odl-afr-notes.json"


def _meta() -> DocMeta:
    return DocMeta(
        doc_id="agao-afr-fy25-notes",
        publisher="agao",
        doc_type="afr-notes",
        fiscal_year=2025,
        extractor="opendataloader",
        source_format="pdf",
    )


def _load():
    return ODLReader().read(FIXTURE)


# --- chunks ----------------------------------------------------------------


def test_chunk_afr_notes_returns_chunks_and_table_map():
    chunks, table_map = chunk_afr_notes(_load(), _meta())
    assert chunks
    assert isinstance(table_map, dict)


def test_chunk_afr_notes_one_chunk_per_note():
    """Fixture has Notes 1, 2, 6, 12 — 4 Notes total."""
    chunks, _ = chunk_afr_notes(_load(), _meta())
    assert len(chunks) == 4


def test_chunk_afr_notes_all_chunks_under_doc_meta():
    chunks, _ = chunk_afr_notes(_load(), _meta())
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.doc_id == "agao-afr-fy25-notes"
        assert c.publisher == "agao"
        assert c.doc_type == "afr-notes"
        assert c.fiscal_year == 2025


def test_chunk_afr_notes_section_path_includes_notes_root_and_note_heading():
    chunks, _ = chunk_afr_notes(_load(), _meta())
    note_1 = next(c for c in chunks if "Note 1" in c.section_path[-1])
    assert note_1.section_path == [
        "Notes to Financial Statements",
        "Note 1 — Summary of Significant Accounting Policies",
    ]


def test_chunk_afr_notes_text_includes_section_header_and_body():
    """Section path denormalized into chunk.text per chunk-shape D6."""
    chunks, _ = chunk_afr_notes(_load(), _meta())
    note_1 = next(c for c in chunks if "Note 1" in c.section_path[-1])
    assert "Notes to Financial Statements" in note_1.text
    assert "Note 1" in note_1.text
    assert "GAAP" in note_1.text  # body content


def test_chunk_afr_notes_multi_paragraph_body_concatenated():
    """Note 1 has 2 body paragraphs; Note 6 has 2 body paragraphs."""
    chunks, _ = chunk_afr_notes(_load(), _meta())
    note_1 = next(c for c in chunks if "Note 1" in c.section_path[-1])
    assert "GAAP" in note_1.text
    assert "Governmental Accounting Standards Board" in note_1.text
    note_6 = next(c for c in chunks if "Note 6" in c.section_path[-1])
    assert "nonspendable, restricted" in note_6.text
    assert "$4.2 billion" in note_6.text


def test_chunk_afr_notes_provenance_uses_first_paragraph_page_and_bbox():
    chunks, _ = chunk_afr_notes(_load(), _meta())
    note_2 = next(c for c in chunks if "Note 2" in c.section_path[-1])
    assert note_2.provenance.page == 175
    assert note_2.provenance.bbox is not None


def test_chunk_afr_notes_chunk_ids_sequential_and_zero_padded():
    chunks, _ = chunk_afr_notes(_load(), _meta())
    ids = [c.chunk_id for c in chunks]
    assert ids[0] == "agao-afr-fy25-notes-0000"
    suffixes = [int(cid.rsplit("-", 1)[-1]) for cid in ids]
    assert suffixes == list(range(len(suffixes)))


def test_chunk_afr_notes_token_count_set():
    chunks, _ = chunk_afr_notes(_load(), _meta())
    for c in chunks:
        assert c.token_count > 0
        # Plan note: most Notes are < 500 tokens; even Note 6 (the longest
        # in the fixture) should comfortably fit under the narrative max.
        assert c.token_count < 1024


def test_chunk_afr_notes_is_table_false():
    """Notes are narrative, not tables."""
    chunks, _ = chunk_afr_notes(_load(), _meta())
    for c in chunks:
        assert c.is_table is False
        assert c.table_html is None


# --- table-name mapping (step 3) -------------------------------------------


def test_chunk_afr_notes_captures_named_financial_statement():
    """Plan §5.3 step 3: Note 6 cites 'Statement of Revenues, Expenditures
    and Changes in Fund Balance' — capture so Phase 1b retrieval can join
    table chunks to this Note's chunk_id."""
    chunks, table_map = chunk_afr_notes(_load(), _meta())
    note_6 = next(c for c in chunks if "Note 6" in c.section_path[-1])
    assert (
        "Statement of Revenues, Expenditures and Changes in Fund Balance"
        in table_map
    )
    assert (
        table_map["Statement of Revenues, Expenditures and Changes in Fund Balance"]
        == note_6.chunk_id
    )


def test_chunk_afr_notes_table_map_empty_when_no_named_statements():
    """Notes that don't cite a named financial statement contribute
    nothing to the table_map."""
    chunks, table_map = chunk_afr_notes(_load(), _meta())
    # Note 1 / 2 / 12 don't cite any 'Statement of …' table by name.
    # The fixture only has the one citation in Note 6.
    assert len(table_map) == 1


# --- empty / degenerate ----------------------------------------------------


def test_chunk_afr_notes_empty_doc_returns_empty_results():
    """When the document has no 'Notes to Financial Statements' section,
    return empty results — don't fabricate."""
    from chunking.readers.types import ExtractedDocument

    doc = ExtractedDocument(source_path=Path("x"), extractor="opendataloader")
    chunks, table_map = chunk_afr_notes(doc, _meta())
    assert chunks == []
    assert table_map == {}


def test_chunk_afr_notes_skips_note_section_with_no_body():
    """A heading 'Note 7 — TBD' with no body paragraphs is skipped — we
    don't emit empty chunks."""
    import json
    import tempfile

    payload = {
        "extractor": "opendataloader-2.4.1",
        "source_pdf": "fake.pdf",
        "page": 1,
        "blocks": [
            {
                "type": "heading",
                "id": "h-section",
                "page number": 1,
                "bounding box": [0, 0, 100, 100],
                "content": "Notes to Financial Statements",
                "heading level": 1,
                "level": "H1",
            },
            {
                "type": "heading",
                "id": "h-note-7",
                "page number": 1,
                "bounding box": [0, 0, 100, 100],
                "content": "Note 7 — TBD",
                "heading level": 2,
                "level": "H2",
            },
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        tmp_path = f.name

    try:
        doc = ODLReader().read(Path(tmp_path))
        chunks, _ = chunk_afr_notes(doc, _meta())
        assert chunks == []
    finally:
        Path(tmp_path).unlink()
