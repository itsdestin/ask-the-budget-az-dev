"""LanceDB dead-version cleanup (Plan 5 Task 20, step 1).

Measured on the Z13 during the backfill: 5.1 GB on disk holding ~18k
chunks, and 200 MB of one table holding 39 MB of live data. Every write
in this app is delete-then-add, so every ingested document leaves a
superseded version behind, and `optimize()` was never pruning them —
its `cleanup_older_than` defaults to SEVEN DAYS, so during a bulk run
where every version is minutes old it prunes exactly nothing.

On the office SMB share this is the difference between a corpus that
copies in minutes and one that doesn't.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from store.chunk_store import ChunkStore
from store.schema import chunk_schema

DIM = 8


def _row(chunk_id: str, *, doc_id: str = "doc-a", text: str = "x" * 400) -> dict:
    return {
        **{f.name: None for f in chunk_schema(dim=DIM)},
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "section_path": [],
        "agency_canonical_ids": [],
        "fund_mentions": [],
        "doc_type": "baseline-per-agency",
        "is_table": False,
        "token_count": 100,
        "publisher": "jlbc",
        "vector": [0.1] * DIM,
    }


def _bytes(path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


@pytest.fixture
def store(tmp_path):
    return ChunkStore(root=tmp_path, dim=DIM)


def test_optimize_reclaims_superseded_versions(store, tmp_path):
    """write → delete → re-write → optimize, and the bytes must FALL.

    This is the exact shape of a re-ingest: `write_doc` deletes the whole
    document and adds it back, so the old data files are dead the moment
    the new ones land.
    """
    root = tmp_path / "lancedb"

    store.upsert_chunks("budget_chunks", [_row(f"c{i}") for i in range(200)])
    store.build_fts_index("budget_chunks")
    store.optimize("budget_chunks", retention=timedelta(days=7))

    for _ in range(5):
        store.delete_doc("budget_chunks", "doc-a")
        store.upsert_chunks("budget_chunks", [_row(f"c{i}") for i in range(200)])
        store.build_fts_index("budget_chunks")

    before = _bytes(root)
    store.optimize("budget_chunks", retention=timedelta(0))
    after = _bytes(root)

    assert after < before, (
        f"cleanup reclaimed nothing: {before} bytes before, {after} after"
    )
    # The data is still there — this is a vacuum, not a truncation.
    assert store.count("budget_chunks") == 200


def test_a_seven_day_retention_reclaims_nothing_from_a_fresh_bulk_run(
    store, tmp_path
):
    """The regression this task exists for.

    Pinning it explicitly because the defect is INVISIBLE: `optimize()`
    was being called, it returned successfully, and it pruned nothing at
    all. Nobody would have found this by reading the call site.
    """
    root = tmp_path / "lancedb"
    store.upsert_chunks("budget_chunks", [_row(f"c{i}") for i in range(200)])
    for _ in range(5):
        store.delete_doc("budget_chunks", "doc-a")
        store.upsert_chunks("budget_chunks", [_row(f"c{i}") for i in range(200)])

    before = _bytes(root)
    store.optimize("budget_chunks", retention=timedelta(days=7))

    assert _bytes(root) >= before


def test_default_retention_is_short_enough_to_matter():
    """A default measured in days reproduces the bug it fixes — on a bulk
    run every version is minutes old, so nothing gets pruned."""
    from store.chunk_store import version_retention

    assert version_retention() <= timedelta(minutes=15)


def test_default_retention_is_not_zero():
    """Zero would prune a version a reader on another office machine may
    be mid-query against, and leaves no margin for clock skew between
    PCs — the prune compares version timestamps to the pruner's clock."""
    from store.chunk_store import version_retention

    assert version_retention() > timedelta(0)


def test_retention_is_configurable(monkeypatch):
    from store.chunk_store import version_retention

    monkeypatch.setenv("JLBC_LANCE_RETENTION_MINUTES", "5")
    assert version_retention() == timedelta(minutes=5)


def test_a_nonsense_retention_falls_back_rather_than_crashing_ingest(monkeypatch):
    """This variable is typed by a human into a shell on an office PC. A
    typo must not take down the write phase — and must not silently mean
    zero, which would prune versions a reader on another machine may be
    mid-query against."""
    from store.chunk_store import DEFAULT_RETENTION_MINUTES, version_retention

    for bad in ("", "  ", "abc", "-1", "1.5"):
        monkeypatch.setenv("JLBC_LANCE_RETENTION_MINUTES", bad)
        assert version_retention() == timedelta(minutes=DEFAULT_RETENTION_MINUTES), (
            f"{bad!r} should have fallen back to the default"
        )


def test_zero_is_honoured_because_it_is_unambiguous(monkeypatch):
    """"0" is a real choice — a supervised bulk backfill on a machine
    nobody else is reading. Distinguished from the invalid values above,
    which are typos."""
    from store.chunk_store import version_retention

    monkeypatch.setenv("JLBC_LANCE_RETENTION_MINUTES", "0")
    assert version_retention() == timedelta(0)


def test_optimize_on_a_missing_table_is_still_a_no_op(store):
    store.optimize("fiscal_note_chunks")  # must not raise
