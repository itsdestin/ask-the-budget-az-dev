"""Tests for store/backup.py — S17 corpus snapshots."""
from __future__ import annotations

import zipfile

import pytest

from store.backup import (
    SNAPSHOT_KEEP,
    backups_dir,
    list_snapshots,
    restore,
    snapshot,
)


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    """A minimal <data_dir> with a lancedb/ folder standing in for the corpus."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    lancedb = tmp_path / "lancedb"
    lancedb.mkdir(parents=True)
    (lancedb / "x.txt").write_text("corpus")
    return tmp_path


def test_snapshot_creates_zip_and_rotates(corpus):
    for _ in range(7):
        snapshot()
    assert len(list_snapshots()) == SNAPSHOT_KEEP == 5


def test_restore_round_trip(corpus):
    name = snapshot()
    (corpus / "lancedb" / "x.txt").write_text("corrupted")
    restore(name)
    assert (corpus / "lancedb" / "x.txt").read_text() == "corpus"


def test_snapshot_preserves_nested_layout(corpus):
    nested = corpus / "lancedb" / "budget_chunks.lance" / "data"
    nested.mkdir(parents=True)
    (nested / "0.lance").write_bytes(b"\x00\x01")
    name = snapshot()
    with zipfile.ZipFile(backups_dir() / name) as zf:
        assert "budget_chunks.lance/data/0.lance" in zf.namelist()


def test_restore_removes_files_added_after_the_snapshot(corpus):
    """A restore must land on exactly the snapshotted corpus — a leftover
    half-written table from the bad write would corrupt the good one."""
    name = snapshot()
    (corpus / "lancedb" / "half-written.lance").write_text("garbage")
    restore(name)
    assert not (corpus / "lancedb" / "half-written.lance").exists()
    assert (corpus / "lancedb" / "x.txt").read_text() == "corpus"


def test_list_snapshots_is_newest_first(corpus):
    names = [snapshot() for _ in range(3)]
    assert list_snapshots() == sorted(names, reverse=True)


def test_snapshot_without_a_corpus_is_a_noop(tmp_path, monkeypatch):
    """First-ever ingest on an empty data dir has nothing to protect."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    assert snapshot() is None
    assert list_snapshots() == []


def test_restore_unknown_snapshot_raises(corpus):
    with pytest.raises(FileNotFoundError):
        restore("lancedb-19700101T000000Z.zip")


def test_restore_rejects_path_traversal(corpus):
    """`name` reaches this from an admin HTTP route in Plan 5."""
    snapshot()
    with pytest.raises(ValueError):
        restore("../../etc/passwd")
