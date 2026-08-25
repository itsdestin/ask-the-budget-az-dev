"""Surgical fund unstamp — null the stamps whose fund no longer exists.

The 2026-08-23 fund-identity repair deleted 50 rows from
data/fund-catalog.yaml that were never funds (schedule "Total -" rows,
agency names, budget-adjustment lines, severed fragments like "Account").
Their stamps are still on the corpus: 5,238 chunks carry `fund:account`
alone, minted by a boundary-less substring match inside "Accounting". This
pass nulls `fund_canonical_id` and scrubs `fund_mentions` for every id that
is not in the repaired catalog, on BOTH corpora, and touches nothing else.

It is the fund twin of `identity/relabel.py` and keeps its five disciplines
on purpose (spec amendment 4):
  (a) the ingest lock is held around the write;
  (b) the corpus snapshot is proven restorable (zip CRC), not merely present;
  (c) rows are written in batches with a progress line each;
  (d) after writing, the chunk-id SETS must be identical and every non-fund
      column byte-identical on touched rows (plus a sample of untouched);
  (e) the reversal record is written tmp+rename and carries the FULL old
      `fund_mentions` list per row — removing one id from a list is not
      invertible from the id alone.

`dry_run=True` (the default) never locks, never snapshots, never writes.

WHY a surgical null and not a re-derivation: re-running the stamper over
97k rows under a rule calibrated on one afternoon churns every fund stamp;
nulling exactly the ids that no longer exist is bounded, reviewable in the
dry-run, and reversible row by row. Future ingests get the fixed rule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from identity.relabel import (
    _ALL_COLUMNS,
    _UNCHANGED_SAMPLE_SIZE,
    DEFAULT_BATCH_SIZE,
    _atomic_write_json,
    _default_snapshot_and_verify,
)
from ingest.lock import IngestLock

FUND_COLUMNS = ("fund_canonical_id", "fund_mentions")
TABLES = ("budget_chunks", "fiscal_note_chunks")


@dataclass
class UnstampResult:
    table: str
    scanned: int
    changed: int
    nulled_primary: int
    scrubbed_mentions: int
    per_id: dict[str, int] = field(default_factory=dict)
    reversal: list[dict[str, Any]] = field(default_factory=list)
    snapshot_name: str | None = None
    reversal_path: Path | None = None


def _default_progress(message: str) -> None:
    print(f"funds.unstamp: {message}", flush=True)


def compute_changes(
    rows: Iterable[dict[str, Any]], keep_ids: set[str]
) -> list[tuple[dict[str, Any], str | None, list[str]]]:
    """Rows whose fund columns reference an id outside `keep_ids`.

    Returns (row, new_primary, new_mentions) for every row that changes.
    """
    changes = []
    for row in rows:
        old_primary = row.get("fund_canonical_id")
        old_mentions = list(row.get("fund_mentions") or [])
        new_primary = old_primary if (old_primary in keep_ids) else None
        new_mentions = [m for m in old_mentions if m in keep_ids]
        if new_primary != old_primary or new_mentions != old_mentions:
            changes.append((row, new_primary, new_mentions))
    return changes


def _summarise(changes) -> tuple[int, int, dict[str, int]]:
    nulled = scrubbed = 0
    per_id: dict[str, int] = {}
    for row, new_primary, new_mentions in changes:
        old_primary = row.get("fund_canonical_id")
        if old_primary and new_primary is None:
            nulled += 1
            per_id[old_primary] = per_id.get(old_primary, 0) + 1
        scrubbed += len(row.get("fund_mentions") or []) - len(new_mentions)
    return nulled, scrubbed, per_id


def _write_changed_rows(store, table, changes, batch_size, progress) -> None:
    total = len(changes)
    if not total:
        return
    batches = math.ceil(total / batch_size)
    for n, start in enumerate(range(0, total, batch_size), start=1):
        rows_to_write = []
        for row, new_primary, new_mentions in changes[start:start + batch_size]:
            new_row = dict(row)
            new_row["fund_canonical_id"] = new_primary
            new_row["fund_mentions"] = new_mentions
            rows_to_write.append(new_row)
        store.upsert_chunks(table, rows_to_write)
        progress(f"{table}: wrote batch {n}/{batches} "
                 f"({min(start + batch_size, total)}/{total} changed rows)")


def _verify_nothing_was_lost(store, table, before_rows, changed_ids, progress):
    after_rows = store.scan(table, _ALL_COLUMNS)
    before_by_id = {r["chunk_id"]: r for r in before_rows}
    after_by_id = {r["chunk_id"]: r for r in after_rows}
    if set(before_by_id) != set(after_by_id):
        missing = set(before_by_id) - set(after_by_id)
        extra = set(after_by_id) - set(before_by_id)
        raise RuntimeError(
            f"funds.unstamp: {table} lost or gained chunk_ids while writing -- "
            f"{len(missing)} missing, {len(extra)} unexpected. Restore from the "
            "snapshot this pass just took before investigating further."
        )

    def _drift(chunk_id: str) -> str | None:
        b, a = before_by_id[chunk_id], after_by_id[chunk_id]
        for col in _ALL_COLUMNS:
            if col in FUND_COLUMNS:
                continue
            if b.get(col) != a.get(col):
                return col
        return None

    for chunk_id in changed_ids:
        bad = _drift(chunk_id)
        if bad is not None:
            raise RuntimeError(
                f"funds.unstamp: chunk {chunk_id!r} lost column {bad!r} while its "
                "fund stamp was being nulled. Restore from the snapshot this pass just took."
            )
    untouched = sorted(set(before_by_id) - changed_ids)[:_UNCHANGED_SAMPLE_SIZE]
    for chunk_id in untouched:
        bad = _drift(chunk_id)
        if bad is not None:
            raise RuntimeError(
                f"funds.unstamp: untouched chunk {chunk_id!r} drifted in column "
                f"{bad!r}. Restore from the snapshot this pass just took."
            )
    progress(f"{table}: verified {len(after_by_id)} chunk_ids intact "
             f"({len(changed_ids)} changed rows checked in full, {len(untouched)} untouched sampled)")
    return after_rows


def unstamp_table(
    *,
    store,
    keep_ids: set[str],
    table: str = "budget_chunks",
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: IngestLock | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> UnstampResult:
    """Null every fund reference outside `keep_ids` on one table."""
    progress = progress or _default_progress

    def _reversal_rows(changes):
        return [
            {
                "doc_id": row.get("doc_id"), "chunk_id": row["chunk_id"],
                "before": {"fund_canonical_id": row.get("fund_canonical_id"),
                           "fund_mentions": list(row.get("fund_mentions") or [])},
                "after": {"fund_canonical_id": new_primary, "fund_mentions": new_mentions},
            }
            for row, new_primary, new_mentions in changes
        ]

    if dry_run:
        rows = store.scan(table, _ALL_COLUMNS)
        changes = compute_changes(rows, keep_ids)
        nulled, scrubbed, per_id = _summarise(changes)
        return UnstampResult(table, len(rows), len(changes), nulled, scrubbed,
                             per_id, _reversal_rows(changes))

    if lock is None:
        lock = IngestLock()
    with lock:
        lock.heartbeat()
        progress(f"{table}: acquired the ingest lock -- taking a corpus snapshot")
        snapshot_name = (snapshot_and_verify or _default_snapshot_and_verify)()
        lock.heartbeat()
        before_rows = store.scan(table, _ALL_COLUMNS)
        changes = compute_changes(before_rows, keep_ids)
        nulled, scrubbed, per_id = _summarise(changes)
        progress(f"{table}: {len(changes)} of {len(before_rows)} rows change")
        _write_changed_rows(store, table, changes, batch_size, progress)
        lock.heartbeat()
        changed_ids = {row["chunk_id"] for row, _p, _m in changes}
        _verify_nothing_was_lost(store, table, before_rows, changed_ids, progress)

        if reversal_dir is None:
            from store.config import data_dir as _resolve_data_dir
            reversal_dir = _resolve_data_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        reversal_path = reversal_dir / f"fund-unstamp-reversal-{table}-{stamp}.json"
        reversal = _reversal_rows(changes)
        _atomic_write_json(reversal_path, {
            "table": table,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot_name,
            "scanned": len(before_rows),
            "changed": len(changes),
            "nulled_primary": nulled,
            "scrubbed_mentions": scrubbed,
            "per_id": per_id,
            "changes": reversal,
        })
        progress(f"{table}: reversal record written: {reversal_path}")
        return UnstampResult(table, len(before_rows), len(changes), nulled, scrubbed,
                             per_id, reversal, snapshot_name, reversal_path)


def catalog_ids() -> set[str]:
    """Every id the repaired catalog still knows — the keep set."""
    import yaml

    from funds.names import DEFAULT_CATALOG_PATH

    raw = yaml.safe_load(Path(DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
    return {e["canonical_id"] for e in raw.get("funds", []) if e.get("canonical_id")}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Null fund stamps whose fund no longer exists.")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    from store.chunk_store import ChunkStore

    store = ChunkStore()
    keep = catalog_ids()
    # One verified snapshot covers both tables -- the archive is the whole
    # corpus directory, so a second zip would only cost 3+ minutes and 2 GB.
    shared_snapshot: str | None = None
    if args.apply:
        shared_snapshot = _default_snapshot_and_verify()
        print(f"snapshot taken and CRC-verified: {shared_snapshot}")
    for table in TABLES:
        res = unstamp_table(
            store=store, keep_ids=keep, table=table, dry_run=not args.apply,
            snapshot_and_verify=(lambda: shared_snapshot) if args.apply else None,
        )
        print(f"{table}: scanned {res.scanned}, changed {res.changed}, "
              f"nulled primary {res.nulled_primary}, scrubbed mentions {res.scrubbed_mentions}")
        for fid, n in sorted(res.per_id.items(), key=lambda kv: -kv[1])[:12]:
            print(f"    {n:6d}  {fid}")
        if res.reversal_path:
            print(f"    reversal: {res.reversal_path}  snapshot: {res.snapshot_name}")
    if not args.apply:
        print("(dry run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
