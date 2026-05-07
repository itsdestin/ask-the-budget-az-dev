"""Phase 1b WS2 loader tests.

Two layers:
- Pure unit tests for `chunk_to_row` -- no DB required, run on every CI tick.
- Integration tests for `load_doc` against a live Postgres -- skipped when
  DATABASE_URL is unset or the local Docker stack isn't up.

Real-chunk fixtures are produced on the fly by calling `chunking.builder.chunk_doc`
against extractor-output JSONs already on disk under tests/fixtures/. That keeps
the test deterministic without forcing a slice re-run (which would need MinerU+CUDA).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Lazy imports so test collection works even if psycopg isn't available yet.
psycopg = pytest.importorskip("psycopg")

from chunking.builder import chunk_doc
from chunking.builders.table_chunk import DocMeta
from chunking.types import Chunk, ChunkProvenance
from db.connection import close_pool, get_connection
from db.loader import (
    DocumentMeta,
    chunk_to_row,
    load_chunk_file,
    load_doc,
    parse_chunk_ndjson,
)
from db.validate import run_checks

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# DB availability helper -- mirrors tests/test_connection.py.
# ---------------------------------------------------------------------------


def _has_database() -> bool:
    """True when DATABASE_URL is set AND the DB is reachable on a 1s timeout."""
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _has_database(),
    reason="DATABASE_URL unset or local Postgres not running. Start with `cd db && docker compose up -d`.",
)


# ---------------------------------------------------------------------------
# Pure unit tests for chunk_to_row.
# ---------------------------------------------------------------------------


def _pdf_chunk(**overrides) -> Chunk:
    """Build a PDF-shaped Chunk with sensible defaults; overrides win."""
    base = dict(
        chunk_id="jlbc-baseline-fy2027-s18-0001",
        doc_id="jlbc-baseline-fy2027-s18",
        text="Department of Corrections General Fund: $1,750,000,000",
        section_path=["Department of Corrections", "Operating Lump Sum"],
        is_table=False,
        table_html=None,
        provenance=ChunkProvenance(page=3, bbox=[72.0, 100.0, 540.0, 200.0]),
        agency_canonical_id="agency:adc",
        fund_canonical_id="fund:general",
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        publisher="jlbc",
        token_count=42,
        fund_mentions=["fund:general"],
    )
    base.update(overrides)
    return Chunk(**base)


def _docx_chunk(**overrides) -> Chunk:
    base = dict(
        chunk_id="legislature-budget-bill-fy2026-sb1735-2025-0042",
        doc_id="legislature-budget-bill-fy2026-sb1735-2025",
        text="Sec. 7. APPROPRIATION; STATE TREASURER...",
        section_path=["Section 7", "State Treasurer"],
        is_table=False,
        table_html=None,
        provenance=ChunkProvenance(paragraph_id="p47"),
        agency_canonical_id="agency:state-treasurer",
        fund_canonical_id=None,
        fiscal_year=2026,
        doc_type="budget-bill",
        publisher="legislature",
        token_count=89,
        fund_mentions=[],
    )
    base.update(overrides)
    return Chunk(**base)


def test_chunk_to_row_pdf_provenance():
    """PDF chunks populate page+bbox; source_anchor stays NULL."""
    row = chunk_to_row(_pdf_chunk(), doc_id="jlbc-baseline-fy2027-s18")

    assert row["page"] == 3
    assert row["bbox"] == [72.0, 100.0, 540.0, 200.0]
    assert row["source_anchor"] is None


def test_chunk_to_row_docx_provenance_paragraph_only():
    """DOCX chunks with no table cell get a single-key source_anchor."""
    row = chunk_to_row(_docx_chunk(), doc_id="legislature-budget-bill-fy2026-sb1735-2025")

    assert row["page"] is None
    assert row["bbox"] is None
    # source_anchor is wrapped in psycopg's Jsonb adapter; .obj exposes the dict.
    anchor = row["source_anchor"].obj
    assert anchor == {"paragraph_id": "p47"}


def test_chunk_to_row_docx_provenance_with_table_cell():
    """DOCX chunks with a table cell carry both keys in source_anchor."""
    row = chunk_to_row(
        _docx_chunk(
            provenance=ChunkProvenance(paragraph_id="p47", table_cell_id="tbl3.r5.c2"),
        ),
        doc_id="legislature-budget-bill-fy2026-sb1735-2025",
    )

    anchor = row["source_anchor"].obj
    assert anchor == {"paragraph_id": "p47", "table_cell_id": "tbl3.r5.c2"}


def test_chunk_to_row_promotes_scalar_agency_to_array():
    """Decision D2: singular agency_canonical_id -> 1-element array."""
    row = chunk_to_row(
        _pdf_chunk(agency_canonical_id="agency:adc"),
        doc_id="jlbc-baseline-fy2027-s18",
    )
    assert row["agency_canonical_ids"] == ["agency:adc"]


def test_chunk_to_row_null_agency_becomes_empty_array():
    """No agency stamp -> empty array, NOT a 1-element [None] array."""
    row = chunk_to_row(
        _pdf_chunk(agency_canonical_id=None),
        doc_id="jlbc-baseline-fy2027-s18",
    )
    assert row["agency_canonical_ids"] == []


def test_chunk_to_row_carries_table_html_when_is_table():
    """is_table chunks preserve table_html for downstream rendering."""
    row = chunk_to_row(
        _pdf_chunk(is_table=True, table_html="<table><tr><td>X</td></tr></table>"),
        doc_id="jlbc-baseline-fy2027-s18",
    )
    assert row["is_table"] is True
    assert row["table_html"] == "<table><tr><td>X</td></tr></table>"


def test_chunk_to_row_carries_section_path_and_fund_mentions():
    """section_path and fund_mentions pass through as Python lists for psycopg adapter."""
    chunk = _pdf_chunk(
        section_path=["A", "B", "C"],
        fund_mentions=["fund:general", "fund:aviation"],
    )
    row = chunk_to_row(chunk, doc_id=chunk.doc_id)
    assert row["section_path"] == ["A", "B", "C"]
    assert row["fund_mentions"] == ["fund:general", "fund:aviation"]


# ---------------------------------------------------------------------------
# parse_chunk_ndjson: file IO smoke.
# ---------------------------------------------------------------------------


def test_parse_chunk_ndjson_round_trip(tmp_path: Path):
    """Pydantic model_dump_json -> file -> parse_chunk_ndjson preserves shape."""
    chunks = [_pdf_chunk(), _docx_chunk()]
    path = tmp_path / "sample.json"
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")

    parsed = parse_chunk_ndjson(path)
    assert len(parsed) == 2
    assert parsed[0].chunk_id == chunks[0].chunk_id
    assert parsed[1].provenance.paragraph_id == "p47"


def test_parse_chunk_ndjson_skips_blank_lines(tmp_path: Path):
    """Blank lines (trailing newline at EOF, etc.) are tolerated."""
    chunks = [_pdf_chunk()]
    path = tmp_path / "sample.json"
    path.write_text(chunks[0].model_dump_json() + "\n\n\n", encoding="utf-8")
    parsed = parse_chunk_ndjson(path)
    assert len(parsed) == 1


# ---------------------------------------------------------------------------
# Integration tests against a live database. Skip when DB isn't available.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool_between_tests():
    yield
    close_pool()


@pytest.fixture
def s18_doc_meta() -> DocumentMeta:
    """DocumentMeta for the JLBC FY27 baseline s18 fixture."""
    return DocumentMeta(
        doc_id="jlbc-baseline-fy2027-s18",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
        title="JLBC FY2027 Baseline s18 — Other Fund Summary by Agency",
        source_url="https://www.azjlbc.gov/27baseline/s18.pdf",
        source_format="pdf",
        source_blob_path="data/cached-pdfs/jlbc-baseline-fy2027-s18.pdf",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    )


@pytest.fixture
def s18_chunks() -> list[Chunk]:
    """Real chunks built via chunk_doc() from the committed MinerU fixture.

    Stable input without re-running the slice ingest -- same path the existing
    chunking tests use.
    """
    chunks = chunk_doc(
        extractor_output_path=FIXTURES / "mineru-jlbc-baseline-s18.json",
        doc_meta=DocMeta(
            doc_id="jlbc-baseline-fy2027-s18",
            publisher="jlbc",
            doc_type="baseline-cross-cut",
            fiscal_year=2027,
            extractor="mineru",
            source_format="pdf",
            source_url="https://www.azjlbc.gov/27baseline/s18.pdf",
        ),
    )
    assert chunks, "chunk_doc returned no chunks -- fixture may have regressed"
    return chunks


@pytest.fixture
def s18_ndjson(tmp_path: Path, s18_chunks: list[Chunk]) -> Path:
    """Write the real chunks to an NDJSON tmp file (mirrors data/chunks/<doc>.json)."""
    path = tmp_path / "jlbc-baseline-fy2027-s18.json"
    with path.open("w", encoding="utf-8") as f:
        for c in s18_chunks:
            f.write(c.model_dump_json() + "\n")
    return path


def _truncate_load_state(conn) -> None:
    """Wipe documents + chunks so each integration test starts clean.

    `RESTART IDENTITY CASCADE` unused -- tables have no SERIAL/IDENTITY columns
    and the FK is documents -> chunks (cascade not needed).
    """
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM documents")


@needs_db
def test_load_chunk_file_inserts_document_and_chunks(
    s18_ndjson: Path,
    s18_doc_meta: DocumentMeta,
    s18_chunks: list[Chunk],
):
    with get_connection() as conn:
        _truncate_load_state(conn)
        n = load_chunk_file(s18_ndjson, s18_doc_meta, conn)
        assert n == len(s18_chunks)

        doc = conn.execute(
            "SELECT publisher, doc_type, fiscal_year, source_format, extractor "
            "FROM documents WHERE doc_id = 'jlbc-baseline-fy2027-s18'"
        ).fetchone()
        assert doc["publisher"] == "jlbc"
        assert doc["doc_type"] == "baseline-cross-cut"
        assert doc["fiscal_year"] == 2027
        assert doc["source_format"] == "pdf"
        assert doc["extractor"] == "mineru-2.5"

        chunks_in_db = conn.execute(
            "SELECT COUNT(*)::INT AS n FROM chunks WHERE doc_id = 'jlbc-baseline-fy2027-s18'"
        ).fetchone()
        assert chunks_in_db["n"] == len(s18_chunks)


@needs_db
def test_load_promotes_agency_id_to_array(
    s18_ndjson: Path, s18_doc_meta: DocumentMeta
):
    """At least one s18 chunk should land with an agency_canonical_ids array."""
    with get_connection() as conn:
        _truncate_load_state(conn)
        load_chunk_file(s18_ndjson, s18_doc_meta, conn)

        row = conn.execute(
            "SELECT chunk_id, agency_canonical_ids FROM chunks "
            "WHERE doc_id = 'jlbc-baseline-fy2027-s18' "
            "AND array_length(agency_canonical_ids, 1) > 0 "
            "LIMIT 1"
        ).fetchone()
        assert row is not None, "no chunks landed with an agency stamped"
        # The DB returns a Python list for TEXT[]
        assert isinstance(row["agency_canonical_ids"], list)
        assert all(aid.startswith("agency:") for aid in row["agency_canonical_ids"])


@needs_db
def test_load_satisfies_provenance_check_for_pdf(
    s18_ndjson: Path, s18_doc_meta: DocumentMeta
):
    """All s18 chunks are PDF -> page IS NOT NULL AND bbox IS NOT NULL."""
    with get_connection() as conn:
        _truncate_load_state(conn)
        load_chunk_file(s18_ndjson, s18_doc_meta, conn)

        bad = conn.execute(
            "SELECT COUNT(*)::INT AS n FROM chunks "
            "WHERE doc_id = 'jlbc-baseline-fy2027-s18' "
            "AND (page IS NULL OR bbox IS NULL)"
        ).fetchone()
        assert bad["n"] == 0


@needs_db
def test_load_idempotent(s18_ndjson: Path, s18_doc_meta: DocumentMeta):
    """Running the loader twice yields the same row count (ON CONFLICT DO UPDATE)."""
    with get_connection() as conn:
        _truncate_load_state(conn)
        n1 = load_chunk_file(s18_ndjson, s18_doc_meta, conn)
        n2 = load_chunk_file(s18_ndjson, s18_doc_meta, conn)
        assert n1 == n2

        actual = conn.execute(
            "SELECT COUNT(*)::INT AS n FROM chunks WHERE doc_id = 'jlbc-baseline-fy2027-s18'"
        ).fetchone()
        assert actual["n"] == n1


@needs_db
def test_load_rejects_chunk_with_wrong_meta(
    s18_chunks: list[Chunk], tmp_path: Path
):
    """Cross-check: meta.publisher mismatching the chunk raises before any insert."""
    bad_meta = DocumentMeta(
        doc_id="jlbc-baseline-fy2027-s18",
        publisher="agao",  # WRONG; chunks say 'jlbc'
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
        title="ignored",
        source_format="pdf",
        source_blob_path="ignored",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    )
    with get_connection() as conn:
        _truncate_load_state(conn)
        with pytest.raises(ValueError, match="publisher"):
            load_doc(s18_chunks, bad_meta, conn)


@needs_db
def test_validate_run_checks_passes_after_load(
    s18_ndjson: Path, s18_doc_meta: DocumentMeta
):
    """db.validate.run_checks reports zero failures on a freshly-loaded slice."""
    with get_connection() as conn:
        _truncate_load_state(conn)
        load_chunk_file(s18_ndjson, s18_doc_meta, conn)

        results = run_checks(conn)
        failed = [r for r in results if not r.passed]
        # Diagnostic dump on failure makes pytest output actionable.
        assert not failed, "Validation failures:\n" + "\n".join(
            f"  - {r.label}: actual={r.actual} ({r.why})" for r in failed
        )
