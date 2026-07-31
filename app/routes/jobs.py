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

from ingest.jobs import (
    IllegalTransition,
    advance,
    load_all,
    load_job,
)

router = APIRouter()


@router.get("/api/jobs")
def list_jobs():
    return {"jobs": [job.view() for job in load_all()]}


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
