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
    # Explicit ::text casts on the agency parameter: psycopg can't
    # infer the type of a bare %s used solely in `%s IS NULL`, and
    # crashes with IndeterminateDatatype. Both occurrences of the
    # parameter need the cast so the planner has a concrete type.
    sql = """
        SELECT c.chunk_id, c.text
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.publisher = %s
          AND c.doc_type = %s
          AND c.fiscal_year = %s
          AND (%s::text IS NULL OR %s::text = ANY(c.agency_canonical_ids))
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


def find_cosine_match(
    dims: QueryDimensions, query_text: str
) -> Optional[str]:
    """Fallback when anchor_text isn't found. Compute the query
    embedding via Voyage, then find the candidate chunk with the
    highest cosine similarity. Returns the chunk_id, or None when no
    candidates match the dimensions."""
    import voyageai

    # See find_anchor_match for the ::text rationale — same psycopg
    # IndeterminateDatatype trap.
    sql = """
        SELECT c.chunk_id, c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.publisher = %s
          AND c.doc_type = %s
          AND c.fiscal_year = %s
          AND (%s::text IS NULL OR %s::text = ANY(c.agency_canonical_ids))
          AND c.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT 1
    """
    vo = voyageai.Client()
    embedding = vo.embed([query_text], model="voyage-3-large").embeddings[0]
    with get_connection() as conn:
        row = conn.execute(
            sql,
            (
                embedding,
                dims.publisher,
                dims.doc_type,
                dims.fiscal_year,
                dims.agency,
                dims.agency,
            ),
        ).fetchone()
    return row["chunk_id"] if row else None


def refresh_queries_file(path: str) -> dict[str, int]:
    """Walk every query in the YAML; refresh stale chunk_ids in place.
    Returns a summary dict: refreshed, manual_review, unchanged."""
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f) or []

    refreshed = 0
    manual_review = 0
    unchanged = 0
    review_ids: list[str] = []

    for query in data:
        for expected in query.get("expected_chunks", []):
            cid = expected.get("chunk_id")
            if not cid:
                continue
            if chunk_exists(cid):
                unchanged += 1
                continue

            dims_raw = expected.get("dimensions", {})
            dims = QueryDimensions(
                publisher=dims_raw["publisher"],
                doc_type=dims_raw["doc_type"],
                fiscal_year=dims_raw["fiscal_year"],
                agency=dims_raw.get("agency"),
            )
            anchor = expected.get("anchor_text")
            new_id = None
            if anchor:
                new_id = find_anchor_match(dims, anchor)
            if new_id is None:
                new_id = find_cosine_match(dims, query.get("query", ""))
            if new_id is None:
                manual_review += 1
                review_ids.append(query.get("id", "?"))
                continue
            expected["chunk_id"] = new_id
            refreshed += 1

    # Only rewrite the file when we actually changed something —
    # ruamel.yaml's round-trip mode is structure-preserving for chunk-
    # id edits but still re-formats blank lines between entries, which
    # makes every "no-op" run produce a noisy git diff. Skipping the
    # write keeps zero-change invocations idempotent.
    if refreshed > 0:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

    return {
        "refreshed": refreshed,
        "manual_review": manual_review,
        "unchanged": unchanged,
        "review_ids": review_ids,
    }


def main() -> None:
    # Windows-friendly: ensure stdout can encode the ✓/⚠/✗ glyphs we
    # print. Default cp1252 console crashes on these. Safe no-op on
    # POSIX where stdout is already utf-8.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Refresh stale chunk_ids in eval/queries.yaml"
    )
    parser.add_argument(
        "--queries", default="eval/queries.yaml",
        help="Path to queries.yaml",
    )
    args = parser.parse_args()

    print(f"Checking chunk_id validity against current corpus...")
    summary = refresh_queries_file(args.queries)
    print(
        f"\n  ✓ {summary['unchanged']} queries: chunk_id still valid"
    )
    if summary["refreshed"]:
        print(
            f"  ⚠ {summary['refreshed']} queries: chunk_id refreshed via "
            "anchor_text or cosine fallback"
        )
    if summary["manual_review"]:
        print(
            f"  ✗ {summary['manual_review']} queries: no candidate matched "
            "dimensions — manual review needed"
        )
        for qid in summary["review_ids"]:
            print(f"    - {qid}")
        print(
            f"\nEdit {args.queries} manually for these queries (or delete "
            "if the underlying entity is gone)."
        )
        sys.exit(1 if summary["manual_review"] else 0)


if __name__ == "__main__":
    main()
