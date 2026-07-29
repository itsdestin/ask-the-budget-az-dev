"""Transform-contract tests for scripts/migrate_to_lancedb.py.

Only the pure row transform is unit-tested: the surrounding script is a
one-time migration whose other moving parts (Postgres, ONNX embedder,
LanceDB) all have their own suites. The one thing that MUST be pinned is
the psycopg-dict -> Arrow-row mapping, because a silent mistake there
(notably source_anchor being str()'d instead of json.dumps()'d) produces
a table that only fails at query time, long after the 10-minute
migration has "succeeded".
"""

from scripts.migrate_to_lancedb import pg_row_to_lance


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
