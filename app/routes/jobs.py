"""Queue-control API: list, retry, cancel.

The queue is shared. Every machine running the app lists every machine's
jobs, because a colleague needs to see that the book they asked for is
running on someone else's PC rather than assume it was lost.

Cancel is a state change in the job FILE, not a signal to a thread — the
worker may be on another machine entirely. It polls its own job record and
stops when it sees `cancelled`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.queue_status import MSG_QUEUE_STALLED, queue_stalled, queue_summary
from ingest.jobs import (
    IllegalTransition,
    advance,
    archived_count,
    load_active,
    load_all,
    load_job,
)

router = APIRouter()


@router.get("/api/jobs")
def list_jobs(all: bool = False):
    """Outstanding work by default; the whole history on request.

    Spec T13: the queue shows work, not history. Before this change the route
    was `load_all()` with no filter, no limit and no sort — measured against
    the live data dir at **7,118 jobs and a 3.02 MB response on every poll**,
    of which **14** needed anybody's attention. The Upload page polls, and the
    office reads it off an SMB share.

    The default set is simply whatever is in the main jobs folder: every
    unfinished job plus every failure, of any age, because finished jobs have
    moved to `jobs/done/` (see ingest/archive.py). There is deliberately NO
    age window and NO state filter here — a window with an exception clause
    for failures is exactly what the 2026-08-13 amendment to T13 removed,
    after measuring that a 24-hour window hid 13 of the 14 live failures. A
    filter here would also be a second place for that rule to be got wrong.

    `finished_count` is a directory listing, not 7,104 file reads. It exists
    so the page can say "N documents finished — view all" rather than leaving
    an analyst to wonder where their document went; "the queue is empty" and
    "the corpus is empty" must not look the same.
    """
    jobs = load_all() if all else load_active()
    # 🔴 The counterweight to the 2026-08-16 ingest-switch fix. The upload
    # and books routes no longer start the queue on a machine set not to
    # process uploads — correct, and the reason the switch exists — but
    # without a word on screen an analyst would queue a document here and
    # watch it sit at "Waiting" for ever with nothing explaining why. That
    # would trade a CPU problem for a trust problem.
    #
    # The predicate and the sentence both come from app/queue_status.py, the
    # same ones the admin page shows. Two surfaces cannot say different
    # things about one queue.
    #
    # Computed from `queue_summary()` and not from `jobs` above, because
    # `?all=true` includes archived jobs and would report a queue that is
    # only historically busy.
    counts, _last = queue_summary()
    return {
        "jobs": [job.view() for job in jobs],
        "finished_count": archived_count(),
        "showing": "all" if all else "active",
        "stalled_message": MSG_QUEUE_STALLED if queue_stalled(counts) else None,
    }


@router.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = _require_job(job_id)
    if job.state != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Only failed documents can be retried; this one is {job.state}.",
        )
    advance(job, "queued")
    return {"job": job.view()}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = _require_job(job_id)
    try:
        advance(job, "cancelled")
    except IllegalTransition as exc:
        # Already live/failed/cancelled. 409 rather than a silent no-op so the
        # UI can say "this already finished" instead of pretending it stopped.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job": job.view()}


def _require_job(job_id: str):
    try:
        job = load_job(job_id)
    except ValueError as exc:
        # A job_id with a path component in it — reject before it reaches
        # the filesystem.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id!r}")
    return job
