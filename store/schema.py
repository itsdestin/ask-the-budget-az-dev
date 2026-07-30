"""PyArrow schema for chunk tables (budget_chunks, fiscal_note_chunks).

Column names deliberately match the psycopg row keys that
RetrievedChunk.from_row (retrieval/types.py) already consumes, so a
LanceDB result dict flows straight into the existing dataclass.
source_anchor is a JSON string because LanceDB rows are Arrow-typed
(no free-form dict column); search_lance.py decodes it.
"""
from __future__ import annotations

import pyarrow as pa


def chunk_schema(*, dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("section_path", pa.list_(pa.string())),
            pa.field("page", pa.int32(), nullable=True),
            pa.field("bbox", pa.list_(pa.float32()), nullable=True),
            pa.field("source_anchor", pa.string(), nullable=True),  # JSON
            pa.field("agency_canonical_ids", pa.list_(pa.string())),
            pa.field("fund_canonical_id", pa.string(), nullable=True),
            pa.field("fund_mentions", pa.list_(pa.string())),
            pa.field("fiscal_year", pa.int32(), nullable=True),
            pa.field("doc_type", pa.string()),
            pa.field("is_table", pa.bool_()),
            pa.field("table_html", pa.string(), nullable=True),
            pa.field("token_count", pa.int32()),
            pa.field("publisher", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )
