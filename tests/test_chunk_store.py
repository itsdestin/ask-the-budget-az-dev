"""ChunkStore against a real LanceDB in tmp_path — no models needed;
vectors are hand-made 8-dim floats."""
import pytest

from store.chunk_store import ChunkStore


def _row(cid: str, text: str, vec: list[float], **over):
    base = dict(
        chunk_id=cid, doc_id="doc-1", text=text, section_path=["A", "B"],
        page=3, bbox=[1.0, 2.0, 3.0, 4.0], source_anchor='{"p": 3}',
        agency_canonical_ids=["ahcccs"], fund_canonical_id=None,
        fund_mentions=[], fiscal_year=2026, doc_type="baseline-per-agency",
        is_table=False, table_html=None, token_count=42, publisher="jlbc",
        vector=vec,
    )
    base.update(over)
    return base


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(root=tmp_path, dim=8)
    s.upsert_chunks("budget_chunks", [
        _row("c1", "ahcccs provider rates increase", [1, 0, 0, 0, 0, 0, 0, 0]),
        _row("c2", "department of child safety caseworkers",
             [0, 1, 0, 0, 0, 0, 0, 0], fiscal_year=2025, publisher="agao"),
        _row("c3", "university operating budget", [0.9, 0.1, 0, 0, 0, 0, 0, 0]),
    ])
    s.build_fts_index("budget_chunks")
    return s


def test_get_by_ids_roundtrip(store):
    got = store.get_by_ids("budget_chunks", ["c2", "c1"])
    assert {r["chunk_id"] for r in got} == {"c1", "c2"}
    r1 = next(r for r in got if r["chunk_id"] == "c1")
    assert r1["text"] == "ahcccs provider rates increase"
    assert list(r1["agency_canonical_ids"]) == ["ahcccs"]


def test_vector_search_orders_by_cosine(store):
    hits = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0], top_k=2)
    assert [h["chunk_id"] for h in hits] == ["c1", "c3"]
    assert hits[0]["_score"] > hits[1]["_score"]


def test_fts_search_finds_lexical_match(store):
    hits = store.fts_search("budget_chunks", "caseworkers", top_k=5)
    assert [h["chunk_id"] for h in hits] == ["c2"]
    assert hits[0]["_score"] > 0


def test_filters_apply_to_both_paths(store):
    where = store.filter_expr(fiscal_year=[2025], publisher=["agao"])
    v = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0],
                            top_k=5, where=where)
    assert [h["chunk_id"] for h in v] == ["c2"]
    f = store.fts_search("budget_chunks", "ahcccs OR caseworkers",
                         top_k=5, where=where)
    assert [h["chunk_id"] for h in f] == ["c2"]


def test_agency_filter_uses_array_overlap(store):
    where = store.filter_expr(agency_canonical_id=["ahcccs", "dcs"])
    v = store.vector_search("budget_chunks", [0, 1, 0, 0, 0, 0, 0, 0],
                            top_k=5, where=where)
    # c1..c3 all stamp agency 'ahcccs' except none stamp 'dcs'; all match via overlap
    assert {h["chunk_id"] for h in v} == {"c1", "c2", "c3"}


def test_upsert_replaces_same_chunk_id(store):
    store.upsert_chunks("budget_chunks", [
        _row("c1", "REPLACED TEXT", [1, 0, 0, 0, 0, 0, 0, 0]),
    ])
    got = store.get_by_ids("budget_chunks", ["c1"])
    assert len(got) == 1 and got[0]["text"] == "REPLACED TEXT"


def test_empty_table_created_on_demand(tmp_path):
    s = ChunkStore(root=tmp_path, dim=8)
    assert s.count("fiscal_note_chunks") == 0


def test_values_with_apostrophes_do_not_break_sql(store):
    """LanceDB filters are SQL strings with no parameter binding, so a
    fund name like "land's fund" must be escaped, not interpolated raw
    (raw yields 'Unterminated string literal'). Guards _sql_str."""
    store.upsert_chunks("budget_chunks", [
        _row("c4", "apostrophe row", [0, 0, 1, 0, 0, 0, 0, 0],
             fund_canonical_id="land's fund",
             agency_canonical_ids=["o'brien"]),
    ])
    got = store.get_by_ids("budget_chunks", ["c4"])
    assert [r["chunk_id"] for r in got] == ["c4"]

    where = store.filter_expr(fund_canonical_id=["land's fund"],
                              agency_canonical_id=["o'brien"])
    hits = store.vector_search("budget_chunks", [0, 0, 1, 0, 0, 0, 0, 0],
                               top_k=5, where=where)
    assert [h["chunk_id"] for h in hits] == ["c4"]
