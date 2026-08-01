"""Per-batch S17 snapshots (Plan 5 Task 20, step 4).

`snapshot()` zips the WHOLE corpus. Taking one per document means the
cost of each snapshot grows with the corpus while the NUMBER of them
grows with the documents — quadratic. Measured during the Z13 backfill:
a ~54 MB zip every ~40s at 68 MB of corpus, projected at 60–90s per
document once the books landed. `JLBC_INGEST_SNAPSHOT=off` exists
because of that, and it works by throwing the safety net away.

One snapshot per BATCH is the shape that keeps the protection without
the quadratic cost: a book edition or a fiscal-note session is the unit
somebody would actually want to roll back, and it is also the unit that
fails as a unit.

A single interactive upload has no batch and still snapshots per
document — that is exactly when an analyst wants a restore point, and
one upload is one zip.
"""
from __future__ import annotations

import pytest

from ingest.jobs import new_job


@pytest.fixture(autouse=True)
def _share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "lancedb").mkdir()
    (tmp_path / "lancedb" / "data.lance").write_bytes(b"corpus" * 1000)
    return tmp_path


def _job(**kw):
    base = dict(
        doc_id="d1", title="T", corpus="budget", source_path="/tmp/x.pdf",
        source_sha256="a" * 64, publisher="jlbc",
        doc_type="baseline-per-agency", fiscal_year=2027,
    )
    base.update(kw)
    return new_job(**base)


# ---------------------------------------------------------------------------
# The policy decision itself
# ---------------------------------------------------------------------------


def test_a_job_with_no_batch_snapshots_every_time(_share):
    """A hand upload. One document, one restore point — unchanged."""
    from ingest.worker import _should_snapshot

    assert _should_snapshot(_job()) is True
    assert _should_snapshot(_job(doc_id="d2")) is True


def test_only_the_first_job_of_a_batch_snapshots(_share):
    from ingest.worker import _should_snapshot, _record_batch_snapshot

    first = _job(doc_id="d1", batch_id="jlbc-baseline-fy2027")
    assert _should_snapshot(first) is True
    _record_batch_snapshot(first)

    for n in range(2, 12):
        later = _job(doc_id=f"d{n}", batch_id="jlbc-baseline-fy2027")
        assert _should_snapshot(later) is False


def test_a_different_batch_snapshots_again(_share):
    from ingest.worker import _should_snapshot, _record_batch_snapshot

    a = _job(batch_id="jlbc-baseline-fy2027")
    _record_batch_snapshot(a)

    assert _should_snapshot(_job(batch_id="jlbc-approps-fy2026")) is True


def test_the_record_lives_ON_THE_SHARE_not_in_memory(_share):
    """A 210-page book is an overnight job that WILL be interrupted. If
    the record were a process-local set, every restart would re-zip the
    whole corpus — the quadratic cost back through the side door.

    Asserted as two properties rather than by reloading the module (a
    mid-suite `importlib.reload` swaps out class objects other tests
    already hold references to, and it broke an unrelated worker test):
    the marker is a real file on the share, and the check reads that file
    every time rather than memoizing.
    """
    from ingest.worker import (
        _batch_marker_path,
        _record_batch_snapshot,
        _should_snapshot,
    )

    job = _job(batch_id="overnight")
    _record_batch_snapshot(job)

    marker = _batch_marker_path("overnight")
    assert marker.is_file()
    assert marker.parent == _share / "backups"
    assert _should_snapshot(job) is False

    # No memoization: delete the file and the answer changes. A cached
    # "already snapshotted" would survive a restart in the wrong direction.
    marker.unlink()
    assert _should_snapshot(job) is True


def test_a_batch_id_cannot_escape_the_backups_directory(_share):
    """Batch ids are built from publisher/family strings. One containing a
    path separator must not write a marker outside `backups/`."""
    from ingest.worker import _batch_marker_path

    marker = _batch_marker_path("../../etc/passwd")

    assert marker.parent == _share / "backups"
    assert ".." not in marker.name


def test_bulk_mode_still_wins_over_everything(_share, monkeypatch):
    """`JLBC_INGEST_SNAPSHOT=off` is an operator saying "I have my own
    archive". Per-batch must not quietly re-enable snapshots for someone
    who explicitly turned them off."""
    from ingest.worker import _should_snapshot

    monkeypatch.setenv("JLBC_INGEST_SNAPSHOT", "off")
    assert _should_snapshot(_job()) is False
    assert _should_snapshot(_job(batch_id="anything")) is False


def test_an_unwritable_marker_falls_back_to_snapshotting(_share, monkeypatch):
    """Fail SAFE. If the marker can't be read, the honest answer is "I
    don't know whether this batch has a restore point", and the
    conservative response is to make one — an extra zip costs time, a
    missing one costs the corpus."""
    import ingest.worker as worker

    monkeypatch.setattr(
        worker, "_batch_marker_path",
        lambda _bid: (_ for _ in ()).throw(OSError("share gone")),
    )
    assert worker._should_snapshot(_job(batch_id="b1")) is True


# ---------------------------------------------------------------------------
# batch_id plumbing
# ---------------------------------------------------------------------------


def test_batch_id_round_trips_through_the_job_file(_share):
    from ingest.jobs import JobRecord, load_job, save

    job = _job(batch_id="jlbc-baseline-fy2027")
    save(job)

    assert load_job(job.job_id).batch_id == "jlbc-baseline-fy2027"
    assert JobRecord.from_json(job.to_json()).batch_id == "jlbc-baseline-fy2027"


def test_a_job_file_written_before_this_change_still_loads(_share):
    """Jobs already queued on the share have no batch_id key. Ingest must
    not fail on them mid-backfill."""
    from ingest.jobs import JobRecord

    payload = _job().to_json()
    payload.pop("batch_id")

    assert JobRecord.from_json(payload).batch_id is None


def test_book_ingest_batches_by_edition(_share):
    """The unit somebody would roll back is a book edition."""
    from app.routes.books import _batch_id_for

    assert _batch_id_for("baseline", 2027) == _batch_id_for("baseline", 2027)
    assert _batch_id_for("baseline", 2027) != _batch_id_for("approps", 2027)
    assert _batch_id_for("baseline", 2027) != _batch_id_for("baseline", 2026)
