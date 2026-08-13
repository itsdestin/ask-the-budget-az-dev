"""Add a JLBC book — catalog, discovery, and bulk enqueue.

This is how a colleague adds next year's Baseline after Destin is gone. The
three endpoints separate looking from doing on purpose: `catalog` and
`discover` touch nothing, so somebody can see exactly what a book contains —
and what's unreachable — before committing a machine to an overnight run.

Invariant 8 needs no checkbox here: everything reachable through these
endpoints is a JLBC-published document, which is public record by definition.
The upload page says so in a static notice rather than asking again.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ingest.book_discovery import (
    DiscoveryError,
    EditionPlan,
    list_editions,
    plan_edition,
    walk_edition,
)
from ingest.driver import make_doc_id
from ingest.jobs import TERMINAL_STATES, load_active, new_job, save
from app.routes.upload import _documents

router = APIRouter()


class EditionBody(BaseModel):
    family: str = Field(pattern="^(approps|baseline)$")
    fiscal_year: int = Field(ge=1970, le=2100)


class HttpProber:
    """Real network seam: HEAD to verify, GET to download.

    HEAD rather than GET for verification because a book edition means ~130
    checks and the bodies are megabytes each. Some IIS configurations answer
    405 to HEAD, so that falls back to a ranged GET rather than reporting the
    document missing.
    """

    def __init__(self, timeout_s: int = 30) -> None:
        self._timeout_s = timeout_s

    def head(self, url: str) -> bool:
        import requests

        try:
            r = requests.head(url, timeout=self._timeout_s, allow_redirects=True)
            if r.status_code == 405:
                r = requests.get(
                    url, timeout=self._timeout_s, stream=True,
                    headers={"Range": "bytes=0-0"},
                )
                r.close()
            return r.status_code < 400
        except requests.RequestException:
            return False

    def get(self, url: str) -> bytes:
        import requests

        r = requests.get(url, timeout=self._timeout_s)
        r.raise_for_status()
        return r.content


def _prober(request: Request):
    """Tests inject a fake through app.state; production gets the real one."""
    return getattr(request.app.state, "book_prober", None) or HttpProber()


def _batch_id_for(family: str, fiscal_year: int) -> str:
    """The batch every document of one book edition shares.

    Family AND year, because both books number their sections identically —
    keying on either alone would merge two genuinely separate editions into
    one restore point. Same reasoning as the `family=` argument to
    `make_doc_id` just below.
    """
    return f"jlbc-{family}-fy{fiscal_year}"


@router.get("/api/books/catalog")
def catalog():
    return {"editions": list_editions()}


@router.post("/api/books/discover")
def discover(body: EditionBody, request: Request):
    plan = _plan(body, request)
    return {
        "source": plan.source,
        "count": len(plan.documents),
        "documents": [
            {"url": d.url, "title": d.title, "doc_type": d.doc_type, "code": d.code}
            for d in plan.documents
        ],
        "unreachable": plan.unreachable,
        "notes": plan.notes,
        "single_file_url": plan.single_file_url,
        "linked_toc_url": plan.linked_toc_url,
    }


@router.post("/api/books/ingest", status_code=202)
def ingest(body: EditionBody, request: Request):
    plan = _plan(body, request)
    known = {
        entry.get("source_url")
        for entry in _documents().values()
        if entry.get("source_url")
    }
    pending = {
        # load_active(): the same set as load_all() under this filter,
        # since every archived job is terminal. A URL that has finished is
        # in `known` (documents.json) just above.
        job.source_url for job in load_active()
        if job.state not in TERMINAL_STATES and job.source_url
    }

    queued, skipped = [], []
    for doc in plan.documents:
        if doc.url in known or doc.url in pending:
            skipped.append(doc.url)
            continue
        job = new_job(
            # `family` is load-bearing, not decoration: both books number
            # their sections the same way, so the doc_type alone cannot say
            # which book `508.pdf` came from. Without it the two books mint
            # the same doc_id and the second ingest silently overwrites the
            # first. This route is the only place that knows the family.
            doc_id=make_doc_id(
                publisher="jlbc", doc_type=doc.doc_type,
                fiscal_year=doc.fiscal_year, filename=doc.url.rsplit("/", 1)[-1],
                family=plan.family,
            ),
            title=doc.title,
            corpus="budget",
            # Empty until the worker downloads it — the job carries the URL,
            # and DownloadCache resolves it at extraction time. Queuing 130
            # jobs must not mean downloading 130 PDFs up front.
            source_path="",
            source_sha256="",
            publisher="jlbc",
            doc_type=doc.doc_type,
            fiscal_year=doc.fiscal_year,
            user_title=doc.title,
            source_url=doc.url,
            # One restore point per BOOK EDITION rather than per document.
            # An edition is ~130 documents; snapshotting each would zip the
            # whole corpus 130 times, and the edition is the unit somebody
            # would actually roll back anyway. See
            # ingest/worker.py::_should_snapshot.
            batch_id=_batch_id_for(plan.family, doc.fiscal_year),
        )
        save(job)
        queued.append(job.job_id)

    worker = getattr(request.app.state, "ingest_worker", None)
    if worker is not None:
        worker.start()

    return {
        "queued": len(queued),
        "job_ids": queued,
        "skipped_existing": len(skipped),
        "unreachable": plan.unreachable,
    }


def _plan(body: EditionBody, request: Request) -> EditionPlan:
    prober = _prober(request)
    try:
        plan = plan_edition(body.family, body.fiscal_year, prober=prober)
        return walk_edition(plan, prober=prober)
    except DiscoveryError as exc:
        # 502: the failure is upstream (azjlbc.gov changed, or the edition
        # isn't published), not a bad request. The message is what the UI
        # shows, so it stays in plain language.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
