"""Tests for ingest/jobs.py — the persistent queue journal."""
from __future__ import annotations

import json
import re

import pytest

from ingest.jobs import (
    TERMINAL_STATES,
    IllegalTransition,
    JobRecord,
    advance,
    jobs_dir,
    load_all,
    load_job,
    mark_stage,
    new_job,
    resumable,
    save,
)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


def _job(**over) -> JobRecord:
    base = dict(
        doc_id="jlbc-baseline-per-agency-fy2027-axs",
        title="FY 2027 Baseline — AHCCCS",
        corpus="budget",
        source_path="uploads/ab/abab.pdf",
        source_sha256="ab" * 32,
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2027,
        user_title="",
        user="TESTUSER",
    )
    base.update(over)
    return new_job(**base)


# --- creation + persistence -------------------------------------------------


def test_new_job_starts_queued_with_a_sortable_id(data_dir):
    job = _job()
    assert job.state == "queued"
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", job.job_id)
    assert job.machine and job.created_at and job.updated_at
    assert job.pct == 0 and job.error is None and job.completed_ranges == []


def test_save_writes_one_file_per_job(data_dir):
    job = _job()
    save(job)
    path = jobs_dir() / f"{job.job_id}.json"
    assert json.loads(path.read_text())["doc_id"] == job.doc_id


def test_save_is_atomic_leaving_no_partial_file(data_dir):
    """Readers on the share poll this directory; a half-written file would
    surface as a crashed queue page."""
    job = _job()
    save(job)
    assert [p.suffix for p in jobs_dir().iterdir()] == [".json"]


def test_round_trip_preserves_every_field(data_dir):
    job = _job()
    job.completed_ranges = [[1, 40], [41, 80]]
    save(job)
    assert load_job(job.job_id) == job


def test_load_all_is_newest_first_across_machines(data_dir):
    old, new = _job(), _job()
    old.created_at = "2026-01-01T00:00:00+00:00"
    new.created_at = "2026-07-30T00:00:00+00:00"
    old.machine, new.machine = "PC-A", "PC-B"
    save(old)
    save(new)
    assert [j.job_id for j in load_all()] == [new.job_id, old.job_id]


def test_load_all_skips_unreadable_files(data_dir):
    """One corrupt job file must not blank the whole queue page."""
    good = _job()
    save(good)
    (jobs_dir() / "20260101T000000Z-deadbeef.json").write_text("{not json")
    assert [j.job_id for j in load_all()] == [good.job_id]


def test_load_missing_job_returns_none(data_dir):
    assert load_job("20260101T000000Z-deadbeef") is None


# --- state machine ----------------------------------------------------------


def test_happy_path_transitions(data_dir):
    job = _job()
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        advance(job, state)
    assert job.state == "live"


def test_illegal_jump_raises(data_dir):
    job = _job()
    with pytest.raises(IllegalTransition):
        advance(job, "live")


def test_any_state_can_fail_and_carries_the_error(data_dir):
    job = _job()
    advance(job, "extracting")
    advance(job, "failed", error="mineru CLI failed: model weights not found")
    assert job.state == "failed"
    assert "model weights" in job.error


def test_failing_without_a_reason_is_rejected(data_dir):
    """A failed job with no reason is a dead end for a non-technical user."""
    job = _job()
    with pytest.raises(ValueError):
        advance(job, "failed")


def test_nonterminal_states_can_be_cancelled(data_dir):
    job = _job()
    advance(job, "extracting")
    advance(job, "cancelled")
    assert job.state == "cancelled"


def test_terminal_states_cannot_be_left(data_dir):
    for terminal in TERMINAL_STATES:
        job = _job()
        job.state = terminal
        with pytest.raises(IllegalTransition):
            advance(job, "cancelled")


def test_retry_reopens_a_failed_job(data_dir):
    job = _job()
    advance(job, "extracting")
    advance(job, "failed", error="boom")
    advance(job, "queued")
    assert job.state == "queued" and job.error is None


def test_advance_persists_and_bumps_updated_at(data_dir):
    job = _job()
    before = job.updated_at
    advance(job, "extracting")
    assert job.updated_at >= before
    assert load_job(job.job_id).state == "extracting"


# --- progress ---------------------------------------------------------------


def test_mark_stage_records_progress_and_persists(data_dir):
    job = _job()
    advance(job, "extracting")
    mark_stage(job, "extracting", pct=16, detail="page 34/210")
    reloaded = load_job(job.job_id)
    assert reloaded.pct == 16 and reloaded.stage_detail == "page 34/210"


def test_mark_stage_clamps_pct(data_dir):
    job = _job()
    advance(job, "extracting")
    mark_stage(job, "extracting", pct=140, detail="")
    assert job.pct == 100
    mark_stage(job, "extracting", pct=-5, detail="")
    assert job.pct == 0


def test_mark_stage_rejects_a_stage_the_job_is_not_in(data_dir):
    """Guards a stale callback from a cancelled stage overwriting live state."""
    job = _job()
    advance(job, "extracting")
    with pytest.raises(IllegalTransition):
        mark_stage(job, "embedding", pct=50, detail="")


# --- resume -----------------------------------------------------------------


def test_resumable_returns_this_machines_unfinished_jobs(data_dir):
    mine = _job()
    advance(mine, "extracting")
    theirs = _job()
    theirs.machine = "SOMEONE-ELSES-PC"
    advance(theirs, "extracting")
    finished = _job()
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        advance(finished, state)
    assert [j.job_id for j in resumable()] == [mine.job_id]


def test_queued_jobs_are_claimable_from_any_machine(data_dir):
    """Queued work is the office's, not one PC's — whoever runs the worker
    picks it up. Only mid-flight jobs are machine-bound."""
    other = _job()
    other.machine = "SOMEONE-ELSES-PC"
    save(other)
    assert [j.job_id for j in resumable()] == []


def test_concurrent_threads_saving_the_same_job_do_not_race(data_dir):
    """Regression: with parallel ingest several worker THREADS share one pid, so
    a pid-only temp path collides and one thread's os.replace fails with
    FileNotFoundError — failing a document that was otherwise fine. Seen live at
    14 workers."""
    import threading as _t

    from dataclasses import replace as _replace

    job = new_job(
        doc_id="race-doc", source_path="/tmp/x.pdf", corpus="budget",
        publisher="jlbc", doc_type="afr", fiscal_year=2025,
        title="Race Doc", source_sha256="ab" * 32,
    )
    save(job)
    errors: list[BaseException] = []
    barrier = _t.Barrier(8)

    def hammer(n: int) -> None:
        try:
            barrier.wait()
            for i in range(25):
                save(_replace(job, stage_detail=f"t{n}-{i}"))
        except BaseException as exc:  # noqa: BLE001 - the assertion is "none"
            errors.append(exc)

    threads = [_t.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent save() raced: {errors[:3]}"
    assert load_job(job.job_id) is not None
    leftovers = list(jobs_dir().glob("*.tmp"))
    assert leftovers == [], f"temp files leaked: {leftovers}"
