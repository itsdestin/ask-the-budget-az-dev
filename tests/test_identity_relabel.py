"""Tests for identity/relabel.py — the corpus re-label pass (spec I2).

This pass rewrites `agency_canonical_ids` on every live `budget_chunks` row
using the fixed matcher (Tasks 2-4). Nothing here opens a real LanceDB table
or loads a model — `FakeStore` and `FakeStamper` below stand in for
`store.chunk_store.ChunkStore` and `chunking.entity_stamper.EntityStamper`,
duck-typed to the same two methods `relabel_corpus` actually calls
(`scan` / `upsert_chunks` and `resolve_all`). `ingest.lock.IngestLock` is
used for real, rooted at `tmp_path` — it is a plain file lock, not a
database, so using the real thing here is safe and is what actually proves
the refusal behaviour (a fake lock could just be programmed to agree).
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from identity.relabel import relabel_corpus
from ingest.lock import IngestLock, LockHeldError

_TABLE = "budget_chunks"


def _row(chunk_id: str, doc_id: str, *, agency_ids: list[str], text: str,
         is_table: bool = False, **extra: Any) -> dict[str, Any]:
    """One full `budget_chunks` row, every schema column present (including
    `vector`) — the shape `store.scan(..., _ALL_COLUMNS)` actually returns."""
    base = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "section_path": ["Some Section"],
        "page": 1,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "source_anchor": None,
        "agency_canonical_ids": list(agency_ids),
        "fund_canonical_id": None,
        "fund_mentions": [],
        "fiscal_year": 2026,
        "doc_type": "baseline-per-agency",
        "is_table": is_table,
        "table_html": None,
        "token_count": 10,
        "publisher": "jlbc",
        "vector": [0.1, 0.2, 0.3],
    }
    base.update(extra)
    return base


@dataclass
class FakeStore:
    """In-memory double for `store.chunk_store.ChunkStore`.

    `scan` mirrors the REAL contract exactly — it returns only the columns
    the caller asked for, nothing more — so a bug that forgets to request
    `vector` shows up here exactly as it would against real LanceDB: a
    silently truncated row, not an error.
    """

    table: str
    rows: dict[str, dict[str, Any]]
    scans: list[list[str]] = field(default_factory=list)
    upsert_calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def scan(self, table, columns, *, where=None, limit=None):
        assert table == self.table
        self.scans.append(list(columns))
        return [
            {c: deepcopy(row[c]) for c in columns if c in row}
            for row in self.rows.values()
        ]

    def upsert_chunks(self, table, rows):
        assert table == self.table
        rows = list(rows)
        self.upsert_calls.append(deepcopy(rows))
        for row in rows:
            self.rows[row["chunk_id"]] = deepcopy(row)

    @property
    def upserted_rows(self) -> list[dict[str, Any]]:
        return [r for batch in self.upsert_calls for r in batch]


class LossyFakeStore(FakeStore):
    """Reproduces the exact hazard `upsert_chunks`' docstring warns about:
    delete-then-add across two commits, interrupted in between. The last row
    of every batch is "deleted" but never "re-added" — simulating a crash in
    that window — so relabel's own post-write verification is what has to
    catch it, not a lucky test double that never misbehaves."""

    def upsert_chunks(self, table, rows):
        assert table == self.table
        rows = list(rows)
        self.upsert_calls.append(deepcopy(rows))
        for row in rows[:-1]:
            self.rows[row["chunk_id"]] = deepcopy(row)
        if rows:
            self.rows.pop(rows[-1]["chunk_id"], None)


class FakeStamper:
    """Double for `chunking.entity_stamper.EntityStamper`. Keyed on chunk
    `text` (each test row gets distinct text) rather than trying to
    reproduce real agency matching — that is identity/resolve.py's job, not
    this pass's."""

    def __init__(self, new_labels_by_text: dict[str, list[str]]):
        self._by_text = new_labels_by_text
        self.calls: list[tuple[str, str | None]] = []

    def resolve_all(self, chunk: Any, *, source_url: str | None = None) -> list[str]:
        # `chunk.agency_canonical_id` MUST be None here — relabel exists to
        # re-resolve, not to rubber-stamp whatever a chunk was already
        # carrying (chunking/entity_stamper.py's own resolve_all treats a
        # set scalar as "already decided" and passes it straight through).
        assert chunk.agency_canonical_id is None
        self.calls.append((chunk.text, source_url))
        return list(self._by_text.get(chunk.text, []))


def test_the_pass_reads_and_rewrites_the_vector_column(tmp_path):
    """`vector` is non-nullable and every convenient reader projects it away
    (`store/chunk_store.py:107`): `get_by_ids`, `vector_search`, `fts_search`
    all use a column list that excludes it. Only `scan` with an explicit list
    returns it. A pass that round-trips through the convenient reader writes
    rows missing a required field -- and would do it 83,016 times."""
    original = _row("c1", "doc1", agency_ids=["agency:old"], text="board of x")
    store = FakeStore(table=_TABLE, rows={"c1": deepcopy(original)})
    stamper = FakeStamper({"board of x": ["agency:new"]})
    lock = IngestLock(root=tmp_path)

    result = relabel_corpus(
        store=store, stamper=stamper, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path,
    )

    assert result.changed == 1
    assert store.scans, "the pass never scanned anything"
    assert all("vector" in cols for cols in store.scans), (
        "every scan() call must request vector explicitly — this is the "
        "one trap that only shows up as a missing column, never an error"
    )
    written = store.upserted_rows[0]
    assert written["vector"] == original["vector"]


def test_no_chunk_id_is_lost(tmp_path):
    """G-I3: count before == count after, and the id SETS are equal."""
    rows = {
        "c1": _row("c1", "doc1", agency_ids=["agency:old"], text="a"),
        "c2": _row("c2", "doc1", agency_ids=["agency:old"], text="b"),
        "c3": _row("c3", "doc2", agency_ids=[], text="c"),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:new"], "b": ["agency:old"], "c": []})
    lock = IngestLock(root=tmp_path)

    result = relabel_corpus(
        store=store, stamper=stamper, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path,
    )

    assert result.chunk_count_before == 3
    assert result.chunk_count_after == 3
    assert set(store.rows) == set(rows)


def test_every_other_column_survives_untouched(tmp_path):
    """G-I3 again, and count equality is not enough for it: this pass rewrites
    `agency_canonical_ids`, so a bug that dropped `doc_type` or `fiscal_year`
    would keep the count identical and be invisible."""
    original = _row(
        "c1", "doc1", agency_ids=["agency:old"], text="a",
        fiscal_year=2016, doc_type="baseline-per-agency", publisher="jlbc",
        page=42, token_count=99, section_path=["Chapter One", "ADOA"],
    )
    store = FakeStore(table=_TABLE, rows={"c1": deepcopy(original)})
    stamper = FakeStamper({"a": ["agency:new"]})
    lock = IngestLock(root=tmp_path)

    relabel_corpus(
        store=store, stamper=stamper, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path,
    )

    after = store.rows["c1"]
    for key, value in original.items():
        if key == "agency_canonical_ids":
            continue
        assert after[key] == value, f"column {key!r} drifted"
    assert after["agency_canonical_ids"] == ["agency:new"]


def test_a_dry_run_writes_nothing(tmp_path):
    rows = {"c1": _row("c1", "doc1", agency_ids=["agency:old"], text="a")}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:new"]})

    result = relabel_corpus(store=store, stamper=stamper, table=_TABLE, dry_run=True)

    assert result.changed == 1  # it DID find the proposed change...
    assert store.upsert_calls == []  # ...but wrote nothing
    assert store.rows == rows  # the fake corpus is untouched
    assert result.reversal_path is None  # nothing landed on disk either


def test_the_pass_refuses_to_run_without_the_ingest_lock(tmp_path):
    """`upsert_chunks` is a delete followed by an add in two separate commits
    and `write_doc` widens the window further. An interruption between them
    leaves those chunk_ids absent, so this is operationally an ingest."""
    rows = {"c1": _row("c1", "doc1", agency_ids=["agency:old"], text="a")}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:new"]})

    rival = IngestLock(root=tmp_path).acquire()
    try:
        with pytest.raises(LockHeldError):
            relabel_corpus(
                store=store, stamper=stamper, table=_TABLE, dry_run=False,
                batch_size=10, lock=IngestLock(root=tmp_path),
                snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
            )
    finally:
        rival.release()

    assert store.upsert_calls == [], "must not write a single row without the lock"
    assert store.rows == rows


def test_a_reversal_record_carries_the_old_labels(tmp_path):
    rows = {"c1": _row("c1", "doc1", agency_ids=["agency:ost"], text="a")}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:adc"]})
    lock = IngestLock(root=tmp_path)

    result = relabel_corpus(
        store=store, stamper=stamper, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path,
    )

    assert result.reversal == [
        {"doc_id": "doc1", "chunk_id": "c1",
         "before": ["agency:ost"], "after": ["agency:adc"]},
    ]
    assert result.reversal_path is not None
    on_disk = json.loads(result.reversal_path.read_text(encoding="utf-8"))
    assert on_disk["changes"] == result.reversal


# --- bonus coverage: the two hazards named in the brief but not required
# by the six specs above -----------------------------------------------


def test_writes_are_batched(tmp_path):
    rows = {
        f"c{i}": _row(f"c{i}", "doc1", agency_ids=["agency:old"], text=f"t{i}")
        for i in range(5)
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({f"t{i}": ["agency:new"] for i in range(5)})
    lock = IngestLock(root=tmp_path)

    result = relabel_corpus(
        store=store, stamper=stamper, table=_TABLE, dry_run=False,
        batch_size=2, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path,
    )

    assert result.changed == 5
    assert [len(b) for b in store.upsert_calls] == [2, 2, 1]


def test_a_lost_chunk_id_after_writing_is_caught_not_silently_accepted(tmp_path):
    """Trap 2, made concrete: if a write really did lose a row, the pass
    must refuse to report success, not just hope its own bookkeeping was
    right."""
    rows = {
        "c1": _row("c1", "doc1", agency_ids=["agency:old"], text="a"),
        "c2": _row("c2", "doc1", agency_ids=["agency:old"], text="b"),
    }
    store = LossyFakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:new"], "b": ["agency:new"]})
    lock = IngestLock(root=tmp_path)

    with pytest.raises(RuntimeError, match="lost"):
        relabel_corpus(
            store=store, stamper=stamper, table=_TABLE, dry_run=False,
            batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
            reversal_dir=tmp_path,
        )


def test_a_failed_snapshot_verification_stops_the_pass_before_any_write(tmp_path):
    rows = {"c1": _row("c1", "doc1", agency_ids=["agency:old"], text="a")}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    stamper = FakeStamper({"a": ["agency:new"]})
    lock = IngestLock(root=tmp_path)

    def _boom():
        raise RuntimeError("corpus snapshot is corrupt")

    with pytest.raises(RuntimeError, match="corrupt"):
        relabel_corpus(
            store=store, stamper=stamper, table=_TABLE, dry_run=False,
            batch_size=10, lock=lock, snapshot_and_verify=_boom,
            reversal_dir=tmp_path,
        )
    assert store.upsert_calls == []
