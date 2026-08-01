"""IngestLock keeps itself alive while it is held (Plan 5 Task 20, step 3).

`ingest/worker.py::_write` heartbeats BEFORE `write_doc` and not during
it. Inside `write_doc` are `build_fts_index` and `optimize`, both of
which grow with the corpus — at 24,841 budget chunks and climbing they
will pass the 120s stale window. When they do, another machine reads a
two-minute-old heartbeat, correctly concludes the holder is dead, steals
the lock, and starts writing to a corpus that is being written.

That is the S6 single-writer invariant failing on a live, healthy writer
— the one failure mode the lock exists to prevent.

The fix is that holding the lock is enough: `acquire()` starts a daemon
thread that heartbeats until `release()`. Nothing has to remember to
call anything.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from ingest.lock import IngestLock, LockHeldError


def _owner(lock: IngestLock) -> dict:
    return json.loads(lock.path.read_text(encoding="utf-8"))


def test_the_lock_heartbeats_itself_while_held(tmp_path):
    """No caller cooperation. This is the whole fix."""
    with IngestLock(tmp_path, heartbeat_every_s=0.05) as lock:
        first = _owner(lock)["heartbeat_at"]
        time.sleep(0.3)
        later = _owner(lock)["heartbeat_at"]

    assert later > first, "the lockfile's timestamp never advanced on its own"


def test_a_long_write_cannot_have_its_lock_stolen(tmp_path):
    """The scenario, end to end: a writer holds the lock through work far
    longer than the stale window, and a second acquirer must never get in.

    Time is compressed — a 0.4s hold against a 0.15s stale window is the
    same shape as a 200s write against a 120s window, without a
    three-minute test.
    """
    stolen: list[bool] = []
    holder_done = threading.Event()

    def hold():
        with IngestLock(tmp_path, stale_after_s=0.15, heartbeat_every_s=0.02):
            time.sleep(0.4)  # ~2.7 stale windows of "work"
        holder_done.set()

    holder = threading.Thread(target=hold)
    holder.start()
    time.sleep(0.05)  # let the holder take it

    deadline = time.monotonic() + 0.35
    while time.monotonic() < deadline:
        # A SEPARATE root object each time, so this contends through the
        # lockfile the way another machine would rather than through the
        # in-process mutex.
        rival = IngestLock(tmp_path, stale_after_s=0.15)
        try:
            rival._root.mkdir(parents=True, exist_ok=True)
            if rival._try_create():
                stolen.append(True)
                rival._unlink_quietly()
            elif rival._is_stale(rival._read_owner()):
                stolen.append(True)
        except LockHeldError:
            pass
        time.sleep(0.02)

    holder.join(timeout=5)
    assert holder_done.is_set()
    assert stolen == [], "a live holder's lock was judged stale and stealable"


def test_the_heartbeat_thread_stops_on_release(tmp_path):
    """A thread per lock that outlives the lock is a leak, and it would
    keep resurrecting a lockfile a later acquirer had legitimately taken."""
    before = threading.active_count()
    lock = IngestLock(tmp_path, heartbeat_every_s=0.02)
    lock.acquire()
    time.sleep(0.05)
    lock.release()
    time.sleep(0.1)

    assert threading.active_count() <= before


def test_release_does_not_recreate_the_lockfile(tmp_path):
    """The race the stop flag alone would not close: a heartbeat that
    fires between `unlink` and the thread noticing would write the
    lockfile back, leaving an ownerless file that blocks everyone until
    it goes stale."""
    lock = IngestLock(tmp_path, heartbeat_every_s=0.01)
    lock.acquire()
    time.sleep(0.05)
    lock.release()
    time.sleep(0.08)

    assert not lock.path.exists()


def test_a_second_acquirer_gets_in_normally_after_release(tmp_path):
    """Guard rail: none of this may make the lock harder to hand over."""
    first = IngestLock(tmp_path, heartbeat_every_s=0.02)
    first.acquire()
    first.release()

    second = IngestLock(tmp_path)
    second.acquire()
    try:
        assert second.held
    finally:
        second.release()


def test_an_abandoned_lock_still_goes_stale(tmp_path):
    """The heartbeat must not make a CRASHED holder's lock immortal.

    Simulated the way a crash really looks: the file is on disk with an
    old timestamp and no process behind it.
    """
    lock = IngestLock(tmp_path, stale_after_s=0.1)
    lock.acquire()
    lock._stop_heartbeat()  # the holder died; nothing refreshes it now
    lock.path.write_text(
        json.dumps({"machine": "gone", "pid": 1, "user": "x",
                    "heartbeat_at": time.time() - 60}),
        encoding="utf-8",
    )

    rival = IngestLock(tmp_path, stale_after_s=0.1)
    assert rival._is_stale(rival._read_owner())


def test_heartbeat_survives_a_share_hiccup(tmp_path, monkeypatch):
    """A dropped SMB connection must not kill the thread — the next beat
    has to retry. A thread that died on one OSError would leave a live
    writer silently un-heartbeated, which is the original bug back."""
    lock = IngestLock(tmp_path, heartbeat_every_s=0.02)
    lock.acquire()
    try:
        calls: list[int] = []
        real = lock._write_payload

        def flaky():
            calls.append(1)
            if len(calls) <= 2:
                raise OSError("share went away")
            real()

        monkeypatch.setattr(lock, "_write_payload", flaky)
        time.sleep(0.2)
        assert len(calls) > 3, "the heartbeat thread stopped after an error"
    finally:
        lock.release()


def test_explicit_heartbeat_still_works(tmp_path):
    """`heartbeat()` stays public — ingest/worker.py and the backfill
    maintainer both call it, and removing it would break them."""
    with IngestLock(tmp_path, heartbeat_every_s=1000) as lock:
        first = _owner(lock)["heartbeat_at"]
        time.sleep(0.01)
        lock.heartbeat()
        assert _owner(lock)["heartbeat_at"] > first


# --- the stale-steal path (2026-08-01) --------------------------------------
#
# `acquire()` has TWO ways to end up holding the lock: the ordinary create,
# and the create that follows stealing a stale lockfile. Only the first one
# started the heartbeat, so a lock taken by stealing sat with a frozen
# `heartbeat_at` and was itself stolen a stale window later — while its holder
# was still writing. Observed live: 866 seconds frozen during a book backfill,
# 147 threads queued behind it. Everything above this line tests the ordinary
# path only, which is why the bug survived.


def _plant_stale_lockfile(tmp_path) -> None:
    """A crashed holder as it really looks on disk: a file, an old
    timestamp, no process behind it."""
    (tmp_path / "ingest.lock").write_text(
        json.dumps({"machine": "DEAD-PC", "pid": 1, "user": "x",
                    "heartbeat_at": time.time() - 999}),
        encoding="utf-8",
    )


def test_a_lock_taken_by_stealing_heartbeats(tmp_path):
    """THE regression guard. Same assertion as
    `test_the_lock_heartbeats_itself_while_held`, reached down the steal
    path instead of the create path."""
    _plant_stale_lockfile(tmp_path)

    lock = IngestLock(tmp_path, stale_after_s=0.1, heartbeat_every_s=0.05)
    lock.acquire()
    try:
        assert lock.held
        # It really was a steal, not a create — the planted file was there.
        assert _owner(lock)["machine"] != "DEAD-PC", "we did not take the lock"

        first = _owner(lock)["heartbeat_at"]
        time.sleep(0.3)
        later = _owner(lock)["heartbeat_at"]
    finally:
        lock.release()

    assert later > first, (
        "a lock acquired by stealing never refreshed itself — after the "
        "stale window every other machine will steal it from a live writer"
    )


def test_a_stolen_lock_is_not_judged_stale_while_it_is_still_held(tmp_path):
    """The end-to-end property the bug broke: a rival must never conclude a
    live holder is dead, even when that holder acquired by stealing.

    Time compressed exactly as in `test_a_long_write_cannot_have_its_lock_
    stolen` — a 0.4s hold against a 0.15s stale window has the same shape as
    a 200s write against the real 120s window.
    """
    _plant_stale_lockfile(tmp_path)

    stolen: list[bool] = []
    holder_done = threading.Event()

    def hold():
        # Acquires by STEALING the planted lockfile, then works far longer
        # than the stale window.
        with IngestLock(tmp_path, stale_after_s=0.15, heartbeat_every_s=0.02):
            time.sleep(0.4)
        holder_done.set()

    holder = threading.Thread(target=hold)
    holder.start()
    time.sleep(0.05)

    deadline = time.monotonic() + 0.35
    while time.monotonic() < deadline:
        # A separate object per pass, contending through the lockfile the way
        # another MACHINE would rather than through the in-process mutex.
        rival = IngestLock(tmp_path, stale_after_s=0.15)
        rival._root.mkdir(parents=True, exist_ok=True)
        if rival._try_create():
            stolen.append(True)
            rival._unlink_quietly()
        elif rival._is_stale(rival._read_owner()):
            stolen.append(True)
        time.sleep(0.02)

    holder.join(timeout=5)
    assert holder_done.is_set()
    assert stolen == [], (
        "a live holder that acquired by stealing was itself judged stale — "
        "two writers on one corpus"
    )


def test_release_after_a_steal_stops_and_joins_the_heartbeat(tmp_path):
    """The hazard `release()`'s docstring names, on the steal path: an
    in-flight beat that fires after the unlink resurrects an OWNERLESS
    lockfile, blocking every machine until it goes stale. Plus the plain
    leak check — no heartbeat thread may outlive its lock."""
    _plant_stale_lockfile(tmp_path)
    before = threading.active_count()

    lock = IngestLock(tmp_path, stale_after_s=0.1, heartbeat_every_s=0.01)
    lock.acquire()
    assert lock.held
    beat = lock._beat_thread
    assert beat is not None, "the steal path started no heartbeat thread"

    time.sleep(0.05)
    lock.release()
    time.sleep(0.08)  # long enough for several missed beats to have fired

    assert not beat.is_alive(), "the heartbeat thread outlived its lock"
    assert threading.active_count() <= before
    assert not lock.path.exists(), "a beat resurrected the lockfile after release"


def test_heartbeat_interval_defaults_to_well_under_the_stale_window():
    """A beat that fires once per stale window is a coin flip: one slow
    SMB round-trip and the holder looks dead."""
    from ingest.lock import DEFAULT_HEARTBEAT_EVERY_S, DEFAULT_STALE_AFTER_S

    assert DEFAULT_HEARTBEAT_EVERY_S <= DEFAULT_STALE_AFTER_S / 4
