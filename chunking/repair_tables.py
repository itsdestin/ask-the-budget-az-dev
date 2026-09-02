"""The one-time repair of JLBC agency operating tables (spec §6), and the
gate calibration that precedes it (spec §4.1).

    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --calibrate
    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables            # dry run
    JLBC_DATA_DIR=<copy>            uv run python -m chunking.repair_tables --apply

Nothing here writes without `--apply`, and `--apply` writes only under
the ingest lock after a CRC-verified snapshot.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, Mapping

from chunking.table_gate import has_fused_marker, has_merged_cell, reconcile
from chunking.table_text import OPERATING_TABLE_DOC_TYPES, has_ladder_marker
from chunking.repair_common import ChunkStoreLike

PLAN_COLUMNS = ["chunk_id", "doc_id", "fiscal_year", "doc_type", "page", "section_path", "text", "table_html"]


def in_scope(row: Mapping[str, Any]) -> bool:
    """Spec D1."""
    return bool(row.get("is_table")) and row.get("doc_type") in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(row.get("text") or "")


def table_rows(text: str) -> list[list[str]]:
    """The tab-joined rows of a stored chunk text (line 0 and a caption have no tabs)."""
    return [line.split("\t") for line in text.split("\n") if "\t" in line]


def calibrate(store: ChunkStoreLike, table: str = "budget_chunks") -> dict[int, dict[str, int]]:
    """Spec §4.1: run the gate over the tables MinerU already read cleanly
    (no merged cell, no fused marker) exactly as stored. Every failure
    here is the RULE's, so this is run before any rebuild code exists.
    Returns {fiscal_year: {"clean": n, "passed": n}}."""
    rows = store.scan(table, ["chunk_id", "doc_type", "fiscal_year", "is_table", "text"],
                      where="is_table = true")
    per_year: dict[int, dict[str, int]] = defaultdict(lambda: {"clean": 0, "passed": 0})
    for r in rows:
        if not in_scope(r):
            continue
        cells = table_rows(r["text"])
        if has_merged_cell(cells) or has_fused_marker(cells):
            continue
        year = int(r["fiscal_year"] or 0)
        per_year[year]["clean"] += 1
        if reconcile(cells).passed:
            per_year[year]["passed"] += 1
    return dict(per_year)


def _print_calibration(per_year: Mapping[int, Mapping[str, int]]) -> None:
    total_clean = sum(v["clean"] for v in per_year.values())
    total_pass = sum(v["passed"] for v in per_year.values())
    print(f"{'year':>6} {'clean':>7} {'passed':>7} {'rate':>6}")
    for year in sorted(per_year):
        v = per_year[year]
        rate = v["passed"] / v["clean"] if v["clean"] else 0.0
        print(f"{year:>6} {v['clean']:>7} {v['passed']:>7} {rate:>6.1%}")
    print(f"{'all':>6} {total_clean:>7} {total_pass:>7} {(total_pass / total_clean if total_clean else 0):>6.1%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default="budget_chunks", choices=("budget_chunks",))
    parser.add_argument("--calibrate", action="store_true", help="spec §4.1: gate the stored clean tables, write nothing")
    args = parser.parse_args(argv)
    from store.chunk_store import ChunkStore
    store = ChunkStore(create=False)
    if args.calibrate:
        _print_calibration(calibrate(store, args.table))
        return 0
    parser.error("only --calibrate exists yet; the dry run arrives with Task 8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
