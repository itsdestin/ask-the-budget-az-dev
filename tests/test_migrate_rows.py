"""Transform-contract tests for scripts/migrate_to_lancedb.py.

Only the pure row transform is unit-tested: the surrounding script is a
one-time migration whose other moving parts (Postgres, ONNX embedder,
LanceDB) all have their own suites. The one thing that MUST be pinned is
the psycopg-dict -> Arrow-row mapping, because a silent mistake there
(notably source_anchor being str()'d instead of json.dumps()'d) produces
a table that only fails at query time, long after the 10-minute
migration has "succeeded".
"""

import json

from scripts.migrate_to_lancedb import (
    DOCS_FIELDS,
    pg_row_to_lance,
    pg_rows_to_documents,
    write_documents_sidecar,
)


def test_pg_row_to_lance_maps_and_encodes():
    row = dict(
        chunk_id="c1", doc_id="d1", text="hello", section_path=["A"],
        page=4, bbox=[1, 2, 3, 4], source_anchor={"page": 4},
        agency_canonical_ids=["ahcccs"], fund_canonical_id=None,
        fund_mentions=[], fiscal_year=2026, doc_type="afr",
        is_table=False, table_html=None, token_count=9, publisher="agao",
    )
    out = pg_row_to_lance(row, vector=[0.1, 0.2])
    assert out["source_anchor"] == '{"page": 4}'
    assert out["vector"] == [0.1, 0.2]
    assert out["publisher"] == "agao"


def test_none_anchor_stays_none():
    row = dict(
        chunk_id="c1", doc_id="d1", text="t", section_path=[],
        page=None, bbox=None, source_anchor=None, agency_canonical_ids=[],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=None,
        doc_type="afr", is_table=False, table_html=None, token_count=1,
        publisher="jlbc",
    )
    assert pg_row_to_lance(row, vector=[0.0])["source_anchor"] is None


# ---------------------------------------------------------------------------
# documents.json sidecar
# ---------------------------------------------------------------------------
# The chunk table has nowhere to put document-level facts, so the migration
# also emits {doc_id: {...}} for the fields /docs/{doc_id} needs — most
# importantly source_format + source_blob_path, without which every citation
# chip in the web app falls into the "unsupported_source_format" branch.


def _doc_row(**over) -> dict:
    row = dict(
        doc_id="jlbc-baseline-fy2026-axs",
        title="JLBC FY2026 — AHCCCS",
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        source_format="pdf",
        source_blob_path="data/cached-pdfs/40/40831007.pdf",
        source_url="https://www.azjlbc.gov/26baseline/axs.pdf",
        page_count=None,
    )
    row.update(over)
    return row


def test_pg_rows_to_documents_keys_by_doc_id():
    docs = pg_rows_to_documents([_doc_row(), _doc_row(doc_id="agao-afr-fy2025")])
    assert set(docs) == {"jlbc-baseline-fy2026-axs", "agao-afr-fy2025"}
    entry = docs["jlbc-baseline-fy2026-axs"]
    # doc_id is the key, not repeated in the value; every other field carried.
    assert set(entry) == set(DOCS_FIELDS)
    assert entry["source_format"] == "pdf"
    assert entry["source_blob_path"] == "data/cached-pdfs/40/40831007.pdf"
    assert entry["title"] == "JLBC FY2026 — AHCCCS"
    assert entry["page_count"] is None  # nullable in Postgres; stays null


def test_pg_rows_to_documents_drops_unrequested_columns():
    """Only the declared field set is copied. A SELECT that later picks up
    `ingested_at` (a datetime) must not reach json.dumps and blow up the
    whole migration at the write step."""
    import datetime

    docs = pg_rows_to_documents([
        _doc_row(ingested_at=datetime.datetime(2026, 7, 29), extractor="mineru-2.5")
    ])
    entry = docs["jlbc-baseline-fy2026-axs"]
    assert "ingested_at" not in entry and "extractor" not in entry
    json.dumps(entry)  # must be serializable


def test_write_documents_sidecar_is_valid_utf8_json(tmp_path, monkeypatch):
    """Titles contain em dashes; the file must round-trip them and land at
    the shared path both the migration and the sidecar agree on."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    docs = pg_rows_to_documents([_doc_row()])
    path = write_documents_sidecar(docs)

    assert path == tmp_path / "documents.json"
    assert json.loads(path.read_text(encoding="utf-8")) == docs
    assert "—" in path.read_text(encoding="utf-8")
    # The atomic-write temp file must not be left behind.
    assert not (tmp_path / "documents.json.tmp").exists()
