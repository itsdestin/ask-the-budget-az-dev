"""Tests for ingest/lock.py — the single-writer lock (spec S6)."""
from __future__ import annotations

import json
import time

import pytest

from ingest.lock import IngestLock, LockHeldError


def test_acquire_creates_lockfile_with_owner(tmp_path):
    with IngestLock(root=tmp_path) as lock:
        assert lock.held
        data = json.loads((tmp_path / "ingest.lock").read_text())
        assert data["machine"] and data["pid"] and data["heartbeat_at"]
    assert not (tmp_path / "ingest.lock").exists()  # released


def test_second_acquire_raises_with_owner_name(tmp_path):
    with IngestLock(root=tmp_path):
        with pytest.raises(LockHeldError) as e:
            IngestLock(root=tmp_path).acquire()
        assert "held by" in str(e.value)


def test_stale_lock_is_stolen(tmp_path):
    stale = {"machine": "DEAD-PC", "pid": 1, "user": "x",
             "heartbeat_at": time.time() - 999}
    (tmp_path / "ingest.lock").write_text(json.dumps(stale))
    with IngestLock(root=tmp_path, stale_after_s=120) as lock:
        assert lock.held


def test_heartbeat_refreshes_timestamp(tmp_path):
    with IngestLock(root=tmp_path) as lock:
        t1 = json.loads((tmp_path / "ingest.lock").read_text())["heartbeat_at"]
        lock.heartbeat()
        t2 = json.loads((tmp_path / "ingest.lock").read_text())["heartbeat_at"]
        assert t2 >= t1


def test_release_tolerates_missing_lockfile(tmp_path):
    """Someone else stealing a lock we thought we held must not crash release."""
    lock = IngestLock(root=tmp_path)
    lock.acquire()
    (tmp_path / "ingest.lock").unlink()
    lock.release()  # no exception
    assert not lock.held


def test_failed_acquire_does_not_release_the_holders_lock(tmp_path):
    """A loser's context-manager exit must not delete the winner's lockfile."""
    holder = IngestLock(root=tmp_path)
    holder.acquire()
    loser = IngestLock(root=tmp_path)
    with pytest.raises(LockHeldError):
        loser.acquire()
    loser.release()
    assert (tmp_path / "ingest.lock").exists()
    assert holder.held
    holder.release()


def test_corrupt_lockfile_is_treated_as_stale(tmp_path):
    """A half-written lockfile on an SMB share must not wedge ingest forever."""
    (tmp_path / "ingest.lock").write_text("{not json")
    with IngestLock(root=tmp_path) as lock:
        assert lock.held


def test_heartbeat_before_acquire_is_a_noop(tmp_path):
    lock = IngestLock(root=tmp_path)
    lock.heartbeat()
    assert not (tmp_path / "ingest.lock").exists()
