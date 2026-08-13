"""Where a job file lives, and what that buys.

Spec T13 as amended 2026-08-13: the queue shows work, not history. Rather
than filter a 7,118-file directory on every poll, a job that reaches a
terminal SUCCESS state moves out of the way, so the main folder comes to
hold exactly what the queue shows. `failed` deliberately never moves.

Measured on the live data dir 2026-08-13, which is why the shape is a
location and not an age window: 7,118 job files -- 7,100 `live`, 14
`failed`, 4 `cancelled` -- and **13 of the 14 failures had files older than
24 hours**. Any age-based filter hides them, which inverts the one rule
spec T13 says not to relax.
"""
import json
import os
from pathlib import Path

import pytest

from ingest import jobs as J


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _job(**over):
    base = dict(
        doc_id="doc-1",
        title="T",
        corpus="budget",
        source_path="/x.pdf",
        source_sha256="abc",
        publisher="jlbc",
        doc_type="jlbc-approps-per-agency",
        fiscal_year=2026,
    )
    base.update(over)
    return J.new_job(**base)


def _finish(job):
    """Walk a job all the way to `live` through the real state machine."""
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)
    return job


def test_a_queued_job_lives_in_the_main_folder(data_dir):
    path = J.save(_job())
    assert path.parent == J.jobs_dir()
    assert path.parent.name == "jobs"


def test_reaching_live_moves_the_file_into_done(data_dir):
    job = _job()
    main = J.save(job)
    assert main.exists()

    _finish(job)

    assert not main.exists(), "the main-folder copy must not be left behind"
    assert (J.archive_dir() / f"{job.job_id}.json").exists()


def test_a_failed_job_NEVER_moves(data_dir):
    """The one rule spec T13 says not to relax.

    A failure that ages out of the folder the queue reads is a failure
    nobody will ever see. 13 of the 14 failures in the live data dir on
    2026-08-13 were 12.6 days old.
    """
    job = _job()
    J.save(job)
    J.advance(job, "extracting")
    J.advance(job, "failed", error="boom")

    assert (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert not (J.archive_dir() / f"{job.job_id}.json").exists()
    assert job.job_id in {j.job_id for j in J.load_active()}


def test_dismissing_a_failure_moves_it(data_dir):
    """Dismiss is `failed -> cancelled` (app/routes/jobs.py::cancel_job).

    T13 says a failure shows "until it is retried, cancelled or dismissed".
    Because `cancelled` is an archived state, that clause falls out of where
    the file lives rather than needing a rule to enforce it.
    """
    job = _job()
    J.save(job)
    J.advance(job, "failed", error="boom")
    J.advance(job, "cancelled")

    assert not (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert (J.archive_dir() / f"{job.job_id}.json").exists()
    assert job.job_id not in {j.job_id for j in J.load_active()}


def test_retrying_a_failure_keeps_it_in_the_main_folder(data_dir):
    job = _job()
    J.save(job)
    J.advance(job, "failed", error="boom")
    J.advance(job, "queued")

    assert (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert job.job_id in {j.job_id for j in J.load_active()}


def test_load_active_excludes_archived_and_load_all_includes_it(data_dir):
    done = _finish(_job(doc_id="done"))
    waiting = _job(doc_id="waiting")
    J.save(waiting)

    assert {j.job_id for j in J.load_active()} == {waiting.job_id}
    assert {j.job_id for j in J.load_all()} == {waiting.job_id, done.job_id}


def test_load_job_finds_an_archived_job(data_dir):
    job = _finish(_job())
    found = J.load_job(job.job_id)
    assert found is not None and found.state == "live"


def test_a_job_in_BOTH_folders_is_returned_once(data_dir):
    """A crash between "write the new copy" and "remove the old" leaves a
    twin. That ordering is deliberate -- the other order can lose the file
    outright -- so the readers must tolerate the duplicate it can produce.
    """
    job = _job()
    J.save(job)
    stale_twin = J.jobs_dir() / f"{job.job_id}.json"
    _finish(job)
    stale_twin.write_text(json.dumps(job.to_json()), encoding="utf-8")

    ids = [j.job_id for j in J.load_all()]
    assert ids.count(job.job_id) == 1


def test_archived_count_opens_no_files(data_dir, monkeypatch):
    """The finished count feeds a line on a page that polls. Rendering it by
    reading 7,100 job files is precisely what spec T13 exists to stop, so
    this asserts the mechanism and not just the number.
    """
    for i in range(3):
        _finish(_job(doc_id=f"d{i}"))

    real_read_text = Path.read_text
    opened: list[Path] = []

    def _spy(self, *a, **k):
        opened.append(self)
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _spy)
    assert J.archived_count() == 3
    assert opened == [], f"archived_count opened {len(opened)} files"


def test_newest_archived_live_skips_cancelled(data_dir):
    """`last_ingest_at` on the admin health panel means "when did a document
    last finish successfully", so a dismissed failure must not answer it.
    """
    old = _finish(_job(doc_id="old"))
    os.utime(J.archive_dir() / f"{old.job_id}.json", (1_000_000, 1_000_000))

    junk = _job(doc_id="junk")
    J.save(junk)
    J.advance(junk, "cancelled")

    newest = J.newest_archived_live()
    assert newest is not None and newest.doc_id == "old"
