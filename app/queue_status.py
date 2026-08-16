"""Is there queued work that nobody is going to pick up?

Extracted from `app/routes/admin.py` on 2026-08-16, when the same question
gained a second asker. The admin's Corpus panel has always shown this. The
UPLOAD page now needs it too, because the routes stopped starting the queue
on a machine set not to process uploads — so an analyst can queue a
document on such a machine and, without this, watch a row sit at "Waiting"
for ever with nothing on screen explaining why.

🔴 ONE MODULE, ONE SENTENCE, TWO SURFACES. Two independent implementations
of "is the queue stalled?" would eventually disagree, and the way it would
show up is the worst possible: the admin page saying everything is fine
while an analyst stares at a stuck upload, or the reverse. The predicate
and the words are both here, and both callers import them.

This module deliberately holds NO route, NO gate and NO FastAPI import —
`app/routes/jobs.py` is ungated and must not acquire a dependency on the
admin module to ask a question about the queue.
"""
from __future__ import annotations

TERMINAL_JOB_STATES = frozenset({"live", "failed", "cancelled"})

MSG_QUEUE_STALLED = (
    "Uploads are waiting and no computer is set to process them. Open JLBC "
    "Insight on the computer that should do this work, go to Admin → "
    'Corpus, and turn on "Process uploads on this computer".'
)


def queue_summary() -> tuple[dict[str, int], str | None]:
    """(counts by state, when the corpus last actually grew).

    "running" is every non-terminal, non-queued state collapsed into one
    number: an admin wants to know that something is moving, not which of
    six pipeline stages it is in — the Documents page already shows that
    per job.
    """
    summary = {"queued": 0, "running": 0, "failed": 0}
    try:
        from ingest.jobs import load_active, newest_live_job

        # load_active(): none of the three counts is an archived state
        # (spec T13 archives only `live` and `cancelled`), so this is the
        # same arithmetic without reading 7,104 finished job files.
        jobs = load_active()
    except Exception:  # noqa: BLE001 — unreadable jobs dir
        return summary, None

    for job in jobs:
        if job.state == "queued":
            summary["queued"] += 1
        elif job.state == "failed":
            summary["failed"] += 1
        elif job.state not in TERMINAL_JOB_STATES:
            summary["running"] += 1

    # NOT derived from `jobs` above, and this is the one caller that
    # genuinely changed rather than merely getting cheaper. Every `live` job
    # is archived by spec T13, so reading "when did the corpus last grow"
    # out of the main folder would report None forever — the health panel
    # saying nothing has ever been ingested, on a corpus of 7,434 documents,
    # with no error to explain it. `newest_live_job()` sorts the archive by
    # file mtime and opens one file in the common case, and skips
    # `cancelled` because a dismissed failure is not an ingest.
    try:
        newest = newest_live_job()
    except Exception:  # noqa: BLE001 — unreadable archive
        newest = None
    return summary, (newest.updated_at if newest else None)


def queue_stalled(queue: dict[str, int]) -> bool:
    """Is there work nobody will ever pick up?

    All three conditions, because any one alone is a false alarm:

    * something is actually queued (nineteen of the twenty PCs sit with an
      empty queue and ingest off all day; that is not a problem),
    * nothing is running (a job in flight proves SOME machine is draining
      the queue even though it isn't this one), and
    * this machine is not the ingest machine (on the machine that IS, a
      queue is just a queue).

    A failed job alone does not count. Failures have their own signal and
    their own UI; this warning is specifically about work with no owner.

    The import is function-local so this module stays free of app-layer
    imports at import time — `ingest/` reads it too.
    """
    from app.machine_config import ingest_enabled

    if not queue.get("queued") or queue.get("running"):
        return False
    return not ingest_enabled()
