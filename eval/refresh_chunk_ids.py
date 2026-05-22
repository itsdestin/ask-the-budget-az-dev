"""Refresh stale chunk_ids in eval/queries.yaml after a re-ingest.

When the ingest pipeline runs (or when chunk boundaries change), the
chunk_ids in eval/queries.yaml may no longer point at real chunks.
This script finds successor chunks for each stale entry, prefers
anchor_text matching when available, falls back to embedding-based
cosine similarity when not, and flags entries that can't be repaired
for manual review.

Invocation:
    uv run python -m eval.refresh_chunk_ids
    uv run python -m eval.refresh_chunk_ids --queries other.yaml
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from eval.schema import QueryDimensions
# Re-export the pooled connection helper for monkeypatching in tests.
# The pool's configure callback runs `register_vector(conn)` so the
# cosine-similarity SQL below can cast a Python list to ::vector.
from db.connection import get_connection


def chunk_exists(chunk_id: str) -> bool:
    """Return True iff the chunks table has a row for the given
    chunk_id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chunk_id FROM chunks WHERE chunk_id = %s",
            (chunk_id,),
        ).fetchone()
    return row is not None


def find_anchor_match(
    dims: QueryDimensions, anchor_text: str
) -> Optional[str]:
    """Find a successor chunk whose text contains anchor_text and
    whose dimensions match. Returns the chunk_id, or None if no
    candidate contains the anchor."""
    sql = """
        SELECT c.chunk_id, c.text
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.publisher = %s
          AND c.doc_type = %s
          AND c.fiscal_year = %s
          AND (%s IS NULL OR %s = ANY(c.agency_canonical_ids))
    """
    with get_connection() as conn:
        rows = conn.execute(
            sql,
            (dims.publisher, dims.doc_type, dims.fiscal_year, dims.agency, dims.agency),
        ).fetchall()
    for r in rows:
        if anchor_text and anchor_text in r["text"]:
            return r["chunk_id"]
    return None
