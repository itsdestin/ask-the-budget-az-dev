"""Post-load sanity checks for the chunks table.

Phase 1b WS2, Task 2.2. Run after `db.loader.load_chunk_file(s)` populates
the database; these queries catch chunker/loader drift early -- before
retrieval queries surface the same issue as a recall failure.

Designed to be cheap (every check is one COUNT or simple aggregate) and
re-runnable. The CLI entry point at the bottom prints a short table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One validation query with its pass condition.

    `sql` returns a single scalar; `pass_pred` decides whether that value
    indicates a clean load. Keep checks single-purpose so failure messages
    point at one root cause.
    """

    label: str
    sql: str
    pass_pred: callable
    why: str  # one-line explanation of what this check guards against


# Pre-defined check list. New checks: append here, no other code changes.
CHECKS: list[Check] = [
    Check(
        label="documents row count > 0",
        sql="SELECT COUNT(*)::INT FROM documents",
        pass_pred=lambda n: n > 0,
        why="Loader must upsert at least one documents row before chunks land.",
    ),
    Check(
        label="chunks row count > 0",
        sql="SELECT COUNT(*)::INT FROM chunks",
        pass_pred=lambda n: n > 0,
        why="No chunks => no retrieval; loader silently dropped everything.",
    ),
    Check(
        label="all chunks have provenance",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks "
            "WHERE page IS NULL AND source_anchor IS NULL"
        ),
        pass_pred=lambda n: n == 0,
        why="Schema CHECK should already enforce this; non-zero means a NULL slipped past.",
    ),
    Check(
        label="bbox shape valid for PDF chunks",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks "
            "WHERE page IS NOT NULL AND (bbox IS NULL OR array_length(bbox, 1) NOT IN (4, 8, 12, 16, 20, 24))"
        ),
        pass_pred=lambda n: n == 0,
        why="PDF chunks must have a bbox; multi-rect bboxes are flattened in groups of 4.",
    ),
    Check(
        label="agency stamping rate >= 0.85",
        sql=(
            "SELECT (COUNT(*) FILTER (WHERE array_length(agency_canonical_ids, 1) > 0)::FLOAT / COUNT(*)) "
            "FROM chunks"
        ),
        pass_pred=lambda r: r >= 0.85,
        why=(
            "Phase 1a slice closed at 91.3% agency stamping; full corpus aims similar. "
            "<85% suggests entity-stamper regression or chunker emitting orphaned chunks."
        ),
    ),
    Check(
        label="agency FK integrity",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks c "
            "WHERE EXISTS ("
            "  SELECT 1 FROM unnest(c.agency_canonical_ids) aid "
            "  WHERE aid NOT IN (SELECT agency_id FROM agencies)"
            ")"
        ),
        pass_pred=lambda n: n == 0,
        why=(
            "Every agency_canonical_id must reference an agencies row. "
            "Non-zero means the chunker emitted a slug missing from the seed catalog "
            "-- usually a new agency that needs to be added to entity-catalog.yaml."
        ),
    ),
    Check(
        label="fund FK integrity",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks "
            "WHERE fund_canonical_id IS NOT NULL "
            "AND fund_canonical_id NOT IN (SELECT fund_id FROM funds)"
        ),
        pass_pred=lambda n: n == 0,
        why="Same shape as agency check, applied to the singular primary-fund column.",
    ),
    Check(
        label="fund_mentions array integrity",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks c "
            "WHERE EXISTS ("
            "  SELECT 1 FROM unnest(c.fund_mentions) fid "
            "  WHERE fid NOT IN (SELECT fund_id FROM funds)"
            ")"
        ),
        pass_pred=lambda n: n == 0,
        why="Same FK rule applied per-element to the fund_mentions array.",
    ),
    Check(
        label="chunks.doc_id references documents",
        sql=(
            "SELECT COUNT(*)::INT FROM chunks "
            "WHERE doc_id NOT IN (SELECT doc_id FROM documents)"
        ),
        pass_pred=lambda n: n == 0,
        why="FK constraint should already prevent this; safety net.",
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    label: str
    actual: Any
    passed: bool
    why: str


def run_checks(conn: psycopg.Connection[Any]) -> list[Result]:
    """Execute every check in CHECKS and return results in the same order.

    Does not raise on failure -- caller decides how to react. The intent is
    that pytest assertions or a CLI can pretty-print all failures rather
    than aborting on the first one.
    """
    results: list[Result] = []
    for check in CHECKS:
        row = conn.execute(check.sql).fetchone()
        # Connection uses dict_row; the value is at index 0 of the dict.
        actual = next(iter(row.values())) if row else None
        results.append(
            Result(
                label=check.label,
                actual=actual,
                passed=bool(check.pass_pred(actual)),
                why=check.why,
            )
        )
    return results


def format_results(results: list[Result]) -> str:
    """Render results as a fixed-width table."""
    label_w = max(len(r.label) for r in results)
    lines = [f"{'STATUS':<6}  {'CHECK':<{label_w}}  ACTUAL"]
    lines.append("-" * (8 + label_w + 8 + 12))
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"{status:<6}  {r.label:<{label_w}}  {r.actual}")
        if not r.passed:
            lines.append(f"        why: {r.why}")
    return "\n".join(lines)


def main() -> int:
    """CLI entry: run checks, print results, exit non-zero on any failure.

    Usage:
        DATABASE_URL=postgresql://... uv run python -m db.validate
    """
    from db.connection import get_connection

    with get_connection() as conn:
        results = run_checks(conn)
    print(format_results(results))
    failed = [r for r in results if not r.passed]
    return 1 if failed else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
