"""Tests for ingest/lance_writer.py — Chunk → LanceDB row + per-doc write."""
from __future__ import annotations

import json

import pytest

from chunking.types import Chunk, ChunkProvenance, DocMeta
from ingest.lance_writer import build_title, chunk_to_lance_row, write_doc
from store.chunk_store import ChunkStore


def _chunk(i: int, **over) -> Chunk:
    base = dict(
        chunk_id=f"gov-test-fy2027-{i:04d}", doc_id="gov-test-fy2027",
        text=f"appropriation text {i}", section_path=["A"], is_table=False,
        table_html=None,
        provenance=ChunkProvenance(page=i + 1, bbox=[1, 2, 3, 4],
                                   paragraph_id=None, table_cell_id=None),
        agency_canonical_id="agency:axs", fund_canonical_id=None,
        fiscal_year=2027, doc_type="governors-budget", publisher="governor",
        token_count=4, alias_chain=[], fund_mentions=[],
    )
    base.update(over)
    return Chunk(**base)


def _meta() -> DocMeta:
    return DocMeta(doc_id="gov-test-fy2027", publisher="governor",
                   doc_type="governors-budget", fiscal_year=2027)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


# --- row mapping ------------------------------------------------------------


def test_row_mapping_matches_schema():
    row = chunk_to_lance_row(_chunk(0), vector=[0.0] * 8)
    assert row["agency_canonical_ids"] == ["agency:axs"]   # scalar → array
    assert json.loads(row["source_anchor"])["page"] == 1
    assert row["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert "alias_chain" not in row


def test_row_columns_exactly_match_the_arrow_schema():
    """A stray key fails the whole batch at add() time, and a missing
    non-nullable column fails just as loudly — pin the set."""
    from store.schema import chunk_schema
    row = chunk_to_lance_row(_chunk(0), vector=[0.0] * 8)
    assert set(row) == {f.name for f in chunk_schema(dim=8)}


def test_row_maps_docx_provenance_to_source_anchor():
    chunk = _chunk(0, provenance=ChunkProvenance(
        paragraph_id="p-12", table_cell_id="t-3"))
    row = chunk_to_lance_row(chunk, vector=[0.0] * 8)
    assert row["page"] is None and row["bbox"] is None
    assert json.loads(row["source_anchor"]) == {
        "paragraph_id": "p-12", "table_cell_id": "t-3"}


def test_row_normalizes_null_list_columns():
    """The Arrow list columns are non-nullable — a None fails the batch."""
    chunk = _chunk(0, agency_canonical_id=None, section_path=[], fund_mentions=[])
    row = chunk_to_lance_row(chunk, vector=[0.0] * 8)
    assert row["agency_canonical_ids"] == []
    assert row["section_path"] == []
    assert row["fund_mentions"] == []


def test_explicit_agency_ids_override_the_scalar():
    """D2: table chunks resolve to several agencies (Task 9 feeds this)."""
    row = chunk_to_lance_row(
        _chunk(0), vector=[0.0] * 8,
        agency_ids=["agency:axs", "agency:dcs", "agency:doc"],
    )
    assert row["agency_canonical_ids"] == ["agency:axs", "agency:dcs", "agency:doc"]


# --- write_doc --------------------------------------------------------------


def test_write_doc_is_idempotent_and_fts_searchable(data_dir):
    store = ChunkStore(root=data_dir, dim=8)
    chunks = [_chunk(0), _chunk(1)]
    vectors = [[1.0] + [0.0] * 7, [0.0, 1.0] + [0.0] * 6]
    for _ in range(2):  # second call is a re-ingest
        write_doc(store, "budget_chunks", chunks, vectors, _meta(),
                  title="FY 2027 Test Budget", source_sha256="ab" * 32,
                  source_blob_path="pdfs/ab/abab.pdf", source_url=None,
                  source_format="pdf", uploaded_by="TESTUSER")
    assert store.count("budget_chunks") == 2                 # no duplicates
    assert store.fts_search("budget_chunks", "appropriation", top_k=5)
    docs = json.loads((data_dir / "documents.json").read_text())
    assert docs["gov-test-fy2027"]["title"] == "FY 2027 Test Budget"
    assert docs["gov-test-fy2027"]["source_sha256"] == "ab" * 32
    assert docs["gov-test-fy2027"]["uploaded_by"] == "TESTUSER"
    assert docs["gov-test-fy2027"]["ingested_at"]


def test_write_doc_drops_chunks_that_vanished_on_reingest(data_dir):
    """Re-extraction can yield different chunk_ids; the old ones must go, or
    the corpus keeps orphans no document points at."""
    store = ChunkStore(root=data_dir, dim=8)
    write_doc(store, "budget_chunks", [_chunk(0), _chunk(1)],
              [[1.0] + [0.0] * 7, [0.0, 1.0] + [0.0] * 6], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    write_doc(store, "budget_chunks", [_chunk(0)], [[1.0] + [0.0] * 7], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    assert store.count("budget_chunks") == 1


def test_write_doc_preserves_other_documents_metadata(data_dir):
    """documents.json is a merge, not a rewrite — one upload must not erase
    the other 381 documents."""
    (data_dir / "documents.json").write_text(
        json.dumps({"other-doc": {"title": "Keep me"}}), encoding="utf-8")
    store = ChunkStore(root=data_dir, dim=8)
    write_doc(store, "budget_chunks", [_chunk(0)], [[1.0] + [0.0] * 7], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    docs = json.loads((data_dir / "documents.json").read_text())
    assert docs["other-doc"]["title"] == "Keep me"
    assert docs["gov-test-fy2027"]["title"] == "t"


def test_write_doc_records_page_count_from_chunks(data_dir):
    store = ChunkStore(root=data_dir, dim=8)
    write_doc(store, "budget_chunks", [_chunk(0), _chunk(4)],
              [[1.0] + [0.0] * 7, [0.0, 1.0] + [0.0] * 6], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    docs = json.loads((data_dir / "documents.json").read_text())
    assert docs["gov-test-fy2027"]["page_count"] == 5


def test_write_doc_rejects_mismatched_vectors(data_dir):
    store = ChunkStore(root=data_dir, dim=8)
    with pytest.raises(ValueError):
        write_doc(store, "budget_chunks", [_chunk(0), _chunk(1)],
                  [[1.0] + [0.0] * 7], _meta(),
                  title="t", source_sha256="ab" * 32, source_blob_path=None,
                  source_url=None, source_format="pdf", uploaded_by="u")


def test_write_doc_with_no_chunks_still_removes_the_old_document(data_dir):
    """An extractor that suddenly yields nothing must not silently leave the
    previous version searchable under a fresh 'live' badge."""
    store = ChunkStore(root=data_dir, dim=8)
    write_doc(store, "budget_chunks", [_chunk(0)], [[1.0] + [0.0] * 7], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    write_doc(store, "budget_chunks", [], [], _meta(),
              title="t", source_sha256="ab" * 32, source_blob_path=None,
              source_url=None, source_format="pdf", uploaded_by="u")
    assert store.count("budget_chunks") == 0


# --- titles -----------------------------------------------------------------


def test_build_title():
    assert build_title(publisher="jlbc", doc_type="baseline-per-agency",
                       fiscal_year=2027, user_title="",
                       agency_name="AHCCCS") == "FY 2027 Baseline — AHCCCS"
    assert build_title(publisher="agao", doc_type="afr", fiscal_year=2025,
                       user_title="", agency_name=None) \
        == "FY 2025 Annual Financial Report"
    assert build_title(publisher="jlbc", doc_type="afr", fiscal_year=2025,
                       user_title="My Custom Name", agency_name=None) \
        == "My Custom Name"


def test_build_title_covers_the_corpus_doc_types():
    assert build_title(publisher="jlbc", doc_type="approps-per-agency",
                       fiscal_year=2026, user_title="", agency_name="AHCCCS") \
        == "FY 2026 Appropriations Report — AHCCCS"
    assert build_title(publisher="governor", doc_type="governors-budget",
                       fiscal_year=2027, user_title="", agency_name=None) \
        == "FY 2027 Executive Budget"
    assert build_title(publisher="legislature", doc_type="budget-bill",
                       fiscal_year=2026, user_title="", agency_name=None) \
        == "FY 2026 Budget Bill"


def test_build_title_falls_back_to_a_humanized_doc_type():
    """This is what retires the 'GOVERNOR FY2027 fy2027' titles: an unknown
    doc_type still yields something a human can read."""
    assert build_title(publisher="jlbc", doc_type="detailed-list-pdf",
                       fiscal_year=2026, user_title="", agency_name=None) \
        == "FY 2026 Detailed List"


def test_build_title_omits_the_agency_when_unresolved():
    assert build_title(publisher="jlbc", doc_type="baseline-per-agency",
                       fiscal_year=2027, user_title="", agency_name=None) \
        == "FY 2027 Baseline"


def test_build_title_trims_user_titles_and_ignores_blank_ones():
    assert build_title(publisher="jlbc", doc_type="afr", fiscal_year=2025,
                       user_title="  Spaced Out  ", agency_name=None) \
        == "Spaced Out"
    assert build_title(publisher="jlbc", doc_type="afr", fiscal_year=2025,
                       user_title="   ", agency_name=None) \
        == "FY 2025 Annual Financial Report"


def test_build_title_appends_the_stage_when_the_pattern_decides_the_title():
    # doc_title is the ONLY place AI Mode can see a document's stage (no
    # chunk column for it) -- the "Engrossed supersedes Introduced" prompt
    # rule can only ever fire by reading this suffix.
    assert build_title(publisher="jlbc", doc_type="budget-bill-summary",
                       fiscal_year=2027, user_title="", agency_name=None,
                       stage="engrossed") \
        == "FY 2027 Budget Bill Summary (Engrossed)"
    assert build_title(publisher="jlbc", doc_type="budget-bill-summary",
                       fiscal_year=2027, user_title="", agency_name=None,
                       stage="introduced") \
        == "FY 2027 Budget Bill Summary (Introduced)"


def test_build_title_appends_the_stage_even_over_a_user_typed_title():
    # A custom title must not silently swallow the stage -- an uploader who
    # typed their own title still needs the ladder rule to see it.
    assert build_title(publisher="jlbc", doc_type="budget-bill-summary",
                       fiscal_year=2027, user_title="HB2001 Feed Bill",
                       agency_name=None, stage="engrossed") \
        == "HB2001 Feed Bill (Engrossed)"


def test_build_title_omits_the_stage_suffix_when_none_is_given():
    assert build_title(publisher="jlbc", doc_type="budget-bill-summary",
                       fiscal_year=2027, user_title="", agency_name=None,
                       stage=None) \
        == "FY 2027 Budget Bill Summary"
