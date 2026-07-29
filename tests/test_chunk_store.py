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
    (raw yields 'Unterminated string literal').

    The apostrophe-bearing chunk_id is deliberate: it exercises all three
    _sql_str call sites — upsert_chunks' delete clause, get_by_ids, and
    filter_expr.
    """
    cid = "doc'1#c4"
    store.upsert_chunks("budget_chunks", [
        _row(cid, "apostrophe row", [0, 0, 1, 0, 0, 0, 0, 0],
             fund_canonical_id="land's fund",
             agency_canonical_ids=["o'brien"]),
    ])
    got = store.get_by_ids("budget_chunks", [cid])
    assert [r["chunk_id"] for r in got] == [cid]

    where = store.filter_expr(fund_canonical_id=["land's fund"],
                              agency_canonical_id=["o'brien"])
    hits = store.vector_search("budget_chunks", [0, 0, 1, 0, 0, 0, 0, 0],
                               top_k=5, where=where)
    assert [h["chunk_id"] for h in hits] == [cid]

    # Re-upserting must replace, not duplicate — proves the delete clause
    # actually matched the escaped id rather than silently matching nothing.
    store.upsert_chunks("budget_chunks", [
        _row(cid, "REPLACED", [0, 0, 1, 0, 0, 0, 0, 0]),
    ])
    got = store.get_by_ids("budget_chunks", [cid])
    assert len(got) == 1 and got[0]["text"] == "REPLACED"


def test_is_table_filter_renders_bare_bool(store):
    """is_table must render as a bare `false`, not a quoted `'False'` —
    DataFusion rejects the quoted form. Also pins that is_table=False is
    treated as a real filter, not as 'no filter' (it is falsy)."""
    where = store.filter_expr(is_table=False)
    assert where == "is_table = false"
    hits = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0],
                               top_k=5, where=where)
    assert {h["chunk_id"] for h in hits} == {"c1", "c2", "c3"}

    assert store.filter_expr(is_table=True) == "is_table = true"
    assert store.filter_expr() is None


def test_unknown_table_name_raises(tmp_path):
    """A typo'd corpus name must fail loudly. It used to CREATE the typo
    table and then report 0 rows / no hits, which looks like an empty
    corpus rather than a bug."""
    s = ChunkStore(root=tmp_path, dim=8)
    for call in (
        lambda: s.count("budget_chunk"),          # missing trailing s
        lambda: s.get_by_ids("nope", ["c1"]),
        lambda: s.vector_search("nope", [1, 0, 0, 0, 0, 0, 0, 0], top_k=1),
        lambda: s.fts_search("nope", "x", top_k=1),
        lambda: s.optimize("nope"),
        lambda: s.upsert_chunks("nope", [_row("c1", "t", [1] + [0] * 7)]),
        lambda: s.build_fts_index("nope"),
    ):
        with pytest.raises(ValueError, match="Unknown corpus table"):
            call()
    assert s._db.table_names() == []


def test_reads_do_not_create_tables(tmp_path):
    """Readers must not write to the shared data dir (spec S6)."""
    s = ChunkStore(root=tmp_path, dim=8)
    assert s.count("budget_chunks") == 0
    assert s.get_by_ids("budget_chunks", ["c1"]) == []
    assert s.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0], top_k=3) == []
    assert s.fts_search("budget_chunks", "anything", top_k=3) == []
    s.optimize("budget_chunks")
    assert s._db.table_names() == []

    # ...but the write paths do create.
    s.ensure_tables()
    assert sorted(s._db.table_names()) == ["budget_chunks", "fiscal_note_chunks"]


def test_cached_handle_sees_another_writers_rows(tmp_path):
    """The handle cache must not pin a reader to a stale table version —
    a second process appending rows has to become visible."""
    reader = ChunkStore(root=tmp_path, dim=8)
    writer = ChunkStore(root=tmp_path, dim=8)
    writer.upsert_chunks("budget_chunks", [_row("c1", "first", [1] + [0] * 7)])
    assert reader.count("budget_chunks") == 1          # populates the cache

    writer.upsert_chunks("budget_chunks", [_row("c2", "second", [0, 1] + [0] * 6)])
    assert reader.count("budget_chunks") == 2
    assert {r["chunk_id"] for r in reader.get_by_ids("budget_chunks", ["c1", "c2"])} \
        == {"c1", "c2"}


def test_results_omit_the_vector_column(store):
    """The 384-float vector is dead weight in results; consumers never read
    it. The score columns must still come through."""
    v = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0], top_k=1)
    assert "vector" not in v[0] and "_score" in v[0]
    f = store.fts_search("budget_chunks", "caseworkers", top_k=1)
    assert "vector" not in f[0] and "_score" in f[0]
    g = store.get_by_ids("budget_chunks", ["c1"])
    assert "vector" not in g[0]
    # Everything else survived the projection.
    assert g[0]["publisher"] == "jlbc" and g[0]["token_count"] == 42


def test_dim_mismatch_raises_plain_language_error(tmp_path):
    """Task 11 switches to a 768-dim model; opening an old 8-dim table with
    the new dim must explain itself rather than surfacing a Rust cast error."""
    ChunkStore(root=tmp_path, dim=8).ensure_tables()
    with pytest.raises(ValueError, match="8-dimensional vectors"):
        ChunkStore(root=tmp_path, dim=768).count("budget_chunks")


def test_filter_expr_drops_none_entries(store):
    """A None inside a filter list used to render as 'None' and match
    nothing, silently emptying the result set."""
    assert store.filter_expr(publisher=["jlbc", None]) == "publisher IN ('jlbc')"
    assert store.filter_expr(fiscal_year=[None]) is None
    assert store.filter_expr(agency_canonical_id=[None, "ahcccs"]) == \
        "array_has_any(agency_canonical_ids, ['ahcccs'])"

    where = store.filter_expr(publisher=["jlbc", None])
    hits = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0],
                               top_k=5, where=where)
    assert {h["chunk_id"] for h in hits} == {"c1", "c3"}


def test_upsert_dedupes_within_one_batch(store):
    """The delete clause removes each id once, so a duplicated chunk_id in a
    single batch would otherwise land twice."""
    store.upsert_chunks("budget_chunks", [
        _row("dup", "first", [0, 0, 0, 1, 0, 0, 0, 0]),
        _row("dup", "second", [0, 0, 0, 1, 0, 0, 0, 0]),
    ])
    got = store.get_by_ids("budget_chunks", ["dup"])
    assert len(got) == 1 and got[0]["text"] == "second"   # last one wins


def test_optimize_is_callable_after_bulk_load(store):
    """Task 10's migration compacts after its batches; just pin that the
    call works and preserves the data."""
    for i in range(5):
        store.upsert_chunks("budget_chunks", [
            _row(f"b{i}", f"batch row {i}", [0, 0, 0, 0, 1, 0, 0, 0]),
        ])
    before = store.count("budget_chunks")
    store.optimize("budget_chunks")
    assert store.count("budget_chunks") == before
    assert store.get_by_ids("budget_chunks", ["b4"])[0]["text"] == "batch row 4"

    assert store.filter_expr(is_table=True) == "is_table = true"
    assert store.filter_expr() is None
