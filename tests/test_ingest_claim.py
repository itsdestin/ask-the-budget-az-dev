"""Tests for ingest/claim.py — atomic per-job claiming (parallel ingest).

The property under test is the one that makes parallel ingest safe at all:
two workers racing for the same job, exactly one wins, and a worker that
dies mid-job releases its hold without a human touching anything.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from ingest.claim import (
    CLAIMS_DIRNAME,
    JobClaim,
    claims_dir,
)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


def _pid_alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- the basic contract -----------------------------------------------------


def test_acquire_creates_a_claim_file_naming_the_owner(data_dir):
    claim = JobClaim("job-1", doc_id="doc-1")
    assert claim.try_acquire()
    try:
        files = list(claims_dir().glob("*.claim"))
        assert files, "a successful claim must leave a file another machine can see"
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["machine"] and payload["pid"] and payload["heartbeat_at"]
    finally:
        claim.release()


def test_release_removes_every_claim_file(data_dir):
    claim = JobClaim("job-1", doc_id="doc-1")
    assert claim.try_acquire()
    claim.release()
    assert list(claims_dir().glob("*.claim")) == []
    assert not claim.held


def test_claims_live_outside_the_human_readable_jobs_directory(data_dir):
    """The jobs dir is meant to be readable in Notepad when something breaks;
    machine bookkeeping does not belong in it."""
    claim = JobClaim("job-1")
    assert claim.try_acquire()
    try:
        assert claims_dir().name == CLAIMS_DIRNAME
        assert claims_dir().parent == data_dir
    finally:
        claim.release()


# --- no double-claim --------------------------------------------------------


def test_a_second_claim_on_the_same_job_fails(data_dir):
    first = JobClaim("job-1", doc_id="doc-1")
    assert first.try_acquire()
    try:
        assert JobClaim("job-1", doc_id="doc-1").try_acquire() is False
    finally:
        first.release()


def test_a_different_job_on_the_same_document_fails(data_dir):
    """Two job records for one doc_id would extract into the same directory
    and then write the same LanceDB rows — serialize them like today."""
    first = JobClaim("job-1", doc_id="shared-doc")
    assert first.try_acquire()
    try:
        assert JobClaim("job-2", doc_id="shared-doc").try_acquire() is False
    finally:
        first.release()


def test_a_failed_claim_leaves_no_partial_state_behind(data_dir):
    """All-or-nothing: a claim that lost the doc key must not keep the job key,
    or that job becomes permanently unclaimable."""
    first = JobClaim("job-1", doc_id="shared-doc")
    assert first.try_acquire()
    loser = JobClaim("job-2", doc_id="shared-doc")
    assert loser.try_acquire() is False
    first.release()

    assert list(claims_dir().glob("*.claim")) == []
    assert JobClaim("job-2", doc_id="shared-doc").try_acquire()


def test_only_one_of_many_racing_threads_wins(data_dir):
    """The headline property. 24 threads, one job, one winner."""
    winners: list[JobClaim] = []
    barrier = threading.Barrier(24)
    lock = threading.Lock()

    def contend() -> None:
        claim = JobClaim("hot-job", doc_id="hot-doc")
        barrier.wait()
        if claim.try_acquire():
            with lock:
                winners.append(claim)

    threads = [threading.Thread(target=contend) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1
    winners[0].release()


# --- crash recovery ---------------------------------------------------------


def test_a_stale_claim_is_stolen(data_dir):
    """A worker that died mid-job must not park its document forever."""
    claim = JobClaim("job-1", stale_after_s=60)
    dead = claim.paths[0]
    dead.parent.mkdir(parents=True, exist_ok=True)
    dead.write_text(
        json.dumps({
            "machine": "DEAD-PC", "pid": 999999, "user": "x",
            "token": "abc", "heartbeat_at": time.time() - 9999,
        }),
        encoding="utf-8",
    )
    assert claim.try_acquire()
    claim.release()


def test_a_live_claim_is_never_stolen(data_dir):
    """The mirror image: a heartbeat that is current means hands off."""
    holder = JobClaim("job-1", stale_after_s=60)
    assert holder.try_acquire()
    try:
        time.sleep(0.1)
        thief = JobClaim("job-1", stale_after_s=60)
        assert thief.try_acquire() is False
    finally:
        holder.release()


def test_a_corrupt_claim_file_is_treated_as_stale(data_dir):
    """A half-written file on an SMB share must not wedge the queue."""
    claim = JobClaim("job-1")
    claim.paths[0].parent.mkdir(parents=True, exist_ok=True)
    claim.paths[0].write_text("{not json", encoding="utf-8")
    assert claim.try_acquire()
    claim.release()


def test_a_dead_pid_on_this_machine_is_reclaimed_before_the_timeout(data_dir):
    """Same-machine crashes are detectable immediately — no 90-second wait
    before the app can resume its own interrupted work after a restart."""
    import os
    import socket

    dead_pid = next(
        pid for pid in range(4_000_000, 4_000_100) if not _pid_alive(pid)
    )
    claim = JobClaim("job-1", stale_after_s=9999)
    claim.paths[0].parent.mkdir(parents=True, exist_ok=True)
    claim.paths[0].write_text(
        json.dumps({
            "machine": socket.gethostname(), "pid": dead_pid, "user": "x",
            "token": "abc", "heartbeat_at": time.time(),   # fresh heartbeat!
        }),
        encoding="utf-8",
    )
    assert claim.try_acquire()
    claim.release()


def test_a_fresh_claim_from_our_own_live_process_is_not_reclaimed(data_dir):
    """The pid shortcut must not let a process steal from itself — that is
    exactly the double-claim the whole module exists to prevent."""
    holder = JobClaim("job-1", stale_after_s=9999)
    assert holder.try_acquire()
    try:
        assert JobClaim("job-1", stale_after_s=9999).try_acquire() is False
    finally:
        holder.release()


def test_release_does_not_delete_a_claim_that_was_stolen_from_us(data_dir):
    """After a steal there are two workers who think they hold the claim. The
    loser's release must not hand the job to a third."""
    loser = JobClaim("job-1", stale_after_s=0)
    assert loser.try_acquire()
    # Someone judged us dead and took over.
    thief = JobClaim("job-1", stale_after_s=0)
    assert thief.try_acquire()

    loser.release()
    assert loser.paths[0].exists(), \
        "the thief's claim file must survive the loser's release"
    thief.release()


# --- heartbeat --------------------------------------------------------------


def test_the_claim_heartbeats_itself_while_held(data_dir):
    """Extraction can spend three minutes on one page with no callback, so the
    heartbeat cannot ride on progress updates."""
    claim = JobClaim("job-1", heartbeat_interval_s=0.02)
    assert claim.try_acquire()
    try:
        path = claim.paths[0]
        first = json.loads(path.read_text(encoding="utf-8"))["heartbeat_at"]
        time.sleep(0.2)
        later = json.loads(path.read_text(encoding="utf-8"))["heartbeat_at"]
        assert later > first
    finally:
        claim.release()


def test_the_heartbeat_thread_stops_on_release(data_dir):
    claim = JobClaim("job-1", heartbeat_interval_s=0.02)
    assert claim.try_acquire()
    claim.release()
    time.sleep(0.1)
    assert not claim.held
    assert list(claims_dir().glob("*.claim")) == []


# --- housekeeping -----------------------------------------------------------


def test_claim_filenames_survive_a_doc_id_with_path_characters(data_dir):
    """doc_ids come from filenames and URLs; one with a slash in it must not
    write a claim outside the claims directory."""
    claim = JobClaim("job-1", doc_id="../../etc/passwd")
    assert claim.try_acquire()
    try:
        for path in claims_dir().glob("*.claim"):
            assert path.parent == claims_dir()
    finally:
        claim.release()


def test_distinct_doc_ids_never_share_a_claim_file(data_dir):
    """Sanitising must not merge two different documents into one key."""
    a = JobClaim("job-a", doc_id="doc/one")
    b = JobClaim("job-b", doc_id="doc:one")
    assert a.try_acquire()
    try:
        assert b.try_acquire(), "two different documents must not collide"
        b.release()
    finally:
        a.release()
