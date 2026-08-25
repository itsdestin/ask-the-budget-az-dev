"""funds.unstamp — the surgical fund-stamp null, tested on an in-memory
store double (same shape as tests/test_identity_relabel.py). Nothing here
opens LanceDB."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from funds.unstamp import FUND_COLUMNS, compute_changes, unstamp_table
from identity.relabel import _ALL_COLUMNS
from ingest.lock import IngestLock, LockHeldError


@dataclass
class FakeStore:
    table: str
    rows: dict[str, dict[str, Any]]
    upsert_calls: list[list[dict[str, Any]]] = field(default_factory=list)
    fts_rebuilds: list[str] = field(default_factory=list)
    optimizes: list[str] = field(default_factory=list)

    def build_fts_index(self, table):
        self.fts_rebuilds.append(table)

    def optimize(self, table):
        self.optimizes.append(table)

    def scan(self, table, columns, *, where=None, limit=None):
        assert table == self.table
        return [{c: deepcopy(r[c]) for c in columns if c in r} for r in self.rows.values()]

    def upsert_chunks(self, table, rows):
        assert table == self.table
        rows = list(rows)
        self.upsert_calls.append(deepcopy(rows))
        for r in rows:
            self.rows[r["chunk_id"]] = deepcopy(r)


class LossyFakeStore(FakeStore):
    """Delete-then-add interrupted: the last row of a batch vanishes."""

    def upsert_chunks(self, table, rows):
        rows = list(rows)
        for r in rows[:-1]:
            self.rows[r["chunk_id"]] = deepcopy(r)
        if rows:
            self.rows.pop(rows[-1]["chunk_id"], None)


def _row(i: int, primary, mentions):
    row = {c: None for c in _ALL_COLUMNS}
    row.update({
        "chunk_id": f"d-{i:04d}", "doc_id": "d", "text": f"passage {i}",
        "fund_canonical_id": primary, "fund_mentions": list(mentions),
        "doc_type": "afr", "fiscal_year": 2024, "vector": [0.1, 0.2],
    })
    return row


KEEP = {"fund:ahcccs", "fund:corrections"}


def _store(cls=FakeStore):
    rows = {
        "d-0001": _row(1, "fund:account", ["fund:total-secretary-of-state"]),   # both junk
        "d-0002": _row(2, "fund:ahcccs", ["fund:account", "fund:corrections"]),  # keep primary, scrub one
        "d-0003": _row(3, "fund:corrections", ["fund:ahcccs"]),                  # untouched
        "d-0004": _row(4, None, []),                                             # untouched
    }
    return cls(table="budget_chunks", rows=rows)


def test_both_fund_columns_are_real_schema_columns():
    assert set(FUND_COLUMNS) <= set(_ALL_COLUMNS)


def test_compute_changes_nulls_only_ids_outside_the_keep_set():
    changes = compute_changes(_store().scan("budget_chunks", _ALL_COLUMNS), KEEP)
    got = {row["chunk_id"]: (p, m) for row, p, m in changes}
    assert got == {
        "d-0001": (None, []),
        "d-0002": ("fund:ahcccs", ["fund:corrections"]),
    }


def test_dry_run_writes_nothing_and_reports_per_id_counts():
    store = _store()
    res = unstamp_table(store=store, keep_ids=KEEP, dry_run=True)
    assert store.upsert_calls == []
    assert res.changed == 2 and res.nulled_primary == 1 and res.scrubbed_mentions == 2
    assert res.per_id == {"fund:account": 1}


def test_apply_writes_only_changed_rows_and_records_full_old_mentions(tmp_path):
    store = _store()
    res = unstamp_table(
        store=store, keep_ids=KEEP, dry_run=False, batch_size=10,
        lock=IngestLock(root=tmp_path), snapshot_and_verify=lambda: "snap.zip",
        reversal_dir=tmp_path, progress=lambda _m: None,
    )
    written = {r["chunk_id"] for batch in store.upsert_calls for r in batch}
    assert written == {"d-0001", "d-0002"}
    assert store.rows["d-0001"]["fund_canonical_id"] is None
    assert store.rows["d-0002"]["fund_mentions"] == ["fund:corrections"]
    # Every non-fund column survives the rewrite.
    assert store.rows["d-0002"]["text"] == "passage 2"
    assert store.rows["d-0002"]["vector"] == [0.1, 0.2]
    # The ingest write contract: re-added rows are invisible to BM25 until
    # the full-text index is rebuilt. A pass that skips this ships a silent
    # keyword-search hole.
    assert store.fts_rebuilds == ["budget_chunks"] and store.optimizes == ["budget_chunks"]
    record = json.loads(res.reversal_path.read_text())
    by_id = {c["chunk_id"]: c for c in record["changes"]}
    assert by_id["d-0002"]["before"]["fund_mentions"] == ["fund:account", "fund:corrections"]
    assert record["snapshot"] == "snap.zip"


def test_a_lost_row_is_caught_by_verification(tmp_path):
    store = _store(LossyFakeStore)
    with pytest.raises(RuntimeError, match="lost or gained chunk_ids"):
        unstamp_table(
            store=store, keep_ids=KEEP, dry_run=False, batch_size=10,
            lock=IngestLock(root=tmp_path), snapshot_and_verify=lambda: None,
            reversal_dir=tmp_path, progress=lambda _m: None,
        )


def test_apply_refuses_without_the_ingest_lock(tmp_path):
    holder = IngestLock(root=tmp_path)
    holder.acquire()
    try:
        with pytest.raises(LockHeldError):
            unstamp_table(
                store=_store(), keep_ids=KEEP, dry_run=False, batch_size=10,
                lock=IngestLock(root=tmp_path), snapshot_and_verify=lambda: None,
                reversal_dir=tmp_path, progress=lambda _m: None,
            )
    finally:
        holder.release()
