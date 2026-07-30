import pyarrow as pa

from store.schema import chunk_schema


def test_schema_fields_and_dim():
    s = chunk_schema(dim=384)
    names = s.names
    # Exact keys RetrievedChunk.from_row expects, plus the vector.
    for expected in [
        "chunk_id", "doc_id", "text", "section_path", "page", "bbox",
        "source_anchor", "agency_canonical_ids", "fund_canonical_id",
        "fund_mentions", "fiscal_year", "doc_type", "is_table",
        "table_html", "token_count", "publisher", "vector",
    ]:
        assert expected in names, expected
    vec = s.field("vector").type
    assert pa.types.is_fixed_size_list(vec) and vec.list_size == 384


def test_source_anchor_is_string_json():
    s = chunk_schema(dim=8)
    assert pa.types.is_string(s.field("source_anchor").type)
